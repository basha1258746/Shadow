import os
import queue
import tempfile
import threading
import time

import settings as settings_store

try:
    import pyttsx3

except ImportError:
    pyttsx3 = None

# ---------------- THE VOICE OF ZOYA ----------------
#
# Primary: Piper neural TTS with the warm "Amy"
# voice - vastly more natural than the robotic
# Windows voices, fully offline. Fallback: the
# old Windows engine (Zira) if Piper or the
# voice files are missing, or if synthesis ever
# fails at runtime.

PREFERRED_VOICE = "zira"

DEFAULT_SPEECH_RATE = 170

MIN_SPEECH_RATE = 100

MAX_SPEECH_RATE = 280

PIPER_DIR = "piper_voices"

PIPER_MODEL = os.path.join(
    PIPER_DIR,
    "en_US-amy-medium.onnx",
)

# Piper speed control: length_scale is how much
# LONGER than normal she stretches sounds, so a
# faster speech rate means a SMALLER length
# scale. 170 wpm (the default) maps to 1.0.

PIPER_BASE_RATE = DEFAULT_SPEECH_RATE


def _piper_available():
    if not os.path.exists(PIPER_MODEL):
        return False

    try:
        from piper import PiperVoice

        return True

    except ImportError:
        return False


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

# When True, new sentences are not spoken.
# Set by the GUI 'stop speaking' button; the
# next user message clears it.

muted = False


def set_muted(value):
    global muted

    muted = bool(value)


def set_after_sentence_hook(hook):
    # Register the microphone-drain function.
    # Must be callable with no arguments.

    global after_sentence_hook

    after_sentence_hook = hook


def _get_piper_voice():
    # Load the neural voice once per session.

    global _piper_voice

    if _piper_voice is None:
        from piper import PiperVoice

        print(
            "[ZOYA VOICE] Loading the Piper neural "
            "voice (Amy)..."
        )

        _piper_voice = PiperVoice.load(
            PIPER_MODEL
        )

    return _piper_voice


_piper_voice = None


def _synthesize_to_wav(text):
    # Render one sentence with Piper and return
    # the path of a temporary WAV file, or None
    # on failure.

    try:
        from piper import SynthesisConfig

        voice = _get_piper_voice()

        length_scale = max(
            0.55,
            min(
                1.9,
                PIPER_BASE_RATE / max(
                    1, speech_rate
                ),
            ),
        )

        config = SynthesisConfig(
            length_scale=length_scale,
        )

        tmp = tempfile.NamedTemporaryFile(
            suffix=".wav",
            delete=False,
        )

        wav_path = tmp.name

        tmp.close()

        import wave as wave_module

        with wave_module.open(
            wav_path, "wb"
        ) as wav_file:
            voice.synthesize_wav(
                text,
                wav_file,
                syn_config=config,
            )

        return wav_path

    except Exception as error:
        print(
            f"[ZOYA VOICE] Piper synthesis failed: "
            f"{error} - falling back."
        )

        return None


def _play_wav(path):
    import winsound

    winsound.PlaySound(
        path,
        winsound.SND_FILENAME,
    )


def _speak_with_piper(text):
    wav_path = _synthesize_to_wav(text)

    if wav_path is None:
        return False

    try:
        _play_wav(wav_path)

        return True

    finally:
        try:
            os.unlink(wav_path)

        except Exception:
            pass


def _init_windows_engine():
    # The fallback engine (Windows Zira).

    engine = pyttsx3.init()

    selected = None

    for voice in engine.getProperty("voices"):
        if PREFERRED_VOICE in voice.name.lower():
            selected = voice.id

            break

    if selected:
        engine.setProperty("voice", selected)

    engine.setProperty("rate", speech_rate)

    return engine


def voice_worker_loop():
    global voice_ready

    # Windows COM must be initialized in the
    # thread that owns the fallback engine.

    try:
        import comtypes

        comtypes.CoInitialize()

    except Exception:
        pass

    fallback_engine = None

    piper_ok = _piper_available()

    if piper_ok:
        try:
            # Warm the neural voice now so the
            # first sentence is not slow.

            _get_piper_voice()

            voice_ready = True

            print(
                "[ZOYA VOICE] Neural voice ready "
                "(Piper/Amy)."
            )

        except Exception as error:
            print(
                f"[ZOYA VOICE] Piper failed to load: "
                f"{error} - using Windows voice."
            )

            piper_ok = False

    if not piper_ok:

        if pyttsx3 is None:
            print(
                "[ZOYA VOICE] No speech engine "
                "available."
            )

            _drain_queue()

            return

        try:
            fallback_engine = _init_windows_engine()

            voice_ready = True

            print(
                "[ZOYA VOICE] Windows voice ready "
                "(Zira)."
            )

        except Exception as error:
            print(
                f"[ZOYA VOICE] Could not start voice: "
                f"{error}"
            )

            _drain_queue()

            return

    while True:
        item = speech_queue.get()

        if item is None:
            speech_queue.task_done()
            break

        # Control messages adjust the speaking
        # speed for upcoming sentences.

        if isinstance(item, dict) and "set_rate" in item:
            new_rate = item["set_rate"]

            if fallback_engine is not None:
                try:
                    fallback_engine.setProperty(
                        "rate", new_rate
                    )

                except Exception:
                    pass

            speech_queue.task_done()
            continue

        spoken = False

        if piper_ok:
            spoken = _speak_with_piper(item)

        if not spoken and fallback_engine is not None:
            try:
                fallback_engine.say(item)

                fallback_engine.runAndWait()

                spoken = True

            except Exception as error:
                print(
                    f"[ZOYA VOICE] Speak failed: {error}"
                )

        # Give the audio output a moment to fully
        # finish, then drop whatever the microphone
        # captured of her own voice.

        time.sleep(0.4)

        if after_sentence_hook is not None:
            try:
                after_sentence_hook()

            except Exception as error:
                print(
                    f"[ZOYA VOICE] Self-voice guard "
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

    # Remove thinking blocks if any slip through.

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

    if muted:
        return

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


# Current requested speed in words per minute.
# Reads the saved value if settings are
# already loaded, otherwise the default.

speech_rate = settings_store.get_setting(
    "speech_rate"
)


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
    print("ZOYA VOICE OUTPUT TEST")

    if setup_voice():
        print(
            "Speaking with the new voice..."
        )

        speak(
            "Hello chief. I am Shadow, your personal "
            "AI companion. Do you like my new voice?"
        )

        wait_until_speech_done()

        print("Now a bit faster...")

        set_speech_rate(220)

        speak(
            "I can also speak faster when you are "
            "in a hurry, chief."
        )

        wait_until_speech_done()

        set_speech_rate(DEFAULT_SPEECH_RATE)

        print("All sentences spoken.")
