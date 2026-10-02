@echo off
REM Headless run: assess the example robot controller and open the HTML report.
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
if not exist reports mkdir reports
python -m emc_analyzer analyze examples\robot_controller.yaml --report reports\robot_controller.html --csv reports\robot_controller.csv
start "" reports\robot_controller.html
