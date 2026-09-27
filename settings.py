import json
import os

SETTINGS_FILE = "settings.json"

DEFAULT_SETTINGS = {
    "voice_enabled": True,
    "speech_rate": 170,
    "mic_device_id": None,
    "mic_device_name": None,
    "semantic_search": True,
    "noise_enabled": True,
    "morning_briefing_enabled": True,
    "online_enabled": False,
    "online_city": None,
    "morning_briefing_last_date": None
}

settings = {}

settings_loaded = False


def load_settings():
    global settings
    global settings_loaded

    # Start from the defaults, then overwrite
    # with anything the user has saved.

    settings = dict(DEFAULT_SETTINGS)

    # Mark loaded BEFORE any early return: a
    # missing file still counts as loaded
    # (defaults). Otherwise every later
    # set_setting() reloads fresh defaults on
    # top of the value it just wrote -
    # silently losing it. That bug would
    # bite exactly when settings.json is
    # absent: a fresh install.

    settings_loaded = True

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

    settings_loaded = True

    return settings


def _ensure_loaded():
    # Safety net: any module may import settings
    # and write without loading first. Load once
    # automatically so nothing gets clobbered.

    if not settings_loaded:
        load_settings()


def save_settings():
    _ensure_loaded()

    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
            json.dump(settings, file, indent=4)

    except Exception as error:
        print(f"[Shadow SETTINGS] Could not save: {error}")


def get_setting(key):
    _ensure_loaded()

    return settings.get(
        key,
        DEFAULT_SETTINGS.get(key)
    )


def set_setting(key, value):
    _ensure_loaded()

    settings[key] = value

    save_settings()

    return value


def get_all_settings_text():
    lines = [
        "Current Shadow settings, sir:",
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
