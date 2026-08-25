# scripts/up_bare.ps1
# 2 "region" + edge chạy trực tiếp bằng uvicorn, KHÔNG cần docker daemon.
# Dùng trên môi trường Windows PowerShell.
$RootDir = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RootDir

# Đảm bảo các thư mục tồn tại
if (-not (Test-Path "run")) { New-Item -ItemType Directory -Path "run" -Force | Out-Null }
if (-not (Test-Path "reports")) { New-Item -ItemType Directory -Path "reports" -Force | Out-Null }

Set-Content -Path "run/region-a.pid" -Value "" -NoNewline
Set-Content -Path "run/region-b.pid" -Value "" -NoNewline
Set-Content -Path "run/edge.pid" -Value "" -NoNewline

# Tự động tìm Python executable có sẵn uvicorn
$PythonCmd = "python"
$PythonPrefixArgs = @()

$null = cmd /c "py -3.11 -c ""import uvicorn"" 2>nul"
if ($LASTEXITCODE -eq 0) {
    $PythonCmd = "py"
    $PythonPrefixArgs = @("-3.11")
} else {
    $null = cmd /c "python -c ""import uvicorn"" 2>nul"
    if ($LASTEXITCODE -eq 0) {
        $PythonCmd = "python"
        $PythonPrefixArgs = @()
    }
}

function Start-RegionProcess {
    param(
        [string]$Region,
        [int]$Port
    )
    $WarmupSec = if ($env:WARMUP_SECONDS) { $env:WARMUP_SECONDS } else { "6" }
    
    $env:REGION = $Region
    $env:STATE_DIR = "state/region-$Region"
    $env:WARMUP_SECONDS = $WarmupSec
    $env:PYTHONUTF8 = "1"
    
    $argsList = $PythonPrefixArgs + @("-m", "uvicorn", "serving.app:app", "--host", "127.0.0.1", "--port", "$Port", "--log-level", "warning")
    
    $proc = Start-Process -FilePath $PythonCmd `
        -ArgumentList $argsList `
        -RedirectStandardOutput "run/region-$Region.out.log" `
        -RedirectStandardError "run/region-$Region.log" `
        -NoNewWindow `
        -PassThru
        
    Set-Content -Path "run/region-$Region.pid" -Value $proc.Id
    Write-Output "region-$Region pid=$($proc.Id) port=$Port"
}

Start-RegionProcess -Region "a" -Port 8001
Start-RegionProcess -Region "b" -Port 8002

$EdgeTtl = if ($env:EDGE_TTL_SECONDS) { $env:EDGE_TTL_SECONDS } else { "5" }
$env:EDGE_TTL_SECONDS = $EdgeTtl
$env:PYTHONUTF8 = "1"

$edgeArgs = $PythonPrefixArgs + @("-m", "uvicorn", "edge.proxy:app", "--host", "127.0.0.1", "--port", "8080", "--log-level", "warning")

$edgeProc = Start-Process -FilePath $PythonCmd `
    -ArgumentList $edgeArgs `
    -RedirectStandardOutput "run/edge.out.log" `
    -RedirectStandardError "run/edge.log" `
    -NoNewWindow `
    -PassThru

Set-Content -Path "run/edge.pid" -Value $edgeProc.Id
Write-Output "edge pid=$($edgeProc.Id) port=8080"

Write-Output "cho service len (toi da 10s)..."
$ok = $true
$services = @(
    @{ Name = "region-a"; Port = 8001; CheckUrl = "http://127.0.0.1:8001/healthz" },
    @{ Name = "region-b"; Port = 8002; CheckUrl = "http://127.0.0.1:8002/healthz" },
    @{ Name = "edge"; Port = 8080; CheckUrl = "http://127.0.0.1:8080/edge/state" }
)

foreach ($svc in $services) {
    $name = $svc.Name
    $port = $svc.Port
    $checkUrl = $svc.CheckUrl
    $up = $false
    
    for ($i = 0; $i -lt 10; $i++) {
        $null = cmd /c "curl.exe -sf -o NUL ""$checkUrl"" 2>nul"
        if ($LASTEXITCODE -eq 0) {
            $up = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    
    if ($up) {
        Write-Output "  $name (port $port): UP"
    } else {
        Write-Output "  $name (port $port): KHONG PHAN HOI -- xem run/$name.log (co the cong da bi chiem)"
        $ok = $false
    }
}

if (-not $ok) {
    Write-Error "MOT SO SERVICE CHUA LEN -- doc log truoc khi chay drill"
    exit 1
}

curl.exe -s "http://127.0.0.1:8080/edge/state"
Write-Output ""
