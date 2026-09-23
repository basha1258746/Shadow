import os
import queue
import json
import array
import time

import settings as settings_store

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

# IMPORTANT LESSON FROM TESTING (2026-09-23):
# This laptop's SST microphone array outputs a
# strong ultrasonic beam-control signal. If we
# capture 4 channels and decimate ourselves,
# that ultrasonic content FOLDS DOWN into the
# speech band and garbles everything.
#
# The fix: open the device at its native rate
# with ONE channel so the DRIVER mixes the
# array down cleanly, then resample gently.

INPUT_RATE = 48000

INPUT_CHANNEL_CHOICES = (1, 2, 4)

DOWN_FACTOR = INPUT_RATE // SAMPLE_RATE

input_channels = 1

effective_down_factor = 1

# All the ways the user might call Shadow.
# "airbus" is how the tiny model mishears
# "Shadow" in some voices (found in testing).

WAKE_WORDS = (
    "Shadow",
    "jervis",
    "Shadow,",
    "hey Shadow",
    "ok Shadow",
    "yo Shadow",
    "airbus"
)

model = None

recognizer = None

mic_stream = None

audio_queue = None

input_ready = False

# Automatic gain: quiet or distant speech is
# amplified before recognition. The gain adapts
# slowly while you speak and never boosts
# silence.

TARGET_RMS = 3000.0

MIN_GAIN = 1.0

MAX_GAIN = 8.0

current_gain = 1.0


def _list_input_devices():
    import sounddevice as sd

    devices = []

    for index, device in enumerate(sd.query_devices()):
        if device["max_input_channels"] > 0:
            devices.append((index, device))

    return devices


def _choose_input_device():
    # Some laptops expose several microphones and
    # the Windows default can be a broken
    # beamformed device. Probe candidates in a
    # smart order and remember the winner.

    import sounddevice as sd

    devices = _list_input_devices()

    # 1. A previously saved working device.

    saved_id = settings_store.get_setting(
        "mic_device_id"
    )

    if saved_id is not None:
        for index, device in devices:
            if index == saved_id:
                return index, device["name"]

    # 2. The Windows default input.

    try:
        default_id = sd.query_devices(
            kind="input"
        )["index"]

        for index, device in devices:
            if index == default_id:
                return index, device["name"]

    except Exception:
        pass

    # 3. A fully-named Realtek array device
    #    (the working twin on this laptop).

    for index, device in devices:
        if device["name"].strip() == (
            "Microphone Array (Realtek(R) Audio)"
        ):
            return index, device["name"]

    # 4. Anything else that can capture.

    for index, device in devices:
        if "Stereo Mix" not in device["name"]:
            return index, device["name"]

    return None, None


def _open_stream(device_id):
    # Open the microphone with the first working
    # configuration from a proven fallback chain.
    # Mono at the native rate is preferred: the
    # DRIVER then mixes the array down cleanly,
    # and live testing proved this captures
    # recognizable speech on this laptop.

    global mic_stream
    global audio_queue
    global input_channels
    global effective_down_factor

    audio_queue = queue.Queue()

    attempts = (
        (48000, 1),
        (44100, 1),
        (44100, 2),
        (16000, 1),
        (48000, 4),
    )

    for rate, channels in attempts:

        try:
            mic_stream = sd.RawInputStream(
                samplerate=rate,
                blocksize=8000,
                dtype="int16",
                channels=channels,
                device=device_id,
                callback=audio_callback
            )

            mic_stream.start()

            # Give the audio driver a moment to
            # settle before we rely on callbacks.

            time.sleep(0.3)

            input_channels = channels

            effective_down_factor = rate / SAMPLE_RATE

            print(
                f"[Shadow EARS] Microphone opened: "
                f"{channels}ch @ {rate}Hz"
            )

            return True

        except Exception:

            try:
                if mic_stream is not None:
                    mic_stream.close()

            except Exception:
                pass

            mic_stream = None

    return False


def setup_stt():
    global model
    global recognizer
    global mic_stream
    global audio_queue
    global input_ready
    global input_channels
    global effective_down_factor

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

    # ALWAYS open a fresh stream for every
    # listen. Testing showed that long-lived
    # streams from this SST array stop producing
    # recognizable speech, while a freshly
    # opened stream hears perfectly.

    _reset_stream()

    model_path = os.path.abspath(MODEL_DIR)

    if not os.path.isdir(model_path):
        print(
            "[Shadow EARS] Speech model folder not found: "
            f"{model_path}"
        )
        return False

    try:
        # The heavy model loads once per session;
        # the recognizer is recreated every listen
        # so no stale audio state carries over.

        if model is None:
            print("[Shadow EARS] Loading speech model...")

            model = Model(model_path)

        recognizer = KaldiRecognizer(
            model,
            SAMPLE_RATE
        )

        device_id, device_name = _choose_input_device()

        if device_id is None:
            print(
                "[Shadow EARS] No usable microphone found."
            )
            return False

        if not _open_stream(device_id):
            print(
                "[Shadow EARS] Could not open "
                "microphone with any known format."
            )

            return False

        # Remember the working microphone so it is
        # used first next time.

        settings_store.set_setting(
            "mic_device_id",
            device_id
        )

        input_ready = True

        print(
            f"[Shadow EARS] Microphone ready: "
            f"{device_name} "
            f"(device {device_id})"
        )

        return True

    except Exception as error:
        print(f"[Shadow EARS] Could not start microphone: {error}")
        mic_stream = None
        recognizer = None
        model = None
        input_ready = False
        return False


def audio_callback(indata, frames, time_info, status):
    # The mic delivers audio at INPUT_RATE
    # (usually clean mono from the driver).
    # Resample to SAMPLE_RATE for the recognizer
    # using linear interpolation, which smooths
    # instead of folding high frequencies down.

    if effective_down_factor == 1 and input_channels == 1:
        audio_queue.put(bytes(indata))
        return

    import numpy as np_module

    samples = np_module.frombuffer(
        bytes(indata),
        dtype=np_module.int16
    ).astype(np_module.float32)

    if input_channels > 1:
        samples = samples[0::input_channels]

    factor = effective_down_factor

    new_len = int(len(samples) / factor)

    if new_len == 0:
        return

    positions = np_module.arange(new_len) * factor

    low = np_module.clip(
        positions.astype(int),
        0,
        len(samples) - 1
    )

    frac = positions - low

    high = np_module.clip(low + 1, 0, len(samples) - 1)

    out = (
        samples[low] * (1.0 - frac)
        + samples[high] * frac
    )

    # Adaptive gain: adapt only on real audio,
    # never on silence, so room noise is not
    # amplified into fake words.

    global current_gain

    rms = float(
        np_module.sqrt(
            np_module.mean(out ** 2)
        )
    )

    if rms > 300.0:
        wanted = TARGET_RMS / rms

        wanted = min(
            max(wanted, MIN_GAIN),
            MAX_GAIN
        )

        # Fast attack / slow release: jump the
        # gain up quickly so the FIRST word is
        # recognized, but come back down gently
        # so quiet speech stays amplified.

        if wanted > current_gain:
            current_gain = (
                0.4 * current_gain + 0.6 * wanted
            )

        else:
            current_gain = (
                0.7 * current_gain + 0.3 * wanted
            )

    out = out * current_gain

    audio_queue.put(
        np_module.clip(
            out,
            -32768,
            32767
        ).astype(np_module.int16).tobytes()
    )


def _reset_stream():
    # Force a clean microphone re-open on the
    # next listen after a dead or failed stream.

    global mic_stream
    global input_ready

    try:
        if mic_stream is not None:
            mic_stream.close()

    except Exception:
        pass

    mic_stream = None
    input_ready = False

    # Start every listen at unity gain so one
    # loud session cannot permanently shape
    # the next one.

    global current_gain

    current_gain = 1.0


def listen_for_command(max_seconds=7):
    global mic_stream

    if not setup_stt():
        return ""

    # Drop anything the microphone captured
    # before this listen started, such as the
    # tail of Shadow's own last sentence.

    flush_audio_queue()

    time.sleep(0.1)

    recognizer.Reset()

    # Measure time by the real clock. Counting
    # converted audio samples is unreliable: the
    # native multi-channel stream is mixed down,
    # so sample counts do not match real seconds.

    deadline = time.time() + max_seconds

    silent_rounds = 0

    try:
        while time.time() < deadline:

            remaining = deadline - time.time()

            wait = max(0.05, min(1.0, remaining))

            try:
                data = audio_queue.get(timeout=wait)

            except queue.Empty:
                silent_rounds += 1

                if silent_rounds >= 5:
                    # Nothing at all for ~5 seconds:
                    # the stream is probably dead.

                    raise

                continue

            silent_rounds = 0

            if recognizer.AcceptWaveform(data):

                final_part = json.loads(
                    recognizer.Result()
                ).get("text", "")

                if final_part:
                    return final_part

        # Time window ended; return any phrase
        # that was still being spoken.

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

        _reset_stream()

    except Exception as error:
        print(f"[Shadow EARS] Listening error: {error}")

        _reset_stream()

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

    # Same wall-clock rule as listen_for_command:
    # the budget must mean real seconds.

    deadline = time.time() + max_seconds

    silent_rounds = 0

    try:
        while time.time() < deadline:

            remaining = deadline - time.time()

            wait = max(0.05, min(1.0, remaining))

            try:
                data = audio_queue.get(timeout=wait)

            except queue.Empty:
                silent_rounds += 1

                if silent_rounds >= 5:
                    # Nothing at all for ~5 seconds:
                    # the stream is probably dead.

                    raise

                continue

            silent_rounds = 0

            if recognizer.AcceptWaveform(data):

                text = json.loads(
                    recognizer.Result()
                ).get("text", "")

                if not text:
                    continue

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
        print(
            "[Shadow EARS] Microphone was quiet. "
            "Try speaking a bit louder."
        )

        _reset_stream()

        return False, ""

    except Exception as error:
        print(f"[Shadow EARS] Listening error: {error}")

        _reset_stream()

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
