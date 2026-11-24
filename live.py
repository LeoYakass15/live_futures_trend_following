"""
Live paper trading of the trend book, updated every weekend.

Every Friday I add the prices of the week to data/bloomberg/live/friday_prices.csv
(columns: date, market, x1, x2, rolled). x1 = price of the 1st contract, x2 = price of
the 2nd contract (only needed the week before a roll and on the last Friday of the month),
rolled = yes if the 1st contract changed since the previous Friday.

    python live.py week        -> P&L of the week, appended to results/live_pnl.csv
    python live.py positions   -> on the last weekend of the month: positions for next month

Both commands print a block to paste into LIVE.md.
"""
import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import backtest as bt

CAPITAL = 1_000_000       # paper capital in USD
PRICES = "data/bloomberg/live/friday_prices.csv"
POSITIONS = "results/positions_live.csv"
PNL = "results/live_pnl.csv"


def load_fridays():
    f = pd.read_csv(PRICES, parse_dates=["date"])
    f["rolled"] = f["rolled"].fillna("").str.lower().eq("yes")
    return f


def period_returns(f, d0, d1):
    """Return of each market between two Fridays. If the 1st contract changed in between,
    the contract we hold now was the 2nd contract at d0."""
    a, b = f[f.date == d0].set_index("market"), f[f.date == d1].set_index("market")
    base = np.where(b["rolled"], a["x2"].reindex(b.index), a["x1"].reindex(b.index))
    return pd.Series(b["x1"].values / base - 1, index=b.index)


def monthly_returns_with_live(f):
    """Bloomberg monthly history + the live months (last Friday of the month = month-end)."""
    ret = bt.load_returns()
    dates = sorted(f.date.unique())
    month_ends = [d for d in dates if d > ret.index[-1]
                  and (d == dates[-1] or pd.Timestamp(d).month != pd.Timestamp(dates[dates.index(d) + 1]).month)]
    prev = ret.index[-1]
    for d in month_ends:
        steps = [x for x in dates if prev < x <= d]
        r, last = 1.0, prev
        for x in steps:                                  # compound the weeks of the month
            r = r * (1 + period_returns(f, last, x))
            last = x
        ret.loc[pd.Timestamp(d)] = r - 1
        prev = d
    return ret


def new_positions():
    f = load_fridays()
    ret = monthly_returns_with_live(f)
    next_month = ret.index[-1] + pd.offsets.MonthEnd(1)
    ret.loc[next_month] = np.nan                       # empty row = the month to come
    _, weight = bt.run_strategy(ret)
    w = weight.iloc[-1]
    past_12m = (1 + ret.iloc[-13:-1]).prod() - 1
    start = pd.Timestamp(f.date.max()) + pd.Timedelta(days=3)  # Monday after the Friday
    table = pd.DataFrame({"from_date": start.date(), "market": w.index, "signal_12m_return": past_12m.round(4).values,
                          "weight": w.round(4).values, "notional_usd": (w * CAPITAL).round(-3).values})
    old = pd.read_csv(POSITIONS) if pd.io.common.file_exists(POSITIONS) else pd.DataFrame()
    pd.concat([old, table]).to_csv(POSITIONS, index=False)

    print(f"### Positions from Monday {start:%d %B %Y}\n")
    print("| Market | 12M return | Position | Weight | Notional (USD) |\n|---|---|---|---|---|")
    for _, row in table.iterrows():
        side = "Long" if row.weight > 0 else "Short"
        print(f"| {bt.MARKETS[row.market][0]} | {row.signal_12m_return:+.1%} | {side} | {row.weight:+.2f} |"
              f" {row.notional_usd:+,.0f} |")
    print(f"\nGross leverage: {table.weight.abs().sum():.2f}x")


def weekly_pnl():
    f = load_fridays()
    dates = sorted(f.date.unique())
    d0, d1 = dates[-2], dates[-1]
    r = period_returns(f, d0, d1)
    pos = pd.read_csv(POSITIONS, parse_dates=["from_date"])
    pos = pos[pos.from_date <= d1]
    current = pos[pos.from_date == pos.from_date.max()].set_index("market")["weight"]

    cost_bp = pd.Series({c: bt.MARKETS[c][3] for c in bt.MARKETS}) / 10_000
    cost = 0.0
    if pos.from_date.max() > d0:                           # new positions this week: trading cost
        older = pos[pos.from_date < pos.from_date.max()]
        before = older[older.from_date == older.from_date.max()].set_index("market")["weight"] \
            if len(older) else current * 0
        cost += ((current - before.reindex(current.index).fillna(0)).abs() * cost_bp).sum()
    rolled = f[f.date == d1].set_index("market")["rolled"]
    cost += (current.abs() * rolled.reindex(current.index).fillna(False) * 2 * cost_bp).sum()

    contrib = current * r.reindex(current.index)
    pnl = contrib.sum() - cost
    hist = pd.read_csv(PNL, parse_dates=["date"]) if pd.io.common.file_exists(PNL) else pd.DataFrame()
    hist = pd.concat([hist, pd.DataFrame({"date": [d1], "pnl": [round(pnl, 6)]})])
    hist["cumulative"] = ((1 + hist.pnl).cumprod() - 1).round(6)
    hist.to_csv(PNL, index=False)

    print(f"### Week ending {pd.Timestamp(d1):%d %B %Y}\n")
    print("| Market | Position | Weight | Price change | P&L (USD) |\n|---|---|---|---|---|")
    for m in current.index:
        side = "Long" if current[m] > 0 else "Short"
        print(f"| {bt.MARKETS[m][0]} | {side} | {current[m]:+.2f} | {r[m]:+.2%} | {contrib[m] * CAPITAL:+,.0f} |")
    print(f"\n**Week: {pnl:+.2%} ({pnl * CAPITAL:+,.0f} USD), costs {cost:.3%}. "
          f"Since launch: {hist.cumulative.iloc[-1]:+.2%}.**")
    live_chart(hist)


def live_chart(hist):
    """Live P&L against what the backtest expects (mean and 1 and 2 standard deviations)."""
    bt_pnl = pd.read_csv("results/monthly_pnl.csv", index_col=0)["pnl"]
    mu, sigma = bt_pnl.mean() * 12 / 52, bt_pnl.std() * np.sqrt(12) / np.sqrt(52)
    weeks = np.arange(0, max(52, len(hist)) + 1)          # the cone covers the first year
    live = np.r_[0, hist.cumulative.values] if len(hist) else np.array([0.0])
    plt.figure(figsize=(8, 4))
    for k, a in [(2, 0.12), (1, 0.25)]:
        plt.fill_between(weeks, mu * weeks - k * sigma * np.sqrt(weeks), mu * weeks + k * sigma * np.sqrt(weeks),
                         color="tab:blue", alpha=a, lw=0)
    plt.plot(weeks, mu * weeks, color="tab:blue", ls="--", label="Backtest expectation (1 and 2 std)")
    plt.plot(np.arange(len(live)), live, color="black", lw=2, marker="o", label="Live")
    plt.axhline(0, color="grey", lw=0.8)
    plt.xlabel("Weeks since launch"); plt.ylabel("Cumulative return"); plt.legend(loc="upper left")
    plt.title("Live vs backtest"); plt.tight_layout(); plt.savefig("results/5_live_vs_backtest.png", dpi=120)
    plt.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "chart":         # empty cone before the first week
        live_chart(pd.DataFrame({"cumulative": []}))
    elif len(sys.argv) > 1 and sys.argv[1] == "positions":
        new_positions()
    else:
        weekly_pnl()
