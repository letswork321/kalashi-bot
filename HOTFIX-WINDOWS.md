# V4 stability and verified-live Windows hotfix

This update keeps manual trading, the existing dashboard layout, lifetime scoreboard, prediction history, settings and Telegram credentials. It does not reset or change the database schema. Install only when you choose; no running installation is changed by downloading this release.

## What changed

- The Coinbase observer previously sampled trades using a clock captured before a database wait. Newer trades could therefore look like future data. Sampling now uses the current clock, independently of persistence delays.
- Duplicate trades and delayed subscription snapshots cannot reset verification. Small out-of-order arrivals are buffered for 250 ms. A genuinely missing trade ID records a gap and requires a new contiguous segment before LIVE returns. Reconnection clears old verification. Heartbeats cannot keep a stalled trade stream LIVE.
- Fresh but unverified quotes show RESYNCING, clock discrepancies show CLOCK SKEW, and delayed dashboard persistence shows OBSERVER DELAY. Actual old quotes still show STALE. No freshness threshold was relaxed to manufacture LIVE status. Existing historical gaps remain gaps.
- All application SQLite connections now share bounded contention handling: WAL, short native waits, explicit writer reservation, nested savepoints and rollback. Bare statements autocommit, avoiding idle write transactions across network calls. Lock errors retry for approximately two seconds, then fail safely; corruption and I/O errors are not treated as contention.
- Scanner, prediction scheduler, collection, execution observer, research/model jobs, V3/V4 workers, Telegram outbox and dashboard settings use this connection layer. Backup files are separate destinations. Health logging can be skipped during contention instead of crashing a worker.
- Lock delays cannot backdate a locked prediction: freshness and the decision deadline are checked again after acquiring the writer. Missed opportunities remain missed.
- Failed workers recover. The Windows launcher restarts an exited scanner or dashboard independently, with bounded backoff. The other service stays running. A surviving but stalled system still needs diagnostics; this is not proof of uninterrupted operation on every network.
- Telegram sends are claimed before HTTP, without holding a database transaction during delivery. If Telegram accepts a send but its database acknowledgement fails, the alert is not blindly resent. Its eventual delivery_unknown state accurately reflects the missing acknowledgement; phone receipt cannot be inferred.

## Install safely on your Windows laptop

1. Download the complete hotfix ZIP from the release commit link provided with this guide. Right-click it, choose **Extract All**, and extract into a NEW folder. Do not extract over your existing bot folder.
2. Keep your current bot running until you are ready. Note its existing folder path. Do not copy a new database into it, delete SQLite WAL/SHM files, or delete scanner lock files.
3. When ready, press **Ctrl+C** in the existing LOCAL bot terminal and wait for it to stop. Close any separately launched local scanner/dashboard. This does not stop a cloud bot.
4. In the NEW extracted folder, double-click **update-windows.cmd**. Paste the path of your EXISTING installation folder when asked. This uses `%USERPROFILE%\Downloads\python.3.12.10\tools\python.exe`; no standard installer or `py` launcher is needed.
5. The updater verifies source hashes, backs up existing code and the complete data folder, and uses SQLite's online backup with integrity checks. It preserves `.venv` and private settings. Keep the printed `recovery\in-place-...` folder path. If it refuses because the scanner is running, stop that local scanner normally and retry; do not bypass the guard.
6. Run **start-windows.cmd in your EXISTING folder**. Open **http://127.0.0.1:8000** in Chrome and press **Ctrl+F5**. Your password, Telegram settings and historical scoreboard should remain unchanged. Do not launch the newly extracted source as a second bot.
7. Check that the lifetime record remains intact, prices and countdown update, and resolved market results arrive. RESYNCING is a verification state, not a reason to force LIVE. If CLOCK SKEW persists, check Windows **Settings → Time & language → Date & time → Sync now**. Never disable security software or certificate checks.

## Roll back

Stop the local bot with Ctrl+C. Open Command Prompt in the NEW extracted folder and run:

```bat
"%USERPROFILE%\Downloads\python.3.12.10\tools\python.exe" inplace_update.py --rollback
```

Paste the printed recovery folder. The updater restores the backed-up code/settings/database and retains post-upgrade data in a separate `before-rollback-...` folder so it is not silently lost. Restart `start-windows.cmd` in your original folder. Keep both recovery folders.

## Verification limits

Automated checks cover real competing SQLite connections, rollback, readers, concurrent writers, prediction deadlines, Telegram deduplication, live-stream continuity/reconnection, authentication and existing V4 functionality. Synthetic stream tests establish correctness, not profitability. The release report gives actual Linux/Windows CI results and public-feed connectivity results. A local laptop soak test remains necessary: confirm stable operation across several rounds and a brief network outage. Public REST availability does not establish WebSocket availability on your network. No private credentials, trading orders, or funds access are required or added.
