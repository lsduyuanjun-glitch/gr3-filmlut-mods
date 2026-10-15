@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================
echo   GR III 胶片滤镜工具
echo ==========================================
echo.

rem —— 可移植 Python 探测：优先本包自带 runtime，否则用系统 python ——
set "PY="
if exist "%~dp0runtime\Scripts\python.exe" (
  set "PY=%~dp0runtime\Scripts\python.exe"
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    set "PY=python"
  ) else (
    echo [错误] 找不到 Python 环境。请确认已安装 Python 3，或本包 runtime 目录完整。
    pause
    exit /b 1
  )
)

echo 正在启动... 浏览器将自动打开 http://localhost:8310
echo 关闭此窗口即可停止工具
echo.

rem 启动浏览器（延迟 1 秒，等服务起来）
start "" /b cmd /c "timeout /t 1 >nul & start http://localhost:8310"

"%PY%" server.py

pause
