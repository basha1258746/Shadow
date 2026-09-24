import re
import threading

try:
    import pygetwindow as gw

    GW_AVAILABLE = True

except ImportError:
    GW_AVAILABLE = False

# ---------------- WATCH DESIGN ----------------
#
# One watched window at a time. A background
# thread captures ONLY the watched window's
# rectangle, reads its text with OCR every
# POLL_SECONDS, and when the content changes
# it announces the change and asks the local
# model for a short summary.
#
# The first reading after starting is the
# BASELINE - a change is only announced
# against that baseline.

POLL_SECONDS = 10

MAX_TEXT_CHARS = 5000

watch_stop = threading.Event()

watch_thread = None

watch_state = {
    "active": False,
    "title": "",
    "last_text": None,   # None until baseline read
    "last_change": None, # {"when": ..., "summary": ...}
    "changes": 0,
}


def _normalize(text):
    return re.sub(r"\s+", " ", text).strip()


def find_window(query):
    # Find a window by (case-insensitive)
    # substring of its title. Exact match wins.

    if not GW_AVAILABLE:
        return None

    query = query.lower().strip()

    windows = gw.getAllWindows()

    for window in windows:
        if window.title.strip().lower() == query:
            return window

    for window in windows:
        if query in window.title.lower():
            return window

    return None


def _ocr_image(shot):
    # Safe OCR shared with the document reader.

    from document_reader import ocr_image_safe

    return ocr_image_safe(shot)


def _grab_window_text(window):
    # OCR only this window's rectangle.

    try:
        from PIL import ImageGrab

        box = (
            window.left,
            window.top,
            window.left + window.width,
            window.top + window.height,
        )

        shot = ImageGrab.grab(bbox=box)

        return _ocr_image(shot)

    except Exception as error:
        print(
            f"[Shadow WATCHER] Read failed: {error}"
        )
        return ""


def _watch_loop(window_title, summarize, speak_fn, voice_on):
    # The background loop. summarize(text)
    # returns a short summary; speak_fn speaks
    # when voice is on.

    print(
        f"[Shadow WATCHER] Watching '{window_title}' "
        f"every {POLL_SECONDS} seconds."
    )

    while not watch_stop.is_set():

        window = find_window(window_title)

        if window is None:
            message = (
                f"baa, the window '{window_title}' is "
                "gone, so I stopped watching it."
            )

            print(f"[Shadow WATCHER] {message}")

            watch_state["active"] = False

            if voice_on():
                speak_fn(message)

            return

        text = _grab_window_text(window)

        limited = text[:MAX_TEXT_CHARS]

        if watch_state["last_text"] is None:
            # First reading = baseline, never an
            # announcement.

            watch_state["last_text"] = limited

        elif _normalize(limited) != _normalize(
            watch_state["last_text"]
        ):
            watch_state["last_text"] = limited

            watch_state["changes"] += 1

            import time as time_module

            when = time_module.strftime("%H:%M:%S")

            print(
                "[Shadow WATCHER] Content changed - "
                "summarizing..."
            )

            summary = summarize(limited)

            watch_state["last_change"] = {
                "when": when,
                "summary": summary,
            }

            message = (
                f"baa, something changed in "
                f"'{window_title}'. {summary}"
            )

            print(f"[Shadow WATCHER] {message}")

            if voice_on():
                speak_fn(message)

        watch_stop.wait(POLL_SECONDS)

    watch_state["active"] = False


def start_watching(query, summarize, speak_fn, voice_on):
    # Start watching a window whose title
    # contains 'query'. Returns (ok, message).

    global watch_thread

    stop_watching(quiet=True)

    window = find_window(query)

    if window is None:
        return False, (
            f"I cannot find a window called "
            f"'{query}', baa. Check the exact name "
            f"and try again."
        )

    title = window.title.strip()

    watch_stop = threading.Event()

    # Rebind the module-level event used by the
    # loop and stop_watching.

    globals()["watch_stop"] = watch_stop

    watch_state.update(
        active=True,
        title=title,
        last_text=None,
        last_change=None,
        changes=0,
    )

    watch_thread = threading.Thread(
        target=_watch_loop,
        args=(title, summarize, speak_fn, voice_on),
        daemon=True,
    )

    watch_thread.start()

    return True, (
        f"Watching '{title}', baa. I will read it "
        f"every {POLL_SECONDS} seconds and tell you "
        f"when its content changes. Say 'stop "
        f"watching' any time."
    )


def stop_watching(quiet=False):
    watch_stop.set()

    if watch_state["active"] and not quiet:
        return (
            f"Stopped watching "
            f"'{watch_state['title']}', baa. I saw "
            f"{watch_state['changes']} change(s)."
        )

    watch_state["active"] = False
    return "Stopped watching."


def watch_status_text():
    if not watch_state["active"]:
        return (
            "I am not watching any window right "
            "now, baa. Start one with: watch "
            "<window name>."
        )

    lines = [
        f"Watching '{watch_state['title']}' "
        f"({watch_state['changes']} change(s) so "
        f"far).",
    ]

    change = watch_state["last_change"]

    if change:
        lines.append(
            f"Last change at {change['when']}: "
            f"{change['summary']}"
        )

    else:
        lines.append(
            "No changes since I started watching."
        )

    return "\n".join(lines)


if __name__ == "__main__":
    print("Shadow WINDOW WATCHER TEST")

    window = find_window("Shadow")

    if window:
        print(f"Found: {window.title}")
    else:
        print("No matching window found.")
