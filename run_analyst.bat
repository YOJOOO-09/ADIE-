@echo off
REM ── ADIE convenience launchers ───────────────────────────────────────────────

REM Run Analyst Agent (PDF → rules.json)
REM Usage: run_analyst.bat standards\ISO_2768.pdf
conda activate adie
if "%~1"=="" (
    echo Usage: run_analyst.bat path\to\standards.pdf
    exit /b 1
)
python setup\analyst_agent.py --pdf "%~1" --output data\rules.json
echo.
echo rules.json written to data\rules.json
pause
