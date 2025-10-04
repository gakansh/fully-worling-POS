@echo off
setlocal enabledelayedexpansion

REM === 1) Create the payload runner (your original logic) ===
>run_app.cmd echo @echo off
>>run_app.cmd echo REM Optional: activate virtualenv
>>run_app.cmd echo if exist venv (call venv\Scripts\activate)
>>run_app.cmd echo cd /d "C:\Users\akg68\Downloads\gaming_pos_app_persistent\gaming_pos_app"
>>run_app.cmd echo echo Installing required packages...
>>run_app.cmd echo pip install -r requirements.txt
>>run_app.cmd echo echo.
>>run_app.cmd echo echo Launching Gaming POS server...
>>run_app.cmd echo start cmd /k python app.py
>>run_app.cmd echo timeout /t 3 ^>nul
>>run_app.cmd echo start http://localhost:8000

REM === 2) Create IExpress SED file ===
set TARGET=run_app.exe
>run_app.sed echo [Version]
>>run_app.sed echo Class=IEXPRESS
>>run_app.sed echo SEDVersion=3
>>run_app.sed echo
>>run_app.sed echo [Options]
>>run_app.sed echo PackagePurpose=InstallApp
>>run_app.sed echo ShowInstallProgramWindow=1
>>run_app.sed echo HideExtractAnimation=1
>>run_app.sed echo UseLongFileName=1
>>run_app.sed echo InsideCompressed=0
>>run_app.sed echo CAB_FixedSize=0
>>run_app.sed echo CAB_ResvCodeSigning=0
>>run_app.sed echo RebootMode=I
>>run_app.sed echo TargetName=%CD%\%TARGET%
>>run_app.sed echo FriendlyName=Gaming POS Launcher
>>run_app.sed echo AppLaunched=%%InstallCmd%%
>>run_app.sed echo PostInstallCmd=<None>
>>run_app.sed echo AdminQuietInstCmd=
>>run_app.sed echo UserQuietInstCmd=
>>run_app.sed echo SourceFiles=SourceFiles
>>run_app.sed echo
>>run_app.sed echo [Strings]
>>run_app.sed echo InstallCmd=run_app.cmd
>>run_app.sed echo
>>run_app.sed echo [SourceFiles]
>>run_app.sed echo SourceFiles0=.
>>run_app.sed echo
>>run_app.sed echo [SourceFiles0]
>>run_app.sed echo %%InstallCmd%%=

REM === 3) Build the EXE ===
echo.
echo Building %TARGET% ...
iexpress /N /Q run_app.sed

if exist "%TARGET%" (
  echo.
  echo ✅ Built %TARGET%
) else (
  echo.
  echo ❌ Build failed. Make sure IExpress is available on this Windows install.
)

REM (Optional) cleanup temp files
REM del run_app.sed
REM del run_app.cmd

endlocal
pause
