# -*- coding: utf-8 -*-

import akshare as ak
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import time

def main():
    mpl.rc("font", family="SimSun")
    data = fetch_stock_data()

    data["date"] = pd.to_datetime(data["date"])
    data.sort_values("date", inplace=True)
    data.set_index("date", inplace=True)

    data["MA5"] = data["close"].rolling(window=5).mean()
    data["MA20"] = data["close"].rolling(window=20).mean()

    data["Signal"] = 0
    data.loc[data["MA5"] > data["MA20"], "Signal"] = 1

    data["Position"] = data["Signal"].shift(1).fillna(0)

    data["Market_Return"] = data["close"].pct_change()
    data["Strategy_Return"] = data["Market_Return"] * data["Position"]

    data["Market_Cum"] = (1 + data["Market_Return"]).cumprod()
    data["Strategy_Cum"] = (1 + data["Strategy_Return"]).cumprod()

    data["Buy"] = (1 == data["Signal"]) & (0 == data["Signal"].shift(1))
    data["Sell"] = (0 == data["Signal"]) & (1 == data["Signal"].shift(1))

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

    print("买入并持有最终收益倍数：", round(data["Market_Cum"].dropna().iloc[-1], 2))
    print("均线策略最终收益倍数：", round(data["Strategy_Cum"].dropna().iloc[-1], 2))
    print("交易次数：", int(data["Buy"].sum() + data["Sell"].sum()))
    
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

if __name__ == "__main__":
    main()
