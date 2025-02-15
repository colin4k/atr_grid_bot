import yaml
import logging
import time
from grid_trading import GridTrading

def main():
    # 读取配置文件
    with open('config.yaml', 'r', encoding='utf-8') as file:
        config = yaml.safe_load(file)

    # 从配置文件获取参数
    api_key = config['api']['key']
    api_secret = config['api']['secret']
    symbol = config['trading']['symbol']
    investment = config['trading']['investment']
    lookback_days = config['trading']['lookback_days']

    while True:
        try:
            # 创建网格交易实例
            bot = GridTrading(api_key, api_secret, symbol, investment)
            
            # 如果没有加载到之前的状态，则重新初始化网格
            if bot.current_grid_prices is None:
                # 获取当前持仓信息
                current_positions = bot.get_current_positions()
                bot.logger.info(f"当前持仓信息: {current_positions}")

                # 获取历史数据
                df = bot.get_historical_data(lookback_days=lookback_days)

                # 计算波动率
                atr = bot.calculate_volatility(df)
                bot.logger.info(f"计算得到的ATR波动率: {atr}")

                # 获取当前价格
                current_price = float(bot.client.get_symbol_ticker(symbol=symbol)['price'])
                bot.logger.info(f"当前价格: {current_price}")

                # 根据当前持仓生成网格价格
                grid_prices = bot.generate_grid_parameters(current_price, atr, current_positions)
                bot.logger.info(f"生成的网格价格: {grid_prices}")

                # 设置网格订单，考虑现有持仓
                orders = bot.place_grid_orders(grid_prices, current_positions)

            # 开始监控和调整
            bot.monitor_and_adjust()

        except Exception as e:
            bot.logger.error(f"程序运行出错: {str(e)}")
            time.sleep(60)  # 出错后等待1分钟再重试
            continue

if __name__ == "__main__":
    main() 