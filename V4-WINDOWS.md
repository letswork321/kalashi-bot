# V4 safe Windows launch — keep V3 as fallback

V4 is a separate development/research release. It does not establish 75% accuracy or validated cash-out profits. Do not replace a working installation just to obtain more confident-looking labels. Data-quality gates intentionally show WAIT/UNAVAILABLE where requirements are unmet.

## Before switching

1. Download the exact tested V4 commit ZIP and choose **Extract All** into a NEW folder, such as `Downloads\kalshi-v4`. Do not extract over V3 or inside its folder.
2. Keep your complete Python NuGet distribution at `%USERPROFILE%\Downloads\python.3.12.10\tools\python.exe`. V4 supports your existing Python setup. No Docker, laptop Node.js, `py` launcher or security-setting changes are needed.
3. Keep V3 running until you deliberately choose to import history. Your Windows live SQLite database is not accessible to the cloud developer unless you share a sanitized export.

## Optional read-only research export while V3 is running

Open Command Prompt in the NEW V4 folder. Run the following with the path of your EXISTING V3 database substituted for `C:\YOUR-V3-FOLDER\data\live.sqlite3`:

```bat
"%USERPROFILE%\Downloads\python.3.12.10\tools\python.exe" research_export.py --db "C:\YOUR-V3-FOLDER\data\live.sqlite3" --output "%USERPROFILE%\Downloads\research-export-v4.json"
```

This exporter uses only the Python standard library. It opens the source read-only, exports at most 2,000 records per allowlisted table with a five-second query budget, and never takes a full database backup. Credential tables, arbitrary JSON/text, Telegram messages, tokens and passwords are excluded. Review the resulting file before sharing. An old V3 database has no V4 feed history; it cannot recover observations that were never recorded. Rejections are attempts, not necessarily distinct missed markets. GAPPED is not a loss.

## Deliberate side-by-side installation

1. When ready, press **Ctrl+C** in the LOCAL V3 console and wait for the scanner/server to stop. Do not stop your cloud bot.
2. In the NEW V4 folder run **upgrade-windows.cmd**. Paste the OLD V3 project-folder path when asked. The importer locks against an active local scanner, backs up and integrity-checks SQLite, imports data into V4, and leaves all V3 code/history/credentials untouched. Save the printed recovery path.
3. Run **start-windows.cmd in the NEW V4 folder**. Its own virtual environment is created/verified; the old V3 `.venv` is not deleted. Your copied credential settings remain protected. The additive v10 schema makes another backup before migration.
4. Open regular Chrome at **http://127.0.0.1:8000** and refresh with Ctrl+F5. Use your existing password. Check history, correct current ticker, strike, countdown, 1m/5m/15m candles, source event ages, and separate score definitions.
5. In **Add manual position**, type `20` for 20 cents, choose UP/DOWN and optionally contracts/actual total entry fee. Blank fee is a clearly labeled standard-taker estimate. You may enter a 5–99% net goal. A mathematically impossible goal is labeled. An observed target touch is not proof you sold.
6. Enable desired categories under Advanced → Telegram settings. New significant-change/cash-out categories are opt-in. Exit watches require supplied position basis. Extreme Move Radar has no Telegram category. Existing phone connectivity can be checked through the normal private setup connection test; never paste tokens into chat.

The dedicated V4 API is `/api/v4/state`. All analytics run on the backend; credentials never go to Chrome. Original engines, fixed +60s forecast protocol, Telegram connection, indicators and historical scoring definitions remain available. Research stays collapsed.

## Required live-data checks

A genuinely LIVE Coinbase chart needs outbound WSS port 443 with CONNECT/Upgrade to `ws-feed.exchange.coinbase.com`, plus HTTPS REST to `api.exchange.coinbase.com`. Kalshi REST needs `api.elections.kalshi.com`. Telegram needs `api.telegram.org`. A REST allowlist alone does not enable WebSockets. Do not bypass TLS, a region restriction, Defender or Smart App Control.

Reliable executable sub-minute cash-out monitoring additionally requires the optional sequenced Kalshi data book and current fees. Optional backend market-data keys remain OFF until explicitly configured after your previously reported laptop security issue is resolved. See V3-IMPLEMENTATION.md for existing `KALSHI_DATA_KEY_ID`, `KALSHI_DATA_PRIVATE_KEY_FILE`, `KALSHI_WS_ENABLED`, `KALSHI_BRTI_ENABLED`, and `KALSHI_DATA_SECURITY_CONFIRMED` settings. These are data-only connections, never trading/funds permissions.

BLS calendar and optional Binance USD-M liquidation adapters are experimental and external access remains unverified. `V4_LIQUIDATION_WS=true` explicitly enables the optional PUBLIC partial liquidation stream; it is off by default. It does not measure market-wide liquidations, open interest or funding. Do not infer zero liquidations from an unavailable stream. Macro consensus/news feeds require licensed access and are currently unavailable; there is no news widget.

## Fall back to V3

Stop only V4 with Ctrl+C. Run `start-windows.cmd` in the ORIGINAL V3 folder. Use the same Chrome bookmark. V3 was never overwritten. Keep both folders and their databases; observations collected in V4 are retained there and are not automatically merged backward. Never run two scanners on one database or two servers on port 8000.

An in-place, backup-preserving `update-windows.cmd` and `rollback-update.cmd` are also retained for later deliberate updates, but side-by-side installation is recommended for this major version.
