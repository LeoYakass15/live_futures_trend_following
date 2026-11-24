"""
Trend following on 8 futures (Moskowitz, Ooi and Pedersen, 2012).

Rule: each month-end, long a future if its 12-month return is positive, short if not.
Each market is sized to 10% volatility, then the whole book is scaled to 10% volatility.

Run:  python backtest.py
Data: monthly Bloomberg prices of the 1st and 2nd contract (data/bloomberg/, not published).
"""
import glob
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import norm, skew, kurtosis
import statsmodels.api as sm

# ---------------------------------------------------------------- settings
QUARTERLY = [3, 6, 9, 12]
MARKETS = {  # code: (name, asset class, months when the 1st contract rolls, one-way cost in bp)
    "ES": ("S&P 500", "Equity", QUARTERLY, 1),
    "VG": ("Euro Stoxx 50", "Equity", QUARTERLY, 2),
    "TY": ("US 10Y Treasury", "Bond", QUARTERLY, 1),
    "RX": ("German Bund", "Bond", QUARTERLY, 1),
    "EC": ("EUR/USD", "FX", QUARTERLY, 1),
    "JY": ("JPY/USD", "FX", QUARTERLY, 1),
    "CL": ("WTI crude oil", "Commodity", list(range(1, 13)), 3),
    "GC": ("Gold", "Commodity", [2, 4, 6, 8, 10, 12], 2),
}
LOOKBACK = 12        # months, the signal
VOL_WINDOW = 24      # months, to estimate volatility
TARGET_VOL = 0.10    # per market and for the book
IN_SAMPLE_END = "2015-12-31"   # 2016-2026 is the frozen out-of-sample period


# ---------------------------------------------------------------- 1. data
def load_prices(code, contract):
    file = glob.glob(f"data/bloomberg/{code.lower()}{contract}_monthly_*.csv")[0]
    return pd.read_csv(file, index_col=0, parse_dates=True)["last"]


def rolled_return(code):
    """Monthly return of a trader who always holds the 1st contract.
    In a roll month the old contract has expired, so the contract we hold at the end
    of the month was the 2nd contract last month: return = X1(t) / X2(t-1) - 1."""
    x1, x2 = load_prices(code, 1), load_prices(code, 2)
    roll = x1.index.month.isin(MARKETS[code][2])
    r = np.where(roll, x1 / x2.shift(1) - 1, x1 / x1.shift(1) - 1)
    return pd.Series(r, index=x1.index)


def load_returns():
    return pd.DataFrame({code: rolled_return(code) for code in MARKETS})


def roll_flags(index):
    return pd.DataFrame({c: index.month.isin(MARKETS[c][2]) for c in MARKETS}, index=index)


# ---------------------------------------------------------------- 2. strategy
def run_strategy(ret, lookback=LOOKBACK, vol_window=VOL_WINDOW, target=TARGET_VOL):
    """Returns the monthly P&L of the book (after costs) and the weights held each month.
    If the last row of ret is empty (next month), its weights are the positions to take now."""
    past_return = (1 + ret).rolling(lookback).apply(np.prod, raw=True) - 1
    signal = np.sign(past_return)                                   # +1 long, -1 short
    vol = ret.rolling(vol_window, min_periods=12).std() * np.sqrt(12)
    n_markets = signal.notna().sum(axis=1)
    raw_weight = signal * (target / vol)
    raw_weight = raw_weight.div(n_markets, axis=0)                  # equal risk per market

    # weights decided at the end of month t are held during month t+1 (no look-ahead)
    raw_weight = raw_weight.shift(1)
    raw_pnl = (raw_weight * ret).sum(axis=1, min_count=1)

    # scale the whole book to 10% vol, using only past months
    book_vol = raw_pnl.rolling(vol_window, min_periods=12).std() * np.sqrt(12)
    scale = (target / book_vol).shift(1).clip(upper=4)
    weight = raw_weight.mul(scale, axis=0)

    gross = (weight * ret).sum(axis=1, min_count=1)
    cost_bp = pd.Series({c: MARKETS[c][3] for c in MARKETS}) / 10_000
    trading = (weight.diff().abs() * cost_bp).sum(axis=1)
    rolling = (weight.abs() * roll_flags(ret.index) * 2 * cost_bp).sum(axis=1)
    pnl = (gross - trading - rolling).where(gross.notna()).dropna()
    return pnl, weight


# ---------------------------------------------------------------- 3. statistics
def stats(pnl):
    n = len(pnl)
    sr = pnl.mean() / pnl.std() * np.sqrt(12)
    nav = (1 + pnl).cumprod()
    return {
        "Return (ann.)": pnl.mean() * 12,
        "Vol (ann.)": pnl.std() * np.sqrt(12),
        "Sharpe": sr,
        "t-stat": sr * np.sqrt(n / 12),       # = mean / (std / sqrt(n))
        "Max drawdown": (nav / nav.cummax() - 1).min(),
        "Skew": skew(pnl),
        "Months": n,
    }


def deflated_sharpe(pnl, trial_sharpes):
    """Bailey and Lopez de Prado (2014). Probability that the true Sharpe is above zero,
    knowing we tried N versions (trial_sharpes, monthly Sharpes of every trial)."""
    n_trials = len(trial_sharpes)
    sr = pnl.mean() / pnl.std()                                     # monthly Sharpe
    euler = 0.5772
    sr0 = np.std(trial_sharpes, ddof=1) * ((1 - euler) * norm.ppf(1 - 1 / n_trials)
                                           + euler * norm.ppf(1 - 1 / (n_trials * np.e)))
    g3, g4 = skew(pnl), kurtosis(pnl, fisher=False)
    z = (sr - sr0) * np.sqrt(len(pnl) - 1) / np.sqrt(1 - g3 * sr + (g4 - 1) / 4 * sr ** 2)
    return norm.cdf(z), sr0 * np.sqrt(12)


# ---------------------------------------------------------------- 4. main
if __name__ == "__main__":
    ret = load_returns()
    ret.to_csv("data/bloomberg/rolled_returns.csv", float_format="%.6f")
    is_ret = ret.loc[:IN_SAMPLE_END]

    # every version I try goes into the trials log, good or bad
    trials = []
    for lb in [1, 3, 6, 9, 12]:
        for vw in [12, 24, 36]:
            pnl_is, _ = run_strategy(is_ret, lb, vw)
            s = stats(pnl_is)
            trials.append({"lookback": lb, "vol_window": vw, "sharpe_in_sample": round(s["Sharpe"], 3),
                           "t_stat": round(s["t-stat"], 2), "monthly_sharpe": pnl_is.mean() / pnl_is.std()})
    trials = pd.DataFrame(trials)
    trials.drop(columns="monthly_sharpe").to_csv("results/trials_log.csv", index=False)

    # the pre-registered rule (12M signal, 24M vol), full history
    pnl, weight = run_strategy(ret)
    pnl_is, pnl_oos = pnl.loc[:IN_SAMPLE_END], pnl.loc[IN_SAMPLE_END:].iloc[1:]
    dsr, lucky_sr = deflated_sharpe(pnl_is, trials["monthly_sharpe"])

    table = pd.DataFrame({"In-sample": stats(pnl_is), "Out-of-sample": stats(pnl_oos), "Full": stats(pnl)})
    print(table.round(3))
    print(f"\nTrials: {len(trials)} | Sharpe the best trial would show by luck: {lucky_sr:.2f}"
          f" | Deflated Sharpe (in-sample): {dsr:.2f}")
    table.round(3).to_csv("results/summary.csv")
    pd.Series({"n_trials": len(trials), "lucky_sharpe": round(lucky_sr, 3), "dsr_in_sample": round(dsr, 3)}
              ).to_csv("results/dsr.csv", header=False)
    pnl.to_csv("results/monthly_pnl.csv", header=["pnl"], float_format="%.6f")

    # contribution of each market (gross of costs)
    contrib = (weight.loc[pnl.index] * ret.loc[pnl.index]).sum() / len(pnl) * 12
    contrib.round(4).to_csv("results/contribution_by_market.csv", header=["return_per_year"])

    # regression on the S&P 500 future: is it alpha or hidden equity beta?
    sp = ret["ES"].loc[pnl.index].dropna()
    reg = sm.OLS(pnl.loc[sp.index], sm.add_constant(sp)).fit()
    print(f"\nRegression on S&P: alpha {reg.params['const'] * 12:.2%}/yr (t={reg.tvalues['const']:.2f}),"
          f" beta {reg.params['ES']:.2f} (t={reg.tvalues['ES']:.2f})")
    pd.Series({"alpha_per_year": reg.params["const"] * 12, "alpha_t": reg.tvalues["const"],
               "beta_sp500": reg.params["ES"], "beta_t": reg.tvalues["ES"], "r2": reg.rsquared}
              ).round(4).to_csv("results/regression_sp500.csv", header=False)

    # optional: AQR TSMOM factor (monthly, file sent by hand) to compare with the real thing
    aqr_file = glob.glob("data/aqr_tsmom.csv")
    if aqr_file:
        aqr = pd.read_csv(aqr_file[0], index_col=0, parse_dates=True).iloc[:, 0]
        aqr.index = aqr.index + pd.offsets.MonthEnd(0)
        both = pd.concat([pnl, aqr], axis=1, join="inner").dropna()
        print(f"Correlation with AQR TSMOM: {both.corr().iloc[0, 1]:.2f}")

    # crises: what does the book do when stocks fall?
    crises = {"Dot-com bear (Sep00-Sep02)": ("2000-09", "2002-09"), "GFC 2008": ("2008-01", "2008-12"),
              "Oil crash (Jul14-Jan15)": ("2014-07", "2015-01"), "Covid (Feb-Mar 2020)": ("2020-02", "2020-03"),
              "Inflation 2022": ("2022-01", "2022-12")}
    rows = []
    for name, (a, b) in crises.items():
        rows.append({"Crisis": name, "Trend book": (1 + pnl.loc[a:b]).prod() - 1,
                     "S&P 500 future": (1 + ret["ES"].loc[a:b]).prod() - 1})
    crisis = pd.DataFrame(rows).set_index("Crisis")
    print("\n", crisis.round(3))
    crisis.round(4).to_csv("results/crises.csv")

    # ------------------------------------------------------------ charts
    plt.figure(figsize=(10, 5))
    sp_scaled = ret["ES"].loc[pnl.index] * TARGET_VOL / (ret["ES"].std() * np.sqrt(12))
    (1 + pnl).cumprod().plot(label="Trend book (10% vol)", lw=2)
    (1 + sp_scaled.fillna(0)).cumprod().plot(label="S&P 500 future, scaled to 10% vol", alpha=0.7)
    plt.axvspan(pd.Timestamp(IN_SAMPLE_END), pnl.index[-1], color="grey", alpha=0.15, label="Out-of-sample")
    plt.yscale("log"); plt.gca().yaxis.set_major_formatter(plt.ScalarFormatter())
    plt.gca().yaxis.set_minor_formatter(plt.NullFormatter()); plt.legend(); plt.title("Growth of 1, after costs"); plt.tight_layout()
    plt.savefig("results/1_equity_curve.png", dpi=120); plt.close()

    plt.figure(figsize=(8, 4))
    contrib.rename(lambda c: MARKETS[c][0]).sort_values().plot.barh()
    plt.title("Return per year by market (gross)"); plt.tight_layout()
    plt.savefig("results/2_contribution.png", dpi=120); plt.close()

    plt.figure(figsize=(8, 4))
    trials.pivot(index="lookback", columns="vol_window", values="sharpe_in_sample").plot.bar()
    plt.ylabel("Sharpe, in-sample"); plt.title("The 15 trials: Sharpe by lookback and vol window")
    plt.tight_layout(); plt.savefig("results/3_trials.png", dpi=120); plt.close()

    crisis.plot.bar(figsize=(9, 4)); plt.axhline(0, color="black", lw=0.8)
    plt.title("Return during equity crises"); plt.xticks(rotation=20, ha="right"); plt.tight_layout()
    plt.savefig("results/4_crises.png", dpi=120); plt.close()
