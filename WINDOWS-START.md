# Open your dashboard privately on Windows

Nothing here publishes a website. The dashboard listens only on your own PC. You place every trade manually.

1. Tell the assistant to stop the private cloud scanner before starting the Windows copy. Running both produces duplicate alerts and separate performance histories.
2. Keep your complete official NuGet Python 3.12.10 folder at `%USERPROFILE%\Downloads\python.3.12.10\tools\`. The launcher automatically finds `python.exe` there. No standard installer, `py` launcher, PATH edit, or Windows security change is required. Do not move only the executable; keep its libraries and DLLs too.
3. Open the `windows-dashboard-setup` branch of your GitHub repository. Click **Code → Download ZIP**, then **Extract All** in Windows. Open the extracted folder that contains `start-windows.cmd`. Do not run from the ZIP viewer. If upgrading an existing local copy, retain its `data` folder (copy it only with that local scanner stopped); do not delete your history. Cloud history does not automatically transfer to Windows.
4. Double-click **start-windows.cmd**. A console shows the selected Python path, creates a private `.venv` folder on first launch, and installs/verifies the pinned dependencies with normal TLS verification. Later launches reuse that environment. The bootstrap also restores pip from bundled `ensurepip` if needed and checks scanner/dashboard imports before asking for credentials. Keep it open. If Windows or organizational security blocks the launcher, do not disable protections; ask for help with the exact error text.
5. At the token prompt, paste the token you already saved in your vault. The prompt is hidden: you will see no characters while typing/pasting. The cloud Personal vault does not automatically supply values to a program on your PC. Never paste your token into a chat or command line.
6. At the chat-ID prompt, enter the private chat ID we verified together. At the dashboard-password prompt, choose a unique password at least 12 characters long. Remember it; the launcher does not save it.
7. A clearly labeled connection-test message should reach your Telegram chat. Your default browser then opens the private dashboard. Log in with username **viewer** and the dashboard password you just chose.
8. Leave the console open and keep your PC awake with Internet access. You can move the browser to your second monitor. Automatic strong-signal, reversal/withdrawal and final-outcome alerts run while the console is running. The bot does not execute trades.
9. To stop, press **Ctrl+C** in the console. Next time, double-click the launcher again and enter the credentials. Credentials are not written to files. Prediction/paper history is kept in the extracted folder's `data` directory; don't delete it.

A **LIVE** badge means the dashboard has a recent valid forecast from real inputs, not that a trade is recommended. **NO TRADE** can be normal even when the feed is live. Missing/stale data, a one-sided Kalshi book or an expired market suppress signals. There is never an automatic mock-price fallback. Probabilities remain heuristic and uncalibrated.

If your firewall asks whether to expose the Python server to other computers, no inbound LAN/public access is needed. Keep the listener private; don't set up router port forwarding, tunnels, or public hosting.

The official NuGet 3.12.10 package was inspected and contains `venv`, `ensurepip`, and pip. A clean Python 3.12 cloud environment installed the requirements successfully; automated tests cover bootstrap success/failure and existing-environment preservation. Scanner/dashboard startup and HTTP authentication are tested on Linux. This environment cannot execute Windows `cmd.exe`, the NuGet Windows binary, or open your Windows browser: automatic path detection, Windows venv creation, hidden prompts, a real Telegram test, and the final browser opening still need to be confirmed on your laptop. Share only error text without credentials if something fails.

## If your NuGet folder is somewhere else

The default above needs no configuration. Only if you move it, open Command Prompt in the project folder and use this optional session-only override (replace the example path):

```cmd
set "KALSHI_PYTHON=C:\your Python folder\tools\python.exe"
start-windows.cmd
```

This does not change PATH or security settings. Paths with spaces are supported. To install/check dependencies without starting the scanner or sending alerts, use:

```cmd
"%USERPROFILE%\Downloads\python.3.12.10\tools\python.exe" windows_setup.py --setup-only
```

If setup reports an incomplete or incompatible `.venv`, leave `data` intact and rename only `.venv` to `.venv-old` before retrying. Setup does not delete your files automatically.
