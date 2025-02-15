from binance.client import Client
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import yaml

class GridTrading:
    def __init__(self, api_key, api_secret, symbol, investment_amount, test_mode=False):
        self.client = Client(api_key, api_secret)
        self.symbol = symbol
        self.investment = investment_amount
        self.test_mode = test_mode
        
        # 从配置文件加载手续费率
        with open('config.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            self.fee_rate = config.get('fee_rate', 0.001)  # 如果未配置则使用默认值0.001
            
        self.profit_stats = {
            'total_profit': 0,
            'total_trades': 0,
            'buy_trades': 0,
            'sell_trades': 0,
            'grid_profits': []  # 记录每个网格的盈利情况
        }
        self.last_rebalance_time = datetime.now()
        self.rebalance_interval = timedelta(hours=24)  # 每24小时重新平衡一次网格

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
        for col in ['open', 'high', 'low', 'close']:
            df[col] = df[col].astype(float)
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
        """优化后的网格参数生成"""
        # 根据市场波动性动态调整网格
        volatility_ratio = atr / current_price
        
        # 根据波动率动态调整网格数量和范围
        if volatility_ratio < 0.02:
            num_grids = 10  # 减少网格数量
            grid_range = 0.15 * current_price  # 设置为当前价格的15%范围
        elif volatility_ratio < 0.05:
            num_grids = 8
            grid_range = 0.2 * current_price   # 设置为当前价格的20%范围
        else:
            num_grids = 6
            grid_range = 0.25 * current_price  # 设置为当前价格的25%范围
        
        grid_step = grid_range / num_grids
        
        # 考虑持仓情况调整网格中心
        if current_positions:
            base_asset = self.symbol.replace('USDT', '')
            if base_asset in current_positions:
                avg_position_price = self.get_average_position_price()
                if avg_position_price:
                    # 网格中心点为当前价格和持仓均价的加权平均
                    position_weight = 0.3  # 持仓均价权重
                    grid_center = (current_price * (1 - position_weight) + 
                                 avg_position_price * position_weight)
                    return self._generate_grid_prices(grid_center, grid_step, num_grids)
        
        return self._generate_grid_prices(current_price, grid_step, num_grids)

    def _generate_grid_prices(self, center_price, grid_step, num_grids):
        """生成网格价格"""
        grid_prices = []
        for i in range(-num_grids, num_grids + 1):
            grid_price = center_price * (1 + i * grid_step)
            grid_prices.append(round(grid_price, 8))  # 根据交易对精度调整
        return sorted(grid_prices)

    def place_grid_orders(self, grid_prices, current_positions=None):
        """优化后的网格订单设置"""
        current_price = float(self.client.get_symbol_ticker(symbol=self.symbol)['price'])
        
        # 考虑手续费后的每格投资金额
        fee_adjusted_investment = self.investment * (1 - self.fee_rate)
        amount_per_grid = fee_adjusted_investment / len(grid_prices)
        
        # 获取交易对的最小交易数量和价格精度
        symbol_info = self.client.get_symbol_info(self.symbol)
        lot_size_filter = next(filter(lambda x: x['filterType'] == 'LOT_SIZE', symbol_info['filters']))
        price_filter = next(filter(lambda x: x['filterType'] == 'PRICE_FILTER', symbol_info['filters']))
        
        min_qty = float(lot_size_filter['minQty'])
        qty_step = float(lot_size_filter['stepSize'])
        price_precision = int(price_filter['tickSize'].find('1') - 1)
        
        orders = []
        for price in grid_prices:
            # 计算符合最小交易量和步长的数量
            quantity = amount_per_grid / price
            quantity = self._adjust_quantity(quantity, min_qty, qty_step)
            price = round(price, price_precision)
            
            if quantity * price < 10:  # 如果订单金额太小（小于10USDT），跳过
                continue
                
            if price < current_price:
                order = self._place_order('BUY', price, quantity)
            elif price > current_price:
                order = self._place_order('SELL', price, quantity)
                
            if order:
                orders.append(order)
                print(f"{'测试模式：' if self.test_mode else ''}下单 - 方向: {order['side']}, "
                      f"价格: {price}, 数量: {quantity}")
        
        return orders

    def _adjust_quantity(self, quantity, min_qty, step_size):
        """调整交易数量以符合交易所规则"""
        quantity = max(min_qty, quantity)
        step_size_decimal = str(step_size)[::-1].find('.')
        return round(quantity - (quantity % step_size), step_size_decimal)

    def _place_order(self, side, price, quantity):
        """统一下单函数"""
        try:
            if self.test_mode:
                return {
                    'symbol': self.symbol,
                    'side': side,
                    'type': 'LIMIT',
                    'timeInForce': 'GTC',
                    'quantity': quantity,
                    'price': price,
                    'status': 'TEST'
                }
            else:
                return self.client.create_order(
                    symbol=self.symbol,
                    side=side,
                    type='LIMIT',
                    timeInForce='GTC',
                    quantity=quantity,
                    price=price
                )
        except Exception as e:
            print(f"下单失败 {side} {quantity} {price}: {str(e)}")
            return None

    def monitor_and_adjust(self):
        """优化后的监控和调整功能"""
        while True:
            try:
                # 检查是否需要重新平衡网格
                if datetime.now() - self.last_rebalance_time > self.rebalance_interval:
                    self._rebalance_grids()
                    self.last_rebalance_time = datetime.now()
                
                # 监控订单状态
                open_orders = self.client.get_open_orders(symbol=self.symbol)
                current_price = float(self.client.get_symbol_ticker(symbol=self.symbol)['price'])
                
                for order in open_orders:
                    status = self.client.get_order(
                        symbol=self.symbol,
                        orderId=order['orderId']
                    )
                    
                    if status['status'] == 'FILLED':
                        self.update_trade_stats(status)
                        self._handle_filled_order(status, current_price)
                
                # 每小时打印一次交易统计
                if datetime.now().minute == 0:
                    self.print_trading_stats()
                
                time.sleep(1)
                
            except Exception as e:
                print(f"监控过程中发生错误: {str(e)}")
                time.sleep(5)

    def _rebalance_grids(self):
        """重新平衡网格"""
        print("开始重新平衡网格...")
        if not self.test_mode:
            self.client.cancel_all_orders(symbol=self.symbol)
        
        # 获取最新市场数据
        df = self.get_historical_data(lookback_days=7)
        atr = self.calculate_volatility(df)
        current_price = float(self.client.get_symbol_ticker(symbol=self.symbol)['price'])
        current_positions = self.get_current_positions()
        
        # 生成新的网格并下单
        grid_prices = self.generate_grid_parameters(current_price, atr, current_positions)
        self.place_grid_orders(grid_prices, current_positions)
        print("网格重新平衡完成")

    def _handle_filled_order(self, filled_order, current_price):
        """处理已成交订单"""
        price = float(filled_order['price'])
        grid_step = price * 0.01  # 假设网格步长为1%
        
        if filled_order['side'] == 'BUY':
            new_sell_price = price * (1 + grid_step)
            self.place_grid_orders([new_sell_price])
        else:
            new_buy_price = price * (1 - grid_step)
            self.place_grid_orders([new_buy_price])

    def update_trade_stats(self, trade):
        """更新交易统计"""
        self.profit_stats['total_trades'] += 1
        
        if trade['side'] == 'BUY':
            self.profit_stats['buy_trades'] += 1
        else:
            self.profit_stats['sell_trades'] += 1
            
        # 计算交易盈亏
        price = float(trade['price'])
        qty = float(trade['qty'])
        fee = float(trade.get('commission', 0))
        
        if trade['side'] == 'SELL':
            avg_cost = self.get_average_position_price() or price
            profit = (price - avg_cost) * qty - fee
            self.profit_stats['total_profit'] += profit
            self.profit_stats['grid_profits'].append(profit)

    def print_trading_stats(self):
        """打印详细的交易统计信息"""
        if self.profit_stats['total_trades'] > 0:
            print("\n====== 交易统计 ======")
            print(f"总盈亏: {self.profit_stats['total_profit']:.4f} USDT")
            print(f"总交易次数: {self.profit_stats['total_trades']}")
            print(f"买入次数: {self.profit_stats['buy_trades']}")
            print(f"卖出次数: {self.profit_stats['sell_trades']}")
            
            if self.profit_stats['grid_profits']:
                avg_profit = sum(self.profit_stats['grid_profits']) / len(self.profit_stats['grid_profits'])
                print(f"平均每网格盈利: {avg_profit:.4f} USDT")
            
            roi = (self.profit_stats['total_profit'] / self.investment) * 100
            print(f"投资回报率: {roi:.2f}%")
            print("=====================") 