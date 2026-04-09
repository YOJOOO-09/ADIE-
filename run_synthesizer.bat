@echo off
REM ── ADIE Synthesizer launcher ────────────────────────────────────────────────
conda activate adie
python setup\synthesizer_agent.py --rules data\rules.json --output validation_scripts\
echo.
echo Validation scripts written to validation_scripts\
pause
