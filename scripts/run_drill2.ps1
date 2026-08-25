# scripts/run_drill2.ps1
# Script tự động thực thi toàn bộ Step 4 Drill 2 (Có DR)
$RootDir = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RootDir

Write-Output "=== 1. Don dep va khoi dong bare services ==="
powershell -ExecutionPolicy Bypass -File scripts/down_bare.ps1
Start-Sleep -Seconds 1
powershell -ExecutionPolicy Bypass -File scripts/up_bare.ps1

Write-Output "=== 2. Khoi chay Ingest & Replication ==="
$ingestJob = Start-Process py -ArgumentList "-3.11", "state/ingest.py", "--region", "a", "--rate", "0.5", "--duration", "150" -PassThru
$replJob = Start-Process py -ArgumentList "-3.11", "state/replicate.py", "--every", "30", "--duration", "150", "--backend", "fs" -PassThru
Start-Sleep -Seconds 6  # Doi snapshot dau tien hoan tat

Write-Output "=== 3. Khoi chay Load Generator & Health Checker ==="
$loadgenJob = Start-Process py -ArgumentList "-3.11", "loadgen/traffic.py", "--duration", "80", "--rps", "2", "--out", "reports/drill-2-withdr.jsonl" -PassThru
$healthJob = Start-Process py -ArgumentList "-3.11", "dr/health_checker.py", "--interval", "5", "--threshold", "3", "--duration", "80", "--out", "reports/health-events.jsonl" -PassThru
Start-Sleep -Seconds 12

Write-Output "=== 4. Red Team Chaos: Kill Region A ==="
py -3.11 chaos/kill_region.py --region a --mode netblock --mock
Start-Sleep -Seconds 16  # Cho health checker phat hien UNHEALTHY (threshold=3, interval=5 -> 15s)

Write-Output "=== 5. Runbook Failover ==="
py -3.11 dr/runbook.py --primary a --target b --backend fs --auto

Write-Output "=== 6. Cho Load Generator hoan tat ==="
$loadgenJob.WaitForExit()

Write-Output "=== 7. Do luong RTO/RPO ==="
py -3.11 tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300 | Out-File -FilePath "reports/measure-drill-2.json" -Encoding utf8
Get-Content "reports/measure-drill-2.json"

Write-Output "=== 8. Cleanup & Stop jobs ==="
try { Stop-Process -Id $ingestJob.Id -Force -ErrorAction SilentlyContinue } catch {}
try { Stop-Process -Id $replJob.Id -Force -ErrorAction SilentlyContinue } catch {}
try { Stop-Process -Id $healthJob.Id -Force -ErrorAction SilentlyContinue } catch {}
py -3.11 chaos/kill_region.py restore --region a --backend bare
