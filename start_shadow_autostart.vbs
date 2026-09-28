' SHADOW autostart launcher
' Starts SHADOW silently (no console window) in
' hands-free listening mode when Windows boots.

Set WshShell = CreateObject("WScript.Shell")

WshShell.CurrentDirectory = "C:\Users\us448\Shadow"

WshShell.Run """C:\Users\us448\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"" ""C:\Users\us448\Shadow\shadow.py"" autostart", 0, False
