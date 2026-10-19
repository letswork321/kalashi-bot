# BTC PRO V3 — Implementation and launch contract

This is a **build requirement**, not permission to misrepresent incomplete features. Review the entire existing repository on branch `btc-pro-v3-live-chart-callouts` and build on top of the current fixes, starting from its latest head. Do not base work on main or older `windows-dashboard-setup`. The existing branch is based on commit `fead361e6cd8e4212ff083c6976ecd2c9c28615f`. It already contains initial plain-English BTC callout tracking, compact top callout summary, 1m/5m historical collection, and tests; validate and fix those before adding features.

## Nonnegotiables
- Windows Python 3.12, Flask/Waitress on http://127.0.0.1:8000, Chrome, Telegram, SQLite `data/live.sqlite3`. No unnecessary Node/Docker installation on the *user's* laptop.
- Trade execution is **MANUAL ONLY**: no account orders, cash access, trading endpoints, portfolio or login automation. Authentication for *market-data-only* sockets must be isolated server-side with keys off GitHub, off Chrome and off alert text. Resolve outstanding Windows malware/Defender issue before requesting sensitive credentials.
- DO NOT modify/delete the currently running local folder or its SQLite. Develop separately. Before Windows patch, gracefully stop only the local scanner, use SQLite online backup, integrity-check the backup, migrate additively, and support rollback. One DB writer per installation; do not start two scanners on the same DB.
- Never invent live BTC prices, Kalshi BRTI readings, timeframes, candles, quotes, trend strengths, probability/confidence percentages, implied profitable fills or model test results. Unverified => WAIT / STALE / UNAVAILABLE. Never call a heuristic score "85% confidence".
- Report latency from **data event timestamp** versus current time, not just last successful HTTP receipt. Show precise stream status: Coinbase spot, BRTI settlement benchmark, and Kalshi orderbook must be named separately.
- User's usual desire: take **60–90% net profit on stake before settlement**. This is a desired target, **not** a prediction or guarantee. The engine must also support smaller exits and occasional settlement analysis. Trading quality should emphasize after-fee positive expected value and risk, not simply maximizing win rate.
- UI is **compact and glanceable** on one second monitor. The top displays CALLER / NOW, ENTER/WAIT/AVOID when validated, contract side, expected target *if validated*, confidence status, countdown, fresh live candle chart, odds, and two tiny score cards. Technical diagnostics, advanced analytics, model audits, long tables, history and settings start collapsed.
- Telegram callouts must be readable in less than ~5 seconds, like "DOWN momentum building — WATCH. BTC broke support; selling pressure is rising; 1m and 5m trends agree. Entry: WAIT for confirmation. Exit: Not validated." Include original ticker, timestamp, time remaining, and data age as a short trailing line. Rate-limit, dedupe and expire alerts; never send a stale entry signal.

## Work streams / all 26 areas
1. TradingView **Lightweight Charts** professionally embedded with correct notice/attribution and tested chart resizing. Self-host the pinned package to avoid runtime CDN dependence. Use its current v5 `addSeries(CandlestickSeries)` API; do not guess obsolete APIs. No need for the retail TradingView website or Webull.
2. Real BTC 1m/5m/15m candles (optional 15s only when continuous tick coverage exists), OHLCV source timestamps, developing last candle from genuine intraperiod trades only. No synthetic 15s from REST candles.
3. Coinbase **streaming** BTC-USD trade feed for rapid BTC spot and volume; reconnect/resync, stale detection, sequence and clock checks. Compare to Coinbase REST as fallback. Show not-LIVE if only slow updates available.
4. Optional authenticated **Kalshi read-only WebSocket** for sequenced YES/NO orderbook, accurate executable bid/ask, depth and fees. Ensure proper events and after-reconnect snapshot, no trading APIs.
5. CF Benchmarks **BRTI** official feed from Kalshi when entitled; distinguish CF stream from Coinbase; use official market strike and 60-second settlement-average logic. If BRTI unavailable, label clearly and do not claim Coinbase==settlement index.
6. Market condition panel / exact KXBTC15M ticker, opening and closing time, official strike, spread, order depth, remaining time; verify market discovery at boundary.
7. Clean compact dashboard: principal decision, caller explanation, possible entry/exit, expected movement, 1m/5m/15m chart, market data health, tiny lifetime settlement and callout score. Hide advanced research.
8. EMA9/21/50, RSI14, MACD, authentic trade-weighted VWAP, volume, support/resistance, trend lines, optional Bollinger, and trend-strength labels, while avoiding chart clutter.
9. Plain-language BTC Caller engine: evaluate actual confirmed breakouts/breakdowns, 1m/5m agreement, direction, momentum, volatility, volume, liquidity and reversals; WATCH for heuristic-only context; ENTER/AVOID only if forward-validated economic edge and executable quotes.
10. Independent trend-following, breakout, mean-reversion, failed breakout, momentum, order-flow and liquidity modules. Keep original 3 strategies independent. Distinguish spot patterns from tradable Kalshi contract forecasts.
11. Model comparisons: preserved heuristic baseline, logistic regression, gradient-boosted models, market-implied baseline; chronological walk-forward and held-out, leakage/overfit prevention, calibration.
12. Early-exit contract bid-price forecast for 20/40/60s and later horizons where validated; do not extrapolate from a small price slope and call that a statistically accurate target.
13. Estimated contract movement (e.g., multiplier 2.50x toward 1.73x) with honest prospective probability/range/time-to-target based on observed contract **sellable BID**, not Coinbase spot alone.
14. Entry quality classifier ENTER / WAIT / AVOID using spread, available depth, BTC trend, Kalshi bid and ask, taker fees, slippage and time left; no entry if unvalidated.
15. Early exit rules for user-configurable 60–90% *net-on-stake* target plus milestones (including +65%), deteriorating trend and risk conditions; never claim to observe user's actual stake unless explicitly input.
16. Paper positions entered after realistic alert/decision delay using observed executable asks, exited with observed executable bids; track misses and slippage. Do not use high-of-window as fill.
17. Separate true profit score versus BTC callout directional score versus fixed-time locked settlement prediction score, all persistent.
18. Plain-English Telegram alerts for trend WATCH, validated entry only when supported, exit alerts when watch position has user-supplied entry basis, invalidations, settlement, daily summaries; selectable settings, dedupe, stop spam.
19. BTC Caller **outcome tracker**: persist original sent callout timestamp/side/spot/target/horizon/source; evaluate strictly using subsequently observed live ticks, not retroactively backfilled highs. Display compact HIT–NOT HIT, hit rate and MISSED / UNSCORED; show definition and history. Avoid conflating WATCH accuracy with trading P&L.
20. Win/loss tracker +60s immutable original 15m settlement forecasts: All time default, official settlement only, no counterfeit lost history; preserve lifetime DB.
21. Historical research: hourly/weekday/weekend/regime patterns with minimum sample counts, uncertainty, liquidity effects, model drift; experiment separately on disjoint data.
22. Data-quality center: source delay, WebSocket sequence, tick cadence, quote age, fee validity, data gaps, alert delivery and misses. A safe stale feed must suppress recommendations.
23. Independent optional alerts controlled from the local protected dashboard; no credentials in web response; retain already-working Telegram token/private setup.
24. Continuous live collection and paper comparison (no auto-learning claims); persist enough raw observations for backtests, bounded retention and backups.
25. CLI/Windows setup/patch preserving Python NuGet `%USERPROFILE%\Downloads\python.3.12.10\tools\python.exe`, existing `.venv`, database, credentials, local-only dashboard.
26. Launch verification: enough documented simulated events and real market samples to demonstrate live timestamps, 1m/5m/15m chart updates, consistent Kalshi tickers and quote behavior, time-locks, chart callouts, expected missing-data handling, Telegram mock tests and Windows rollback.

## Required chart accuracy
- A professional-looking candlestick chart that shows 5-minute-delayed data as "LIVE" **fails**. Add a continuously updated genuine intrabar candle with event-time-stamped ticks, and a red "STALE" mask if source ticks stall for a small tested threshold (e.g., 3s) instead of painting unverified new bars.
- Show price source right on the chart: Coinbase BTC-USD vs official BRTI; do not silently substitute one for the other.
- 1m is main trade view; 5m confirms trend; 15m provides context; keyboard/button timeframe switching stays within same chart footprint. Indicators toggled rather than sprawling vertically.
- If source access, price timestamp, spread, or tick coverage is insufficient, NO recommendation, NO measured entry edge and NO invented target.
- Technical and perceived "big caller" setups are candidates to *evaluate*, not magic/guaranteed signals. Track every forecast as issued, including misses.

## Callout scoring acceptance
- One immutable prediction event only, not modified after future outcome. Telegram send acknowledgment is distinct from phone read.
- Freeze direction/time/spot/target/horizon on alert issuance.
- Clearly label whether the score means hit sometime inside the prediction window or exactly at its end; do not mix those denominators. The early prototype in `intelligence/callouts.py` currently chooses an **exact 3-minute endpoint with >=0.05% move** and 10s tolerance, which is a research placeholder. Replace or add a second immutable **path-target-hit** metric using continuously observed ticks with gap detection for a user-relevant "move soon" forecast, leaving early records labeled by metric/version.
- Missed quote observations and delayed/unacknowledged Telegram do not count as wins/losses.
- Score 0–0 until genuine acknowledged forward events settle; never seed it with guesses.

## Release requirements
1. Inspect latest HEAD and list changes already present; repair tests and frontend as necessary. Verify no branch-to-branch code regression.
2. Implement missing streams, candlestick chart, scoring refinements, algorithms and simplified Telegram; do not claim partial scaffold is finished.
3. Test unit/integration suites, lint/compile all Python/JS, backend API data, source freshness, authenticated settings, safety invariants and persistence. Verify browser screenshot manually when possible.
4. Provide tested commit SHA and Windows **one-shot backup-preserving patch** instructions. Do not tell the user to stop working local scanner until we have a truly ready build. Do not disable Windows security.
5. State specifically what LIVE feed and profitable strategy remains unverified. No statement of proven profitability until sufficient genuinely forward-tracked after-fee samples.


## Research addendum — proposed quantitative algorithms (October 18, 2026)

User supplied a third-party "15-minute Kalshi quant architecture" document. Audit its suggestions before coding any of them. This section is **research-only / gated experimentation**, not proof that a named strategy works.

### Include as testable, independent candidates

**A. Settlement-average-aware probabilistic pricer.** Current `scanner.forecast_components` already computes a normal-CDF/GBM-like directional heuristic with drift, volatility and book consensus; keep it as the baseline. Develop a separately named, *time-consistent* fair-value estimator that uses official `floor_strike` and the fact that settlement is the **arithmetic mean of sixty 1-second BRTI index readings in the final minute**, not just final Coinbase spot. For the final minute, where authenticated BRTI data is actually available, use a simple arithmetic running sum of observed index prices and estimate the unknown remaining readings. Do not use volume-weighted average of "index components" as a substitute or imply settlement is already guaranteed while future index samples remain. If BRTI stream/permissions unavailable, label the index-specific model unavailable. If historic BRTI is inaccessible, do not fabricate accuracy. Any benchmark comparison should be on the *same markets* and as-of observation times.

**B. Monte Carlo and jump/volatility sensitivity.** Add an optional reproducible, seed-controlled simulation *in Python* comparing (i) normal-CDF diffusion baseline, (ii) event-window arithmetic-average GBM path simulation, (iii) stress-tested jump or heavy-tail variants, (iv) market-implied quote. 10,000 paths is a simulation-size choice, not a magic accuracy boost; convergence and input calibration matter. Use observed 1m/5m volatility and varying intraround regimes, with explicit annualization/time units, scenario confidence intervals and OOS calibration tests. Never label risk-neutral Black-Scholes `N(d2)` as "true" or objectively correct trading probability; under the settlement-average rule ordinary terminal-value digital `N(d2)` is not the exact payoff model.

**C. Kalshi market-lifecycle regime study.** Segment observed 15m markets into 0–5 / 5–10 / 10–15 minutes *as hypotheses*, then statistically compare spread, executable bid-ask, depth, volatility, available paper early-exit P&L, and missed fills. Do not assume the center segment always has the best prices or that later liquidity always disappears. Evaluate regime-conditioned strategy performance with adequate independent market sample sizes.

**D. "Panic fade" and cross-exchange lead–lag WATCH research.** Record BRTI/Coinbase spot impulses, Kalshi quote movements and late-round prices. Forward test whether a >85¢ contract in the late minutes is actually too expensive given remaining index/spot volatility **after fees and spread**. Do not claim 85% implies retail panic or automatic value. Examine purported crypto spot lead → Kalshi book lag using timestamp-correct recordings and realistic manual order-delay assumptions; do not pretend a human can capture millisecond market-making/latency arbitrage. Do not present a profitable edge until holdout and live forward results exist.

**E. Conservative risk and sizing information (manual-only).** Show expected loss scenarios, max exposure, proposed stop/invalidated setup, worst-case loss, and a configurable stake cap. Optional fractional-Kelly *informational* comparison may be researched ONLY after calibrated post-fee P&L distributions exist. Standard binary bet Kelly formulas estimate hold-to-settlement bet fractions and do not apply unchanged to early cash-outs or uncertain stop fills; default to no calculated Kelly recommendation until appropriate validated inputs exist.

### Reject as mismatched/unproven
- **No Avellaneda–Stoikov market-maker engine** for an alert-only human trading manually. Its reservation-price quoting/inventory model is for active two-sided market makers, not evidence of profitable directional entries.
- **No Redis/multiprocess rewrite** solely because a generic article recommends it. The existing Windows app can use independent Python feed collectors, queues and SQLite with tests. Only consider Redis after measured and reproducible throughput problems.
- **Absolutely no execution worker / account trading / real-money order placement / order cancellation automation / cash access.** Respect user's manual-only requirement, even if another AI's draft calls for RSA-PSS trading endpoints.
- Do **not** implement the pasted proposed `abs(P_fair - P_market) - fee` as a trade signal. It can overstate a buy opportunity when model price is *below* ask, and it ignores sell-side costs. Compute side-specific actionable economics from realistic executable prices and costs. For user early cash-out, predict distribution of future observable **sell bids**, not simply settlement P_fair.
- No guarantee of a consistent 60–90% return, 75% win rate, or uninterrupted low-latency profit by using fancy math. Separate model uncertainty from real sample-based predictive confidence.

Evaluation bar: real forward timestamped observations, persistent original forecasts, all abstentions and misses retained; out-of-sample per-regime results, realistic quotes/delay/fees, and independent caller score versus simulated early-exit profitability. Do not prematurely promote an unverified research strategy into an ENTER Telegram recommendation.
