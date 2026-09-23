import os
import queue

try:
    from vosk import Model, KaldiRecognizer

    VOSK_AVAILABLE = True
except ImportError:
    VOSK_AVAILABLE = False

try:
    import sounddevice as sd

    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False

MODEL_DIR = "vosk-model-small-en-us-0.15"

SAMPLE_RATE = 16000

# All the ways the user might call Shadow.

WAKE_WORDS = (
    "Shadow",
    "jervis",
    "Shadow,",
    "hey Shadow",
    "ok Shadow",
    "yo Shadow"
)

model = None
recognizer = None
mic_stream = None
audio_queue = None

input_ready = False


def setup_stt():
    global model
    global recognizer
    global mic_stream
    global audio_queue
    global input_ready

    if not VOSK_AVAILABLE:
        print(
            "[Shadow EARS] vosk is not installed. "
            "Voice input is disabled."
        )
        return False

    if not SOUNDDEVICE_AVAILABLE:
        print(
            "[Shadow EARS] sounddevice is not installed. "
            "Voice input is disabled."
        )
        return False

    if input_ready:
        return True

    model_path = os.path.abspath(MODEL_DIR)

    if not os.path.isdir(model_path):
        print(
            "[Shadow EARS] Speech model folder not found: "
            f"{model_path}"
        )
        return False

    try:
        print("[Shadow EARS] Loading speech model...")

        model = Model(model_path)

        recognizer = KaldiRecognizer(
            model,
            SAMPLE_RATE
        )

        audio_queue = queue.Queue()

        mic_stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=8000,
            dtype="int16",
            channels=1,
            callback=audio_callback
        )

        mic_stream.start()

        input_ready = True

        print("[Shadow EARS] Microphone ready.")

        return True

    except Exception as error:
        print(f"[Shadow EARS] Could not start microphone: {error}")
        mic_stream = None
        recognizer = None
        model = None
        input_ready = False
        return False


def audio_callback(indata, frames, time_info, status):
    audio_queue.put(bytes(indata))


def listen_for_command(max_seconds=7):
    global mic_stream

    if not setup_stt():
        return ""

    recognizer.Reset()

    collected = []

    total_frames = 0

    frames_needed = int(SAMPLE_RATE * max_seconds)

    try:
        while total_frames < frames_needed:

            data = audio_queue.get(timeout=1.0)

            collected.append(data)

            total_frames += len(data) // 2

            if recognizer.AcceptWaveform(data):

                result_text = (
                    recognizer.Result()
                )

                import json

                final_part = json.loads(
                    result_text
                ).get("text", "")

                if final_part:
                    collected.clear()

                    collected.append(data)

                    total_frames = len(data) // 2

        # Check for a final result one more time.

        import json

        final_part = json.loads(
            recognizer.FinalResult()
        ).get("text", "")

        if final_part:
            return final_part

    except queue.Empty:
        print(
            "[Shadow EARS] Microphone was quiet. "
            "Try speaking a bit louder."
        )

    except Exception as error:
        print(f"[Shadow EARS] Listening error: {error}")

        try:
            mic_stream.close()
        except Exception:
            pass

        mic_stream = None
        input_ready = False

        return ""

    spoken = " ".join(
        part
        for part in [
            json.loads(recognizer.Result()).get("text", "")
        ]
        if part
    )

    return spoken


def flush_audio_queue():
    # Drop everything the microphone already
    # heard. Used after Shadow speaks so she
    # cannot wake herself up with her own
    # voice.

    if audio_queue is None:
        return

    while True:
        try:
            audio_queue.get_nowait()

        except queue.Empty:
            break


def strip_wake_word(text):
    # Remove the wake word from the start of a
    # heard phrase and return (found, rest).

    if not text:
        return False, ""

    lowered = text.lower().strip()

    # Longest first so "hey Shadow" is removed
    # completely, not just "Shadow".

    for wake in sorted(
        WAKE_WORDS,
        key=len,
        reverse=True
    ):
        if lowered.startswith(wake):
            rest = text[
                len(wake):
            ].strip(" ,.!?\t")

            return True, rest

    return False, text


def listen_for_wake_word(max_seconds=30):
    # Listen continuously. Return as soon as the
    # wake word is heard: (True, command_after_wake)
    # or (False, "") if nothing was heard.

    global mic_stream

    if not setup_stt():
        return False, ""

    flush_audio_queue()

    recognizer.Reset()

    collected = []

    total_frames = 0

    frames_needed = int(SAMPLE_RATE * max_seconds)

    import json

    try:
        while total_frames < frames_needed:

            data = audio_queue.get(timeout=1.0)

            collected.append(data)

            total_frames += len(data) // 2

            if recognizer.AcceptWaveform(data):

                text = json.loads(
                    recognizer.Result()
                ).get("text", "")

                if not text:
                    continue

                # Only keep audio since this phrase;
                # older phrases are irrelevant now.

                collected.clear()

                collected.append(data)

                total_frames = len(data) // 2

                found, rest = strip_wake_word(text)

                if found:
                    return True, rest

        # Time window ended; check the last
        # partial phrase for the wake word.

        text = json.loads(
            recognizer.Result()
        ).get("text", "")

        found, rest = strip_wake_word(text)

        if found:
            return True, rest

        return False, ""

    except queue.Empty:
        return False, ""

    except Exception as error:
        print(f"[Shadow EARS] Listening error: {error}")

        try:
            mic_stream.close()
        except Exception:
            pass

        mic_stream = None
        input_ready = False

        return False, ""


def close_stt():
    global mic_stream
    global input_ready

    if mic_stream is not None:
        try:
            mic_stream.close()
        except Exception:
            pass

    mic_stream = None
    input_ready = False


if __name__ == "__main__":
    print("Shadow WAKE WORD TEST")
    print("-" * 40)
    print("Say 'Shadow' followed by a command.")
    print("Example: Shadow, what can you do")
    print()

    found, command = listen_for_wake_word(30)

    if found:
        print(f"Wake word detected!")
        print(f"Command: '{command}'")

    else:
        print("No wake word heard.")

    close_stt()
