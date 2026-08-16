' Start AccessCam elevated, with no UAC prompt.
'
' AccessCam wants administrator rights: UIPI stops a normal-privilege process
' delivering input to a higher-privilege window, so on-screen keyboards and
' anything else that reacts to hovering silently ignore the cursor. See
' docs/RUNNING.md.
'
' A process cannot elevate itself once it is running, and relaunching through
' "Run as administrator" puts a UAC prompt on the secure desktop - which a
' head-tracked cursor cannot reach, because AccessCam is not elevated at that
' moment by definition. Anyone who needs this application to move their pointer
' would be stranded at a dialog they cannot click.
'
' The scheduled task is the way out. Task Scheduler launches it with highest
' privileges and asks nobody, so this script is one line: tell the task to run.
' Creating the task needs administrator rights once; running it never does.
'
' WScript rather than a shortcut straight to schtasks.exe, only so that no
' console window flashes up on the way.

Option Explicit

Dim shell, result
Set shell = CreateObject("WScript.Shell")

' 0 hides the console; True waits for schtasks itself to return, which it does
' as soon as the task is started rather than when AccessCam exits.
result = shell.Run("schtasks /run /tn AccessCam", 0, True)

If result <> 0 Then
    MsgBox "Could not start AccessCam." & vbCrLf & vbCrLf & _
           "schtasks returned " & result & ", which usually means the AccessCam " & _
           "task is not registered on this machine. Register it from the " & _
           "Application tab of the settings window, running as administrator." & _
           vbCrLf & vbCrLf & _
           "See docs/RUNNING.md for the schtasks command that does the same thing.", _
           vbExclamation, "AccessCam"
End If
