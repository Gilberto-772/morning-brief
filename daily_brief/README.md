# Daily Brief

This generates a local Markdown morning brief with:

- financial headlines
- breaking world news
- AI news
- new AI model and research headlines
- stock-market ETF snapshots
- housing-market headlines

Run it manually:

```powershell
C:\Users\perez\AppData\Local\Python\pythoncore-3.14-64\python.exe .\daily_brief\brief.py
```

Then open `morning_brief_site/index.html` for the local website, `DAILY_BRIEF.html` for the standalone browser view, or `DAILY_BRIEF.md` for the plain Markdown view.

VS Code opens `.html` files as source code by default. To see the website, run the VS Code task named `Open Daily Brief in Browser`, or double-click `Open Daily Brief.url`.

With the Live Server extension installed, click `Go Live` in VS Code's status bar. This workspace is configured so Live Server uses `morning_brief_site` as the website root, so the site opens at:

```text
http://127.0.0.1:5500/
```

In VS Code, run the task named `Refresh Daily Brief`. The included `.vscode/tasks.json` also asks VS Code to refresh the brief when this folder opens. If VS Code prompts you to allow automatic tasks, approve it for this workspace.

Edit `daily_brief/config.json` to add/remove sources, change symbols, or adjust the number of headlines per section.

The refresh script for Windows Task Scheduler is `daily_brief/refresh_daily_brief.cmd`.

## Email delivery

The brief can email itself through iCloud Mail after each refresh. It is configured to send from and to `betitoperez705@icloud.com`.

Do not use your normal Apple password. Apple requires an app-specific password for third-party mail sending. Generate one from your Apple Account security settings, then save it as a Windows user environment variable:

```powershell
setx DAILY_BRIEF_ICLOUD_APP_PASSWORD "paste-app-specific-password-here"
```

Or in VS Code, run the task named `Set iCloud Email Password` and paste the app-specific password when prompted.

Close and reopen VS Code after saving the password, then run `Refresh Daily Brief` once to test. The scheduled 8 AM task will use the same setting.
