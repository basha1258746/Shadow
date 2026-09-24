import time

try:
    import pyautogui

    PYAUTOGUI_AVAILABLE = True

    # EMERGENCY STOP: slamming the mouse into
    # the top-left corner instantly aborts
    # any action. This is always on.

    pyautogui.FAILSAFE = True

    # A small pause between actions keeps
    # rapid sequences visible to the user.

    pyautogui.PAUSE = 0.2

except ImportError:
    PYAUTOGUI_AVAILABLE = False

# ---------------- SAFETY DESIGN ----------------
#
# 1. ALLOWLIST ONLY. The language model can
#    never invent computer actions. The only
#    executable actions are the fixed patterns
#    parsed below; everything else is ignored.
#
# 2. CONFIRMATION GATE. Parsed actions are
#    never executed directly - they are staged
#    in Shadow.py and only run after the user
#    explicitly says yes.
#
# 3. FAILSAFE. pyautogui's corner slam aborts
#    everything, always.
#
# 4. No dragging, no hotkey combos, no
#    arbitrary coordinates in one step: the
#    user always SEES the cursor move before
#    any click is confirmed.

MAX_TYPE_CHARS = 200

ALLOWED_KEYS = (
    "enter", "space", "tab", "escape",
    "backspace", "delete",
    "up", "down", "left", "right",
    "pageup", "pagedown", "home", "end",
)

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10,
}


def word_to_number(token):
    if token.isdigit():
        return int(token)

    return NUMBER_WORDS.get(token)


def screen_size():
    if not PYAUTOGUI_AVAILABLE:
        return (1920, 1080)

    size = pyautogui.size()

    return (size.width, size.height)


def parse_command(text):
    # The ONLY door from words to actions.
    # Returns an action dict, or None when the
    # text is not a known safe command.

    if not PYAUTOGUI_AVAILABLE:
        return None

    lowered = text.lower().strip()
    words = lowered.split()

    if not words:
        return None

    # ---- CLICKS (at the current cursor spot) ----

    if lowered in (
        "double click",
        "double-click",
        "click twice",
    ):
        return {"action": "double_click"}

    if lowered in (
        "right click",
        "right-click",
    ):
        return {"action": "right_click"}

    if lowered == "click":
        return {"action": "click"}

    # ---- MOVES ----

    if lowered.startswith(
        ("move mouse", "move the mouse", "move cursor")
    ):
        rest = lowered.replace(
            "move the mouse", ""
        ).replace(
            "move mouse", ""
        ).replace(
            "move cursor", ""
        ).strip()

        rest = rest.replace("to", " ", 1).strip() \
            if rest.startswith("to ") else rest

        size = screen_size()
        mid_x = size[0] // 2
        mid_y = size[1] // 2

        named = {
            "center": (mid_x, mid_y),
            "middle": (mid_x, mid_y),
            "left": (size[0] // 4, mid_y),
            "right": (size[0] * 3 // 4, mid_y),
            "top": (mid_x, size[1] // 4),
            "bottom": (mid_x, size[1] * 3 // 4),
            "corner": (size[0] - 5, size[1] - 5),
        }

        if rest in named:
            return {
                "action": "move",
                "where": rest,
                "x": named[rest][0],
                "y": named[rest][1],
            }

        # Exact coordinates: move mouse to 500 300

        parts = rest.replace("to", " ").split()

        if len(parts) == 2:
            try:
                x = int(parts[0])
                y = int(parts[1])

                if 0 <= x <= size[0] and 0 <= y <= size[1]:
                    return {
                        "action": "move",
                        "where": f"({x}, {y})",
                        "x": x,
                        "y": y,
                    }

            except ValueError:
                pass

        return None

    # ---- SCROLL ----

    if lowered.startswith("scroll"):
        parts = lowered.split()

        direction = None
        amount = 3

        for token in parts:
            if token in ("up", "down"):
                direction = token

            number = word_to_number(token)

            if number:
                amount = number

        if direction is None:
            return None

        return {
            "action": "scroll",
            "direction": direction,
            "amount": amount,
        }

    # ---- TYPE ----

    if lowered.startswith("type "):
        payload = text[5:].strip()

        if not payload or len(payload) > MAX_TYPE_CHARS:
            return None

        return {"action": "type", "text": payload}

    # ---- PRESS A SAFE KEY ----

    if lowered.startswith(("press ", "hit ", "tap ")):
        key = lowered.split()[1].strip(" .!?")

        if key in ALLOWED_KEYS:
            return {"action": "press", "key": key}

        return None

    return None


def describe_action(action):
    # Human-friendly text for the confirmation
    # question.

    kind = action["action"]

    if kind == "move":
        return (
            f"move the mouse to {action['where']}"
        )

    if kind == "click":
        return (
            "click ONCE at the current mouse "
            "position"
        )

    if kind == "double_click":
        return (
            "double-click at the current mouse "
            "position"
        )

    if kind == "right_click":
        return (
            "right-click at the current mouse "
            "position"
        )

    if kind == "scroll":
        return (
            f"scroll {action['direction']} "
            f"{action['amount']} notches"
        )

    if kind == "type":
        return (
            f"type: \"{action['text']}\""
        )

    if kind == "press":
        return f"press the {action['key']} key"

    return "do an unknown action"


def execute_action(action):
    # Runs ONLY after explicit user confirmation.
    # Returns a result message.

    if not PYAUTOGUI_AVAILABLE:
        return (
            "pyautogui is not installed, chief, so I "
            "cannot control the computer."
        )

    kind = action["action"]

    try:
        if kind == "move":
            pyautogui.moveTo(
                action["x"],
                action["y"],
                duration=0.4
            )

            return (
                f"Done. The mouse is now at "
                f"{action['where']}."
            )

        if kind == "click":
            pyautogui.click()

            return "Done. I clicked."

        if kind == "double_click":
            pyautogui.doubleClick()

            return "Done. I double-clicked."

        if kind == "right_click":
            pyautogui.rightClick()

            return "Done. I right-clicked."

        if kind == "scroll":
            amount = action["amount"]

            if action["direction"] == "up":
                amount = -amount

            pyautogui.scroll(amount)

            return (
                f"Done. I scrolled "
                f"{action['direction']} "
                f"{action['amount']} notch(es)."
            )

        if kind == "type":
            payload = action["text"].replace(
                "\n", " "
            )

            pyautogui.typewrite(
                payload,
                interval=0.02
            )

            return (
                f"Done. I typed {len(payload)} "
                f"characters."
            )

        if kind == "press":
            pyautogui.press(action["key"])

            return (
                f"Done. I pressed "
                f"{action['key'].upper()}."
            )

        return (
            "That action is not on my allowlist, "
            "so I did nothing."
        )

    except pyautogui.FailSafeException:
        return (
            "EMERGENCY STOP, chief! The mouse hit "
            "the screen corner, so I cancelled "
            "everything immediately. Nothing "
            "further was done."
        )

    except Exception as error:
        return (
            f"The action failed safely: {error}"
        )


if __name__ == "__main__":
    print("Shadow COMPUTER CONTROL PARSER TEST")
    print("-" * 40)

    tests = (
        "move mouse to center",
        "move mouse to 500 300",
        "click",
        "double click",
        "right click",
        "scroll down 5",
        "scroll up",
        "type hello world",
        "press enter",
        "press winkey",
        "delete all my files",
        "hello how are you",
    )

    for test in tests:
        action = parse_command(test)

        if action is None:
            print(f"  '{test}' -> NOT an action (safe)")
        else:
            print(
                f"  '{test}' -> {describe_action(action)}"
            )
