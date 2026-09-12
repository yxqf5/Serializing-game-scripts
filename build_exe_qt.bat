@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

rem 打包 Qt(PySide6)版界面:生成 一键长草助手Qt.exe
set "PY="
if exist "%USERPROFILE%\miniconda3\python.exe" set "PY=%USERPROFILE%\miniconda3\python.exe"
if not defined PY for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY set "PY=%%P"
if not defined PY (
    echo 未找到 Python，请先安装 miniconda 或把 python 加入 PATH
    pause
    exit /b 1
)

echo [1/3] 语法检查...
"%PY%" -m py_compile "runner_core.py" "log_watcher.py" "assistant_setup.py" "preset_resolver.py" "preset_catalog.py" "preflight.py" "ui_qt\theme.py" "ui_qt\core_glue.py" "ui_qt\run_controller.py" "ui_qt\app.py" "ui_qt\home_page.py" "ui_qt\log_panel.py" "ui_qt\add_page.py" "ui_qt\edit_page.py" "ui_qt\wizard_page.py" "ui_qt\settings_page.py" "ui_qt\help_page.py" "ui_qt\dialogs.py" "游戏助手Qt.pyw"
if errorlevel 1 (
    echo 语法检查失败，请先修复上面的报错再打包
    pause
    exit /b 1
)

echo [2/3] 打包 exe（Qt 版体积较大，约 3-5 分钟）...
"%PY%" -m PyInstaller --noconfirm --clean "一键长草助手Qt.spec"
if errorlevel 1 (
    echo 打包失败
    pause
    exit /b 1
)

echo [3/3] 复制到程序目录...
copy /Y "dist\一键长草助手Qt.exe" "一键长草助手Qt.exe" >nul
copy /Y "使用说明.txt" "dist\使用说明.txt" >nul
echo.
echo 完成。输出：
echo   dist\一键长草助手Qt.exe
echo   dist\使用说明.txt
echo.
echo plugins、settings.json 与 tkinter 版共用，无需迁移。
echo.
pause
