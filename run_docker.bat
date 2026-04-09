@echo off
REM ═══════════════════════════════════════════════════════════════════════════
REM ADIE — Isolated Docker Launch
REM Run this script to boot up the ADIE environment inside a Docker container.
REM ═══════════════════════════════════════════════════════════════════════════

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║   ADIE Docker Environment Setup                      ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

where docker-compose >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] docker-compose not found! Please install Docker Desktop.
    pause
    exit /b 1
)

echo [INFO] Building and starting ADIE container...
docker-compose up -d --build

echo.
echo [OK] Container is running!
echo [INFO] Launching interactive shell inside ADIE container...
echo.
echo Type 'exit' to leave the container.
echo To run your scripts inside:
echo   python setup/analyst_agent.py ...
echo   python e2e_simulate_fusion.py
echo.

docker-compose exec -it adie-core bash
