import json
import os

SETTINGS_FILE = "settings.json"

DEFAULT_SETTINGS = {
    "voice_enabled": True,
    "speech_rate": 170,
    "mic_device_id": None
}

settings = {}


def load_settings():
    global settings

    # Start from the defaults, then overwrite
    # with anything the user has saved.

    settings = dict(DEFAULT_SETTINGS)

    if not os.path.exists(SETTINGS_FILE):
        return settings

    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
            stored = json.load(file)

        for key in DEFAULT_SETTINGS:
            if key in stored:
                settings[key] = stored[key]

    except Exception as error:
        print(f"[Shadow SETTINGS] Could not load: {error}")

    return settings


def save_settings():
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
            json.dump(settings, file, indent=4)

    except Exception as error:
        print(f"[Shadow SETTINGS] Could not save: {error}")


def get_setting(key):
    return settings.get(
        key,
        DEFAULT_SETTINGS.get(key)
    )


def set_setting(key, value):
    settings[key] = value

    save_settings()

    return value


def get_all_settings_text():
    lines = [
        "Current Shadow settings, baa:",
        ""
    ]

    for key, value in settings.items():
        lines.append(f"- {key}: {value}")

    return "\n".join(lines)


if __name__ == "__main__":
    print("Shadow SETTINGS TEST")
    print("-" * 40)

    print("Loaded:", load_settings())

    set_setting("speech_rate", 200)

    print("After change:", settings)

    set_setting("speech_rate", 170)
