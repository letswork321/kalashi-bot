# BTC PRO V5 — MASTER BUILD & LAUNCH INSTRUCTIONS

**Repository:** `letswork321/kalashi-bot`  
**Starting branch:** `btc-pro-v4-intelligence`  
**New branch:** `btc-pro-v5-accuracy-intelligence`

I am ready to begin building and launching BTC Pro V5 immediately.

This must be a MAJOR improvement focused on developing genuinely smarter predictions for Kalshi's KXBTC15M Bitcoin 15-minute markets.

**MY #1 PRIORITY IS ACCURACY AND MARKET INTELLIGENCE.**

I do NOT want another professional-looking dashboard with the same V3 prediction algorithm underneath it.

I want a new system that analyzes Bitcoin price action, volume, volatility, market structure, technical indicators, order flow, liquidity, potential reversals, and the official Kalshi settlement mechanics before making its own independent prediction.

My ultimate goal is to achieve approximately 75% prediction accuracy or better, but you must not fabricate that accuracy, overfit data, or claim an improvement without evidence.

My trades remain 100% MANUAL. No automated order execution, no access to funds, and no trading permissions.

---

## 1. CRITICAL — Build a genuinely new independent V5 prediction engine

Inspect the current production formula in `scanner.py` and related scheduler code.

The existing model uses approximately:

- 60% BTC price/strike calculation
- 40% Kalshi market-implied probability
- Small adjustments from momentum, RSI, volume and orderbook imbalance

I strongly suspect it frequently follows whichever side Kalshi already favors.

**THIS MUST CHANGE IN V5.**

Build a completely new directional forecasting engine that independently predicts whether BTC will settle UP or DOWN relative to the official Kalshi target.

The initial directional forecast must NOT use Kalshi YES/NO odds, contract payouts or the current favorite as directional inputs.

Instead, determine the predicted outcome through independent BTC/BRTI market evidence.

Only AFTER generating the independent prediction should the bot compare it with Kalshi contract prices and implied probabilities to evaluate potential trading value.

Track disagreements between V5 and the Kalshi favorite. V5 should disagree when the evidence supports disagreement, not just to pick underdogs.

All new market-intelligence features must genuinely influence V5's forecasting logic where validated, rather than merely appearing on the dashboard.

V5 needs its own model version, prediction database records, live forecasts, Telegram alerts and independently scored performance history.

Do not label the unchanged V3 baseline as a new V5 model.

---

## 2. CRITICAL — Prioritize making an initial UP/DOWN prediction EVERY round

I DO NOT want a new NO CALL filter causing many rounds to be skipped.

My preference is to receive an initial directional opinion, even if it sometimes turns out wrong, and then use updated 3-, 5- and 10-minute predictions to decide whether to hold, enter, avoid or cash out manually.

Implement the following:

- At approximately +60 seconds into every valid KXBTC15M round, issue and permanently record a V5 UP or DOWN forecast.
- When indicators disagree but the minimum verified forecasting inputs are available, still generate the model's favored direction and label its conviction LOW rather than skipping the round.
- Keep directional forecasts separate from trade recommendations. For example, the model can predict UP while recommending WAIT because the price is unfavorable or the evidence is weak.
- Reserve NO CALL for genuinely unusable, missing, invalid or excessively stale essential data where a defensible forecast cannot be generated.
- Never fabricate a prediction or silently use stale prices to improve prediction coverage.
- Record MISSED separately when the system fails to deliver the scheduled forecast before its technical deadline.
- Track prediction coverage, low-conviction accuracy, technical misses and genuine data-based abstentions separately.
- Do not widen or manipulate historical prediction deadlines to improve the reported record.

I want significantly fewer preventable technical misses without hiding them.

---

## 3. NEW — Four independently scored predictions per 15-minute round

Every market must have four prediction checkpoints:

**Checkpoint 1 — +1 minute**

- Original immutable UP/DOWN prediction
- Independent V5 probability estimate
- Model version and confidence/conviction status
- Strongest supporting evidence
- Strongest conflicting evidence
- Official strike, BTC/BRTI reference price, and time remaining
- Permanently retained even if the prediction subsequently changes

**Checkpoint 2 — +3 minutes**

- Reevaluate the entire market using updated data
- Issue a new independently scored UP/DOWN prediction
- Identify whether direction changed
- Explain what changed in market conditions
- Show potential reversal or increased conviction

**Checkpoint 3 — +5 minutes**

- Reevaluate momentum, volume, support/resistance, liquidity, order flow, volatility and market structure
- Record a new UP/DOWN opinion
- Explain whether the original prediction is strengthening or weakening
- Highlight reversal and cash-out risks where relevant

**Checkpoint 4 — +10 minutes**

- Analyze the remaining five minutes, strike distance, volatility, BRTI, momentum and potential settlement outcomes
- Issue the final scheduled updated UP/DOWN prediction
- Explain any major direction changes
- Evaluate whether changing market conditions increase the risk of continuing to hold a position

All four checkpoints must have separate immutable records and independent accuracy statistics.

Do not overwrite the original prediction.

Run the checkpoints using the market's official opening timestamp, not a guessed time or an arbitrary polling interval.

---

## 4. CRITICAL — Telegram notifications at all four checkpoints

Use my existing Telegram bot configuration and securely preserve its credentials when possible.

Automatically send a Telegram notification at:

- +1 minute
- +3 minutes
- +5 minutes
- +10 minutes

Each notification must include:

- BTC Pro V5 and market ticker
- Current checkpoint
- Original locked prediction
- Latest updated prediction
- UP/DOWN direction
- Estimated probability where defensibly calibrated; otherwise clearly marked uncalibrated
- Strongest bullish and bearish evidence
- Whether the forecast changed from UP to DOWN or DOWN to UP
- Official strike
- Current BRTI price if verified, otherwise labeled proxy price
- Time remaining
- Data freshness and model version
- Any serious reversal warning
- Relevant manual-position cash-out information, if I have entered a position in the dashboard

**Important:** A changed prediction is not proof that the earlier prediction was wrong. Official settlement determines prediction accuracy.

Alerts must be delivered promptly, deduplicated across restarts, and configurable by category/checkpoint.

Keep separate optional notifications for significant market reversals, entry watches, manual cash-out opportunities, target touches, liquidity warnings, settlement results and daily performance.

Do not flood Telegram with repeated identical warnings.

Telegram messages must not say a trade was executed or cashed out automatically.

---

## 5. Advanced multi-timeframe Bitcoin market analysis

The bot needs to continuously examine real 1-minute, 5-minute and 15-minute BTC charts together.

Implement and evaluate:

- Higher highs and higher lows
- Lower highs and lower lows
- Trending versus sideways/choppy markets
- Trend strength
- EMA 9, 20/21 and 50 where supported
- EMA crossovers and separation
- RSI 14 and useful timeframes
- MACD momentum and divergence
- VWAP and price distance from VWAP
- Bollinger Bands
- Momentum acceleration and deceleration
- Actual completed candle closes
- Candle body-to-wick ratios
- Large bullish/bearish candles
- Trend exhaustion
- Multi-timeframe agreement and disagreement
- Actual volatility and volatility regime changes
- Market reaction at important technical levels

Do not blindly assume that all indicators need to agree.

Develop testable evidence combinations and investigate which features contribute measurable predictive value.

Use timestamp-correct data and prevent future candles from leaking into earlier historical predictions.

---

## 6. Volume analysis and real buying/selling pressure

Volume is extremely important.

A BTC price increase without genuine buying strength may be weaker than it appears.

The bot must measure:

- Current volume versus normal historical volume
- Volume spikes and declining volume
- Volume-price divergence
- Buying and selling aggression
- Buy/sell trade-size totals
- Cumulative Volume Delta (CVD)
- Volume supporting or contradicting breakouts
- Volume exhaustion
- Aggressive selling against rising prices
- Aggressive buying against falling prices
- Large trade clusters
- Changes in short-term order-flow pressure

Use actual available trade feeds and correct aggressor-side interpretation.

For Buy/Sell Pressure, provide useful 15-second and 60-second measurements, with optional longer comparisons if reliable.

Identify when short-term pressure is strengthening, weakening or reversing.

**Redesign the Buy/Sell Pressure dashboard** with clear compact horizontal BUY versus SELL bars, actual measured percentages or quantities, timestamps and source-quality status.

Do not show meaningless percentages when trade continuity is unavailable.

---

## 7. Support, resistance and price-action intelligence

Identify important technical levels rather than treating every BTC move equally.

Implement:

- Recent swing highs and lows
- Important support/resistance levels
- Previous breakout/rejection levels
- Retests
- Breakout confirmation
- Failed breakouts
- Repeated level tests
- Price rejection
- Trend continuation versus reversal evidence
- Liquidity zones
- Stop-run/liquidity-sweep-like price patterns

Use historical completed candles and timestamped trade data.

Test whether breakouts are more likely to succeed or fail under different volume, momentum, volatility and liquidity conditions.

Detect large green or red candles where chasing momentum may be risky.

The model should recognize when BTC is moving into resistance or support and adjust its evaluation accordingly.

---

## 8. Potential manipulation, abnormal trading and fakeout analysis

The bot must observe unusual market behavior, including:

- Sudden BTC price spikes that reverse within seconds
- Sudden crashes followed by rapid rebounds
- Long candle wicks
- False breakouts
- Repeated liquidity sweeps
- Sudden volume spikes without sustained directional movement
- Orderbook liquidity appearing and disappearing
- Abnormally large trades
- Rapid changes in visible orderbook depth
- Cross-exchange price disagreement
- Unusually sharp moves during low-volume periods
- Buying/selling aggression that contradicts price movement

Research techniques for distinguishing ordinary volatility from unusual price-action anomalies.

Where verified sequenced orderbook data exists, analyze rapid order cancellations and depth changes.

Do not claim spoofing or manipulation is proven from chart patterns. These are warnings and research features, not confirmed findings of trader intent.

The bot should consider these patterns as potential risk factors in predictions only when the historical evidence supports their value.

---

## 9. Kalshi settlement intelligence — BRTI is critical

The KXBTC15M market outcome depends on the official CF Benchmarks Bitcoin Real-Time Index, not simply the last Coinbase spot price.

Inspect and improve the existing `BRTIStream` integration.

Investigate authenticated Kalshi BRTI WebSocket access and authorized historical benchmark data.

Where access is available and validated:

- Record official live BRTI values
- Compare BRTI to Coinbase spot
- Analyze differences between them
- Track distance from the official strike
- Track time remaining
- Correctly model the final-minute averaging mechanics
- Use historical benchmark behavior for settlement-aware model development
- Investigate how strike distance interacts with volatility and remaining time

When official BRTI is unavailable, use a clearly labeled proxy if appropriate, never fabricate official benchmark observations.

Study and respect the current Kalshi market rules, target-price metadata, settlement timing and official outcomes.

Do not substitute contract market prices for independent settlement forecasting.

---

## 10. Cross-exchange data, orderbooks, liquidity and unusual transactions

Investigate reliable public feeds from Coinbase and other major BTC exchanges where access permits.

Compare significant moves across exchanges to identify possible isolated exchange anomalies.

Monitor:

- Genuine trade volume and aggressor flow
- Large trades
- Orderbook depth
- Liquidity withdrawal and replenishment
- Bid/ask spreads
- Orderbook imbalance
- Kalshi executable bid/ask prices
- Liquidity near important levels
- Available verified futures-liquidation snapshots
- Funding and open interest only if trustworthy data sources are available

Keep Kalshi contract odds separate from the independent BTC direction model. Kalshi prices and executable liquidity should be used afterward for entry-quality evaluation and trading-risk analysis.

Do not fabricate unavailable whale identities, liquidation totals or cross-exchange readings.

---

## 11. Different strategies for different market conditions

One strategy should not blindly operate identically during all market conditions.

Develop and evaluate distinct, measurable approaches for:

- Strong bullish trends
- Strong bearish trends
- Sideways/ranging markets
- High-volatility reversals
- Low-volume periods
- False breakout conditions
- Momentum continuation
- Exhaustion near support/resistance
- Large distance from strike
- Small distance from strike
- Early versus late round conditions

Research whether regime-aware forecasting improves results over one fixed strategy.

Preserve the existing independent Breakout, Reversal and Confluence intelligence engines. Upgrade and evaluate them rather than deleting existing functionality.

Use regime detection and signal interactions in the new prediction logic only when justified by historical and forward evidence.

---

## 12. Learning from past mistakes and improving predictions

This must be a core V5 feature.

Analyze past locked predictions and determine which conditions were associated with losses.

For each recorded forecast, preserve the information genuinely available at decision time:

- Direction
- Model probability
- Model version
- Official strike
- Price/index source
- Distance from strike
- Time remaining
- Market regime
- RSI/EMA/MACD/VWAP
- Momentum
- Volume
- Support/resistance
- Buying/selling pressure
- Reversal signals
- Liquidity conditions
- Source freshness
- Kalshi favorite and implied probability for comparison
- Official settlement result after the market ends

Investigate whether the bot loses more often during particular market conditions.

Evaluate V3 baseline, V4 shadow models, V5 independent model and a simple Kalshi-favorite benchmark on comparable markets.

Use:

- Chronological historical evaluation
- Proper training/validation/test separation
- Forward paper prediction tracking
- Brier score
- Log loss
- Calibration
- Directional accuracy
- Prediction coverage
- Accuracy by checkpoint
- Accuracy by market regime
- Model disagreement results
- Financial results after costs

Do not tune strategies using outcomes the model would not have known at prediction time.

Do not assume more indicators automatically mean better accuracy.

Evaluate whether the new model truly outperforms V3/V4 and the market-favorite baseline.

Provide evidence before calling a model improved or promoting it into any production recommendation role.

---

## 13. Manual trading and cash-out intelligence

I am personally making every trade and every cash-out decision.

The bot must NEVER enter, sell, close or manage a real position automatically.

Preserve and improve my manual-position tools.

I want to enter my:

- UP or DOWN side
- Actual entry price in cents
- Number of contracts
- Entry fees where known
- Desired profit target

My preferred cash-out target is around **+65% net profit**, but I want the dashboard to support adjustable targets, including the approximately 60–99% range where appropriate.

Calculate using actual available sellable bid prices, liquidity, fees and estimated slippage:

- Current estimated position value
- Net profit/loss
- ROI
- Actual executable exit estimate
- Target sell price needed
- Whether the desired target is presently achievable
- Whether a target was genuinely observed in market data
- Whether the original forecast is weakening or reversing

Where statistically validated, research the likelihood of reaching a profit target. Otherwise show UNVALIDATED/UNAVAILABLE rather than invented probabilities.

At the +3, +5 and +10-minute checkpoints, evaluate my currently entered manual position and explain whether updated conditions suggest increasing or decreasing reversal risk.

A changed prediction should be communicated as information to help me decide what to do, not as an automatic sell instruction.

Continue supporting cash-out, reversal, potential entry, Flip Radar and Scalp Radar alerts with appropriate data-quality gates and fee-aware economics.

Preserve the prior first-passage/target-touch paper research and clearly separate hypothetical outcomes from real user-confirmed profits.

---

## 14. Mandatory V5 dashboard redesign

Preserve the professional layout, main chart and existing functioning tools while making critical information easier to see.

### Top pinned scoreboard — highest visibility

Keep the lifetime record always visible in the top-right area.

Add the **actual original +1-minute locked UP/DOWN direction** prominently in the existing pinned 15M prediction area.

Show:

- Current round ticker
- Original locked UP/DOWN
- PENDING before a valid lock
- MISSED for a technical miss
- Latest checkpoint UP/DOWN separately
- Current probability and confidence status
- V5 prediction record
- V3/V4 historical results separately
- Countdown and important data-health warnings

Never rewrite the original locked prediction when subsequent opinions change.

### Flip Radar

Investigate why the V4 Flip Radar repeatedly shows 35/100 or 0/100.

Fix the underlying scoring and input limitations.

Replace the confusing numeric gauge with a compact horizontal bar style similar to the existing Signal/Estimated Probabilities visualization.

Keep the same approximate card size. Use evidence-based strength indicators, not fabricated probabilities.

Show directional evidence, freshness, market conditions and relevant liquidity information.

### Buy/Sell Pressure

Redesign with intuitive comparative BUY/SELL bars and actual verified aggressive-trade data.

Include meaningful short-term changes and pressure divergence.

### Extreme Move Radar

Improve detection of unusual price moves, acceleration, high volatility, abnormal trade activity and rapid reversals.

Show actual measured severity/evidence rather than meaningless fixed scores.

### Whale/Liquidity Radar

Improve large-trade analysis, verified liquidity changes, available futures-liquidation observations, and data-source status.

Do not pretend unavailable data exists.

### Existing features to preserve

- Live BTC chart and indicators
- Kalshi strike and countdown
- Original production baseline comparison
- Breakout/Reversal/Confluence engines
- Flip Radar and Scalp Radar
- Cash-Out Caller
- Manual positions
- Market odds and executable prices
- Prediction history
- Lifetime win/loss scoreboard
- Model comparison
- Telegram integration
- Notification controls
- Performance and mistake-investigation reports

Avoid excessive scrolling and oversized panels. Prioritize the information I actually watch while manually trading.

---

## 15. CRITICAL — Fix crashes, missing rounds and unreliable data

My V4 bot has already experienced:

- `sqlite3.OperationalError: database is locked`
- Scanner shutdown
- Dashboard becoming unreachable
- Coinbase LIVE/STALE flickering
- Missed scheduled predictions
- Unreliable radar input availability

Investigate the actual causes.

Implement:

- Safe SQLite writer coordination
- Appropriate busy handling, retries and transaction management
- Prevention of duplicate active scanner instances sharing one writable database
- Safe shutdown and recovery
- Reliable crash diagnostics
- Feed reconnection and resynchronization
- Coinbase trade-ID gap detection and recovery where possible
- Correct source/event timestamps
- Monitoring of stale market data
- Independent, time-critical prediction scheduling
- Logging of precise reasons for missed forecasts
- No blocking research work on prediction-critical threads
- Bounded CPU/memory usage
- Efficient dashboard polling and chart rendering

My Windows laptop should ideally be able to run V5 while I play PC games.

The bot must continue collecting data and issuing Telegram predictions when I close the browser dashboard, provided the background process remains running.

Add a clear health display for scanner, feeds, Telegram, prediction clock, database, and optional external data sources.

---

## 16. Preserve all existing history and credentials

Do NOT overwrite, reset or delete my existing V4 setup.

Preserve:

- All historical prediction records
- V3-imported results
- V4 lifetime scoreboard
- Current prediction history
- Official settlement results
- Telegram configuration
- Dashboard password
- Existing manual position records
- Working features and preferences

Use a consistent SQLite online backup or other SQLite-safe copying method, including consideration of WAL transactions.

Launch V5 with its own isolated writable database.

Avoid requiring me to recreate Telegram credentials when they can be safely reused. Do not expose secrets, private keys or passwords.

My existing V4 must remain usable as a fallback.

---

## 17. Windows installation and immediate launch

I want a working V5 research/paper-forecast system running on my Windows laptop as soon as technically feasible.

Create a separate V5 branch and a simple Windows installation/update package.

Use the Python installation already working on my computer if available:

`%USERPROFILE%\Downloads\python.3.12.10\tools\python.exe`

Do not force me to reinstall Python unnecessarily.

Provide:

- A simple setup/start command or one-click CMD launcher
- Safe database initialization
- Dashboard launch instructions
- Telegram verification
- Real-feed verification
- Startup health checks
- Safe shutdown procedure
- V4 rollback instructions

Do not automatically deploy or alter my Windows installation.

Do not make a cloud/Railway deployment a requirement for tonight's local launch.

---

## 18. Required testing and acceptance conditions

Before describing V5 as ready:

1. Verify the new independent V5 model genuinely generates its own predictions rather than reusing V3 direction or Kalshi favorite.
2. Verify forecasts are issued at +1, +3, +5 and +10 minutes with correct market timestamps.
3. Verify the original locked forecast remains immutable.
4. Verify Telegram alerts at all four checkpoints and prevent duplicate sends.
5. Verify changed opinions explain the strongest evidence behind the change.
6. Verify low-confidence but valid forecasts do not get unnecessarily suppressed.
7. Verify genuine missing-data failures never masquerade as valid predictions.
8. Verify all checkpoints are scored against official settlement.
9. Verify the scoreboard preserves historical results while tracking V5 separately.
10. Verify the upgraded analysis actually influences V5 forecasts.
11. Verify BRTI availability and correctly label any proxy fallback.
12. Verify database locking, restart recovery and feed-gap behavior.
13. Verify accurate cash-out estimates from genuinely available executable prices.
14. Verify manual trading only and no order-execution permissions.
15. Run Windows/Linux tests and relevant simulated failure tests.
16. Verify that the dashboard can close without stopping the scanner or Telegram.
17. Do not claim improved real-world accuracy without legitimate forward-test evidence.

Do not fabricate market data, performance results, trained-model quality or unavailable API capabilities.

---

## 19. Build priorities — START NOW

**P0:**
Repository audit, data integrity, SQLite crashes, feed/scheduler reliability, safe database isolation and accurate original prediction tracking.

**P1:**
Create the genuinely independent V5 directional engine, multi-timeframe features, settlement awareness and real-time +1/+3/+5/+10 forecasts.

**P2:**
Integrate the checkpoint Telegram alerts, independent V5 scoreboard and visible locked UP/DOWN display.

**P3:**
Implement the broader market intelligence: support/resistance, volume, liquidity, reversal/fakeout analysis, cross-exchange evidence and regime-aware strategies.

**P4:**
Redesign Flip Radar, Buy/Sell Pressure, Extreme Move, Whale/Liquidity and manual cash-out intelligence.

**P5:**
Historical accuracy audits, model comparison, forward-test evaluation, optimization and additional validated strategies.

Implement everything reasonably feasible. Do not hold the usable V5 core release hostage to optional external APIs or features requiring extensive historical validation.

Do not skip features silently. Report each requirement as IMPLEMENTED, VERIFIED, EXPERIMENTAL, BLOCKED or NOT YET IMPLEMENTED.

### FINAL NON-NEGOTIABLE GOALS

- A truly new independent prediction engine.
- An initial UP/DOWN forecast for virtually every round with valid data.
- Updated independently scored predictions at 3, 5 and 10 minutes.
- Telegram notifications at all four checkpoints.
- Genuine technical, volume, momentum, liquidity and reversal intelligence influencing predictions.
- Official settlement-index awareness.
- Fewer preventable misses and crashes.
- A redesigned, easier-to-understand dashboard.
- A prominently pinned original UP/DOWN prediction.
- Better manual cash-out information.
- Separate V5 accuracy tracking and model comparisons.
- Preservation of V4 and all historical data.
- No automatic trades.

**START IMPLEMENTING NOW.**

Inspect the actual repository and identify concrete blockers first, then proceed with development instead of stopping after writing a plan.

My goal is to launch a functional V5 tonight if feasible. The new engine must make and record actual live paper forecasts, not simply exist as unused research code.

When the build and tests finish, explain what is ready, what is experimental, and give me clear, beginner-friendly Windows installation steps.

Do not deploy to my machine without my approval.