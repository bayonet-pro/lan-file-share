@echo off
chcp 65001 >nul
title LanShare 防火墙放行

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo 需要管理员权限，正在申请提权 ...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo 正在放行 LanShare 所需的 TCP 入站端口 ...
echo.
netsh advfirewall firewall add rule name="LanShare File Share (LAN)" dir=in action=allow protocol=TCP localport=80,8080,8888,6666,9999,8000-8100 profile=any enable=yes

if %errorlevel% equ 0 (
    echo.
    echo [完成] 已放行。现在用手机再打开一次网址试试。
) else (
    echo.
    echo [失败] 未能添加规则。请手动执行 README 里的 netsh 命令。
)
echo.
pause
