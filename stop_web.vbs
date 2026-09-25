Set sh = CreateObject("WScript.Shell")
sh.Run "powershell -NoProfile -Command ""Get-NetTCPConnection -LocalPort 8501 -ErrorAction SilentlyContinue | Where-Object {$_.State -eq 'Listen'} | ForEach-Object { taskkill /F /PID $_.OwningProcess }""", 0, True
