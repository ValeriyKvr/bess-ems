@echo off
chcp 65001 >nul
echo ========================================================
echo   Запуск BESS-EMS симулятора локально (без Docker)
echo ========================================================
echo.

cd /d "%~dp0"

:: 1. MQTT Broker (порт 1883)
echo [1/4] Запуск MQTT брокера (порт 1883)...
start "BESS-EMS [1/4] - MQTT Broker" cmd /k "chcp 65001 >nul && echo ======================================== && echo  MQTT Broker запущено на localhost:1883 && echo ======================================== && uv run --with amqtt amqtt"
timeout /t 2 /nobreak >nul

:: 2. EMS Core (порт 8000)
echo [2/4] Запуск EMS Core (порт 8000)...
start "BESS-EMS [2/4] - EMS Core" cmd /k "chcp 65001 >nul && cd /d "%~dp0ems" && echo ======================================== && echo  EMS Core запущено на http://localhost:8000 && echo ======================================== && uv run uvicorn ems.main:app --host 0.0.0.0 --port 8000"
timeout /t 3 /nobreak >nul

:: 3. BESS Simulator (Modbus 5020, MQTT 1883)
echo [3/4] Запуск BESS симулятора...
start "BESS-EMS [3/4] - BESS Simulator" cmd /k "chcp 65001 >nul && cd /d "%~dp0bess-sim" && echo ======================================== && echo  BESS Simulator запущено (Modbus: 5020) && echo ======================================== && uv run python -m bess_sim.main"
timeout /t 2 /nobreak >nul

:: 4. Web Frontend (порт 5173)
echo [4/4] Запуск Web Dashboard (порт 5173)...
start "BESS-EMS [4/4] - Web UI" cmd /k "chcp 65001 >nul && cd /d "%~dp0web" && echo ======================================== && echo  Web Dashboard запущено на http://localhost:5173 && echo ======================================== && pnpm dev"

echo.
echo ========================================================
echo   Всі 4 сервіси успішно запущено у власних вікнах!
echo   Інтерфейс доступний за адресою: http://localhost:5173
echo   Для зупинки всіх сервісів запустіть stop-local.bat
echo ========================================================
echo.

timeout /t 3 /nobreak >nul
start http://localhost:5173
