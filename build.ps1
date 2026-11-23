# 一键构建：PyInstaller 打包 exe → Inno Setup 生成安装包
# 用法：powershell -ExecutionPolicy Bypass -File .\build.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root
$out = Join-Path $env:LOCALAPPDATA "DownloadButler_build"   # 构建目录放在项目之外

# 找一个能用的 Python：PATH 里的 python 可能只是 Microsoft Store 的占位程序（运行后退出码 9009）
$py = $null
foreach ($cand in @(@("python"), @("py", "-3"))) {
    $exe, $pre = $cand[0], @($cand | Select-Object -Skip 1)
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    & $exe @pre -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { $py = $cand; break }
}
if (-not $py) { throw "未找到 Python 3.10+：winget install Python.Python.3.13" }
$exe, $pre = $py[0], @($py | Select-Object -Skip 1)
Write-Host "使用 Python：$(& $exe @pre -c 'import sys; print(sys.executable, sys.version.split()[0])')"

& $exe @pre -m pip install -r requirements-build.txt
if ($LASTEXITCODE) { throw "安装依赖失败" }

& $exe @pre -m PyInstaller --noconfirm --windowed --name "DownloadButler" `
    --icon "$root\assets\icon.ico" --add-data "$root\assets;assets" --hidden-import converter_link `
    --exclude-module PyQt6.QtWebEngineCore --exclude-module PyQt6.QtWebEngineWidgets `
    --exclude-module PyQt6.QtPdf --exclude-module PyQt6.Qt3DCore --exclude-module PyQt6.QtQml `
    --exclude-module PyQt6.QtQuick --exclude-module PyQt6.QtMultimedia --exclude-module tkinter `
    --workpath "$out\work" --specpath "$out\work" --distpath "$out\dist" download_manager.py
if ($LASTEXITCODE) { throw "PyInstaller 失败" }

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "未找到 Inno Setup 6：winget install JRSoftware.InnoSetup" }
& $iscc /Qp "/DDistDir=$out\dist\DownloadButler" "$root\installer\DownloadButler.iss"
if ($LASTEXITCODE) { throw "Inno Setup 失败" }
Write-Host "完成：安装包在 installer\Output\" -ForegroundColor Green
