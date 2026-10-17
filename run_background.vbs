Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\PC\Desktop\pinterest bot"
WshShell.Run "pythonw.exe bot.py", 0, False
