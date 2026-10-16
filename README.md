# BTC 15-minute monitor: dashboard + Telegram

This bot reads public Kalshi and Coinbase data, estimates UP/DOWN probabilities, records predictions, and maintains a paper-trading ledger. It never places orders or accesses a Kalshi account. You do not need a Kalshi trading API key.

**Current state:** live Kalshi market discovery, official strike, orderbook, fee metadata, finalized-result API, and fresh Coinbase trade/candle data have been verified. Automated tests cover signals, accounting, alerts, and dashboard behavior. Actual Telegram delivery still requires your token/chat ID. Nothing has been published or deployed to a public website.

## Private Windows use (no public deployment)

Follow [WINDOWS-START.md](WINDOWS-START.md). Double-click `start-windows.cmd` after extracting the Windows ZIP. This uses hidden credential prompts and a loopback-only Waitress server. Stop the cloud worker first to avoid duplicate alerts.

## 1. Network settings

In Codex environment settings, keep **restricted access**, preserve existing domains and package-manager presets, and allow these HTTPS domains (port 443):

- `api.elections.kalshi.com` — public Kalshi API
- `api.exchange.coinbase.com` — BTC/USD trades and one-minute candles
- `api.telegram.org` — phone alerts
- `kalshi.com` — official fee schedule; retained existing domain
- `docs.kalshi.com` — API documentation

The draft includes these domains. Save the network changes to apply them to the running machine. Publishing is a separate step: wait until live checks and a real Telegram test pass. An HTTP proxy tunnel 403 means the destination is still denied; changing application code or disabling TLS does not solve it. Telegram's root URL redirects to another site, so test the bot API rather than the root homepage. A 401 from the bot API means the domain is reachable but the token is missing/invalid.

## 2. Create your Telegram bot (one time)

1. In Telegram, find the verified **@BotFather**, send `/newbot`, and follow its instructions.
2. It gives you a **bot token**. Treat this like a password. In environment settings, add `TELEGRAM_BOT_TOKEN` as a private runtime variable. Do not paste it in chat, GitHub, screenshots, or a command line.
3. Open your new bot in Telegram and send `/start`. A bot cannot initiate a private conversation until you do this.
4. Run the chat-ID helper below. It prints only available chat IDs and chat types, never tokens or message text. Choose your private chat's ID. Save it in environment settings as `TELEGRAM_CHAT_ID`. Do not use a third-party bot to obtain your token or share it.
5. Add `DASHBOARD_PASSWORD` in environment settings. Use a long unique password from your password manager. The dashboard username is **viewer**.
6. Save the variables so they are available to the running process, then run the Telegram test. Check that the message arrives on your phone. Enable Telegram notifications for your bot's chat.

From the project directory, using the prepared cloud environment:

```bash
/workspace/kalashi-runtime/.venv/bin/python scanner.py --telegram-chat-id
/workspace/kalashi-runtime/.venv/bin/python scanner.py --telegram-test
```

If the chat list is empty, send a new `/start` and rerun it. If you already attached a webhook or another process consumes updates for this bot, use a dedicated bot. Telegram tokens are needed as real application runtime values; a generic API bearer-token header does not work for this API.

## 3. Validate before deployment

```bash
/workspace/kalashi-runtime/.venv/bin/python scanner.py --check-live
/workspace/kalashi-runtime/.venv/bin/python -m unittest discover -s tests -v
/workspace/kalashi-runtime/.venv/bin/python scanner.py --telegram-test
```

`--check-live` must exit successfully and print `ready_for_prediction: true`. It makes real read-only requests, does not generate paper positions, and does not send messages. A successful preflight does not establish model accuracy. `--telegram-test` sends one clearly labeled test message, not a trade signal.

The cloud onboarding UI cannot host a public dashboard preview. Use local HTTP checks for validation here, then deploy to a website host for your second monitor. A local server or saved draft is not a public deployment.

## 4. Deploy a website (example: Render)

A persistent paid service/disk may be required. Avoid free services that sleep or erase local files: the scanner must run continuously and its SQLite history must survive restarts.

1. Put the project files from this folder into a GitHub repository: `scanner.py`, `dashboard.py`, `templates/`, `tests/`, `requirements.txt`, `start.sh`, `.gitignore`, `.python-version`, and this README. Do not upload `.venv`, `data`, passwords, tokens, or the original placeholder `main.py.`. The prepared code is left for your review; it has not been pushed.
2. On Render, create a **Web Service** linked to that repository, using the Python runtime. Set Python to **3.12** (a supported 3.12 patch release).
3. Build command: `pip install -r requirements.txt`
4. Start command: `SCANNER_PYTHON=python bash start.sh`
5. Add private environment variables `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and `DASHBOARD_PASSWORD`. Never put these values in a build command or repository.
6. Attach a persistent disk at `/var/data` and set `SCANNER_DB=/var/data/live.sqlite3`. Use one service instance. The script runs one scanner plus one web server; scaling duplicate scanners produces duplicate alerts and paper accounting.
7. Choose the health-check path `/healthz`. This checks the web process; the dashboard separately shows source failures and stale data. Startup runs a live preflight and refuses to start if live feeds fail.
8. Deploy. Open the host-provided **HTTPS** address. Sign in as `viewer` with your dashboard password and leave it open on your second monitor. Never expose this dashboard over plain HTTP; Basic authentication requires HTTPS from your host.
9. Confirm the status is **LIVE**, trade timestamps update, the strike matches Kalshi, and your Telegram test arrives. Only then consider the deployment complete. If the host restricts outbound traffic, allow the domains above on HTTPS/443 there too. Cloud onboarding network settings do not automatically configure a separate hosting provider.

For an existing server, run `start.sh` under a process supervisor with an HTTPS reverse proxy. Do not expose Flask's development server publicly. `PORT` defaults to 8000; most hosts inject it. Credentials stay on the server and are never sent to dashboard JavaScript.

## What the dashboard shows

- Current Coinbase BTC/USD trade and timestamp, current KXBTC15M ticker, official Kalshi `floor_strike`, and countdown to `close_time`.
- Estimated UP/DOWN probability, strong/weak/NO TRADE signal, RSI14, EMA9/21, momentum, volume ratio, volatility, orderbook imbalance/spread, and estimated paper entry/edge.
- Recent forecasts and official results, first-forecast-per-market accuracy, Brier score, paper win rate, net P&L, ROI, open positions and realized drawdown.
- A clear BLOCKED/STALE status when live inputs fail. It stops showing an actionable signal after disconnection, stale data or market close. Your browser is read-only; it cannot submit trades or change the scanner.

## Signals and phone notifications

This is an **uncalibrated heuristic model**, not a trained prediction model. It combines a volatility-scaled price-to-strike calculation, damped momentum/EMA drift, RSI, relative volume, book imbalance and market-implied probability. It caps estimates between 5% and 95%. These numbers are estimates, not established odds of success; the settlement log and calibration bins are how you evaluate them over time.

Defaults: estimated net edge at least 5 percentage points and side probability at least 60%; STRONG additionally requires probability >=75% and edge >=10 points. It blocks new signals in the last 90 seconds, on wide spreads (>8 cents), missing depth/strike, invalid candles, stale BTC trades (>20 seconds), stale candle data (>120 seconds after the last close), and slow combined snapshots (>15 seconds).

Phone notifications: first strong signal, subsequent material strong-probability changes (>=5 points), meaningful reversals (opposite side with probability >=65%), withdrawals to NO TRADE, and one final official outcome per paper position. Weak first signals stay on the dashboard without phone alerts. There is a 60-second per-market cooldown. Alerts are persisted, retried with backoff, and deduplicated; stale/opposite pending signals expire. Delivery is at-least-once: an ambiguous network timeout after Telegram accepts a message can still cause a duplicate. No alerts are ever sent from mock mode.

Coinbase is a reliable spot venue, **not Kalshi's CF Benchmarks settlement index**. Kalshi's rules use a 60-second average at opening and closing. The bot takes the official price to beat from Kalshi and waits for Kalshi's official yes/no result; it never substitutes Coinbase for settlement. Venue basis differences and averaging can cause wrong predictions.

## Prediction history and paper trading

All live scans (including NO TRADE and input failures) are recorded in SQLite. No real trade is executed. One estimated position per market is opened on the first actionable signal and held to official settlement; later signals do not retroactively change that position. Entry walks opposite-side bids as complementary asks and adds $0.002 per-contract slippage. Default size is one contract (`--quantity`).

Estimated taker fee uses the official quadratic rate 0.07, series/event multiplier, and rounds total fee + position cost up to $0.0001 per the fetched July 7, 2026 schedule. Event fee changes are checked; unknown fee types suppress forecasts. Fee on an average multi-level fill is an approximation. The current schedule charges no settlement fee. Real fees, fills, tick sizes, queueing and slippage can differ; verify the schedule before manual trading.

A position pays $1 per winning contract and $0 if it loses. Net P&L subtracts estimated entry cost and fee. Unsettled/void/unknown outcomes remain pending and do not count as wins or losses. First-forecast-per-market accuracy avoids counting repeated snapshots as independent markets; all-snapshot accuracy/Brier and calibration bins are also available. A win rate without a settled sample is shown as unavailable, never invented.

```bash
/workspace/kalashi-runtime/.venv/bin/python scanner.py --report
/workspace/kalashi-runtime/.venv/bin/python scanner.py --settle
```

Back up the SQLite database regularly using SQLite's online backup API. Do not copy a live DB without its WAL or use network-mounted SQLite storage. History is not reconstructed when the database is lost.

## Mock mode and tests

```bash
/workspace/kalashi-runtime/.venv/bin/python scanner.py --mock
```

This explicit one-cycle synthetic fixture writes only `data/mock.sqlite3`, is labeled MOCK TEST ONLY, ignores `--db`, and cannot call Telegram or live feeds. There is **no automatic fallback to mock prices**. Tests use temporary databases. To inspect a mock dashboard, explicitly point `SCANNER_DB` at the mock database; it displays MOCK TEST ONLY and hides actionable probabilities. Never label it LIVE.

## File layout

`scanner.py` owns all live polling, signals, SQLite records and Telegram delivery. `dashboard.py` serves authenticated read-only snapshots. `templates/dashboard.html` is the second-monitor view. `start.sh` supervises the two processes. `requirements.txt` pins dependencies. The existing cloud venv is outside the checkout, at `/workspace/kalashi-runtime/.venv`.
