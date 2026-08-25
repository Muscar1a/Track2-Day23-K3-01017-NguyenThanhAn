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

@(8001, 8002, 8080) | ForEach-Object {
    $port = $_
    $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($conns) {
        $conns | ForEach-Object {
            if ($_.OwningProcess -and $_.OwningProcess -gt 0) {
                try {
                    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
                } catch {}
            }
        }
    }
}

Write-Output "all stopped"
