# MapleBot 自动备份脚本 - 每30分钟执行一次
$src = "C:\Users\PC\Doubao\chats\2026-08-15\new-chat-4\maple_bot\maple_route_ui.py"
$backupDir = "C:\Users\PC\Doubao\chats\2026-08-15\new-chat-4\maple_bot\auto_backups"

if (-not (Test-Path $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
}

if (Test-Path $src) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $dst = Join-Path $backupDir "maple_route_ui_$timestamp.py"
    Copy-Item $src $dst -Force
    Write-Host "已备份: $dst"

    # 只保留最近20个备份
    $files = Get-ChildItem $backupDir -Filter "maple_route_ui_*.py" | Sort-Object LastWriteTime -Descending
    if ($files.Count -gt 20) {
        $files | Select-Object -Skip 20 | Remove-Item -Force
        Write-Host "已清理旧备份，保留最近20个"
    }
} else {
    Write-Host "源文件不存在: $src"
}
