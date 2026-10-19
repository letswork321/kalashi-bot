# BTC Pro V3: all 26 upgrade areas

This release implements all 26 master-document areas below. Implemented code is not proof of a working external entitlement, live stream in this cloud, validated probabilities, or profitable trading. No funds, account balances, or order-management endpoints are used. Existing engines and lifetime histories remain separate.

| # | Area | Implementation and current limit |
|---|---|---|
| 1 | Professional chart | Self-hosted Lightweight Charts 5.0.9, verified registry integrity, Apache license, TradingView attribution, resize and mobile tests. |
| 2 | Real candles | Coinbase 1m/5m/15m REST history; real trade-built developing bars. Partial bars labeled. Optional 15s requires continuous actual ticks. |
| 3 | Coinbase streaming | Public matches/heartbeat, clock/ID/gap checks, reconnects, bounded tape. Cloud WSS proxy blocks connection; REST stays operational and explicitly not LIVE. |
| 4 | Kalshi book stream | Existing authenticated sequenced snapshot/delta transport hardened with event timestamps and reconnect checks. Backend only, optional; not connected here. |
| 5 | BRTI | Separate optional authenticated cfbenchmarks_value subscription, timestamp/sequence checks, trailing/final-minute averages. Entitlement and live values unverified; never replaced with Coinbase. Official Kalshi results remain settlement authority. |
| 6 | Current market | Official metadata, strike, boundary discovery, UTC storage/ET display, countdown, bid/ask, spread/depth and source age. Public REST checked. |
| 7 | Compact layout | Decision/chart/market strip and two small records above collapsed advanced diagnostics/history/settings. Tested at desktop and mobile sizes. |
| 8 | Indicators | EMA9/21/50, RSI14, MACD, BB, volume, causal trend line and support/resistance. Authentic VWAP only with certified session trade coverage. |
| 9 | English caller | Confirmed patterns, 1m/5m agreement and liquidity explained in plain English. Heuristic WATCH, not fabricated probability. |
| 10 | Independent modules | Seven separate caller modules plus preserved independent breakout/reversal/confluence cards; disagreements retained. |
| 11 | Model comparisons | Preserved heuristic/logistic/implied baselines plus actual fitted gradient-boosted stumps, validation calibration and disjoint chronological test folds. Shadow only. Needs genuine settled observations for useful evaluation. |
| 12 | Sellable-bid forecasts | Prospective 20/40/60/120/180-second bid observations and missed/gapped endpoints. Comparable entry bins, nonoverlapping chronological samples, train-only intervals and held-out checks. Insufficient forward data now. |
| 13 | Contract movement | Validated-only bid range, horizon, empirical target frequency and price multiplier; unavailable until calibration/coverage gates pass. No slope extrapolation labeled accurate. |
| 14 | ENTER/WAIT/AVOID | Fresh event-verified executable book, fees, spread, depth, time and conservative validated expected value required. Otherwise WAIT. |
| 15 | Early exits | Configurable 5–90% net-on-stake goal (default 65%), milestone/risk watches from explicitly supplied entry price/quantity/fee. No account access. |
| 16 | Paper execution | Actual delayed ask entry and later bid exit, fee/slippage/depth, frozen early-exit rules and missed fills. Separate directional/flip/scalp ledgers. |
| 17 | Separate records | Official fixed-time settlement accuracy, acknowledged caller path-hit accuracy, and after-cost paper P&L are distinct. |
| 18 | Telegram | Short caller/entry/flip/scalp/exit messages, expiry/dedup/cooldowns, delivery audit, independent switches. New actionable categories require verified evidence. No real test messages sent during this release. |
| 19 | Caller accuracy | Immutable source/version/target/time; new acknowledged path-target metric never mixed with original endpoint-v1 records. Gaps/unacknowledged events cannot earn wins. |
| 20 | Locked forecasts | One immutable +60s forecast, +5s deadline, separate late records, official settlement, all-time default, pending/missed/streak/ET views. Live lock observed +0.20s after schedule. |
| 21 | Historical research | Existing public backfill, weekday/hour/regime tables, sample sizes and model audits; module results by regime added. Older depth cannot be recovered from candles. No claimed weekend advantage. |
| 22 | Data quality | Individual spot/BRTI/book states, event age, sequence/clock gaps, fee validity, observation misses and delivery outcomes. Browser independently masks stale values. |
| 23 | Protected switches | Existing authentication/CSRF plus local settings for entry/flip/scalp/settlement and optional exit watches. Credentials absent from browser responses. |
| 24 | Collection | Raw observed ticks, provenance, contract samples, caller events, model artifacts, indexes, bounded retention and additive backups. Storage alone is not learning. |
| 25 | Windows patch | Existing NuGet path/venv/secret reuse preserved; hash-verified in-place updater, online SQLite backups and rollback. No laptop Node/Docker needed. |
| 26 | Verification | Full Python suite, JS compilation, actual browser/REST checks, isolated real lock, migration/update/rollback checks; native Windows and successful WSS still require external verification. See V3-VERIFICATION.md. |

## Profit targets and interpretation

A desired +65% return means net profit divided by the supplied stake INCLUDING entry fee. Both transaction fees and modeled exit slippage must be paid before the goal is met. At high entry prices a +60–90% return can be impossible even at a $1 payout: the dashboard must say so. Smaller goals are supported. An inverse contract-price multiplier is not net ROI. Endpoint target frequency is not a promise that a target will be touched earlier in the window. Paper results are not actual earnings.

The caller path study freezes a 0.05% spot move within 180 seconds, then observes only subsequent continuously recorded ticks after timely Telegram acknowledgment. This is a documented research movement definition, not a contract-profit promise. Legacy exact-endpoint records keep their original definition. No initial wins are seeded.

## Data connections and official references

Reviewed official Kalshi AsyncAPI at https://docs.kalshi.com/asyncapi.yaml and market/orderbook documentation. BRTI uses index_ids ["BRTI"] on cfbenchmarks_value; source time/value are separate from Coinbase trades. Public order books contain bids; opposite-side bids determine executable asks. Official metadata/results, series fees and current public market checks remain authoritative; never infer settlement from spot. Rules and fee changes must continue to be checked per market.

Chart package provenance and license are in static/vendor. Coinbase REST works here; official Coinbase documentation access and public WebSocket Upgrade were blocked by this cloud proxy. Do not weaken TLS or bypass security. Allow HTTPS to api.exchange.coinbase.com and api.elections.kalshi.com, and outbound port 443 WSS/CONNECT/Upgrade to ws-feed.exchange.coinbase.com and the Kalshi market-data endpoint. Telegram requires HTTPS api.telegram.org. A REST allowlist alone does not allow WebSockets.

Public Coinbase streaming needs no key and defaults enabled. Optional backend-only Kalshi data streams additionally require KALSHI_WS_ENABLED=true, KALSHI_DATA_KEY_ID, KALSHI_DATA_PRIVATE_KEY_FILE and KALSHI_DATA_SECURITY_CONFIRMED=true; BRTI additionally KALSHI_BRTI_ENABLED=true and entitlement. Check the exact environment names in intelligence/streams.py before configuration. Install requirements-ws.txt only if the optional integration requires it. Never put keys in Chrome/GitHub. Because the reported laptop malware/Defender issue remains unresolved, do not connect new private credentials yet. These integrations remain disabled until you explicitly configure them after resolving that issue.
