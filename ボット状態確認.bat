@echo off
chcp 65001 >nul
echo === 楽天クーポンボットの状態 ===
echo.
powershell -Command "$t = Get-ScheduledTask -TaskName 'RakutenCouponBot' -ErrorAction SilentlyContinue; if ($t) { Write-Host ('稼働中です  状態: ' + $t.State) } else { Write-Host '動いていません（タスクは登録されていません）' }"
echo.
echo （Ready/Running=動いている / 見つからない=止まっている）
pause
