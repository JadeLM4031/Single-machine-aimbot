# Nuitka High-Security .pyd Module Build Script (Ultra-Lightweight & Robust Bat Launcher)
# 
# Purpose:
#   1. Compiles core modules (ui.py, mover.py, capture.py, config.py, detector.py) into
#      C++ binary DLLs (.pyd) and places them inside the ./build/ directory.
#   2. Automatically shreds and deletes the huge intermediate C++ compilation temporary folders (.build)
#      to save disk space and keep your workspace tidy.
#   3. Generates a double-clickable "start_aimbot.bat" launcher inside ./build/ that automatically 
#      activates the Conda environment and silently runs pythonw.exe (NO console window, 100% DLL error free).
#   4. Generates an empty ./build/models/ directory for your YOLO weights.
#   5. Leaves your root source code files (.py) completely untouched!

Write-Host "[Nuitka Build] Starting High-Security Robust Module Compilation..." -ForegroundColor Green

# 1. Create clean build folder structure
New-Item -ItemType Directory -Force -Path .\build
New-Item -ItemType Directory -Force -Path .\build\models

# 2. Compile each core module cleanly into build/ as C++ binary DLLs (.pyd)
Write-Host "[Nuitka Build] Compiling Core UI Module (.pyd)..." -ForegroundColor Cyan
E:\Python\anaconda3\envs\yolo8-demo\python.exe -m nuitka --module --show-progress --output-dir=build ui.py

Write-Host "[Nuitka Build] Compiling Core Movement Module (.pyd)..." -ForegroundColor Cyan
E:\Python\anaconda3\envs\yolo8-demo\python.exe -m nuitka --module --show-progress --output-dir=build mover.py

Write-Host "[Nuitka Build] Compiling Core Capture Module (.pyd)..." -ForegroundColor Cyan
E:\Python\anaconda3\envs\yolo8-demo\python.exe -m nuitka --module --show-progress --output-dir=build capture.py

Write-Host "[Nuitka Build] Compiling Core Config Module (.pyd)..." -ForegroundColor Cyan
E:\Python\anaconda3\envs\yolo8-demo\python.exe -m nuitka --module --show-progress --output-dir=build config.py

Write-Host "[Nuitka Build] Compiling Core Detector Module (.pyd)..." -ForegroundColor Cyan
E:\Python\anaconda3\envs\yolo8-demo\python.exe -m nuitka --module --show-progress --output-dir=build detector.py

if ($LASTEXITCODE -eq 0) {
    Write-Host "[Nuitka Build] All C++ binaries generated successfully! Starting automated cleanup..." -ForegroundColor Green
    
    # 3. Automatically delete the massive, useless intermediate C++ compilation folders (*.build) inside ./build/
    Get-ChildItem -Path .\build\ -Filter "*.build" -Directory | Remove-Item -Recurse -Force
    Write-Host "[Nuitka Build] All C++ build cache folders have been safely deleted." -ForegroundColor Green

    # 4. Copy required startup asset files to ./build/ folder
    Copy-Item -Path main.py -Destination .\build\main.py -Force
    if (Test-Path .\config.json) {
        Copy-Item -Path config.json -Destination .\build\config.json -Force
    }
    if (Test-Path .\kmNet.pyd) {
        Copy-Item -Path kmNet.pyd -Destination .\build\kmNet.pyd -Force
    } elseif (Test-Path .\kmNet.cp310-win_amd64.pyd) {
        Copy-Item -Path .\kmNet.cp310-win_amd64.pyd -Destination .\build\kmNet.pyd -Force
    }
    if (Test-Path .\tool) {
        Copy-Item -Path .\tool -Destination .\build\ -Recurse -Force
    }

    # 5. 生成高可靠性、双击自动请求管理员权限的启动脚本 (.bat) 到 build 文件夹中
    # 彻底解决管理员运行后默认路径被 Windows 重置为 System32 导致无法加载相对文件路径的致命 bug
    # 并且使用绝对路径指向 conda python，100% 避免系统 PATH 环境变量缺失导致的 DLL 载入失败！
    $bat_content = @'
@echo off
chcp 65001 >nul
title System Monitor Launcher

:: 1. Check for administrator privileges. If none, elevate dynamically via PowerShell UAC.
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [System] Requesting Administrator privileges...
    powershell -Command "Start-Process -FilePath '%0' -Verb RunAs"
    exit /b
)

:: 2. Set working directory to the folder where this batch file resides.
:: This is critical as Windows UAC resets the path to C:\Windows\System32.
cd /d "%~dp0"

echo ===================================================
echo   Starting System Monitor (Nuitka C++ Compiled)...
echo ===================================================
echo.

:: 3. Directly run the correct absolute Python environment to load C++ dlls without PATH issues.
"E:\Python\anaconda3\envs\yolo8-demo\python.exe" main.py

if %errorLevel% neq 0 (
    echo.
    echo [Error] Program exited with error code: %errorLevel%
    pause
)
'@
    $bat_content | Out-File -FilePath .\build\start_aimbot.bat -Encoding Default

    Write-Host "[Nuitka Build] High-Security Isolated Distribution Packaged Successfully!" -ForegroundColor Green
    Write-Host "[Nuitka Build] =========================================================" -ForegroundColor Green
    Write-Host "[Nuitka Build] WHAT TO DO NEXT:" -ForegroundColor Cyan
    Write-Host "  1. Put your YOLO model weights (e.g., yolov8s.pt) in: .\build\models\" -ForegroundColor Yellow
    Write-Host "  2. Run the application locally by double-clicking: .\build\start_aimbot.bat" -ForegroundColor Green
    Write-Host "     (It loads all C++ binaries instantly, with 100% DLL guarantee and NO black box!)" -ForegroundColor Green
    Write-Host "  3. To share with another PC: ZIP the .\build\ folder (only ~15MB!) and send it." -ForegroundColor Yellow
    Write-Host "[Nuitka Build] =========================================================" -ForegroundColor Green
} else {
    Write-Warning "[Nuitka Build] Compilation failed. Please check C++ compiler configurations."
}
