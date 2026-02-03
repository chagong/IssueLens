# Load environment variables from .env file
# Usage: . .\Load-Env.ps1 [-EnvFile <path>]

param(
    [string]$EnvFile = "$PSScriptRoot\.env"
)

if (-not (Test-Path $EnvFile)) {
    Write-Error "Environment file not found: $EnvFile"
    exit 1
}

Write-Host "Loading environment variables from: $EnvFile" -ForegroundColor Cyan

Get-Content $EnvFile | ForEach-Object {
    # Skip empty lines and comments
    if ($_ -match '^\s*$' -or $_ -match '^\s*#') {
        return
    }
    
    # Parse KEY=VALUE format
    if ($_ -match '^([^=]+)=(.*)$') {
        $name = $matches[1].Trim()
        $value = $matches[2].Trim()
        
        # Remove surrounding quotes if present
        if ($value -match '^"(.*)"$' -or $value -match "^'(.*)'$") {
            $value = $matches[1]
        }
        
        # Set environment variable
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
        Write-Host "  Set: $name" -ForegroundColor Green
    }
}

Write-Host "Environment variables loaded successfully!" -ForegroundColor Cyan
