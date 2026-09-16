@echo off
REM Build a standalone Windows .exe for the PrinterPro file checker.
REM Run this ON WINDOWS (PyInstaller cross-compilation is not reliable).
REM
REM Usage (from the project root, e.g. in a cmd/PowerShell prompt):
REM   build\build_windows.bat

setlocal
cd /d "%~dp0\.."

python -m venv .buildvenv
call .buildvenv\Scripts\activate.bat

pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

pyinstaller --onefile --windowed --name PrinterProChecker ^
    --add-data "specs.json;." ^
    --add-data "xml_field_map.json;." ^
    main.py

echo.
echo Build complete: dist\PrinterProChecker.exe
endlocal
