# scripts/down_bare.ps1
# Dừng toàn bộ các tiến trình bare-mode dựa vào PID trong run/*.pid
$ErrorActionPreference = "SilentlyContinue"
$RootDir = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RootDir

if (Test-Path "run") {
    Get-ChildItem -Path "run\*.pid" | ForEach-Object {
        $pidContent = (Get-Content $_.FullName -ErrorAction SilentlyContinue | Out-String).Trim()
        if ($pidContent -match '^\d+$') {
            $procId = [int]$pidContent
            try {
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            } catch {
                # Tiến trình có thể đã dừng trước đó
            }
        }
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    }
}
Write-Output "all stopped"
