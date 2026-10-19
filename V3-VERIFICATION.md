# V3 release verification — 2026-10-19 UTC

## Automated and browser checks

- Python 3.12.14 Linux: 236 tests run, 235 passed, one native Windows DPAPI test skipped. Fixtures verify correctness and failure handling, not profitability.
- Python application compilation, all three application JavaScript syntax checks and pip dependency integrity passed.
- Authenticated isolated local Waitress + real Chromium: pinned v5 chart renders; 1m/5m/15m and indicator toggles work; source-delay warning visible; all three existing engine cards retained; authenticated setting saved; advanced area collapsed; no JavaScript errors and no 390px mobile overflow. Desktop market strip ends at 831px in a 900px-high viewport.
- Synthetic browser response tests separately prove LIVE-to-STALE masking. These are not real stream measurements. The screenshot references/v3-real-rest-dashboard.png uses genuine REST data and explicitly shows stream unavailable.
- Uncached combined SQLite state/chart reads: 20 calls, median 59.25ms, maximum 90.6ms; compact JSON 9,428 bytes with 280 real bars. This is local rendering/read performance, not market-data latency.
- Empty-data compare-models and v3-report CLI commands run successfully and preserve insufficient-data states.

## Actual read-only public-data observations

Isolated test databases under /tmp; Telegram sender disabled. Public Kalshi metadata, official strike, fee information and Coinbase REST prices/candles received. Approximately 281 one-minute, 280 five-minute and 672 fifteen-minute candles were available in the short validation run. An additional nine-minute run ended with error=null, database integrity OK, and froze ticker KXBTC15M-26OCT182130-30 DOWN at UTC epoch 1792372560.2001355, 0.2001s after its scheduled +60s decision. Probability was explicitly uncalibrated; official result was pending when collection stopped. This is evidence of timing/data integration, not prediction accuracy or profit. Future markets discovered during the run remain pending until the service observes their scheduled decision; stopping a diagnostic is not continuous production coverage.

Coinbase WebSocket failed through the cloud proxy with WebSocketProxyException. The REST data was never labeled LIVE. Kalshi authenticated orderbook/BRTI were not connected. No live sub-minute scalp profitability, calibrated caller targets, private entitlement, Telegram phone delivery, or successful streaming is claimed. Genuine forward sample requirements leave targets/entry recommendations unavailable safely.

## Preservation and platform limits

Migration is additive schema v9, with pre-migration backup. Existing original histories, fixed predictions and legacy endpoint caller definitions are retained. Updater/rollback fixtures cover database backups, credentials/venv/research retention, active-scanner refusal and copy-failure recovery. A full 87-file source-manifest update/migration/rollback rehearsal passed: every original value across 25 old tables was unchanged, credential and venv sentinels survived, integrity checks passed, and rollback retained the post-upgrade database separately.

GitHub Actions defines Linux and Windows Python 3.12.10 checks plus actual NuGet bootstrap from the official package with its published SHA512. Native Windows execution and workflow success must be verified externally; they were not run on this Linux host. A Windows-specific DPAPI roundtrip test is intentionally skipped here. Browser Node tooling is developer-only, never a laptop dependency.

No running user installation was stopped, no funds/account APIs were used, no public deployment occurred, and no real Telegram alert was sent by release tests. Do not configure new sensitive keys while the reported Windows security issue remains unresolved.
