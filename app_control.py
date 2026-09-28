import subprocess
import os


APPS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "settings": "ms-settings:",

    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",

    "vs code": r"C:\Users\us448\AppData\Local\Programs\Microsoft VS Code\Code.exe",
    "vscode": r"C:\Users\us448\AppData\Local\Programs\Microsoft VS Code\Code.exe",
}


def open_application(app_name):

    app_name = app_name.lower().strip()

    if app_name not in APPS:
        return False, f"I don't have permission to open '{app_name}' yet."

    application = APPS[app_name]

    try:

        if application == "ms-settings:":
            os.startfile(application)

        else:
            subprocess.Popen(
                application,
                shell=False
            )

        if app_name == "vscode":
            display_name = "VS Code"

        else:
            display_name = app_name

        return True, f"Opening {display_name}."

    except FileNotFoundError:
        return False, f"I couldn't find {app_name} on this computer."

    except Exception as error:
        return False, f"I couldn't open {app_name}: {error}"


if __name__ == "__main__":

    print("SHADOW application control test")
    print("-" * 40)

    test_apps = [
        "notepad",
        "calculator",
        "file explorer",
        "settings",
        "chrome",
        "vs code"
    ]

    for app in test_apps:

        success, message = open_application(app)

        print(message)