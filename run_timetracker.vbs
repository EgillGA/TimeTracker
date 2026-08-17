' Launch TimeTracker with no console window.
'
' Task Scheduler running python.exe directly makes a black console box flash
' on screen every weekday at 15:30, which is exactly the kind of small
' irritation that gets an automation switched off. wscript with a hidden
' window avoids it.
'
' Paths are derived from this file's own location, so moving or renaming the
' folder does not break the scheduled task.

Option Explicit

Dim fso, shell, root, args, argument

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

root = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = root

args = ""
For Each argument In WScript.Arguments
    args = args & " " & argument
Next

' pyw.exe is the windowless Python launcher; it ships with Python and lives
' on PATH, unlike pythonw.exe which sits inside the install directory.
shell.Run "pyw.exe -m timetracker" & args, 0, False
