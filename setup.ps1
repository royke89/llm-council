# One-time setup for LLM Council on a Windows machine.
# Installs dependencies, registers the `council-review` command + desktop
# shortcut, and scaffolds the .env file. Safe to re-run (idempotent).

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
Write-Host "== LLM Council setup =="
Write-Host "Repo: $repo"

# --- Prerequisites ---------------------------------------------------------
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python not found. Install Python 3.10+ from https://www.python.org/ and re-run."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "Node.js/npm not found. Install Node from https://nodejs.org/ and re-run."
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv (Python package manager)..."
    python -m pip install uv
}

# --- Backend deps ----------------------------------------------------------
# Use a non-roaming Python install dir; the default Roaming AppData path can
# fail to extract managed CPython on some Windows setups.
$env:UV_PYTHON_INSTALL_DIR = Join-Path $env:LOCALAPPDATA "uv-python"
Write-Host "Installing backend dependencies (uv sync)..."
uv sync --project $repo

# --- Frontend deps ---------------------------------------------------------
Write-Host "Installing frontend dependencies (npm install)..."
Push-Location (Join-Path $repo "frontend")
try { npm install --no-fund --no-audit } finally { Pop-Location }

# --- Put repo on PATH so `council-review` works anywhere -------------------
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if (($userPath -split ';') -notcontains $repo) {
    [Environment]::SetEnvironmentVariable("PATH", "$userPath;$repo", "User")
    Write-Host "Added repo to your PATH (open a NEW terminal to use 'council-review')."
} else {
    Write-Host "Repo already on PATH."
}

# --- Desktop shortcut to the web-app launcher ------------------------------
try {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $lnk = Join-Path $desktop "LLM Council.lnk"
    $ws = New-Object -ComObject WScript.Shell
    $s = $ws.CreateShortcut($lnk)
    $s.TargetPath = Join-Path $repo "Start LLM Council.bat"
    $s.WorkingDirectory = $repo
    $s.IconLocation = "C:\Windows\System32\shell32.dll,13"
    $s.Description = "Start LLM Council (backend + frontend + browser)"
    $s.Save()
    Write-Host "Created desktop shortcut: $lnk"
} catch {
    Write-Host "Could not create desktop shortcut (non-fatal): $($_.Exception.Message)"
}

# --- .env scaffold ---------------------------------------------------------
$envFile = Join-Path $repo ".env"
$needKey = $true
if (Test-Path $envFile) {
    if (Get-Content $envFile | Where-Object { $_ -match '^OPENROUTER_API_KEY=.+' }) {
        $needKey = $false
    }
} else {
    "# Get your key at https://openrouter.ai/keys`r`nOPENROUTER_API_KEY=" |
        Out-File -Encoding utf8 $envFile
}

Write-Host ""
Write-Host "Setup complete."
if ($needKey) {
    Write-Host "ACTION NEEDED: add your OpenRouter API key to:" -ForegroundColor Yellow
    Write-Host "  $envFile"
    Write-Host "  Get one at https://openrouter.ai/keys"
}
Write-Host ""
Write-Host "  Web app : double-click 'LLM Council' on your Desktop"
Write-Host "  CLI     : run  council-review --ask `"your question`"  inside any project"
