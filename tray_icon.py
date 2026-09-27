import threading

from PIL import Image, ImageDraw

import pystray

# ---------------- Shadow IN THE SYSTEM TRAY ----------------
#
# A small icon lives next to the clock so sir
# can always see his state and control him:
#
#   - purple pulsing-free dot: listening
#   - green: ready/idle
#   - orange: speaking or thinking
#   - red: paused (mic muted from the tray)
#
# Right-click menu:
#   Pause / resume listening
#   Mute / unmute voice
#   Stop speaking (drop the queue)
#   Exit Shadow
#
# The icon runs on its own daemon thread; state
# changes are cheap image redraws. Works in the
# terminal, GUI, and autostart modes.

# Shared control state. Other modules import
# tray_icon and set these; the menu reads them.

state = {
    "listening": False,
    "muted": False,
    "paused": False,
    "status_text": "Shadow starting...",
}

pause_event = threading.Event()

# Set by Shadow.py so menu actions can reach
# the running program (stop speech, exit, open
# the GUI window).

actions = {
    "on_exit": None,
    "on_stop_speech": None,
}

_icon = None

_thread = None

_lock = threading.Lock()

COLORS = {
    "listening": (171, 71, 188),   # purple
    "ready": (76, 175, 80),        # green
    "busy": (255, 152, 0),         # orange
    "paused": (244, 67, 54),       # red
}


def _current_color():
    if state["paused"]:
        return COLORS["paused"]

    if state["listening"]:
        return COLORS["listening"]

    if state["muted"]:
        return COLORS["busy"]

    return COLORS["ready"]


def _draw_icon(color):
    # 64x64 for crisp scaling; a filled circle
    # with a small "Z".

    image = Image.new(
        "RGBA",
        (64, 64),
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(image)

    draw.ellipse(
        (6, 6, 58, 58),
        fill=color + (255,),
    )

    draw.text(
        (24, 16),
        "Z",
        fill=(255, 255, 255, 255),
    )

    return image


def _refresh():
    # Redraw with the current state. Safe from
    # any thread.

    with _lock:
        if _icon is None:
            return

        try:
            _icon.icon = _draw_icon(
                _current_color()
            )

            _icon.title = _title_text()

        except Exception:
            pass


def _title_text():
    parts = ["Shadow"]

    if state["paused"]:
        parts.append("- mic PAUSED")

    if state["muted"]:
        parts.append("- voice muted")

    parts.append(f"- {state['status_text']}")

    return " ".join(parts)


def set_state(
    listening=None,
    muted=None,
    paused=None,
    status_text=None,
):
    if listening is not None:
        state["listening"] = listening

    if muted is not None:
        state["muted"] = muted

    if paused is not None:
        state["paused"] = paused

    if status_text is not None:
        state["status_text"] = status_text

    _refresh()


def _toggle_pause(icon, item):
    if state["paused"]:
        pause_event.clear()

        set_state(
            paused=False,
            status_text="listening again",
        )

    else:
        pause_event.set()

        set_state(
            paused=True,
            listening=False,
            status_text="mic paused from tray",
        )


def _toggle_mute(icon, item):
    try:
        import voice_output

        new_value = not state["muted"]

        voice_output.set_muted(new_value)

        set_state(muted=new_value)

    except Exception:
        pass


def _show_qr(icon, item):
    handler = actions.get("on_show_qr")

    if handler:
        try:
            handler()

        except Exception:
            pass


def _stop_speech(icon, item):
    handler = actions.get("on_stop_speech")

    if handler:
        try:
            handler()

        except Exception:
            pass


def _exit(icon, item):
    handler = actions.get("on_exit")

    if handler:
        try:
            handler()

        except Exception:
            pass

    try:
        icon.stop()

    except Exception:
        pass


def start():
    # Build the icon and run it on a daemon
    # thread. Safe to call once per process.

    global _icon
    global _thread

    with _lock:
        if _icon is not None:
            return

        menu = pystray.Menu(
            pystray.MenuItem(
                lambda item: (
                    "Resume listening"
                    if state["paused"]
                    else "Pause listening"
                ),
                _toggle_pause,
            ),
            pystray.MenuItem(
                lambda item: (
                    "Unmute voice"
                    if state["muted"]
                    else "Mute voice"
                ),
                _toggle_mute,
            ),
            pystray.MenuItem(
                "Show phone QR",
                _show_qr,
            ),
            pystray.MenuItem(
                "Stop speaking now",
                _stop_speech,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Exit Shadow",
                _exit,
            ),
        )

        _icon = pystray.Icon(
            "Shadow",
            _draw_icon(COLORS["ready"]),
            _title_text(),
            menu,
        )

        _thread = threading.Thread(
            target=_icon.run,
            daemon=True,
        )

        _thread.start()


if __name__ == "__main__":
    print("Shadow tray icon test")

    print(
        "Look at the system tray (near the clock): "
        "a green circle with Z. The color changes "
        "every 2 seconds."
    )

    start()

    import time

    demo = [
        ("listening", True, False, "listening"),
        ("listening", False, False, "speaking"),
        ("listening", False, False, "listening again"),
        ("listening", False, True, "paused"),
    ]

    for listening, muted, paused, text in demo:
        set_state(
            listening=listening,
            muted=muted,
            paused=paused,
            status_text=text,
        )

        time.sleep(2)

    print("Demo done. Right-click the icon for the")
    print("menu. This test stays running; Ctrl+C to")
    print("stop.")

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        pass
