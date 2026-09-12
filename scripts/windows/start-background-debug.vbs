REM Velluma background start (debug, no terminal window).
REM A python supervisor owns the service tree: spawns backend/vite/electron,
REM auto-restarts on crash, serves the web dashboard. The app window appears
REM after the first frontend build finishes (about 30-60 seconds).
REM Stop everything: run stop-velluma.bat in this folder.
REM NOTE: this file must stay ASCII-only; paths with spaces need quote handling.
REM pythonw = no console at all: killing/w closing anything cannot teardown-kill
REM the supervisor via console destruction (that chain killed it once).
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
root = fso.GetParentFolderName(fso.GetParentFolderName(scriptDir))
py = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(py) Then
  MsgBox "venv python not found: " & py
  WScript.Quit 1
End If
q = """"
REM script path needs quoting too: a project dir with spaces would break the
REM command line at the first space and pythonw would die silently.
cmdline = q & py & q & " " & q & root & "\scripts\dev_dashboard.py" & q & " --supervise --mode debug --root " & q & root & q & " --dir " & q & root & "\logs" & q & " --status " & q & root & "\data\dev_status.json" & q & " --port 0"
sh.CurrentDirectory = root
sh.Run cmdline, 0, False
