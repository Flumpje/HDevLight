@echo off
echo Installing / upgrading PyInstaller...
pip install --upgrade pyinstaller

echo.
echo Building SigaH.exe ...
pyinstaller SigaH.spec --noconfirm

echo.
echo Done.  Executable is at:  dist\HDevLight.exe
pause
