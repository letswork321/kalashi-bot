# Kalshi BTC 15-minute intelligence dashboard

Private Chrome dashboard + Telegram; Python 3.12 / Flask / Waitress / SQLite. **No automatic trades, account access, balance queries or fund controls.** Public Kalshi/Coinbase data only; optional market-data WebSocket is off by default.

**Upgrading an existing Windows installation:** follow [UPGRADE-WINDOWS.md](UPGRADE-WINDOWS.md). Keep the old folder and use the included side-by-side data importer. Your NuGet Python at `%USERPROFILE%\Downloads\python.3.12.10\tools\python.exe` remains supported. The Chrome bookmark stays `http://127.0.0.1:8000`. No Node, Docker, standard installer, py launcher, PATH edits or security changes are needed.

## Implemented upgrade

- Immutable +60s (+5s deadline) per-market UP/DOWN tracker, official results, ET today/7d/30d/all statistics, streak/pending/missed counts and pagination; separate preliminary outlook.
- Independent breakout, timed reversal and seven-vote confluence engines, three cards, documented causal indicators and explicit data gaps.
- Flip/scalp radars, validated-candidate fair value gates, regime context and separate delayed bid/ask/depth/fee/slippage simulator ledgers.
- Public historical backfill, weekday/hour tables/charts, strategy/regime performance and raw-data provenance.
- Actual logistic candidate fitting, validation calibration, expanding time-ordered OOS evaluation, audit artifacts and live shadow versions. Original heuristic remains baseline, never automatically replaced.
- Timestamped collection, indexes/retention/hourly aggregates, optional authenticated sequenced book transport and opt-in throttled Telegram categories.
- Additive schema backups, side-by-side Windows import/rollback, optional current-user Windows DPAPI encrypted credential reuse.

**The panels do not imply validated profitability.** VWAP requires complete real session-trade coverage; exact-timed observations can be missed; public REST is insufficient for reliable 20-second scalp signals; historical depth cannot be backfilled from candles. Candidate probability validation needs genuine locked/settled samples. Empty samples and unvalidated estimates are explicitly displayed. All details and thresholds: [ANALYTICS.md](ANALYTICS.md).

## Development / verification

```bash
python windows_setup.py --setup-only
python -m unittest discover -s tests -v
python scanner.py --check-live
```

The setup-only command installs dependencies and checks imports without starting the scanner or sending Telegram messages. Unit tests use isolated synthetic fixtures, not evidence of live trading accuracy. See [VERIFICATION.md](VERIFICATION.md) for observed results and platform limits.

Additional research commands (run with the project venv):

```bash
python -m intelligence.cli backfill --days 7 --max-pages 10
python -m intelligence.cli report --days 30
python -m intelligence.cli train
```

For 30/90-day research, explicitly select that backfill window and sufficient bounded pages; inspect the persisted COMPLETE/PARTIAL/FAILED job status. Network allowlist: `api.elections.kalshi.com`, `api.exchange.coinbase.com`, `api.telegram.org`; `docs.kalshi.com` and `kalshi.com` for official contracts. Preserve existing environment bindings. No public deployment was performed.

For a first-time installation and original commands, see [WINDOWS-START.md](WINDOWS-START.md) and [LEGACY-README.md](LEGACY-README.md).
