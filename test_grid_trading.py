import unittest
from unittest.mock import Mock, patch
import pandas as pd
from datetime import datetime, timedelta
from grid_trading import GridTrading
import yaml

class TestGridTrading(unittest.TestCase):
    def setUp(self):
        # 从配置文件读取真实的API密钥
        with open('config.yaml', 'r', encoding='utf-8') as file:
            config = yaml.safe_load(file)
            
        self.api_key = config['api']['key']
        self.api_secret = config['api']['secret']
        self.symbol = config['trading']['symbol']
        self.investment = config['trading']['investment']
        
        # 创建带真实API的GridTrading实例
        self.grid_trading = GridTrading(
            api_key=self.api_key,
            api_secret=self.api_secret,
            symbol=self.symbol,
            investment_amount=self.investment,
            test_mode=True  # 启用测试模式
        )
        
        # 保存原始client用于获取市场数据
        self.real_client = self.grid_trading.client
        
        # 创建模拟client用于交易操作
        self.mock_client = Mock()
        self.mock_client.get_symbol_info.return_value = {
            'filters': [
                {
                    'filterType': 'LOT_SIZE',
                    'minQty': '0.00001000',
                    'stepSize': '0.00001000'
                },
                {
                    'filterType': 'PRICE_FILTER',
                    'tickSize': '0.01000000'
                }
            ]
        }
        self.mock_client.orders = []
        
    def test_get_historical_data(self):
        """使用真实API测试历史数据获取"""
        df = self.grid_trading.get_historical_data(lookback_days=7)
        
        # 验证数据结构
        self.assertIsInstance(df, pd.DataFrame)
        self.assertTrue(len(df) > 0)
        required_columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        for col in required_columns:
            self.assertIn(col, df.columns)
            
        # 验证数据时间范围
        end_time = datetime.now()
        start_time = end_time - timedelta(days=7)
        self.assertTrue(df['timestamp'].min() >= start_time.timestamp() * 1000)
        print(f"获取到 {len(df)} 条历史数据")

    def test_calculate_volatility(self):
        """使用真实市场数据测试波动率计算"""
        df = self.grid_trading.get_historical_data(lookback_days=7)
        atr = self.grid_trading.calculate_volatility(df)
        
        self.assertIsInstance(atr, float)
        self.assertTrue(atr > 0)
        print(f"计算得到的ATR波动率: {atr}")
        print(f"相对于当前价格的波动率百分比: {atr/float(self.real_client.get_symbol_ticker(symbol=self.symbol)['price'])*100:.2f}%")

    def test_grid_generation_with_real_data(self):
        """使用真实市场数据测试网格生成"""
        # 获取真实市场数据
        df = self.grid_trading.get_historical_data(lookback_days=7)
        atr = self.grid_trading.calculate_volatility(df)
        current_price = float(self.real_client.get_symbol_ticker(symbol=self.symbol)['price'])
        
        # 生成网格
        grid_prices = self.grid_trading.generate_grid_parameters(current_price, atr)
        
        # 验证网格
        self.assertTrue(len(grid_prices) > 0)
        self.assertTrue(all(isinstance(price, float) for price in grid_prices))
        self.assertTrue(grid_prices[0] < grid_prices[-1])
        
        print(f"当前市场价格: {current_price}")
        print(f"生成的网格价格范围: {grid_prices[0]} - {grid_prices[-1]}")
        print(f"网格数量: {len(grid_prices)}")
        print(f"平均网格间距: {(grid_prices[-1] - grid_prices[0]) / (len(grid_prices)-1):.2f}")

    @patch('binance.client.Client')
    def test_order_placement(self, mock_client_class):
        """使用真实价格但模拟下单"""
        # 保存真实client的引用
        real_client = self.grid_trading.client
        
        # 设置模拟client用于下单
        mock_client_class.return_value = self.mock_client
        
        try:
            # 使用真实client获取市场数据
            df = real_client.get_klines(
                symbol=self.symbol,
                interval='1h',
                limit=168  # 7天 * 24小时
            )
            df = pd.DataFrame(df, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 
                                         'close_time', 'quote_volume', 'trades', 'taker_buy_base', 
                                         'taker_buy_quote', 'ignored'])
            
            # 计算ATR
            atr = self.grid_trading.calculate_volatility(df)
            current_price = float(real_client.get_symbol_ticker(symbol=self.symbol)['price'])
            
            # 切换到模拟client进行下单测试
            self.grid_trading.client = self.mock_client
            
            # 生成网格并测试下单
            grid_prices = self.grid_trading.generate_grid_parameters(current_price, atr)
            orders = self.grid_trading.place_grid_orders(grid_prices)
            
            # 验证订单
            self.assertTrue(len(orders) > 0)
            for order in orders:
                self.assertEqual(order['status'], 'TEST')
                self.assertIn(order['side'], ['BUY', 'SELL'])
                self.assertEqual(order['symbol'], self.symbol)
                
                # 打印订单详情
                print(f"测试订单 - 方向: {order['side']}, 价格: {order['price']}, "
                      f"数量: {order['quantity']}, "
                      f"金额: {float(order['price']) * float(order['quantity']):.2f} USDT")
        
        finally:
            # 确保恢复真实client
            self.grid_trading.client = real_client

    def tearDown(self):
        """测试清理"""
        # 确保恢复真实client
        self.grid_trading.client = self.real_client

if __name__ == '__main__':
    unittest.main() 