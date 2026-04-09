@echo off
setlocal
echo ═══════════════════════════════════════════════════════
echo   ADIE Dashboard Web Server
echo ═══════════════════════════════════════════════════════

echo [INFO] Starting FastAPI Backend on port 8000...
start cmd /k "cd backend && python -m uvicorn main:app --reload"

echo [INFO] Starting Vite React Frontend on port 5173...
start cmd /k "cd frontend && npm run dev"

echo [INFO] Opening UI in default browser...
timeout /t 3 >nul
start http://localhost:5173

echo.
echo Dashboard is now running! 
echo Close this window or the popup terminals to stop the server.
pause
