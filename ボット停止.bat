@echo off
chcp 65001 >nul
echo === 楽天クーポンボットを停止します ===
echo.
powershell -Command "try { Unregister-ScheduledTask -TaskName 'RakutenCouponBot' -Confirm:$false; Write-Host '停止しました（自動チェックのタスクを削除しました）' } catch { Write-Host '停止済み、またはタスクが見つかりませんでした（もう動いていません）' }"
echo.
echo このウィンドウは閉じてOKです。
pause
