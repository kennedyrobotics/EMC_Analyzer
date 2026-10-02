@echo off
REM Creates a local virtual environment and installs dependencies.
REM If you use Anaconda instead:  conda create -n emc python=3.11 -y && conda activate emc && pip install -r requirements.txt
cd /d "%~dp0"
where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.
echo Environment ready. Start the GUI with run_gui.bat
pause
