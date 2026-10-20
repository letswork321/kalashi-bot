# V4 lifetime scoreboard update

The pinned top-right scoreboard reads `/api/v4/scoreboard` directly every two seconds. It uses the same lifetime immutable-lock/official-settlement calculation as V3, including imported history. Accuracy excludes pending and missed rounds. Caller path scores and paper P&L are not mixed into this record. Missing/unavailable databases show unavailable, never a fabricated 0–0; failed updates retain last verified counts with a stale warning.

The existing top-right summary-column footprint is retained, keeping the chart, cash-out panel and radars in place. The scoreboard stays pinned while scrolling. No schema migration or history reset is introduced by this patch.

## Safe Windows update

1. Download the exact tested commit ZIP and Extract All into a NEW temporary update folder. Do not extract over your working installation.
2. When ready, stop only your LOCAL running V4 console/server with Ctrl+C. Leave the cloud bot alone.
3. From the NEW folder run `update-windows.cmd`. Paste the path to your EXISTING V4 installation (the folder containing `scanner.py` and `data\live.sqlite3`).
4. Save the printed `recovery\in-place-...` path. The updater verifies hashes, uses integrity-checked SQLite backups, and preserves history, private configuration, encrypted credentials and `.venv`.
5. Run `start-windows.cmd` in the EXISTING installation. Open http://127.0.0.1:8000 and press Ctrl+F5. The lifetime WINS–LOSSES, accuracy, pending and missed counts should load in the top-right card and remain visible on scroll.

Your existing NuGet Python path remains supported. Do not delete data or credentials or run two scanners against one DB. To roll back, stop the local updated bot, run `rollback-update.cmd` from the temporary folder and supply the saved recovery path. Post-update data is retained separately by rollback.

## Verification

292 local tests ran: 291 passed, with the existing native-Windows DPAPI check skipped on Linux. Existing tests were retained. Dedicated tests cover imported lifetime history, pending/missed/late exclusions, official settlement updates without a live feed, authentication, read-only behavior, unavailable databases, and absence of hidden-DOM dependencies.

An isolated Chromium test with explicit test-fixture history verified counts/accuracy, a backend settlement update, pinning during scroll, failure retention and recovery, independence from hidden DOM, mobile bounds and no JavaScript errors. It also measured the existing 387px chart height; this is layout verification, not evidence of market profitability. No production DB, credentials or running user bot were changed. Platform CI results are linked in the release response.
