$password = Read-Host "Paste your NEW Apple app-specific password for Morning Brief"
if ([string]::IsNullOrWhiteSpace($password)) {
    Write-Host "No password entered. Nothing was saved."
    exit 1
}

setx DAILY_BRIEF_ICLOUD_APP_PASSWORD "$password" | Out-Null
Write-Host "Saved DAILY_BRIEF_ICLOUD_APP_PASSWORD for your Windows user."
Write-Host "Close and reopen VS Code before testing Refresh Daily Brief."
