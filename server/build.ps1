# 打包服务端为免安装 exe（产物在 dist\server\）
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

# 应用名用码点拼接，免得 .ps1 在非 UTF-8 代码页下被读错
$APP = -join ([char]0x6084, [char]0x533F, [char]0x793E, [char]0x4EA4)      # 悄匿社交
$SUFFIX = -join ([char]0x002D, [char]0x670D, [char]0x52A1, [char]0x7AEF)   # -服务端

py -m PyInstaller --noconfirm --clean --onedir --console --name server `
  --distpath "$root\dist" --workpath "$root\build" --specpath "$root\build" `
  "$root\chat_server.py"

$exe = Join-Path "$root\dist\server" ($APP + $SUFFIX + '.exe')
if (Test-Path "$root\dist\server\server.exe") {
  Move-Item -Force "$root\dist\server\server.exe" $exe
}
Write-Host ("server : {0}" -f $exe)
Write-Host '把 dist\server 整个文件夹拷到服务器上运行（_internal 不能删）'
