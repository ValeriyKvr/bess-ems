# BESS ↔ EMS Simulator - Local Startup Script (PowerShell)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  Запуск BESS-EMS симулятора локально (без Docker)" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

$rootDir = $PSScriptRoot

# 1. MQTT Broker (порт 1883)
Write-Host "[1/4] Запуск MQTT брокера (порт 1883)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$rootDir'; Write-Host 'MQTT Broker запущено на порту 1883...' -ForegroundColor Green; uv run --with amqtt amqtt"
Start-Sleep -Seconds 2

# 2. EMS Core (порт 8000)
Write-Host "[2/4] Запуск EMS Core (порт 8000)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$rootDir\ems'; Write-Host 'EMS Core запущено на http://localhost:8000...' -ForegroundColor Green; uv run uvicorn ems.main:app --host 0.0.0.0 --port 8000"
Start-Sleep -Seconds 3

# 3. BESS Simulator (порт 5020, MQTT 1883)
Write-Host "[3/4] Запуск BESS симулятора..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$rootDir\bess-sim'; Write-Host 'BESS Simulator запущено (Modbus: 5020)...' -ForegroundColor Green; uv run python -m bess_sim.main"
Start-Sleep -Seconds 2

# 4. Web Frontend (порт 5173)
Write-Host "[4/4] Запуск Web Dashboard (порт 5173)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$rootDir\web'; Write-Host 'Web Dashboard запущено на http://localhost:5173...' -ForegroundColor Green; pnpm dev"

Write-Host ""
Write-Host "========================================================" -ForegroundColor Green
Write-Host "  Всі сервіси запущено в окремих вікнах!" -ForegroundColor Green
Write-Host "  Інтерфейс: http://localhost:5173" -ForegroundColor Green
Write-Host "  Для зупинки: .\scripts\stop-local.ps1 або .\stop-local.bat" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green

Start-Sleep -Seconds 3
Start-Process "http://localhost:5173"
