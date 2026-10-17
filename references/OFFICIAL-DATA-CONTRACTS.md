# Official contracts reviewed for this upgrade

Reviewed through verified HTTPS during the upgrade, alongside real read-only responses:

- https://docs.kalshi.com/websockets/websocket-connection
- https://docs.kalshi.com/websockets/orderbook-updates
- https://docs.kalshi.com/websockets/public-trades
- https://docs.kalshi.com/api-reference/market/get-trades
- https://docs.kalshi.com/api-reference/market/get-market-candlesticks
- https://docs.kalshi.com/api-reference/market/get-market-orderbook
- https://docs.kalshi.com/openapi.yaml
- https://kalshi.com/docs/kalshi-fee-schedule.pdf
- Public Coinbase Exchange `/products/BTC-USD/ticker`, `/trades` (1000 rows and backward trade-ID pagination), `/candles` (60/900s with explicit UTC start/end).

Verified API fields: Kalshi `floor_strike`, actual `open_time`/`close_time`, current `rules_primary`, finalized explicit `result`, `settlement_ts`, series fee type/multiplier and event overrides. REST `orderbook_fp.yes_dollars/no_dollars` are decimal dollars and fixed-point quantities. Public trades use `count_fp`, `yes_price_dollars`, `created_time`; historical candlesticks are aggregated intervals, not past depth/fills.

WebSocket snapshots use `yes_dollars_fp` / `no_dollars_fp`; updates use `price_dollars`, `delta_fp`, `side`, subscription ID and sequence. Authentication is required for the connection/orderbook. Public trades have no extra channel-level auth beyond the authenticated connection. This implementation does not require the optional WebSocket for public REST operation. It requests explicit NO-leg pricing (`use_yes_price=false`) because the docs describe a future default migration to unified YES-leg prices; rejection/unsupported schema fails closed.

Historical markets/candles before `market_settled_ts` from `/historical/cutoff` use `/historical/markets` and `/historical/markets/{ticker}/candlesticks`. No portfolio historical endpoints are used. The current live public API was verified at `https://api.elections.kalshi.com/trade-api/v2`; current docs also show an `external-api.kalshi.com` host. The known-working host is retained; no untested host substitution is made.

KXBTC15M rules use the opening/closing 60-second averages of CF Benchmarks BRTI and “at least” comparison. Coinbase is not that official index. The fetched official general taker fee is `M × 0.07 × C × P × (1-P)`, rounding cost+fee up to a centicent, with no settlement fee. Fee schedule changes/unknown types must be reverified rather than silently assumed.

Raw downloaded documentation was used for inspection but is not distributed as vendored application data. See ANALYTICS.md for implemented thresholds, timing tolerance, provenance, and limitations.
