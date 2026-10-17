# Tracker and Telegram patch verification

Base installed version: `79a67c7507342c93db3fea4ee24408de5228407b` (`btc-intelligence-upgrade`). Delivery branch: `btc-alert-tracker-fixes`. Changes are in a separate checkout. No user/cloud scanner was stopped or reconfigured, and no laptop installation or original database was accessed remotely.

## Automated correctness

**172 tests pass** on Linux Python 3.12.14, including the original scanner/dashboard/Windows-bootstrap tests. `pip check` reports no broken requirements. Fixtures establish correctness, not trading profitability.

New coverage includes independent clock execution without network/research waits, stale/slow input diagnostics, rollover, one immutable lock, SQL-immutable LATE forecasts, separate official-result scoring, preservation of 92 MISSED rows, frozen alert evidence, preliminary unknown-strike warnings, calibrated-entry gates without a STRONG-label requirement, per-horizon scalp watches, no REST/mock scalp entries, post-acknowledgement delayed entry/bid exits, late acknowledgement/missing observations, per-event depth exhaustion across repeated polls, one-time withdrawals, unified legacy/new settlement dispatch, persistent notification switches, authentication/CSRF/origin/type checks, and forward flip studies without hypothetical target fills.

In-place update tests verify unchanged database bytes, encrypted settings/research/venv preservation, integrity manifests, refusal of an active scanner, backup failure safety, automatic code restoration after a caught partial copy failure, and rollback with post-update history retained separately. A complete source-package update from the exact installed commit, migration and rollback also passed, with new forward history retained in the rollback backup. Native Windows file sharing is not claimed from Linux tests.

## Browser and real data

Headless Chromium, authenticated private listener on a temporary local port, isolated live database, **no Telegram credentials**: 22 panels, three independent engine cards, two flip comparison cards, persistent checkbox settings across reload, range selectors, expanded readings retained, no JavaScript errors, no page overflow at390px, stale/disconnection warning. No external/public site was deployed. The screenshot in `references/dashboard-preview.png` is a real-data/warming-up view; it is not proof of profitable signals.

A schema-v5 isolated live-data copy was migrated to v7. All **19 pre-existing tables' original columns and row values** remained unchanged (except the schema-version audit table, intentionally excluded); an integrity-checked pre-migration backup exists. Source databases were opened read-only and untouched.

The independent scheduler was run with real public Kalshi and Coinbase data across rollover, entirely outside the original running bot. Real scheduled-lock evidence: `KXBTC15M-26OCT162330-30` locked UP at UTC epoch `1792206960.12847`, **0.12847 seconds after the scheduled open+60s target**, before the +65s deadline. Stored strike81340.25, BTC81361.56, p_up0.7461242183494068 and `heuristic-v1-uncalibrated`. It is pending official settlement and is not counted as a win/loss. These test rows are not shipped or inserted into the user's history. Transient stale quotes and one-sided near-expiry books were reported honestly as unavailable, not substituted.

## Remaining boundaries

- Windows11 `cmd.exe`, NuGet executable, native locking, DPAPI, Chrome launch and actual phone receipt require the laptop smoke check in PATCH-WINDOWS.md. The existing Python path is retained; no new dependency/installer/security change is required.
- Telegram transport/content/retry logic is tested with isolated doubles. No fake opportunity or unsolicited test was sent to the user's phone. Startup sends the explicitly labeled existing connection test; genuine entry messages await validated live economics.
- Optional authenticated Kalshi market-data streaming remains OFF and has not been tested with the user's private key. REST remains operational; it is insufficient for actionable sub-minute scalp entries. Faster-data and forward-validation gates are not bypassed by a settings switch.
- Live strategy/model evidence is initially sparse. Flip targets are scenarios, not established positive expected value. Unvalidated fast scalp candidates can produce watches only. Actual results must accumulate; no profitability is claimed.
- Network-free scheduling avoids research/network waits on the clock but cannot force an unavailable exchange feed to deliver. +65s deadline misses remain MISSED; eligible fresh +65–120s observations are separately LATE. Beyond +120s no forecast is reconstructed.
- Telegram API acknowledgement does not reveal phone display/read time; ambiguous network acceptance cannot guarantee exactly-once delivery. Rapid expirations and withdrawal messages instruct the user to recheck current quotes manually.
