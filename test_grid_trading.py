import unittest
from unittest.mock import Mock, patch
import pandas as pd
from datetime import datetime, timedelta
from grid_trading import GridTrading
import yaml

class TestGridTrading(unittest.TestCase):
    def setUp(self):
        """测试初始化"""
        # 从配置文件读取API密钥
        with open('config.yaml', 'r', encoding='utf-8') as file:
            config = yaml.safe_load(file)
            
        self.api_key = config['api']['key']
        self.api_secret = config['api']['secret']
        self.symbol = config['trading']['symbol']
        self.investment = config['trading']['investment']
        
        # 创建GridTrading实例
        self.grid_trading = GridTrading(
            api_key=self.api_key,
            api_secret=self.api_secret,
            symbol=self.symbol,
            investment_amount=self.investment,
            test_mode=True
        )
        
        # 保存真实client用于获取市场数据
        self.real_client = self.grid_trading.client
        
        # 创建模拟client
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
        
    def test_get_historical_data(self):
        """测试历史数据获取功能"""
        df = self.grid_trading.get_historical_data(lookback_days=7)
        
        # 验证数据结构
        self.assertIsInstance(df, pd.DataFrame)
        self.assertTrue(len(df) > 0)
        required_columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        for col in required_columns:
            self.assertIn(col, df.columns)
            
        # 验证数据类型
        numeric_columns = ['open', 'high', 'low', 'close']
        for col in numeric_columns:
            self.assertTrue(df[col].dtype in ['float64', 'float32'])
            
        # 验证数据时间范围
        end_time = datetime.now()
        start_time = end_time - timedelta(days=7)
        self.assertTrue(df['timestamp'].min() >= start_time.timestamp() * 1000)
        print(f"获取到 {len(df)} 条历史数据")

    def test_calculate_volatility(self):
        """测试波动率计算功能"""
        df = self.grid_trading.get_historical_data(lookback_days=7)
        atr = self.grid_trading.calculate_volatility(df)
        
        # 验证ATR计算结果
        self.assertIsInstance(atr, float)
        self.assertTrue(atr > 0)
        
        # 计算相对波动率
        current_price = float(self.real_client.get_symbol_ticker(symbol=self.symbol)['price'])
        volatility_ratio = atr / current_price
        
        print(f"计算得到的ATR波动率: {atr}")
        print(f"相对波动率: {volatility_ratio*100:.2f}%")
        
        # 验证波动率在合理范围内
        self.assertTrue(0 < volatility_ratio < 0.5)  # 波动率通常不会超过50%

    def test_generate_grid_parameters(self):
        """测试网格参数生成功能"""
        # 获取市场数据
        df = self.grid_trading.get_historical_data(lookback_days=7)
        atr = self.grid_trading.calculate_volatility(df)
        current_price = float(self.real_client.get_symbol_ticker(symbol=self.symbol)['price'])
        
        # 生成网格
        grid_prices = self.grid_trading.generate_grid_parameters(current_price, atr)
        
        # 验证网格价格
        self.assertTrue(len(grid_prices) > 0)
        self.assertTrue(all(isinstance(price, float) for price in grid_prices))
        self.assertTrue(grid_prices[0] < current_price < grid_prices[-1])
        
        # 验证网格间距
        grid_gaps = [grid_prices[i+1] - grid_prices[i] for i in range(len(grid_prices)-1)]
        avg_gap = sum(grid_gaps) / len(grid_gaps)
        
        print(f"当前价格: {current_price}")
        print(f"网格范围: {grid_prices[0]} - {grid_prices[-1]}")
        print(f"网格数量: {len(grid_prices)}")
        print(f"平均网格间距: {avg_gap:.2f} ({avg_gap/current_price*100:.2f}%)")

    @patch('binance.client.Client')
    def test_place_grid_orders(self, mock_client_class):
        """测试网格订单下单功能"""
        # 保存真实client
        real_client = self.grid_trading.client
        
        try:
            # 设置模拟client
            mock_client_class.return_value = self.mock_client
            
            # 设置 get_symbol_ticker 的返回值
            current_price = float(real_client.get_symbol_ticker(symbol=self.symbol)['price'])
            self.mock_client.get_symbol_ticker.return_value = {'price': str(current_price)}
            
            self.grid_trading.client = self.mock_client
            
            # 使用真实数据生成网格
            df = real_client.get_klines(
                symbol=self.symbol,
                interval='1h',
                limit=168
            )
            df = pd.DataFrame(df, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 
                                         'close_time', 'quote_volume', 'trades', 'taker_buy_base', 
                                         'taker_buy_quote', 'ignored'])
            
            # 转换价格列为浮点数
            for col in ['open', 'high', 'low', 'close']:
                df[col] = df[col].astype(float)
            
            # 计算网格参数
            atr = self.grid_trading.calculate_volatility(df)
            grid_prices = self.grid_trading.generate_grid_parameters(current_price, atr)
            
            # 测试下单
            orders = self.grid_trading.place_grid_orders(grid_prices)
            
            # 验证订单
            self.assertTrue(len(orders) > 0)
            for order in orders:
                self.assertEqual(order['status'], 'TEST')
                self.assertIn(order['side'], ['BUY', 'SELL'])
                self.assertEqual(order['symbol'], self.symbol)
                
                # 验证订单金额
                order_amount = float(order['price']) * float(order['quantity'])
                self.assertTrue(order_amount >= 10)  # 确保订单金额不小于10USDT
                
                print(f"测试订单 - 方向: {order['side']}, 价格: {order['price']}, "
                      f"数量: {order['quantity']}, 金额: {order_amount:.2f} USDT")
        
        finally:
            # 恢复真实client
            self.grid_trading.client = real_client

    def tearDown(self):
        """测试清理"""
        self.grid_trading.client = self.real_client

if __name__ == '__main__':
    unittest.main() 