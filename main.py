import yaml
from grid_trading import GridTrading

# 读取配置文件
with open('config.yaml', 'r', encoding='utf-8') as file:
    config = yaml.safe_load(file)

# 从配置文件获取参数
api_key = config['api']['key']
api_secret = config['api']['secret']
symbol = config['trading']['symbol']
investment = config['trading']['investment']
lookback_days = config['trading']['lookback_days']

# 创建网格交易实例
bot = GridTrading(api_key, api_secret, symbol, investment)

# 获取当前持仓信息
current_positions = bot.get_current_positions()

# 获取历史数据
df = bot.get_historical_data(lookback_days=lookback_days)

# 计算波动率
atr = bot.calculate_volatility(df)

# 获取当前价格
current_price = float(bot.client.get_symbol_ticker(symbol=symbol)['price'])

# 根据当前持仓生成网格价格
grid_prices = bot.generate_grid_parameters(current_price, atr, current_positions)

# 设置网格订单，考虑现有持仓
orders = bot.place_grid_orders(grid_prices, current_positions)

# 开始监控和调整
bot.monitor_and_adjust() 