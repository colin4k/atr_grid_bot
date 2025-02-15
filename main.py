import yaml
import logging
import time
import argparse
from grid_trading import GridTrading

def main():
    # 首先读取配置文件
    try:
        with open('config.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        config = {}

    parser = argparse.ArgumentParser(description='网格交易机器人')
    parser.add_argument('--api_key', help='API Key')
    parser.add_argument('--api_secret', help='API Secret')
    parser.add_argument('--symbol', help='交易对符号')
    parser.add_argument('--investment', type=float, help='投资金额')
    parser.add_argument('--test_mode', type=bool, default=False, help='是否为测试模式')
    parser.add_argument('--ignore_orders', type=int, default=0, help='是否忽略历史订单(0:否, 1:是)')

    args = parser.parse_args()

    # 从嵌套的配置结构中获取值
    params = {
        'api_key': args.api_key or config.get('api', {}).get('key'),
        'api_secret': args.api_secret or config.get('api', {}).get('secret'),
        'symbol': args.symbol or config.get('trading', {}).get('symbol'),
        'investment': args.investment or config.get('trading', {}).get('investment'),
        'test_mode': args.test_mode if args.test_mode is not None else config.get('test_mode', False),
        'ignore_orders': bool(args.ignore_orders if args.ignore_orders is not None else config.get('ignore_orders', 0))
    }

    # 验证必要参数
    required_params = ['api_key', 'api_secret', 'symbol', 'investment']
    missing_params = [param for param in required_params if not params[param]]
    if missing_params:
        raise ValueError(f"缺少必要参数: {', '.join(missing_params)}")

    while True:
        try:
            # 创建网格交易实例
            bot = GridTrading(
                api_key=params['api_key'],
                api_secret=params['api_secret'],
                symbol=params['symbol'],
                investment_amount=params['investment'],
                test_mode=params['test_mode'],
                ignore_orders=params['ignore_orders']
            )
            
            # 开始监控和调整
            bot.monitor_and_adjust()

        except Exception as e:
            bot.logger.error(f"程序运行出错: {str(e)}")
            time.sleep(60)  # 出错后等待1分钟再重试
            continue

if __name__ == "__main__":
    main() 