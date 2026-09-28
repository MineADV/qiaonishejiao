# 打包客户端为免安装 exe（产物在 dist\client\）
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

$APP = -join ([char]0x6084, [char]0x533F, [char]0x793E, [char]0x4EA4)      # 悄匿社交

py -m PyInstaller --noconfirm --clean --onedir --windowed --name client `
  --distpath "$root\dist" --workpath "$root\build" --specpath "$root\build" `
  --collect-all customtkinter --collect-all PIL --collect-all tkinterdnd2 `
  "$root\chat_gui.py"

$exe = Join-Path "$root\dist\client" ($APP + '.exe')
if (Test-Path "$root\dist\client\client.exe") {
  Move-Item -Force "$root\dist\client\client.exe" $exe
}
Write-Host ("client : {0}" -f $exe)
Write-Host '把 dist\client 整个文件夹发给用户（_internal 不能删）'
