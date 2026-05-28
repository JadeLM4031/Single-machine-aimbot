# 启动脚本
# 使用方法: .\start.ps1

$env:PYTHON = "E:\Python\anaconda3\envs\yolo8-demo\python.exe"

Write-Host "启动 OBS Aim Demo..." -ForegroundColor Green
& $env:PYTHON "e:\Temp\aimbot\main.py"
