from binance.client import Client
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import yaml
import logging
import os
import json

class GridTrading:
    def __init__(self, api_key, api_secret, symbol, investment_amount, test_mode=False, ignore_orders=False):
        self.client = Client(api_key, api_secret)
        self.symbol = symbol
        self.investment = investment_amount
        self.test_mode = test_mode
        self.ignore_orders = ignore_orders  # 新增参数
        
        # 设置日志
        self.setup_logger()
        
        if self.ignore_orders:
            self.logger.info("已启用忽略历史订单模式")
        
        # 从配置文件加载配置参数
        with open('config.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            self.fee_rate = config.get('fee_rate', 0.001)  # 如果未配置则使用默认值0.001
            self.lower_price = config.get('lower_price', 150)  # 添加下限价格配置
            self.upper_price = config.get('upper_price', 350)  # 添加上限价格配置
            
        # 状态文件路径
        self.state_file = f'states/grid_trading_state_{self.symbol}.json'
        
        # 确保states目录存在
        if not os.path.exists('states'):
            os.makedirs('states')
        
        # 初始化或加载状态
        self.load_state()
        
        self.logger.info(f"初始化网格交易 - 交易对: {symbol}, 投资金额: {investment_amount}, 测试模式: {test_mode}")
        self.profit_stats = {
            'total_profit': 0,
            'total_trades': 0,
            'buy_trades': 0,
            'sell_trades': 0,
            'grid_profits': []  # 记录每个网格的盈利情况
        }
        self.last_rebalance_time = datetime.now()
        self.rebalance_interval = timedelta(hours=24)  # 每24小时重新平衡一次网格

    def setup_logger(self):
        """设置日志记录器"""
        # 创建logs目录（如果不存在）
        if not os.path.exists('logs'):
            os.makedirs('logs')
            
        # 获取当前日期作为日志文件名
        log_filename = f"logs/grid_trading_{datetime.now().strftime('%Y%m%d')}.log"
        
        # 配置日志记录器
        self.logger = logging.getLogger('GridTrading')
        self.logger.setLevel(logging.INFO)
        
        # 创建文件处理器
        file_handler = logging.FileHandler(log_filename, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        
        # 创建控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # 创建格式化器
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        # 添加处理器到记录器
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        # 防止日志重复
        self.logger.propagate = False

    def get_historical_data(self, lookback_days=30):
        """获取历史K线数据"""
        self.logger.info(f"获取 {self.symbol} 最近 {lookback_days} 天的历史数据")
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
        # 使用配置的价格范围
        lower_price = self.lower_price
        upper_price = self.upper_price
        
        # 根据市场波动性动态调整网格数量
        volatility_ratio = atr / current_price
        
        # 根据波动率动态调整网格数量
        if volatility_ratio < 0.02:
            num_grids = 20  # 低波动率时使用更多网格
        elif volatility_ratio < 0.05:
            num_grids = 15
        else:
            num_grids = 10  # 高波动率时使用较少网格
        
        # 计算网格步长
        grid_range = upper_price - lower_price
        grid_step = grid_range / num_grids
        
        # 考虑持仓情况调整网格中心
        if current_positions:
            base_asset = self.symbol.replace('USDT', '')
            if base_asset in current_positions:
                avg_position_price = self.get_average_position_price()
                if avg_position_price:
                    # 确保网格中心点在设定范围内
                    grid_center = min(max(avg_position_price, lower_price), upper_price)
                    return self._generate_grid_prices(grid_center, grid_step, num_grids)
        
        # 使用当前价格作为网格中心，但确保在设定范围内
        grid_center = min(max(current_price, lower_price), upper_price)
        return self._generate_grid_prices(grid_center, grid_step, num_grids)

    def _generate_grid_prices(self, center_price, grid_step, num_grids):
        """生成网格价格"""
        grid_prices = []
        half_range = (num_grids * grid_step) / 2
        
        # 确保网格价格不会超出配置的范围
        start_price = max(self.lower_price, center_price - half_range)
        end_price = min(self.upper_price, center_price + half_range)
        
        # 重新计算实际使用的网格步长
        actual_range = end_price - start_price
        actual_step = actual_range / num_grids
        
        for i in range(num_grids + 1):
            grid_price = start_price + i * actual_step
            grid_prices.append(round(grid_price, 8))  # 根据交易对精度调整
            
        return grid_prices

    def place_grid_orders(self, grid_prices, current_positions=None):
        """优化后的网格订单设置"""
        current_price = float(self.client.get_symbol_ticker(symbol=self.symbol)['price'])
        self.logger.info(f"开始设置网格订单 - 当前价格: {current_price}")
        
        # 保存网格价格和当前价格
        self.current_grid_prices = grid_prices
        self.last_known_price = current_price
        
        # 修改：确保投资金额合理分配到每个网格
        num_grids = len(grid_prices) - 1  # 网格数量
        amount_per_grid = self.investment / num_grids  # 每个网格分配的资金
        
        # 获取交易对的最小交易数量和价格精度
        symbol_info = self.client.get_symbol_info(self.symbol)
        lot_size_filter = next(filter(lambda x: x['filterType'] == 'LOT_SIZE', symbol_info['filters']))
        price_filter = next(filter(lambda x: x['filterType'] == 'PRICE_FILTER', symbol_info['filters']))
        
        min_qty = float(lot_size_filter['minQty'])
        qty_step = float(lot_size_filter['stepSize'])
        price_precision = int(price_filter['tickSize'].find('1') - 1)
        
        orders = []
        for i in range(len(grid_prices) - 1):  # 遍历相邻的价格对
            lower_price = grid_prices[i]
            upper_price = grid_prices[i + 1]
            
            # 计算当前网格的数量
            quantity = amount_per_grid / ((lower_price + upper_price) / 2)  # 使用平均价格计算数量
            quantity = self._adjust_quantity(quantity, min_qty, qty_step)
            
            # 确保数量大于最小交易量
            if quantity < min_qty:
                quantity = min_qty
            
            # 根据当前价格决定买卖方向
            if lower_price < current_price:
                order = self._place_order('SELL', upper_price, quantity)
            else:
                order = self._place_order('BUY', lower_price, quantity)
            
            if order:
                orders.append(order)
                self.logger.info(f"{'测试模式：' if self.test_mode else ''}下单 - 方向: {order['side']}, "
                               f"价格: {order['price']}, 数量: {quantity}")
        
        # 保存状态
        self.save_state()
        return orders

    def _adjust_quantity(self, quantity, min_qty, step_size):
        """调整交易数量以符合交易所规则"""
        # 确保数量不小于最小交易量
        quantity = max(min_qty, quantity)
        
        # 根据步长调整数量
        step_size_decimal = len(str(float(step_size)).split('.')[-1])
        quantity = round(quantity - (quantity % float(step_size)), step_size_decimal)
        
        # 再次确保不小于最小交易量
        return max(min_qty, quantity)

    def _place_order(self, side, price, quantity):
        """统一下单函数"""
        try:
            # 获取交易对的价格精度
            symbol_info = self.client.get_symbol_info(self.symbol)
            price_filter = next(filter(lambda x: x['filterType'] == 'PRICE_FILTER', symbol_info['filters']))
            tick_size = float(price_filter['tickSize'])
            
            # 根据tick_size调整价格精度
            price_precision = len(str(tick_size).rstrip('0').split('.')[-1])
            adjusted_price = round(price, price_precision)
            
            if self.test_mode:
                return {
                    'symbol': self.symbol,
                    'side': side,
                    'type': 'LIMIT',
                    'timeInForce': 'GTC',
                    'quantity': quantity,
                    'price': adjusted_price,
                    'status': 'TEST'
                }
            else:
                return self.client.create_order(
                    symbol=self.symbol,
                    side=side,
                    type='LIMIT',
                    timeInForce='GTC',
                    quantity=quantity,
                    price=adjusted_price
                )
        except Exception as e:
            self.logger.error(f"下单失败 {side} {quantity} {price}: {str(e)}")
            return None

    def monitor_and_adjust(self):
        """优化后的监控和调整功能"""
        self.logger.info("开始监控和调整网格...")
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
                
                # 定期保存状态（每小时）
                if datetime.now().minute == 0:
                    self.save_state()
                    self.print_trading_stats()
                
                time.sleep(1)
                
            except Exception as e:
                self.logger.error(f"监控过程中发生错误: {str(e)}")
                # 发生错误时也保存状态
                self.save_state()
                time.sleep(5)

    def _rebalance_grids(self):
        """重新平衡网格"""
        self.logger.info("开始重新平衡网格...")
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
        self.logger.info("网格重新平衡完成")

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
            stats_message = "\n====== 交易统计 ======\n"
            stats_message += f"总盈亏: {self.profit_stats['total_profit']:.4f} USDT\n"
            stats_message += f"总交易次数: {self.profit_stats['total_trades']}\n"
            stats_message += f"买入次数: {self.profit_stats['buy_trades']}\n"
            stats_message += f"卖出次数: {self.profit_stats['sell_trades']}\n"
            
            if self.profit_stats['grid_profits']:
                avg_profit = sum(self.profit_stats['grid_profits']) / len(self.profit_stats['grid_profits'])
                stats_message += f"平均每网格盈利: {avg_profit:.4f} USDT\n"
            
            roi = (self.profit_stats['total_profit'] / self.investment) * 100
            stats_message += f"投资回报率: {roi:.2f}%\n"
            stats_message += "====================="
            
            self.logger.info(stats_message)

    def get_average_position_price(self):
        """
        计算当前持仓的平均价格
        返回：如果有持仓则返回平均价格，如果没有持仓则返回None
        """
        positions = self.get_current_positions()
        # 检查持仓是否为空或数量为0
        if not positions or float(positions.get('positionAmt', 0)) == 0:
            return None
        
        # 使用 positionAmt 替代 qty，并确保转换为浮点数
        position_amt = float(positions.get('positionAmt', 0))
        entry_price = float(positions.get('entryPrice', 0))
        
        return entry_price if position_amt != 0 else None

    def save_state(self):
        """保存当前状态到文件"""
        state = {
            'profit_stats': self.profit_stats,
            'last_rebalance_time': self.last_rebalance_time.isoformat(),
            'active_orders': self.get_active_orders(),
            'current_grid_prices': self.current_grid_prices if hasattr(self, 'current_grid_prices') else None,
            'investment': self.investment,
            'last_known_price': self.last_known_price if hasattr(self, 'last_known_price') else None
        }
        
        try:
            with open(self.state_file, 'w') as f:
                json.dump(state, f)
            self.logger.info("状态已保存")
        except Exception as e:
            self.logger.error(f"保存状态失败: {str(e)}")

    def load_state(self):
        """从文件加载状态"""
        try:
            if os.path.exists(self.state_file) and not self.ignore_orders:  # 增加ignore_orders检查
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                
                self.profit_stats = state['profit_stats']
                self.last_rebalance_time = datetime.fromisoformat(state['last_rebalance_time'])
                self.current_grid_prices = state['current_grid_prices']
                self.last_known_price = state['last_known_price']
                
                self.logger.info("已加载之前的交易状态")
                
                # 恢复之前的订单
                if not self.test_mode:
                    self._restore_orders(state['active_orders'])
            else:
                if self.ignore_orders:
                    self.logger.info("忽略历史订单模式：使用初始状态")
                else:
                    self.logger.info("未找到之前的状态文件，使用初始状态")
                self.current_grid_prices = None
                self.last_known_price = None
        except Exception as e:
            self.logger.error(f"加载状态失败: {str(e)}")
            self.current_grid_prices = None
            self.last_known_price = None

    def _restore_orders(self, saved_orders):
        """恢复之前的订单"""
        try:
            # 取消所有现有订单
            self.client.cancel_all_orders(symbol=self.symbol)
            
            # 获取当前市场价格
            current_price = float(self.client.get_symbol_ticker(symbol=self.symbol)['price'])
            
            # 检查是否需要重新平衡网格
            if self.current_grid_prices:
                price_change_ratio = abs(current_price - self.last_known_price) / self.last_known_price
                if price_change_ratio > 0.05:  # 如果价格变化超过5%
                    self.logger.info("价格变化显著，需要重新生成网格")
                    return False
                
                # 重新下达保存的订单
                for order in saved_orders:
                    try:
                        self._place_order(
                            side=order['side'],
                            price=order['price'],
                            quantity=order['quantity']
                        )
                    except Exception as e:
                        self.logger.error(f"恢复订单失败: {str(e)}")
                
                self.logger.info("已恢复之前的订单")
                return True
            
            return False
        except Exception as e:
            self.logger.error(f"恢复订单过程中出错: {str(e)}")
            return False

    def get_active_orders(self):
        """获取当前活动订单的详细信息"""
        try:
            if self.test_mode:
                return []
            
            orders = self.client.get_open_orders(symbol=self.symbol)
            return [{
                'symbol': order['symbol'],
                'side': order['side'],
                'price': float(order['price']),
                'quantity': float(order['origQty']),
                'order_id': order['orderId']
            } for order in orders]
        except Exception as e:
            self.logger.error(f"获取活动订单时发生错误: {str(e)}")
            return []