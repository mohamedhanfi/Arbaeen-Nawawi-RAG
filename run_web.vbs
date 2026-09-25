Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
repo = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = repo
sh.Run "pythonw -m uvicorn backend.main:app --host 127.0.0.1 --port 8501", 0, False
WScript.Sleep 12000
sh.Run "http://localhost:8501"
