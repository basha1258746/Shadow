import time

import screen_vision

# A live observation session: peek at the
# user's real screen three times while they
# work normally, and describe each moment.

ROUNDS = 3

GAP_SECONDS = 90

CHAR_LIMIT = 3000


def describe(text, title):
    from shadow import ask_ollama

    prompt = f"""
You are SHADOW.

The text below was read from the user's
screen while they were working normally.

ACTIVE WINDOW: {title or "unknown"}

SCREEN TEXT:
----------------
{text[:CHAR_LIMIT]}
----------------

In TWO short sentences: what app is this,
and what is the user doing right now?
Do not invent details.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "You are SHADOW. Describe the user's "
                "activity from OCR text only. Two "
                "short sentences. Never invent "
                "details."
            )
        },

        {
            "role": "user",
            "content": prompt
        }
    ]

    return ask_ollama(messages)


def main():
    observations = []

    print("=" * 55)
    print("SHADOW LIVE VISION SESSION")
    print("=" * 55)
    print("baa: use the laptop normally!")
    print(f"SHADOW will peek {ROUNDS} times, "
          f"about every {GAP_SECONDS} seconds.")
    print("=" * 55)

    for round_number in range(1, ROUNDS + 1):

        print()
        print(f"--- PEEK {round_number}/{ROUNDS} at "
              f"{time.strftime('%H:%M:%S')} ---")

        title, text = screen_vision.read_screen_text()

        if not text:
            note = (
                "Could not read any text "
                "(maybe a video or image was "
                "fullscreen)."
            )

            print(f"SHADOW saw: {note}")

            observations.append(
                (time.strftime("%H:%M:%S"),
                 title, note)
            )

        else:
            print(
                f"read {len(text)} characters from "
                f"'{title}' - thinking..."
            )

            start = time.time()

            note = describe(text, title)

            print(
                f"SHADOW saw ({time.time() - start:.0f}s):"
            )
            print(note)

            observations.append(
                (time.strftime("%H:%M:%S"),
                 title, note)
            )

        if round_number < ROUNDS:
            print()
            print(
                f"(next peek in {GAP_SECONDS} seconds "
                f"- keep working, baa!)"
            )

            time.sleep(GAP_SECONDS)

    print()
    print("=" * 55)
    print("SESSION DIARY")
    print("=" * 55)

    for when, title, note in observations:
        print()
        print(f"[{when}] window: {title or '?'}")
        print(f"  {note}")

    print()
    print("SESSION COMPLETE")


if __name__ == "__main__":
    main()
