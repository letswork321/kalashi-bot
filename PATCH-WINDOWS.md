# In-place update for your installed intelligence dashboard

This patch updates the existing installation based on `79a67c7507342c93db3fea4ee24408de5228407b`. **Do not use the old database-import procedure.** Your existing `data`, `.venv`, Telegram settings, password, Python installation and Chrome bookmark stay in place.

1. Download the **btc-alert-tracker-fixes** branch ZIP from GitHub. Right-click → **Extract All** into a temporary NEW folder. Do not extract over your working installation.
2. When ready, press **Ctrl+C in your existing LOCAL Windows bot console**. This deliberately pauses your local scanner and dashboard for the update. Do not stop or reconfigure a separate cloud bot. Leave the old installation folder where it is.
3. In the newly extracted patch folder, double-click **update-windows.cmd**. Paste the path of your EXISTING installation folder (the folder containing `scanner.py` and `data/live.sqlite3`). The updater checks the package, refuses an active local scanner, integrity-checks online SQLite backups, saves all existing data/research/encrypted settings and replaced source files under `recovery/in-place-...`, then replaces code only. It never copies a new database into your installation. Keep the printed recovery path.
4. Double-click **start-windows.cmd in your EXISTING installation folder**. It reuses `%USERPROFILE%\Downloads\python.3.12.10\tools\python.exe` and your `.venv`. The additive schema migration makes another integrity-checked backup before adding tables/columns. No history is deleted, guessed, relabeled as a win, or imported from test files. Existing MISSED rows remain immutable.
5. Use your same Chrome bookmark: **http://127.0.0.1:8000**. Sign in as `viewer` with the same password. Existing process environment/Windows-encrypted settings are reused. Credentials that the old version held only in memory may require the same values again after stopping; the patch cannot recover secrets from an exited process.
6. Open **Telegram Notification Settings**. Click Save after choosing categories. **Locked forecasts default ON**, regular potential entries and official settlements retain ON defaults; preliminary, flip and scalp categories default OFF unless previously configured. Your saved choices survive restarts. No token or chat ID appears in this settings interface. Turning on scalps does not bypass the faster-data or validation gates.

No reinstallation, new Python version, Node, Docker, `py` launcher, administrator rights or changed Windows security settings are required. Keep your laptop awake and its console open. A private local server only is started.

## Check one new forecast

Keep the bot running before the next actual KXBTC15M opening. At roughly **open +60 seconds**, inspect **15-Minute Prediction Tracker**:

- A new **LOCKED** UP or DOWN row should appear with observed time, official strike, baseline version and uncalibrated probability. Exactly one on-time forecast is permitted per ticker.
- **Recent lock attempts and failure reasons** explains missing inputs. Network workers cannot block the clock; unavailable/stale inputs can still prevent a valid forecast.
- If first valid data arrives after +65s but by +120s, a separate **LATE** observation appears, with its real timestamp and separate wins/losses. The original MISSED on-time row is retained. Later arrivals are not reconstructed.
- Once Kalshi publishes its official finalized YES/NO result, the appropriate on-time or LATE record is scored. Settlement can be published after market close; spot price alone never scores it.
- If locked notifications are enabled, the forecast should appear on Telegram, labeled **not an entry recommendation**. Telegram API acknowledgement and phone receipt are different; the dashboard reports API acknowledgement only.

## Check a real potential entry alert

The startup connection test verifies credentials and delivery transport; it is clearly labeled as a test. A genuine **POTENTIAL UP/DOWN ENTRY** requires a defensible calibrated shadow model with sufficient chronological out-of-sample evidence, supported current inputs, >=5% estimated after-cost edge, <=4c spread, sufficient observed depth and fresh quotes. It does not require the legacy STRONG label.

With no validated model yet, entry alerts correctly remain silent. Locked forecasts continue collecting the real labels needed for evaluation. Do not increase confidence percentages or send fake recommendations to force a phone test. When a genuine entry qualifies, compare its ticker/time/ask with **Telegram Alert Performance**. It records the send acknowledgement, then attempts a paper entry only from a later observed ask after a further 2s delay. Official direction correctness and after-fee paper P&L remain separate. Missing execution observations stay missed, never assumed filled. One withdrawal/expiry message is issued if a delivered directional opportunity loses support or expires.

## Flip and scalp interpretation

Flip UP/DOWN cards compare actual buy asks and sell bids. The target and target net are **conditional scenarios**, not established expected profits. Forward studies record delayed asks and subsequent 60s bids. Overlapping studies are not a fundable portfolio; validation uses nonoverlapping observations and a chronological holdout.

Public REST is retained. Sub-minute actionable alerts require optional authenticated, sequenced market-data streaming plus strict freshness/cadence and per-side/per-window forward validation. Streaming is OFF until you explicitly configure the documented backend market-data settings. No order, balance or portfolio requests are made. Without fast data, the display says **FASTER DATA REQUIRED**. With fast but unvalidated evidence, only **SCALP WATCH — NOT AN ENTRY** can be sent if you enable scalps. Future exit targets are never guaranteed.

## Roll back

Stop the updated LOCAL console with Ctrl+C. From the extracted patch folder, double-click **rollback-update.cmd** and paste the printed `recovery/in-place-...` path. It restores the backed-up code and matching pre-update data, while preserving all post-update history separately in `recovery/before-rollback-...`. It does not merge new rows into the older database. Your `.venv` is retained. Then run `start-windows.cmd` from your existing installation folder.

If update/backup/migration fails, do not delete `data`, overwrite the project manually or disable protections. The updater restores files it changed on a caught copy failure; the recovery manifest also supports manual rollback after an interrupted update. Send the error text only, without credentials.

## Platform verification boundary

Automated tests exercise package integrity, refusal of active scanners, data/credential/venv preservation, backup failures, partial-copy recovery, migration and rollback on Linux Python 3.12. Native Windows `cmd.exe`, file-sharing behavior, NuGet execution, DPAPI and your actual phone require the above laptop check. No cloud test can establish live trading profitability or guarantee that all networks deliver a forecast within five seconds.
