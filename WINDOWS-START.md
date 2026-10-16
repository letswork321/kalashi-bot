# Open your dashboard privately on Windows

Nothing here publishes a website. The dashboard listens only on your own PC. You place every trade manually.

1. Tell the assistant to stop the private cloud scanner before starting the Windows copy. Running both produces duplicate alerts and separate performance histories.
2. Install **Python 3.12 for Windows** from the official python.org website. Include the **Python launcher** option. No Telegram token is needed by the Python installer.
3. Download the prepared `kalshi-bot-windows.zip`. Right-click it and choose **Extract All**. Open the extracted folder. Do not run files from inside the ZIP viewer.
4. Double-click **start-windows.cmd**. A console opens and installs the pinned dependencies with normal TLS verification. Keep it open. If Windows or organizational security blocks the launcher, do not disable protections; ask for help with the exact error text.
5. At the token prompt, paste the token you already saved in your vault. The prompt is hidden: you will see no characters while typing/pasting. The cloud Personal vault does not automatically supply values to a program on your PC. Never paste your token into a chat or command line.
6. At the chat-ID prompt, enter the private chat ID we verified together. At the dashboard-password prompt, choose a unique password at least 12 characters long. Remember it; the launcher does not save it.
7. A clearly labeled connection-test message should reach your Telegram chat. Your default browser then opens the private dashboard. Log in with username **viewer** and the dashboard password you just chose.
8. Leave the console open and keep your PC awake with Internet access. You can move the browser to your second monitor. Automatic strong-signal, reversal/withdrawal and final-outcome alerts run while the console is running. The bot does not execute trades.
9. To stop, press **Ctrl+C** in the console. Next time, double-click the launcher again and enter the credentials. Credentials are not written to files. Prediction/paper history is kept in the extracted folder's `data` directory; don't delete it.

A **LIVE** badge means the dashboard has a recent valid forecast from real inputs, not that a trade is recommended. **NO TRADE** can be normal even when the feed is live. Missing/stale data, a one-sided Kalshi book or an expired market suppress signals. There is never an automatic mock-price fallback. Probabilities remain heuristic and uncalibrated.

If your firewall asks whether to expose the Python server to other computers, no inbound LAN/public access is needed. Keep the listener private; don't set up router port forwarding, tunnels, or public hosting.

The Python application and Waitress server were checked in the cloud, including HTTP/authentication and the cross-platform lock branches. The actual Windows launcher has not been run on your PC yet. Share only error text without credentials if something fails.
