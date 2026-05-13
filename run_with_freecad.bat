@echo off
REM ============================================================
REM  CAD图纸3D建模 — FreeCAD 环境一键启动
REM  使用 FreeCAD 自带的 Python 解释器运行，确保所有模块可用
REM ============================================================
setlocal enabledelayedexpansion

REM 自动查找 FreeCAD Python
set FREECAD_PYTHON=

REM 方式1: 从 config.yaml 读取
if exist "config\config.yaml" (
    for /f "tokens=2 delims=: " %%a in ('findstr "bin_path" config\config.yaml') do (
        set "FC_PATH=%%~a"
        if exist "!FC_PATH:\=/!\python.exe" (
            set "FREECAD_PYTHON=!FC_PATH!\python.exe"
            goto :found
        )
    )
)

REM 方式2: 常见安装位置
for %%d in (
    "D:\FreeCAD 1.0\bin"
    "C:\Program Files\FreeCAD 1.0\bin"
    "D:\FreeCAD 0.21\bin"
    "C:\Program Files\FreeCAD 0.21\bin"
) do (
    if exist "%%~d\python.exe" (
        set "FREECAD_PYTHON=%%~d\python.exe"
        goto :found
    )
)

echo [ERROR] FreeCAD Python not found.
echo Please install FreeCAD 1.0+ or edit this script to set FREECAD_PYTHON manually.
echo.
pause
exit /b 1

:found
echo.
echo ============================================================
echo  CAD Drawing to 3D Model - FreeCAD Direct Mode
echo  Python: %FREECAD_PYTHON%
echo ============================================================
echo.

cd /d "%~dp0"

if "%~1"=="" (
    echo Usage: run_with_freecad.bat ^<script.py^> [args...]
    echo.
    echo Examples:
    echo   run_with_freecad.bat cad_cli.py --list
    echo   run_with_freecad.bat cad_cli.py -f sample.dxf -H 10
    echo   run_with_freecad.bat cad_cli.py --intelligent -f 底座二视图.dxf
    echo   run_with_freecad.bat examples/scripts/quickstart.py
    echo.
    pause
    exit /b 0
)

echo Running: %FREECAD_PYTHON% %*
echo.
"%FREECAD_PYTHON%" %*

if errorlevel 1 (
    echo.
    echo ============================================================
    echo  Execution failed with exit code %errorlevel%
    echo ============================================================
    pause
) else (
    echo.
    echo ============================================================
    echo  Execution completed successfully
    echo ============================================================
)

endlocal
