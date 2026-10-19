# BTC Pro V3 release

Start with [safe V3 Windows update](V3-WINDOWS.md), [all 26 implementation areas](V3-IMPLEMENTATION.md), and [verified results and limitations](V3-VERIFICATION.md). Existing history and manual-only trading are preserved. Live streaming and validated profitability are not implied by this release.

# Kalshi BTC 15-minute intelligence dashboard

Private Chrome dashboard + Telegram; Python 3.12 / Flask / Waitress / SQLite. **No automatic trades, account access, balance queries or fund controls.** Public Kalshi/Coinbase data only; optional market-data WebSocket is off by default.

**Already installed the intelligence upgrade?** Follow [PATCH-WINDOWS.md](PATCH-WINDOWS.md): `update-windows.cmd` performs a backed-up **in-place code update**, retaining your data, `.venv`, credentials and bookmark. No old data-import process is needed. Native Windows final checks remain on your laptop. Fresh installations can still use [UPGRADE-WINDOWS.md](UPGRADE-WINDOWS.md).

## Implemented upgrade

- Immutable +60s (+5s deadline) per-market UP/DOWN tracker, official results, ET today/7d/30d/all statistics, streak/pending/missed counts and pagination; separate preliminary outlook.
- Independent breakout, timed reversal and seven-vote confluence engines, three cards, documented causal indicators and explicit data gaps.
- Flip/scalp radars, validated-candidate fair value gates, regime context and separate delayed bid/ask/depth/fee/slippage simulator ledgers.
- Public historical backfill, weekday/hour tables/charts, strategy/regime performance and raw-data provenance.
- Actual logistic candidate fitting, validation calibration, expanding time-ordered OOS evaluation, audit artifacts and live shadow versions. Original heuristic remains baseline, never automatically replaced.
- Timestamped collection, indexes/retention/hourly aggregates, optional authenticated sequenced book transport and opt-in throttled Telegram categories.
- Additive schema backups, backed-up in-place Windows patch/rollback (legacy side-by-side import remains available), optional current-user Windows DPAPI encrypted credential reuse.

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

## Reliable locking and separate Telegram alerts

The dedicated forecast clock uses independent short-timeout metadata, candles, BTC quote and Kalshi book workers; slow research, fee lookups, settlement and Telegram delivery cannot block it. New forecasts target +60s; +65s to +120s observations are immutable LATE records scored separately. Historical MISSED rows remain intact, and rejected attempts expose precise reasons.

Persistent authenticated notification settings control preliminary outlooks, locked forecasts, calibrated potential entries, flips, scalps, engines, settlements and daily reports. Locked baseline forecasts are not entry recommendations. Legacy heuristic-only entries are no longer sent as recommendations after migration. Real entries require validated shadow-model economics. Scalp watches require verified fast data; scalp-entry alerts additionally need per-side/horizon forward evidence. Telegram Alert Performance starts execution observation after API acknowledgement, retains missing fills/exits, and never confuses unalerted paper positions with alerted trades.

Latest patch checks and platform limits: [PATCH-VERIFICATION.md](PATCH-VERIFICATION.md). Original release verification remains in [VERIFICATION.md](VERIFICATION.md).
