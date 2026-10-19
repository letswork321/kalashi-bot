# Safe Windows V3 update

The source package is ready for staged installation; successful live WebSocket access and native Windows execution remain to be checked on your laptop. Nothing in this release changes your currently running installation or cloud scanner automatically.

You reported an unresolved malware/Defender issue. Resolve it using Windows Security or trusted support before entering new credentials or launching sensitive integrations. Do not disable security, add exclusions, or configure optional private data keys to work around a warning. Public-data-only V3 development/testing does not require those keys.

## When you deliberately choose to install

1. Download the complete project ZIP from the tested GitHub commit link supplied with this release. In File Explorer choose **Extract All** into a NEW separate folder, for example `Downloads\kalshi-v3-update`. Do not extract over your working bot. Keep that folder for rollback tools.
2. Locate your EXISTING working folder: it contains `scanner.py`, `start-windows.cmd`, and `data\live.sqlite3`. Do not move or delete its data, passwords, `.venv`, or private configuration.
3. When ready, press **Ctrl+C** in the old LOCAL bot's Command Prompt and wait for shutdown. Close its dashboard server if it runs separately. Do not stop your cloud scanner. Never run two scanners against one SQLite database.
4. In the NEW extracted folder, double-click **update-windows.cmd**. Paste the full EXISTING project-folder path when asked. The updater verifies release hashes, refuses an active scanner, backs up all historical/research files and code, uses SQLite online backup with integrity checks, and prints a `recovery\in-place-...` folder. Save that path. If it reports any error, stop there and keep the original installation.
5. In your EXISTING folder, double-click **start-windows.cmd**. It automatically checks `%USERPROFILE%\Downloads\python.3.12.10\tools\python.exe`, retains your existing virtual environment and private configuration, installs pinned dependencies, and applies additive schema migrations with backup. Keep the complete NuGet tools folder; no standard installer or `py` launcher is needed.
6. Open regular Chrome at **http://127.0.0.1:8000**. Use your existing password and refresh with Ctrl+F5. No public deployment or extension is required. Confirm your lifetime history, correct current ticker/strike and source health. Do not mistake REST history for LIVE streaming.
7. Keep new actionable categories disabled until data quality and forward validation pass. Existing Telegram settings remain stored. Settings are in the collapsed advanced area; entry, flip, scalp, settlement and exit watches have separate switches. A watch basis is supplied manually; it is not a connected position. Alerts never execute a trade.

## What to check on Windows

Confirm the chart's 1m/5m/15m buttons, countdown, indicators, both accuracy cards, and your old history. Verify Coinbase stream event age and genuine intrabar updates; disconnecting the feed must turn the chart stale and guidance WAIT. Kalshi authenticated book/BRTI remain optional and OFF until your security issue is resolved and you explicitly configure backend-only read-only credentials. See V3-IMPLEMENTATION.md for exact variables and network requirements.

If public WSS is blocked, the network must allow outbound HTTPS/WSS port 443 and WebSocket Upgrade to `ws-feed.exchange.coinbase.com`. REST-only operation is supported, but reliable actionable 20/40/60-second scalp alerts require a fresh verified Kalshi book too. Do not disable Windows protection to enable networking. No validated contract forecasts are expected until enough genuinely forward-observed data passes the documented tests.

Telegram API delivery, native NuGet startup and Windows DPAPI must be checked on your laptop/Windows CI; Linux fixture tests cannot prove phone delivery. Do not paste your token into chat or GitHub. Existing protected private setup remains the way to configure credentials. A Telegram send acknowledgment means API acceptance, not proof you read it.

## Rollback

Stop only the updated LOCAL bot with Ctrl+C. In the NEW extracted folder run **rollback-update.cmd** and paste the saved `recovery\in-place-...` path. It restores the previous code and matching database; any post-upgrade records are retained separately in `recovery\before-rollback-...`. Start `start-windows.cmd` in your existing folder and use the same Chrome bookmark. Keep recovery folders until you are satisfied. Never delete or replace your only database copy manually.
