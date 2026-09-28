import platform
import os
import subprocess


def get_system_info():

    # Get CPU name from Windows
    cpu_name = platform.processor()

    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_Processor).Name"
            ],
            capture_output=True,
            text=True,
            timeout=5
        )

        detected_cpu = result.stdout.strip()

        if detected_cpu:
            cpu_name = detected_cpu

    except Exception:
        pass

    info = {
        "Computer": platform.node(),
        "Operating System": platform.system(),
        "OS Version": platform.version(),
        "Machine": platform.machine(),
        "Processor": cpu_name,
        "Python Version": platform.python_version(),
        "CPU Cores": os.cpu_count()
    }

    return info


def get_system_info_text():

    info = get_system_info()

    lines = []

    for key, value in info.items():
        lines.append(f"{key}: {value}")

    return "\n".join(lines)


if __name__ == "__main__":

    print("SHADOW SYSTEM INFORMATION")
    print("-" * 40)
    print(get_system_info_text())