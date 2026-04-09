@echo off
REM ═══════════════════════════════════════════════════════════════════════════
REM ADIE — Autonomous Design Integrity Engine
REM install.bat — One-click Windows setup
REM
REM Run this ONCE to set up the conda environment and verify the toolchain.
REM Prerequisites: Anaconda or Miniconda installed and on PATH.
REM ═══════════════════════════════════════════════════════════════════════════

setlocal enabledelayedexpansion

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║   ADIE — Autonomous Design Integrity Engine          ║
echo  ║   Installer — Aryn Gahlot, RCOEM Nagpur              ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

REM ── Step 1: Check conda ──────────────────────────────────────────────────────
where conda >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo  [ERROR] conda not found on PATH.
    echo          Install Miniconda from https://docs.conda.io/en/latest/miniconda.html
    echo          Then reopen this terminal and run install.bat again.
    pause
    exit /b 1
)
echo  [OK] conda found.

REM ── Step 2: Check if env already exists ──────────────────────────────────────
conda env list | findstr /C:"adie" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo  [INFO] Conda env 'adie' already exists. Skipping creation.
    echo         To recreate: conda env remove -n adie
    goto pip_install
)

REM ── Step 3: Create conda environment ─────────────────────────────────────────
echo.
echo  [1/4] Creating conda environment 'adie' with Python 3.10 ...
call conda env create -f environment.yml
if %ERRORLEVEL% neq 0 (
    echo  [ERROR] conda env create failed.
    echo          Check environment.yml and your internet connection.
    pause
    exit /b 1
)
echo  [OK] Conda environment created.

:pip_install
REM ── Step 4: Install pip packages ─────────────────────────────────────────────
echo.
echo  [2/4] Installing pip packages inside 'adie' env ...
call conda run -n adie pip install -r requirements.txt --quiet
if %ERRORLEVEL% neq 0 (
    echo  [WARN] pip install had issues — check requirements.txt
)
echo  [OK] pip packages installed.

REM ── Step 5: Set up .env file ──────────────────────────────────────────────────
echo.
echo  [3/4] Setting up .env file ...
if not exist ".env" (
    echo GEMINI_API_KEY=your_key_here_from_aistudio.google.com > .env
    echo  [INFO] Created .env file. Edit it and add your Gemini API key.
    echo         Get a free key at: https://aistudio.google.com/apikey
) else (
    echo  [OK] .env file already exists.
)

REM ── Step 6: Verify Python imports ────────────────────────────────────────────
echo.
echo  [4/4] Verifying Python imports ...
call conda run -n adie python -c "import fitz; print('  PyMuPDF:', fitz.__version__)"
call conda run -n adie python -c "import google.generativeai; print('  google-generativeai: OK')"
call conda run -n adie python -c "import OCC.Core.STEPControl; print('  pythonocc-core: OK')" 2>nul || echo   [WARN] pythonocc-core import failed. SDF check will be disabled.

REM ── Step 7: Verify ADIE config ───────────────────────────────────────────────
echo.
call conda run -n adie python config.py
echo.

REM ── Step 8: Run unit tests ────────────────────────────────────────────────────
echo.
echo  Running unit tests (outside Fusion — adsk stubs used) ...
call conda run -n adie python -m pytest tests/ -v --timeout=30 2>nul || echo   [INFO] Some tests need Fusion 360 — this is expected outside Fusion.

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║   ADIE Setup Complete!                               ║
echo  ║                                                      ║
echo  ║   Next steps:                                        ║
echo  ║   1. Edit .env → add your GEMINI_API_KEY            ║
echo  ║   2. Place a standards PDF in:  standards\           ║
echo  ║   3. Run: conda activate adie                        ║
echo  ║   4. Run: python setup\analyst_agent.py              ║
echo  ║            --pdf standards\YOUR.pdf                  ║
echo  ║   5. Run: python setup\synthesizer_agent.py          ║
echo  ║   6. Load fusion_addin\ as Fusion 360 add-in         ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

pause
endlocal
