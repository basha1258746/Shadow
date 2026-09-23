import queue
import threading

import settings as settings_store

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None

PREFERRED_VOICE = "zira"

DEFAULT_SPEECH_RATE = 170

MIN_SPEECH_RATE = 100

MAX_SPEECH_RATE = 280

# Current requested speed in words per minute.
# The worker applies it to the engine.
# Reads the saved value if settings are
# already loaded, otherwise the default.

speech_rate = settings_store.get_setting(
    "speech_rate"
)

# Sentences waiting to be spoken.

speech_queue = queue.Queue()

voice_worker = None
voice_ready = False
voice_failed = False


def setup_voice():
    global voice_worker
    global speech_rate

    if pyttsx3 is None:
        if not voice_failed:
            print(
                "[Shadow VOICE] pyttsx3 is not installed. "
                "Voice output is disabled."
            )
        return False

    if voice_ready or voice_failed:
        return voice_ready

    # Restore the speed the user chose in an
    # earlier session.

    speech_rate = settings_store.get_setting(
        "speech_rate"
    )

    # The engine lives inside the worker thread.
    # All speaking happens there, in the background.

    voice_worker = threading.Thread(
        target=voice_worker_loop,
        daemon=True
    )

    voice_worker.start()

    return True


def voice_worker_loop():
    global voice_ready
    global voice_failed

    try:
        engine = pyttsx3.init()

        selected = None

        for voice in engine.getProperty("voices"):
            if PREFERRED_VOICE in voice.name.lower():
                selected = voice.id
                break

        if selected:
            engine.setProperty("voice", selected)

        engine.setProperty("rate", speech_rate)

        voice_ready = True

        print("[Shadow VOICE] Voice output ready.")

    except Exception as error:
        print(f"[Shadow VOICE] Could not start voice: {error}")
        voice_failed = True
        return

    while True:
        item = speech_queue.get()

        if item is None:
            break

        # Control messages adjust the engine,
        # for example a new speaking speed.

        if isinstance(item, dict) and "set_rate" in item:
            try:
                engine.setProperty("rate", item["set_rate"])

            except Exception as error:
                print(
                    f"[Shadow VOICE] Could not change "
                    f"speed: {error}"
                )

            speech_queue.task_done()
            continue

        try:
            engine.say(item)
            engine.runAndWait()

        except Exception as error:
            print(f"[Shadow VOICE] Speak failed: {error}")

        speech_queue.task_done()


def clean_for_speech(text):
    if not text:
        return ""

    import re

    # Remove Qwen3 thinking blocks if any slip through.

    text = re.sub(
        r"<think>.*?</think>",
        "",
        text,
        flags=re.DOTALL
    )

    # Turn markdown into plain speakable text.

    text = re.sub(r"[*_#`>\[\]]", " ", text)
    text = re.sub(r"\|", " ", text)
    text = re.sub(r"\s*[-]{3,}\s*", " ", text)

    # Make URLs speakable-ish (shortened).

    text = re.sub(
        r"https?://\S+",
        "link",
        text
    )

    # Collapse leftover symbols and spaces.

    text = re.sub(r"\s+", " ", text).strip()

    # Remove emoji and other non-ASCII symbols
    # so the voice does not try to read them.

    text = re.sub(r"[^\x00-\x7F]+", " ", text)

    text = re.sub(r"\s+", " ", text).strip()

    return text


def speak(text):
    # Queue a sentence for speaking and return
    # immediately (non-blocking).

    if not setup_voice():
        return

    speech_text = clean_for_speech(text)

    if not speech_text:
        return

    speech_queue.put(speech_text)


def speak_blocking(text):
    # Queue a sentence and wait until everything
    # (including this sentence) has been spoken.

    if not setup_voice():
        return

    speak(text)

    wait_until_speech_done()


def wait_until_speech_done():
    if not voice_ready:
        return

    speech_queue.join()


def stop_speech():
    # Drop everything still waiting in the queue.
    # The sentence currently being spoken finishes.

    while not speech_queue.empty():
        try:
            speech_queue.get_nowait()
            speech_queue.task_done()
        except queue.Empty:
            break


def set_speech_rate(new_rate):
    global speech_rate

    new_rate = int(new_rate)

    if new_rate < MIN_SPEECH_RATE:
        new_rate = MIN_SPEECH_RATE

    if new_rate > MAX_SPEECH_RATE:
        new_rate = MAX_SPEECH_RATE

    speech_rate = new_rate

    # Remember this choice for future sessions.

    settings_store.set_setting("speech_rate", new_rate)

    # Tell the worker to apply the new speed.
    # It takes effect after the current sentence.

    if setup_voice():
        speech_queue.put({"set_rate": new_rate})

    return new_rate


def get_speech_rate():
    return speech_rate


if __name__ == "__main__":
    print("Shadow VOICE OUTPUT TEST")
    print("-" * 40)

    if setup_voice():
        print("Queueing three sentences...")

        speak("Hello baa. I am Shadow.")
        speak("This sentence should start before the next one is ready.")
        speak("If you hear these in order, the queue works.")

        print("Typing while speaking works if this appears immediately.")

        wait_until_speech_done()

        print("Now trying faster...")

        set_speech_rate(230)
        speak("I can speak much faster when you ask me to.")
        wait_until_speech_done()

        set_speech_rate(DEFAULT_SPEECH_RATE)

        print("All sentences spoken.")
    else:
        print("Voice is not available on this system.")
