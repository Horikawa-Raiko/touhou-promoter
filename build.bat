@echo off
cd /d "%~dp0"
echo === Building 原初电台 ===
pyinstaller touhou_promoter.spec --noconfirm --distpath "%USERPROFILE%\Desktop"
echo === Done. Exe on Desktop. ===
pause
