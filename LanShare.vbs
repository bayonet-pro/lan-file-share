' LanShare.vbs - launch LanShare without a console window
' Prefers LanShare.exe in the same folder; falls back to pythonw from PATH.
' NOTE: keep this file ASCII-only, because cscript/wscript reads .vbs as ANSI.
Option Explicit

Dim sh, fso, base, exePath, scriptPath
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

base = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = base

exePath = fso.BuildPath(base, "LanShare.exe")
scriptPath = fso.BuildPath(base, "LanShare.pyw")

If fso.FileExists(exePath) Then
    sh.Run """" & exePath & """", 1, False
    WScript.Quit 0
End If

' No exe found: try pythonw from PATH. No absolute path is hard-coded here.
On Error Resume Next
sh.Run "pythonw """ & scriptPath & """", 0, False
If Err.Number <> 0 Then
    MsgBox "LanShare.exe was not found, and pythonw is not available in PATH." & vbCrLf & vbCrLf & _
           "Run LanShare.pyw directly, or build the exe (see README).", 48, "LanShare"
End If
