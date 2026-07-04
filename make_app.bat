@echo off
REM 双击运行,在桌面创建带自定义图标的「文章保存工具」快捷方式。
REM 可放 assets\icon.ico 自定义图标,没有就用默认蓝色渐变。
REM 用 UTF-8 codepage 保证中文文件名正确
chcp 65001 >nul
setlocal

cd /d "%~dp0"
set "PROJECT_DIR=%cd%"

REM 1. 检查 python 是否可用
where python >nul 2>nul
if errorlevel 1 (
    echo 找不到 python 命令。请先安装 Python 3^(勾选 "Add to PATH"^)。
    pause
    exit /b 1
)

REM 2. 检查 pythonw.exe(GUI 版 Python,快捷方式用它才不会弹黑窗)
where pythonw >nul 2>nul
if errorlevel 1 (
    echo 找不到 pythonw.exe。请用官方 python.org 安装包重新安装 Python。
    pause
    exit /b 1
)

REM 3. 生成默认 ICO(仅当 assets\icon.ico 不存在时)
if not exist "%PROJECT_DIR%\assets" mkdir "%PROJECT_DIR%\assets"
if not exist "%PROJECT_DIR%\assets\icon.ico" (
    echo -^> 生成默认蓝色渐变图标...
    python -c "import save_webpage,sys; open(sys.argv[1],'wb').write(save_webpage.make_default_icon_ico(256))" "%PROJECT_DIR%\assets\icon.ico"
    if errorlevel 1 (
        echo 生成图标失败。
        pause
        exit /b 1
    )
)

REM 4. 调用独立的 PowerShell 脚本创建桌面快捷方式(避免 batch/pwsh 转义地狱)
echo -^> 创建桌面快捷方式...
powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%\assets\make_shortcut.ps1" -ProjectDir "%PROJECT_DIR%"
if errorlevel 1 (
    echo 创建快捷方式失败。
    pause
    exit /b 1
)

echo.
echo v 完成:桌面上多了一个「文章保存工具」快捷方式,双击就能启动。
echo.
echo 想换图标?把 %PROJECT_DIR%\assets\icon.ico 换成自己的图,再双击本文件一次即可。
echo.
pause
