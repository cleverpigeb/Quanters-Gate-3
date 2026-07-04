# -*- coding: utf-8 -*-

import akshare as ak
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import time

def main():
    mpl.rc("font", family="SimSun")
    data = fetch_stock_data()  # 获取股票数据

    # 整理数据的时间格式
    data["date"] = pd.to_datetime(data["date"])
    data.sort_values("date", inplace=True)
    data.set_index("date", inplace=True)

    # 计算 5 日和 20 日均线
    data["MA5"] = data["close"].rolling(window=5).mean()
    data["MA20"] = data["close"].rolling(window=20).mean()

    # 按照双均线策略计算交易信号
    data["Signal"] = 0
    data.loc[data["MA5"] > data["MA20"], "Signal"] = 1

    # 根据交易策略实施持仓情况
    data["Position"] = data["Signal"].shift(1, fill_value=0)

    data["Market_Return"] = data["close"].pct_change()

    # 标记某日是否发生交易，diff() 会计算与前日持仓标记的差异，若有差异则为 1，无差异则为 0
    data["Trade"] = data["Position"].diff().abs().fillna(0)
    
    commission_rate = 0.0003  # 假设交易手续费为 0.03%
    slippage_rate = 0.0005   # 假设滑点为 0.05%
    total_cost_rate = commission_rate + slippage_rate

    # 计算决策收益，涵盖手续费
    data["Cost"] = data["Trade"] * total_cost_rate
    data["Strategy_Return"] = data["Market_Return"] * \
        data["Position"] - data["Cost"]

    data["Market_Cum"] = (1 + data["Market_Return"]).cumprod()
    data["Strategy_Cum"] = (1 + data["Strategy_Return"]).cumprod()
    
    # 计算最大回撤
    data["Strategy_Peak"] = data["Strategy_Cum"].cummax()
    data["Drawdown"] = data["Strategy_Cum"] / data["Strategy_Peak"] - 1
    max_drawdown = data["Drawdown"].min()

    # 标记买入和卖出信号
    data["Buy"] = (1 == data["Signal"]) & \
        (0 == data["Signal"].shift(1, fill_value=0))
    data["Sell"] = (0 == data["Signal"]) & \
        (1 == data["Signal"].shift(1, fill_value=0))

    # 计算年化收益
    total_return = data["Strategy_Cum"].dropna().iloc[-1] - 1
    days = (data.index[-1] - data.index[0]).days
    annual_return = (1 + total_return) ** (365 / days) - 1
    
    # 计算夏普比率，假设一年有 252 个交易日
    daily_return = data["Strategy_Return"].dropna()
    sharpe = daily_return.mean() / daily_return.std() * (252 ** 0.5)
    
    # 获取每笔交易的详细信息
    trades = track_every_trade(data)
    # 计算胜率和平均每笔收益
    win_rate = (trades["return"] > 0).mean()
    avg_trade_return = trades["return"].mean()

    print(f"买入并持有最终收益倍数：{round(data['Market_Cum'].dropna().iloc[-1], 2)}")
    print(f"均线策略最终收益倍数：{round(data['Strategy_Cum'].dropna().iloc[-1], 2)}")
    print(f"交易次数：{int(data['Trade'].sum())}")
    print(f"年化收益率：{round(annual_return * 100, 2)}%")
    print(f"最大回撤：{round(max_drawdown * 100, 2)}%")
    print(f"夏普比率：{round(sharpe, 2)}")
    print(f"胜率：{round(win_rate * 100, 2)}%")
    print(f"平均每笔收益：{round(avg_trade_return * 100, 2)}%")

    # 画图
    plt.figure(figsize=(12, 6))
    plt.plot(data.index, data["close"], label="收盘价")
    plt.plot(data.index, data["MA5"], label="5日均线")
    plt.plot(data.index, data["MA20"], label="20日均线")

    plt.scatter(
        data.index[data["Buy"]],
        data["close"][data["Buy"]],
        marker="^",
        label="买入信号"
    )

    plt.scatter(
        data.index[data["Sell"]],
        data["close"][data["Sell"]],
        marker="v",
        label="卖出信号"
    )

    plt.title("000001 MA5 / MA20 交易策略回测")
    plt.legend()
    plt.grid(True)

    plt.figure(figsize=(12, 6))
    plt.plot(data.index, data["Market_Cum"], label="市场累计收益")
    plt.plot(data.index, data["Strategy_Cum"], label="策略累计收益")
    plt.title("回测结果")
    plt.legend()
    plt.grid(True)

    plt.show()

# 统一东财与其他数据接口的格式
def normalise_stock_data(data):
    data_copy = data.copy()

    rename_map = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
    }

    data_copy.rename(columns=rename_map, inplace=True)

    return data_copy

# 获取股票数据，会使用三种接口
def fetch_stock_data():
    providers = [
        (
            "东财",
            lambda: ak.stock_zh_a_hist(
                symbol="000001",
                period="daily",
                start_date="20210101",
                end_date="20260630",
                adjust="hfq"
            )
        ),
        (
            "新浪",
            lambda: ak.stock_zh_a_daily(
                symbol="sz000001",
                start_date="20210101",
                end_date="20260630",
                adjust="hfq"
            )
        ),
        (
            "腾讯",
            lambda: ak.stock_zh_a_hist_tx(
                symbol="sz000001",
                start_date="20210101",
                end_date="20260630",
                adjust="hfq"
            )
        ),
    ]

    for name, fetch_func in providers:
        try:
            print(f"正在尝试{name}接口获取数据...")
            data = fetch_func()

            if data is None or data.empty:
                raise ValueError("接口返回数据为空")

            data = normalise_stock_data(data)

        except Exception as e:
            print(f"{name}接口获取失败：", e)
            time.sleep(5)
        else:
            print(f"{name}接口获取成功！")
            return data

    raise RuntimeError("三个数据接口全部获取失败，请检查网络连接或 AkShare 服务状态")

# 追踪每一笔交易的情况
def track_every_trade(data):
    # 因为 Buy 是前一天的信号，所以要 shift(1) 来获取前一天的信号
    data["Buy_Pos"] = data["Buy"].shift(1, fill_value=False)
    data["Sell_Pos"] = data["Sell"].shift(1, fill_value=False)

    trades = []
    buy_date = None
    buy_price = None
    
    for date, row in data.iterrows():
        if row["Buy_Pos"]:
            buy_date = date
            buy_price = row["close"]
        elif row["Sell_Pos"]:
            sell_date = date
            sell_price = row["close"]
            
            trade_return = sell_price / buy_price - 1
            holding_days = (sell_date - buy_date).days
            
            trades.append({
                "buy_date": buy_date,
                "buy_price": buy_price,
                "sell_date": sell_date,
                "sell_price": sell_price,
                "holding_days": holding_days,
                "return": trade_return
            })

    return pd.DataFrame(trades)

if __name__ == "__main__":
    main()
