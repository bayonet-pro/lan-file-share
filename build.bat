@echo off
chcp 65001 >nul
cd /d "%~dp0"
title LanShare 一键打包

echo ============================================
echo   LanShare - 打包成单文件 exe
echo ============================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [错误] 没找到 python，请先安装 Python 3.8+ 并勾选 Add to PATH。
    echo.
    pause
    exit /b 1
)

echo [1/3] 安装打包依赖 ^(pyinstaller / qrcode / pillow^) ...
python -m pip install --quiet --upgrade pyinstaller qrcode pillow
if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络或 pip 源。
    echo.
    pause
    exit /b 1
)

echo [2/3] 清理旧产物 ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/3] 开始打包，约 30~60 秒，请稍候 ...
python -m PyInstaller --noconfirm --clean --onefile --noconsole --name LanShare ^
    --icon LanShare.ico --add-data "LanShare.ico;." ^
    --hidden-import qrcode ^
    --hidden-import PIL --hidden-import PIL.Image ^
    --hidden-import PIL.ImageGrab --hidden-import PIL.JpegImagePlugin ^
    --distpath dist --workpath build --specpath build LanShare.pyw
if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请查看上方日志。
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   打包完成： dist\LanShare.exe
echo ============================================
echo.
pause
