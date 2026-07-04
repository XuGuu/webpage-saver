# 在桌面创建「文章保存工具」快捷方式。
# 用法:powershell -NoProfile -ExecutionPolicy Bypass -File make_shortcut.ps1 -ProjectDir "C:\..."
param(
    [Parameter(Mandatory=$true)][string]$ProjectDir
)

$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$lnkPath = Join-Path $desktop '文章保存工具.lnk'

$lnk = $shell.CreateShortcut($lnkPath)
$lnk.TargetPath = 'pythonw.exe'
$lnk.Arguments = '"' + (Join-Path $ProjectDir 'gui.py') + '"'
$lnk.WorkingDirectory = $ProjectDir
$lnk.IconLocation = Join-Path (Join-Path $ProjectDir 'assets') 'icon.ico'
$lnk.Description = '把公众号、B 站、掘金等文章保存为 HTML+Markdown'
$lnk.Save()

Write-Host "✓ 已在桌面创建:$lnkPath"
