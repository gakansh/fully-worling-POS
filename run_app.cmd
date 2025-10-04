@echo off
REM Optional: activate virtualenv
if exist venv (call venv\Scripts\activate)
cd /d "C:\Users\akg68\Downloads\gaming_pos_app_persistent\gaming_pos_app"
echo Installing required packages...
pip install -r requirements.txt
echo.
echo Launching Gaming POS server...
start cmd /k python app.py
timeout /t 3 >nul
start http://localhost:8000
