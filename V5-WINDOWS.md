# BTC Pro V5 — safe side-by-side Windows research launch

V5 is a new **experimental paper forecasting system**. Its BTC-only model is different from V3, but better real-world accuracy has not been demonstrated. No 75% result is promised. Trades and cash-outs remain entirely manual.

## Install without overwriting V4

1. Download the complete V5 commit ZIP using GitHub's **Code → Download ZIP**, or the exact-commit ZIP link in the release report. Extract into a NEW sibling folder, for example `Downloads\kalashi-bot-v5`. Do not extract over or inside V4. Your existing V4 keeps working until you choose to switch.
2. When ready to import, stop only the LOCAL V4 bot with **Ctrl+C** and wait for shutdown. Do not delete databases, WAL/SHM or lock files. A cloud scanner is unaffected.
3. In the NEW V5 folder, double-click **start-v5.cmd**. It uses `%USERPROFILE%\Downloads\python.3.12.10\tools\python.exe`, creates its own `.venv` and installs the pinned Python dependencies. No standard Python installer, `py`, Docker or Node.js is needed on your laptop.
4. Paste your existing V4 project-folder path when prompted. The importer takes SQLite online backups, checks integrity, copies settings/history/manual positions to a separate writable V5 database and keeps a recovery copy. It refuses to overwrite populated data or import from a running local scanner. All old files remain in V4.
5. Existing Windows DPAPI credentials are copied encrypted and reused for the same Windows user. Environment-provided credentials also work. If credentials were never saved, hidden prompts will appear. Do not paste secrets into GitHub or this chat. No optional private market-data keys are enabled.
6. The normal private setup sends a clearly labeled Telegram connection test and opens **http://127.0.0.1:8000**. Username is `viewer`, password is your existing dashboard password. Do not run V4 and V5 on port 8000 simultaneously. Refresh Chrome with **Ctrl+F5**.
7. Confirm V3/V4 lifetime counts match your old installation. V5 starts a NEW separate record; imported results are not relabeled as V5 wins. Check the pinned original +1m direction, latest checkpoint, countdown, source health and four checkpoint cards. Initial forecasts arrive in the next eligible round; missed deadlines are never backfilled.
8. In **V5 checkpoint history…**, enable/disable +1/+3/+5/+10 Telegram independently. These are enabled by default. V5 settlement is on, daily summary is off. Existing V4 notification switches retain their saved values: old baseline/settlement alerts may also arrive until you disable those categories in the existing notification settings. Do not run a second scanner against the same database.

## Verify operation before relying on it

- Watch one complete round: +1, +3, +5 and +10 must each show one immutable paper forecast. A later direction change leaves the original intact. The technical recording window is target through target+5 seconds, based on official market opening timestamps.
- Telegram must identify V5, checkpoint, original/latest direction, uncertainty, evidence, strike, reference source and freshness. Delivery expiry is 20 seconds after issue. `sent` means Telegram accepted the HTTP request, not that your phone displayed it. Ambiguous delivery is not blindly retried; inspect `delivery_unknown` and expired counts.
- BRTI must be labeled a proxy if not actually connected. Coinbase event age alone does not prove trade continuity. RESYNCING is not LIVE. If clock skew appears, use Windows time synchronization; do not disable security software or TLS verification.
- After Kalshi publishes the official result, each checkpoint receives its own win/loss through the official-results join. Closed time and Coinbase price are not settlement labels.
- Paper positions can show MISSED_ENTRY when timely book/fees/depth are unavailable. That is correct; it is not a simulated fill. Existing cash-out tools use supplied entry basis, available bids, fees, depth and slippage, with a configurable target (default +65%). No automatic sale occurs.
- Close Chrome: the scanner and Telegram keep running while the terminal stays open. Sleep, shutdown, lost internet or closing the terminal stops forecasting. Avoid Windows sleep while you want continuous monitoring; no security changes are required.

## Stop and return to V4

Press Ctrl+C in the V5 terminal and wait for shutdown. Start `start-windows.cmd` in your original V4 folder. Its code, credentials and historical database remain intact. Keep the V5 folder and recovery backup: predictions collected separately after switching are not automatically merged backward. To resume V5 later, stop V4 and run `start-v5.cmd` again; it will not import over an existing V5 database.

## Data and validation limits

Public Kalshi REST plus Coinbase REST supports initial paper forecasts without private account access. Fast executable scalp/cash-out signals still require sufficiently fast verified data; V5 does not bypass those gates. Official BRTI and Kalshi sequenced order books require optional authenticated market-data access/entitlement. The previously unresolved Windows security issue must be resolved before configuring private keys. Never add trading/funds permissions.

The final release report distinguishes Linux and native Windows test results from live-feed checks. Local Windows end-to-end Telegram delivery, optional authenticated feeds and a multi-round soak test still require your laptop. Synthetic tests prove behavior, not forecasting profitability. Research weights, Gaussian final-minute averaging and any trained candidates remain experimental; no automatic promotion occurs.
