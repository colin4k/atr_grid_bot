import unittest
import yaml
from grid_trading import GridTrading
import pandas as pd
from datetime import datetime, timedelta

class TestGridTrading(unittest.TestCase):
    def setUp(self):
        # 从配置文件读取API密钥
        with open('config.yaml', 'r', encoding='utf-8') as file:
            config = yaml.safe_load(file)
            
        self.api_key = config['api']['key']
        self.api_secret = config['api']['secret']
        self.symbol = config['trading']['symbol']
        self.investment = config['trading']['investment']
        
        # 创建测试模式的GridTrading实例
        self.grid_trading = GridTrading(
            api_key=self.api_key,
            api_secret=self.api_secret,
            symbol=self.symbol,
            investment_amount=self.investment,
            test_mode=True
        )

    def test_historical_data(self):
        """测试历史数据获取"""
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

    def test_volatility_calculation(self):
        """测试波动率计算"""
        df = self.grid_trading.get_historical_data(lookback_days=7)
        atr = self.grid_trading.calculate_volatility(df)
        
        self.assertIsInstance(atr, float)
        self.assertTrue(atr > 0)
        print(f"计算得到的ATR波动率: {atr}")

    def test_grid_generation(self):
        """测试网格生成"""
        # 获取实时市场数据
        df = self.grid_trading.get_historical_data(lookback_days=7)
        atr = self.grid_trading.calculate_volatility(df)
        current_price = float(self.grid_trading.client.get_symbol_ticker(symbol=self.symbol)['price'])
        
        # 生成网格
        grid_prices = self.grid_trading.generate_grid_parameters(current_price, atr)
        
        # 验证网格
        self.assertTrue(len(grid_prices) > 0)
        self.assertTrue(all(isinstance(price, float) for price in grid_prices))
        self.assertTrue(grid_prices[0] < grid_prices[-1])
        
        print(f"当前价格: {current_price}")
        print(f"生成的网格价格: {grid_prices}")

    def test_order_placement(self):
        """测试订单生成（测试模式）"""
        # 获取实时市场数据
        df = self.grid_trading.get_historical_data(lookback_days=7)
        atr = self.grid_trading.calculate_volatility(df)
        current_price = float(self.grid_trading.client.get_symbol_ticker(symbol=self.symbol)['price'])
        
        # 生成网格并下单
        grid_prices = self.grid_trading.generate_grid_parameters(current_price, atr)
        orders = self.grid_trading.place_grid_orders(grid_prices)
        
        # 验证订单
        self.assertTrue(len(orders) > 0)
        for order in orders:
            self.assertEqual(order['status'], 'TEST')
            self.assertIn(order['side'], ['BUY', 'SELL'])
            self.assertEqual(order['symbol'], self.symbol)

if __name__ == '__main__':
    unittest.main() 