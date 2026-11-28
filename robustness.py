"""
Robustness test: the same frozen rule on 6 markets that were NOT in the original universe.

The live book stays on the 8 original markets (RULES.md is frozen). This script only asks:
does the rule also work on markets I did not use to build it?
New markets: FTSE 100, Nikkei 225, UK Gilt, JGB, GBP/USD, AUD/USD (Bloomberg, 1996-2026).

Run:  python robustness.py   (after backtest.py)
"""
import glob
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import backtest as bt

Q = bt.QUARTERLY
NEW_MARKETS = {
    "Z":  ("FTSE 100", "Equity", Q, 2),
    "NK": ("Nikkei 225", "Equity", Q, 2),
    "G":  ("UK Gilt", "Bond", Q, 1),
    "JB": ("Japan 10Y (JGB)", "Bond", Q, 1),
    "BP": ("GBP/USD", "FX", Q, 1),
    "AD": ("AUD/USD", "FX", Q, 1),
}
ORIGINAL = list(bt.MARKETS)
bt.MARKETS.update(NEW_MARKETS)          # the functions of backtest.py read this dict


def month_end(s):
    s.index = s.index + pd.offsets.MonthEnd(0)   # some files use the last business day
    return s


def rolled_return(code):
    x1 = month_end(bt.load_prices(code, 1))
    x2 = month_end(bt.load_prices(code, 2))
    roll = x1.index.month.isin(bt.MARKETS[code][2])
    return pd.Series(np.where(roll, x1 / x2.shift(1) - 1, x1 / x1.shift(1) - 1), index=x1.index)


if __name__ == "__main__":
    ret = pd.DataFrame({c: rolled_return(c) for c in bt.MARKETS})
    universes = {"Original 8 markets": ORIGINAL,
                 "6 new markets only": list(NEW_MARKETS),
                 "All 14 markets": list(bt.MARKETS)}

    rows, curves = [], {}
    for name, codes in universes.items():
        pnl, _ = bt.run_strategy(ret[codes])
        pnl = pnl.loc["1998-12-31":]                 # same start for the three books
        curves[name] = (1 + pnl).cumprod()
        for period, p in [("In-sample 1999-2015", pnl.loc[:bt.IN_SAMPLE_END]),
                          ("Out-of-sample 2016-2026", pnl.loc[bt.IN_SAMPLE_END:].iloc[1:]),
                          ("Full 1999-2026", pnl)]:
            s = bt.stats(p)
            rows.append({"Universe": name, "Period": period, "Sharpe": s["Sharpe"],
                         "t-stat": s["t-stat"], "Max drawdown": s["Max drawdown"]})
    table = pd.DataFrame(rows).set_index(["Universe", "Period"])
    print(table.round(2))
    table.round(3).to_csv("results/robustness_14_markets.csv")

    # each new market on its own (signed, vol-scaled), gross: does trend pay everywhere?
    alone = {}
    for c in NEW_MARKETS:
        p, _ = bt.run_strategy(ret[[c]])
        alone[bt.MARKETS[c][0]] = bt.stats(p.loc["1998-12-31":])["Sharpe"]
    alone = pd.Series(alone).sort_values()
    print("\nSharpe of each new market traded alone:\n", alone.round(2))

    plt.figure(figsize=(10, 5))
    for name, c in curves.items():
        c.plot(label=name, lw=2 if name.startswith("Original") else 1.5)
    plt.axvspan(pd.Timestamp(bt.IN_SAMPLE_END), c.index[-1], color="grey", alpha=0.15, label="Out-of-sample")
    plt.yscale("log"); plt.gca().yaxis.set_major_formatter(plt.ScalarFormatter())
    plt.gca().yaxis.set_minor_formatter(plt.NullFormatter())
    plt.yticks([1, 2, 4, 8], ["1", "2", "4", "8"])
    plt.title("Same frozen rule, different markets (growth of 1, after costs)")
    plt.legend(); plt.tight_layout(); plt.savefig("results/6_robustness.png", dpi=120); plt.close()
