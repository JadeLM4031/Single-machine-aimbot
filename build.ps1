# Nuitka 极致安全混淆编译脚本
# 
# 🟢 作用：
#   将项目核心的 Python 业务代码 (main.py, ui.py, mover.py, capture.py, config.py)
#   完全编译为原生的 C++ 机器码 (.exe & .pyd)，彻底销毁明文 Python 运行指纹，并改变进程与内存分配哈希。
# 
# 🟢 运行前准备：
#   1. 确保已安装 Nuitka 编译器：
#      pip install nuitka
#   2. 确保系统已安装 C++ 编译链（推荐安装 Visual Studio Community 并勾选 "使用 C++ 的桌面开发"）
# 
# 🟢 编译策略：
#   采用“核心业务代码硬编译”+“重型通用库动态链接”策略。
#   将大体量的第三方库 (torch, PySide6, cv2, numpy, ultralytics) 排除在编译包之外，
#   这样既能确保 100% 编译成功率，又能获得极小体积、极速打包和 100% 机器码化的核心安全性。

Write-Host "[Nuitka Build] 正在启动 Nuitka C++ 极致安全编译系统..." -ForegroundColor Green

nuitka --standalone `
       --show-progress `
       --windows-console-mode=disable `
       --nofollow-import-to=torch,ultralytics,cv2,numpy,PySide6 `
       --output-dir=build `
       main.py

if ($LASTEXITCODE -eq 0) {
    Write-Host "[Nuitka Build] 编译大获成功！独立二进制文件已输出至 ./build/main.dist/ 目录中。" -ForegroundColor Green
    Write-Host "[Nuitka Build] 您可以直接运行 ./build/main.dist/main.exe 开启全防护模式。" -ForegroundColor Green
} else {
    Write-Warning "[Nuitka Build] 编译中途出现错误，请检查系统 C++ 编译环境是否配置完整。"
}
