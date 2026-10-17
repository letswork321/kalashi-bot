# Install the intelligence upgrade safely on Windows 11

Your working version is **052010c93f6102b29a1e904059590f55f73df9cb** on `windows-dashboard-setup`. Keep its extracted folder. This upgrade lives on **btc-intelligence-upgrade** and does not change the old installation until you deliberately switch.

1. Download this branch from GitHub: **Code → Download ZIP**. Choose **Extract All** into a new folder beside your working folder, not inside or over it. Keep the complete NuGet Python folder at `%USERPROFILE%\Downloads\python.3.12.10\tools\`.
2. When ready to switch, press **Ctrl+C in the OLD LOCAL Windows bot console**. Do not stop unrelated applications or change any cloud service. The importer refuses to copy while that local scanner holds its lock.
3. In the NEW folder, double-click **upgrade-windows.cmd**. Paste the path of the OLD extracted project folder (the one containing `scanner.py` and `data`). It makes an integrity-checked online backup of SQLite and copies your data/research/encrypted settings into the new folder. Old files stay intact. The backup and install manifest are in `recovery` in the new folder.
4. Double-click **start-windows.cmd** in the NEW folder. It uses your existing NuGet Python, creates/reuses a private `.venv`, and installs pinned dependencies. No Docker, Node.js, `py` launcher, administrator install, PATH edit, or security-setting change is required.
5. Before the additive analytics schema migration, another integrity-checked database backup is saved in `data/backups`. Existing predictions, positions, Telegram outbox, and passwords are not overwritten. If any backup/migration fails, startup stops.
6. Existing process environment credentials are reused. Existing `data/credentials.dpapi` is reused on the same Windows user account. If the old version kept credentials only in memory, enter the SAME bot token, chat ID and dashboard password once in the hidden prompts. This information cannot be recovered from a stopped process. Optionally choose **y** to remember them encrypted with Windows DPAPI, so later launches need no re-entry. No plaintext secret file is created. Do not share tokens in screenshots or messages.
7. A labeled Telegram connection test is sent, then your browser opens the dashboard. Your existing Chrome bookmark **http://127.0.0.1:8000** still works. Username: **viewer**, password: your existing dashboard password. Keep the new console open and the PC awake for collection/alerts. No public server is created.
8. Read the section statuses. Raw trade coverage, the next on-time lock/10-minute observation, and settled labels need time to accumulate. Historical outcomes do not manufacture missed predictions, past depth, or candidate training features. New alert categories default OFF; your existing directional/final-result alerts continue.

## Roll back

Press **Ctrl+C** in the NEW console and close its dashboard tab. Double-click **start-windows.cmd** in your untouched OLD folder. It uses the old code/history and the same bookmark. Keep both folders: forecasts recorded only after upgrading remain in the new database and are not silently merged into the old version. Your old data, the import backup, and the pre-migration backup remain available.

If installation stops, send only the error text without credentials. Do not delete `data` or disable Windows protections. If credentials must be re-entered, rename `data/credentials.dpapi` to a backup name while the local bot is stopped; the next launch asks again.

## What still needs testing on your laptop

The Windows executable, `cmd.exe`, Windows DPAPI encryption/decryption, native file locking and default-Chrome launch cannot be executed on this Linux cloud machine. Automated tests cover their control flow with isolated substitutes; they are not claimed as native Windows verification. The final laptop checks are: NuGet detection → dependency install → successful import/backup/migration → same-password login → real Telegram test → live data → next on-time locked prediction and final official result.
