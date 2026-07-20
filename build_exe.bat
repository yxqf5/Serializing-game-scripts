@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "PY=C:\Users\yxqf\miniconda3\python.exe"
if not exist "%PY%" set "PY=python"

echo [1/2] 打包 exe（约 1-2 分钟）...
"%PY%" -m PyInstaller --noconfirm --clean "一键长草助手.spec"
if errorlevel 1 (
    echo 打包失败
    pause
    exit /b 1
)

echo [2/2] 复制到程序目录...
copy /Y "dist\一键长草助手.exe" "一键长草助手.exe" >nul
copy /Y "使用说明.txt" "dist\使用说明.txt" >nul
echo.
echo 完成。发给好友请打包：
echo   dist\一键长草助手.exe
echo   dist\使用说明.txt
echo.
echo 本地启动：双击 一键长草助手.exe
echo plugins、settings.json 与本目录共用，无需迁移。
echo.
pause
