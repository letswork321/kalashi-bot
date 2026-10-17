# Upgrade verification and remaining limits

## Protected working version

Base: `windows-dashboard-setup`, commit `052010c93f6102b29a1e904059590f55f73df9cb`.
Upgrade: separate `btc-intelligence-upgrade` branch in a separate checkout. The working checkout remained clean at the base commit; no running user process was stopped, reconfigured or switched to the new code. The user's Windows installation was not accessed or overwritten. No public website was deployed.

## Automated checks

**136 tests passed** on Linux CPython 3.12.14 with the pinned dependencies. This includes all 34 existing tests plus new tests for:

- Causal EMA, RSI, Bollinger, MACD, real-trade weighted VWAP and deviation; exact 15-minute boundaries and missing intervals.
- Breakout candle-low confirmation/previous-25-high exclusion, no retroactive attribution, bullish/bearish six-of-seven matrix thresholds and independent contradictory signals.
- Immutable per-market locks, early/late/invalid/stale samples, official-only settlement, pending/missed counts, accuracy/streak and Eastern daylight saving.
- 10-minute sample timing, missed observations, frozen opening-time bands and measurable reversal outcomes.
- Depth/complementary bid-ask economics, both fees, entry/exit slippage, conditional raw-bid targets, delayed fills, missed exits, shared-observation quantity consumption and unresolved open risk.
- REST scalp gating, optional fast-cadence conditions, missing sequence/rollover/negative/nonfinite book rejection and disabled optional transport.
- Chronological train/validation/test periods, train-only normalization, calibration metrics, delayed label exclusion, invariance to future test-label changes, actual persisted fitted shadow artifacts, and insufficient-data states.
- Backend opt-in alerts, deduplication, cooldown, expiration, retries and hourly limits.
- Existing Flask authentication, all panel routes/ranges, no write API, side-by-side import/rollback, existing data preservation and encrypted-cache interfaces.
- Existing NuGet bootstrap behavior, environment credential reuse and cleanup on local service-start failure.

Unit fixtures and fitted synthetic test datasets are isolated; their scores are **not live accuracy or profitability evidence**. Mock Telegram sends in tests do not prove message delivery.

Fresh environment setup, repeat setup and `pip check` passed. Windows CPython 3.12 wheel resolution/download succeeded for **16 normal dependencies** and **4 optional WebSocket dependency wheels**. Optional dependencies are not required or automatically enabled for normal REST operation.

## Read-only live checks

Actual public Kalshi/Coinbase data was used in isolated databases with Telegram sending disabled:

- Current KXBTC15M market metadata, official `floor_strike`, rules, effective series/event fee metadata, fixed-point books, public trades and official finalized outcome responses verified.
- Current official fee PDF retrieved through verified TLS: effective July 7, 2026; quadratic 0.07 multiplier formula, cost+fee rounded to centicent, no settlement fee.
- Coinbase fresh trades, ticker, 60-second and 900-second candles verified. Legitimate before/after trade-ID pagination prevents stale latest-page URLs from being treated as fresh. Quote freshness and sequence gates remain strict.
- A bounded seven-day public backfill completed with **1,486 outcome/candle rows**, including **150 sampled Kalshi minute candles**; actual coverage/jobs are recorded, not presumed from a selected range. Historical depth was not generated.
- A real backward trade backfill collected **23,000 contiguous prints** to the UTC-session anchor. A fresh check produced a genuine size-weighted session VWAP and live independent outputs of **NO BREAKOUT** and **NO MAJOR CONFLUENCE**, rather than fabricated opportunities.
- One actual on-time +10-minute reversal observation was recorded without a band excursion. This is functional timing evidence, not a statistically meaningful reversal-success estimate.
- The next early-market lock window was observed separately; see the recorded release note below. No live win rate is claimed from an unsettled or tiny sample.

## Browser checks

Headless Chromium/Playwright checks ran against a real isolated collector and private Waitress listener. All **20 panels**, three independent cards, range controls, authentication, live input rendering, mobile 390px layout (no horizontal page overflow), persistent expandable indicator readings and disconnected-data warnings were checked with no JavaScript errors. The tooling is used only in cloud verification; your laptop needs neither Node.js nor Playwright.

Preview: [dashboard-preview.png](references/dashboard-preview.png). This is a timestamped live-data screenshot, not proof of future profitability.

## Migration evidence

A copy of the actual existing cloud SQLite history was migrated. All **seven legacy tables** had identical row-value hashes before/after. The pre-migration backup passed integrity checks. The original database was not migrated in place. Separate tests cover importing research files/encrypted settings, refusal to overwrite existing destination data, running-local-process locks, retained old code, and rollback instructions. Raw books referenced by simulated fills survive raw-data retention.

## What is not claimed

- No native Windows execution was possible here: `cmd.exe`, NuGet Windows binary/venv creation, real Windows DPAPI/file locking, same-password Chrome login and default-browser opening still require the final laptop smoke test. The Python 3.12.10 NuGet distribution was inspected and the existing path/bootstrap preserved; Linux tests do not replace those Windows checks.
- The optional authenticated WebSocket was not authenticated against a user's key. Its sequence/parser/reconnect logic was tested with fixtures. It stays disabled until explicitly configured and verified. Public REST cannot certify reliable 20-second scalp fills.
- There are not yet enough genuine on-time locked/officially settled samples for candidate or reversal probability validation. Real fitting/evaluation is implemented but remains gated. Baseline is preserved; no automatic promotion, confidence inflation, or claim of improved live profitability.
- Historical order-book depth and exact timed quotes cannot be recovered from OHLC candles. Missing historical predictions/10-minute observations are marked missing. Passive/maker fills are not assumed.
- New Telegram categories remain off by default. Existing connection/alerts are preserved in code; a real Telegram connection test is deliberately part of the user's controlled Windows launch. Optional new alert categories were not spam-tested against the user's phone.

Install and rollback: [UPGRADE-WINDOWS.md](UPGRADE-WINDOWS.md). Calculation/retention details: [ANALYTICS.md](ANALYTICS.md).

## Live early-lock release note

The isolated worker recorded exactly one LOCKED forecast for `KXBTC15M-26OCT162200-00` at UTC epoch `1792201560.1358104`, **0.1358104 seconds after the scheduled open+60s target** (before the +65s deadline). It stored baseline version `heuristic-v1-uncalibrated`, direction UP, p_up 0.6384119813470126. This was an actual read-only live observation, not a reconstruction or test fixture. The market had not officially settled at release verification, so it remains pending and is not counted as a win/loss. These test-database records are not shipped or injected into the user's history.
