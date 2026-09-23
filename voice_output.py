import queue
import threading
import time

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

# Protects worker startup so rapid speak()
# calls can never create two engines.

worker_lock = threading.Lock()

voice_worker = None

voice_ready = False

# Called after each sentence is spoken so the
# microphone can drop Shadow's own voice before
# it is treated as a wake word or a command.

after_sentence_hook = None


def set_after_sentence_hook(hook):
    # Register the microphone-drain function.
    # Must be callable with no arguments.

    global after_sentence_hook

    after_sentence_hook = hook


def voice_worker_loop():
    global voice_ready

    # Windows COM must be initialized in the
    # thread that owns the speech engine.

    try:
        import comtypes

        comtypes.CoInitialize()

    except Exception:
        pass

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

        _drain_queue()

        return

    while True:
        item = speech_queue.get()

        if item is None:
            speech_queue.task_done()
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

        # Give the audio output a moment to fully
        # finish, then drop whatever the microphone
        # captured of her own voice.

        time.sleep(0.4)

        if after_sentence_hook is not None:
            try:
                after_sentence_hook()

            except Exception as error:
                print(
                    f"[Shadow VOICE] Self-voice guard "
                    f"failed: {error}"
                )

        speech_queue.task_done()


def _drain_queue():
    # Empty the queue if the worker is dying,
    # so wait_until_speech_done can never hang.

    while not speech_queue.empty():
        try:
            speech_queue.get_nowait()
            speech_queue.task_done()

        except queue.Empty:
            break


def setup_voice():
    global voice_worker
    global voice_ready

    if pyttsx3 is None:
        return False

    with worker_lock:

        # Healthy and running?

        if (
            voice_ready
            and voice_worker is not None
            and voice_worker.is_alive()
        ):
            return True

        # Worker still starting up?

        if (
            voice_worker is not None
            and voice_worker.is_alive()
        ):
            return True

        # No worker, or it died earlier: start a
        # fresh one (self-healing restart).

        voice_ready = False

        voice_worker = threading.Thread(
            target=voice_worker_loop,
            daemon=True
        )

        voice_worker.start()

    return True


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
    # Wait for the worker to be ready first,
    # otherwise a fast caller could return
    # before speaking even starts.

    waited = 0.0

    while waited < 10.0:

        if voice_ready:
            break

        if voice_worker is None or not voice_worker.is_alive():
            # No worker will ever speak; if the
            # queue is also empty there is nothing
            # to wait for.

            if speech_queue.empty():
                return

            break

        time.sleep(0.1)

        waited += 0.1

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
        print("Queueing sentences rapidly (race test)...")

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
