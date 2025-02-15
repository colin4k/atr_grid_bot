import yaml
import logging
import time
import argparse
from grid_trading import GridTrading

def main():
    parser = argparse.ArgumentParser(description='网格交易机器人')
    parser.add_argument('--api_key', required=True, help='API Key')
    parser.add_argument('--api_secret', required=True, help='API Secret')
    parser.add_argument('--symbol', required=True, help='交易对符号')
    parser.add_argument('--investment', type=float, required=True, help='投资金额')
    parser.add_argument('--test_mode', type=bool, default=False, help='是否为测试模式')
    parser.add_argument('--ignore_orders', type=int, default=0, help='是否忽略历史订单(0:否, 1:是)')

    args = parser.parse_args()

    while True:
        try:
            # 创建网格交易实例
            bot = GridTrading(
                api_key=args.api_key,
                api_secret=args.api_secret,
                symbol=args.symbol,
                investment_amount=args.investment,
                test_mode=args.test_mode,
                ignore_orders=bool(args.ignore_orders)
            )
            
            # 开始监控和调整
            bot.monitor_and_adjust()

        except Exception as e:
            bot.logger.error(f"程序运行出错: {str(e)}")
            time.sleep(60)  # 出错后等待1分钟再重试
            continue

if __name__ == "__main__":
    main() 