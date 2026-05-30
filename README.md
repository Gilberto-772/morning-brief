# Morning Brief

A generated daily morning brief website with market movers, financial news, world news, political events, AI news, AI model updates, and housing market headlines.

## Local use

Run the generator:

```powershell
C:\Users\perez\AppData\Local\Python\pythoncore-3.14-64\python.exe .\daily_brief\brief.py
```

Open the site:

```text
morning_brief_site/index.html
```

## Email secrets

For local email delivery, set these environment variables:

```powershell
setx BRIEF_EMAIL_SENDER "your-icloud-email@icloud.com"
setx BRIEF_EMAIL_RECIPIENT "your-icloud-email@icloud.com"
setx ICLOUD_APP_PASSWORD "your-apple-app-specific-password"
```

For GitHub Actions, add repository secrets with the same names:

- `BRIEF_EMAIL_SENDER`
- `BRIEF_EMAIL_RECIPIENT`
- `ICLOUD_APP_PASSWORD`

Do not commit real passwords or app-specific passwords.

## GitHub Pages setup

After this folder is pushed to GitHub:

1. Open the repository on GitHub.
2. Go to `Settings` > `Secrets and variables` > `Actions`.
3. Add these repository secrets:
   - `BRIEF_EMAIL_SENDER`
   - `BRIEF_EMAIL_RECIPIENT`
   - `ICLOUD_APP_PASSWORD`
4. Go to `Settings` > `Pages`.
5. Set `Source` to `GitHub Actions`.
6. Open the `Actions` tab and run `Daily Morning Brief` manually once.

The scheduled workflow runs at the UTC times that correspond to 8 AM New York during daylight saving time and standard time. The workflow checks New York time before sending so it only publishes/sends during the 8 AM hour.
