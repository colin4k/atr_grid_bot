from binance.client import Client
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time

class GridTrading:
    def __init__(self, api_key, api_secret, symbol, investment_amount, test_mode=False):
        self.client = Client(api_key, api_secret)
        self.symbol = symbol
        self.investment = investment_amount
        self.test_mode = test_mode  # 新增测试模式标志
        
    def get_historical_data(self, lookback_days=30):
        """获取历史K线数据"""
        end_time = datetime.now()
        start_time = end_time - timedelta(days=lookback_days)
        
        klines = self.client.get_historical_klines(
            self.symbol,
            Client.KLINE_INTERVAL_1HOUR,
            start_time.strftime("%d %b %Y %H:%M:%S"),
            end_time.strftime("%d %b %Y %H:%M:%S")
        )
        
        df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote', 'ignored'])
        df['close'] = pd.to_numeric(df['close'])
        return df

    def calculate_volatility(self, df, window=24):
        """计算ATR波动率"""
        df['high'] = pd.to_numeric(df['high'])
        df['low'] = pd.to_numeric(df['low'])
        
        tr1 = df['high'] - df['low']
        tr2 = abs(df['high'] - df['close'].shift(1))
        tr3 = abs(df['low'] - df['close'].shift(1))
        
        df['tr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr'] = df['tr'].rolling(window=window).mean()
        
        return df['atr'].iloc[-1]

    def get_current_positions(self):
        """获取当前持仓信息"""
        positions = self.client.get_account()
        symbol_positions = {}
        for asset in positions['balances']:
            if float(asset['free']) > 0 or float(asset['locked']) > 0:
                symbol_positions[asset['asset']] = {
                    'free': float(asset['free']),
                    'locked': float(asset['locked'])
                }
        return symbol_positions

    def generate_grid_parameters(self, current_price, atr, current_positions=None):
        """根据当前持仓生成网格参数"""
        if current_positions:
            # 根据持仓调整网格范围
            # 可以将持仓价格作为网格的中心点
            # 根据持仓量调整网格大小
            pass
        # 原有的网格生成逻辑
        grid_range = 3 * atr  # 设置网格范围为3倍ATR
        num_grids = 10  # 网格数量
        
        grid_step = grid_range / num_grids
        
        grid_prices = []
        for i in range(-num_grids, num_grids + 1):
            grid_prices.append(current_price + i * grid_step)
            
        return sorted(grid_prices)

    def place_grid_orders(self, grid_prices, current_positions=None):
        """考虑现有持仓设置网格订单"""
        current_price = float(self.client.get_symbol_ticker(symbol=self.symbol)['price'])
        amount_per_grid = self.investment / len(grid_prices)
        
        orders = []
        for price in grid_prices:
            if price < current_price:
                if self.test_mode:
                    # 测试模式下只打印订单信息
                    order = {
                        'symbol': self.symbol,
                        'side': 'BUY',
                        'type': 'LIMIT',
                        'timeInForce': 'GTC',
                        'quantity': amount_per_grid/price,
                        'price': price,
                        'status': 'TEST'
                    }
                else:
                    order = self.client.create_order(
                        symbol=self.symbol,
                        side='BUY',
                        type='LIMIT',
                        timeInForce='GTC',
                        quantity=amount_per_grid/price,
                        price=price
                    )
            elif price > current_price:
                if self.test_mode:
                    # 测试模式下只打印订单信息
                    order = {
                        'symbol': self.symbol,
                        'side': 'SELL',
                        'type': 'LIMIT',
                        'timeInForce': 'GTC',
                        'quantity': amount_per_grid/price,
                        'price': price,
                        'status': 'TEST'
                    }
                else:
                    order = self.client.create_order(
                        symbol=self.symbol,
                        side='SELL',
                        type='LIMIT',
                        timeInForce='GTC',
                        quantity=amount_per_grid/price,
                        price=price
                    )
            orders.append(order)
            print(f"{'测试模式：' if self.test_mode else ''}下单 - 方向: {order['side']}, 价格: {price}, 数量: {amount_per_grid/price}")
        
        return orders

    def monitor_and_adjust(self):
        """监控价格并调整订单"""
        while True:
            try:
                # 获取当前订单状态
                open_orders = self.client.get_open_orders(symbol=self.symbol)
                
                # 检查已成交订单
                for order in open_orders:
                    status = self.client.get_order(
                        symbol=self.symbol,
                        orderId=order['orderId']
                    )
                    
                    if status['status'] == 'FILLED':
                        # 订单成交后，在对应方向设置新的网格订单
                        if status['side'] == 'BUY':
                            new_sell_price = float(status['price']) * (1 + self.grid_step)
                            self.place_grid_orders([new_sell_price])
                        else:
                            new_buy_price = float(status['price']) * (1 - self.grid_step)
                            self.place_grid_orders([new_buy_price])
                            
                time.sleep(1)  # 避免频繁请求
                
            except Exception as e:
                print(f"发生错误: {str(e)}")
                time.sleep(5) 