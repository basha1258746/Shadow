import ctypes

try:
    from PIL import Image, ImageGrab

    PIL_AVAILABLE = True

except ImportError:
    PIL_AVAILABLE = False

# Screen understanding is ALWAYS on-demand:
# Shadow only captures when the user asks.
# Nothing is saved to disk; the screenshot
# lives in memory just long enough to be
# read, then it is dropped.

MAX_SCREEN_WIDTH = 1600


def get_active_window_title():
    # Title of the window the user is looking
    # at right now. Pure ctypes: no new
    # dependencies.

    try:
        user32 = ctypes.windll.user32

        handle = user32.GetForegroundWindow()

        length = user32.GetWindowTextLengthW(handle)

        if length <= 0:
            return ""

        buffer = ctypes.create_unicode_buffer(
            length + 1
        )

        user32.GetWindowTextW(
            handle,
            buffer,
            length + 1
        )

        return buffer.value.strip()

    except Exception:
        return ""


def capture_screen():
    # Capture the primary screen and gently
    # downscale so OCR stays fast on this
    # 8 GB laptop. Returns a PIL image or None.

    if not PIL_AVAILABLE:
        print(
            "[Shadow EYES] Pillow is not installed."
        )
        return None

    try:
        print(
            "[Shadow EYES] Taking a screenshot..."
        )

        shot = ImageGrab.grab()

        if shot.width > MAX_SCREEN_WIDTH:
            ratio = MAX_SCREEN_WIDTH / shot.width

            new_size = (
                MAX_SCREEN_WIDTH,
                int(shot.height * ratio),
            )

            resample = getattr(
                Image, "Resampling", Image
            ).LANCZOS

            shot = shot.resize(
                new_size,
                resample
            )

        return shot

    except Exception as error:
        print(
            f"[Shadow EYES] Capture failed: {error}"
        )
        return None


def read_screen_text():
    # Capture + OCR. Returns (window_title,
    # text). Text may be empty if nothing
    # readable is on screen.

    window_title = get_active_window_title()

    from document_reader import setup_ocr, ocr_image_safe

    if not setup_ocr():
        return window_title, ""

    shot = capture_screen()

    if shot is None:
        return window_title, ""

    try:
        print(
            "[Shadow EYES] Reading the screen..."
        )

        text = ocr_image_safe(shot)

    except Exception as error:
        print(
            f"[Shadow EYES] OCR failed: {error}"
        )
        return window_title, ""

    text = text.strip()

    print(
        f"[Shadow EYES] Read {len(text)} characters "
        f"from the screen."
    )

    # The image is dropped here; only text
    # survives.

    return window_title, text


def describe_screen(question=None):
    # The full flow: capture -> OCR -> let
    # the local model describe it. The model
    # only ever sees extracted text, never
    # the image itself.

    from Shadow import ask_ollama

    window_title, screen_text = read_screen_text()

    if not screen_text:
        return (
            "I looked at your screen, baa, but could "
            "not read any text on it. It may be "
            "mostly images or video right now."
        )

    # Very long OCR text would slow the small
    # model down; keep the most useful part.
    # Descriptions need less text than
    # targeted questions, so they trim harder
    # for a faster reply.

    char_limit = 6000 if question else 4000

    limited = screen_text[:char_limit]

    if len(screen_text) > char_limit:
        limited += (
            "\n\n[Screen text was limited to the "
            f"first {char_limit} characters.]"
        )

    if question:
        task = (
            f"The user asks about the screen: "
            f"{question}\n\nAnswer it using ONLY "
            f"what is visible in the text. If the "
            f"answer is not there, say so honestly."
        )

    else:
        task = (
            "Describe what is on the screen in a "
            "few short, useful sentences: what app "
            "or content this looks like, and "
            "anything important visible. Be "
            "concise."
        )

    prompt = f"""
You are Shadow, a local AI assistant.

The text below was read from the user's
screen with OCR (it may contain small
reading errors and layout junk - do not
comment on that, just interpret it).

ACTIVE WINDOW TITLE:
----------------
{window_title or "unknown"}
----------------

SCREEN TEXT:
----------------
{limited}
----------------

{task}
"""

    messages = [
        {
            "role": "system",
            "content": (
                "You are Shadow. Describe the user's "
                "screen using only the provided OCR "
                "text. Never invent details. Be "
                "concise and helpful."
            )
        },

        {
            "role": "user",
            "content": prompt
        }
    ]

    print(
        "[Shadow EYES] Thinking about what I saw..."
    )

    return ask_ollama(messages)


if __name__ == "__main__":
    print("Shadow SCREEN VISION TEST")

    title, text = read_screen_text()

    print()
    print(f"Active window: {title or '(unknown)'}")
    print(f"Characters read: {len(text)}")
    print()
    print("--- first 500 characters ---")
    print(text[:500])
