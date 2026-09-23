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

# The laptop microphone is a multi-channel SST
# array. Opening it at a low simple rate makes
# Windows deliver processed garbage, so we open
# it NATIVELY and convert ourselves.

INPUT_RATE = 48000

INPUT_CHANNEL_CHOICES = (4, 2, 1)

DOWN_FACTOR = INPUT_RATE // SAMPLE_RATE

input_channels = 1

effective_down_factor = 1

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

        device_id, device_name = _choose_input_device()

        if device_id is None:
            print(
                "[Shadow EARS] No usable microphone found."
            )
            return False

        audio_queue = queue.Queue()

        # Try the native multi-channel, high-rate
        # format first; fall back to simpler ones.

        opened = False

        for channels in INPUT_CHANNEL_CHOICES:
            try:
                mic_stream = sd.RawInputStream(
                    samplerate=INPUT_RATE,
                    blocksize=8000,
                    dtype="int16",
                    channels=channels,
                    device=device_id,
                    callback=audio_callback
                )

                mic_stream.start()

                # Give the audio driver a moment to
                # settle before we rely on callbacks.

                time.sleep(0.5)

                input_channels = channels

                effective_down_factor = (
                    INPUT_RATE // SAMPLE_RATE
                )

                opened = True

                break

            except Exception:
                mic_stream = None

        if not opened:
            # Last resort: the simple old way.

            try:
                mic_stream = sd.RawInputStream(
                    samplerate=SAMPLE_RATE,
                    blocksize=8000,
                    dtype="int16",
                    channels=1,
                    device=device_id,
                    callback=audio_callback
                )

                mic_stream.start()

                input_channels = 1

                effective_down_factor = 1

                opened = True

            except Exception as error:
                print(
                    f"[Shadow EARS] Could not open "
                    f"microphone: {error}"
                )

                return False

        if not opened:
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
    # The mic delivers multi-channel audio at
    # INPUT_RATE. Convert it to mono at
    # SAMPLE_RATE for the recognizer.

    if effective_down_factor == 1 and input_channels == 1:
        audio_queue.put(bytes(indata))
        return

    import array as array_module

    samples = array_module.array("h")

    samples.frombytes(bytes(indata))

    mono = samples[0::input_channels]

    if effective_down_factor > 1:
        factor = effective_down_factor

        usable = (len(mono) // factor) * factor

        out_count = usable // factor

        converted = array.array(
            "h",
            bytes(2 * out_count)
        )

        out_index = 0

        for start in range(0, usable, factor):
            total = 0

            for offset in range(factor):
                total += mono[start + offset]

            converted[out_index] = total // factor

            out_index += 1

        audio_queue.put(converted.tobytes())

    else:
        audio_queue.put(mono.tobytes())


def listen_for_command(max_seconds=7):
    global mic_stream

    if not setup_stt():
        return ""

    recognizer.Reset()

    collected = []

    total_frames = 0

    frames_needed = int(SAMPLE_RATE * max_seconds)

    quiet_rounds = 0

    try:
        while total_frames < frames_needed:

            try:
                data = audio_queue.get(timeout=1.0)

            except queue.Empty:
                quiet_rounds += 1

                if quiet_rounds >= 3:
                    raise

                continue

            quiet_rounds = 0

            collected.append(data)

            total_frames += len(data) // 2

            if recognizer.AcceptWaveform(data):

                result_text = (
                    recognizer.Result()
                )

                final_part = json.loads(
                    result_text
                ).get("text", "")

                if final_part:
                    collected.clear()

                    collected.append(data)

                    total_frames = len(data) // 2

        # Check for a final result one more time.

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

    quiet_rounds = 0

    try:
        while total_frames < frames_needed:

            try:
                data = audio_queue.get(timeout=1.0)

            except queue.Empty:
                quiet_rounds += 1

                if quiet_rounds >= 3:
                    raise

                continue

            quiet_rounds = 0

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
