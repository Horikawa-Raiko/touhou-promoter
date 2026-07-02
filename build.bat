@echo off
cd /d "%~dp0"
echo === Building 东方Project一键宣发姬 ===
pyinstaller touhou_promoter.spec --noconfirm --distpath "%USERPROFILE%\Desktop"
echo === Done. Exe on Desktop. ===
pause
