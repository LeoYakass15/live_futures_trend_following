# Rules of the live book (frozen on 24 November 2026)

These rules are written before the first live trade. If I change one, the book becomes
"v2" and starts a new track record. I never rewrite the past.

1. **Markets**: S&P 500 (ES), Euro Stoxx 50 (VG), US 10Y (TY), Bund (RX), EUR/USD (EC), JPY/USD (JY), WTI (CL), Gold (GC). Always the 1st contract.
2. **Signal**: sign of the 12-month return, rolled futures, measured on the last Friday of the month.
3. **Size**: 10% volatility per market (24 months of monthly returns), equal risk, then the book is scaled to 10% volatility. Same code as the backtest (`backtest.run_strategy`).
4. **Rebalancing**: once a month. New positions on the Monday after the last Friday of the month. No change during the month, whatever happens.
5. **Prices**: Bloomberg 1st contract, photo taken on Friday. Not always the official close (the US closes at 22:00 Paris time). The time of the photo is written in LIVE.md.
6. **Roll**: when the 1st contract expires during the week, the return is computed from the 2nd contract of the previous Friday. I list the contracts to roll every Thursday.
7. **Costs**: same as the backtest, 1 to 3 bp per trade and two trades per roll.
8. **Capital**: 10,000,000 USD on paper. P&L in USD and in % of capital.
9. **Publication**: positions are committed to GitHub before Monday 09:00 Paris time. The commit time stamp is the proof.
10. **No discretion**: I report every week, good or bad. A missed Friday is written as missed, and the P&L is carried to the next week.
