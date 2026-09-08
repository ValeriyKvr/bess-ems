# BESS ↔ EMS Simulator - Stop Local Services
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  Пошук та зупинка локальних сервісів BESS-EMS..." -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

$ports = @(1883, 8000, 5020, 5173)
$stoppedAny = $false

foreach ($port in $ports) {
    $connections = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($connections) {
        $pids = $connections | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($pidToKill in $pids) {
            if ($pidToKill -gt 0) {
                try {
                    $proc = Get-Process -Id $pidToKill -ErrorAction SilentlyContinue
                    if ($proc) {
                        Write-Host "Зупинка процесу $($proc.ProcessName) (PID: $pidToKill) на порту $port..." -ForegroundColor Yellow
                        Stop-Process -Id $pidToKill -Force -ErrorAction SilentlyContinue
                        $stoppedAny = $true
                    }
                } catch {
                    # Ignore permission/not found errors
                }
            }
        }
    }
}

if (-not $stoppedAny) {
    Write-Host "Активних процесів на портах 1883, 8000, 5020, 5173 не знайдено." -ForegroundColor Green
} else {
    Write-Host "Всі локальні сервіси BESS-EMS успішно зупинено!" -ForegroundColor Green
}
