import os
import queue
import json
import array
import time

from collections import deque

import settings as settings_store

import noise_suppression

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

# Speech models, best first. The 0.22-lgraph
# generation is markedly more accurate in noisy
# rooms than the tiny 0.15 model (7.82 vs 9.85
# word error rate on the standard benchmark)
# while still small enough for an 8 GB laptop.
# The tiny model remains the automatic fallback
# if the better one is ever missing.

PREFERRED_MODELS = (
    "vosk-model-en-us-0.22-lgraph",
    "vosk-model-small-en-us-0.15",
)


def _choose_model_dir():
    # First available model from the preference
    # list, as an absolute path.

    for name in PREFERRED_MODELS:
        path = os.path.abspath(name)

        if os.path.isdir(path):
            return path

    return None

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

# All the ways the user might call him.
# Renamed to SHADOW (2026-09-24); "Shadow" is
# kept as a legacy alias. The misspellings
# are how the small speech model commonly
# hears each name in different voices.

WAKE_WORDS = (
    # SHADOW and the words the recognizer
    # reaches for when the name comes fast
    # or clipped. Only REAL model-vocabulary
    # words belong here - invented spellings
    # can never match.

    "shadow",
    "shadows",
    "shadowy",
    "shallow",
    "shade",

    # The old name, still honored end to
    # end - and its soundalikes stay as
    # safety nets in the legal vocabulary.

    "Shadow",
    "soya",
    "joya",
    "zoyla",

    "zoe",
    "zoey",
    "sonya",
    "sonia",
    "soy",
    "joy",
    "jo",
    "zoa",

    "hey shadow",
    "ok shadow",
    "yo shadow",
    "hey Shadow",
    "ok Shadow",
    "yo Shadow",
    "hey soya",
    "ok soya",
    "yo soya",
    "hey joya",
    "ok joya",
    "yo joya"
)

# Filler tokens that surround a real command:
# speech hesitations, address words, and the
# recognizer's unknown-token mark. TV chatter
# in the gap after his names tends to leave
# exactly these behind (2026-09-25: "the"
# once reached the brain as a command). Only
# leading and trailing fillers are dropped -
# words in the middle of a sentence are
# never touched ("what the time is it" must
# survive).

ADDRESS_WORDS = (
    "hey",
    "yo",
    "ok",
    "okay",
)

# Single tokens that are never a command on
# their own. Live-tuning lesson 2026-09-25:
# degraded speech keeps surfacing as one of
# these after the beep ("this", "the"), and
# the brain answered each with fluffy
# nothing. A REAL one-word command like
# "time" or "stop" is not in this list.

NOISE_SINGLE_WORDS = (
    "the",
    "a",
    "an",
    "this",
    "that",
    "these",
    "those",
    "it",
    "its",
    "and",
    "but",
    "or",
    "of",
    "to",
    "in",
    "on",
    "at",
    "is",
    "are",
    "was",
    "were",
    "i",
    "you",
    "he",
    "he",
    "we",
    "my",
    "your",
    "me",
    "uh",
    "um",
    "uhm",
    "erm",
    "eh",
    "hey",
    "ok",
    "okay",
    "yo",
    "so",
    "like",
    "[unk]",
)

FILLER_WORDS = (
    "the",
    "a",
    "an",
    "uh",
    "um",
    "uhm",
    "erm",
    "eh",
    "hey",
    "ok",
    "okay",
    "yo",
    "so",
    "like",
    "[unk]",
)

model = None

recognizer = None

# Wake-word-only recognizer: restricted to a
# tiny grammar of just his names. Vosk's full
# language model prefers common words, so a
# close-up "SHADOW" was winning as "the" or
# "excuse". With the grammar, the name is
# one of the ONLY legal outputs, so it wins
# every time. TV chatter can no longer
# confuse the match either.

WAKE_GRAMMAR = json.dumps(
    list(WAKE_WORDS) + ["[unk]"]
)

wake_recognizer = None

# Rolling buffer of the last few seconds of
# processed audio. One-breath support: the
# wake grammar only knows his names, so
# "SHADOW what time is it" arrives there as
# "Shadow [unk] [unk]". When he wakes, the
# buffer is re-heard with the FULL vocabulary
# to recover the real command words.

AUDIO_HISTORY_SECONDS = 6.0

audio_history = deque()

audio_history_samples = 0

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

# Loudest post-gain RMS seen in the current
# listening window. Diagnostic for the log:
# shows how loud sir's voice actually
# arrives at the recognizer.

window_peak_rms = 0.0

# When the room was last genuinely loud (any
# window). Live-tuning lesson 2026-09-25:
# sir's loud "HEY" and the grammar's "yo"
# sighting landed in DIFFERENT windows, so a
# per-window gate stood down mid-phrase. The
# rescue and net now accept "loud within the
# last 10 s" instead of only the current
# window peak.

last_loud_moment = 0.0

# Measured 2026-09-24: this laptop's SST
# microphone array delivers loud but garbled
# audio for the first ~12 seconds of every
# process that opens it, regardless of rate
# or channel count. After that window every
# capture is clean. SHADOW therefore warms
# his ears once per session, before the
# first real listen.

WARMUP_SECONDS = 12.0

warmup_done = False

# Name fragments that mark an EXTERNAL mic
# (USB webcam/speakerphone/headset) in the
# Windows device list. When one of these is
# present he prefers it over the built-in
# array: a desktop mic sits close to sir's
# mouth, which is exactly what the SST array
# could not do.

EXTERNAL_MIC_HINTS = (
    "usb",
    "yeti",
    "snowball",
    "snowball ice",
    "blue ",
    "logitech",
    "webcam",
    "conference",
    "speakerphone",
    "headset",
    "usb pnp",
    "digital microphone",
    "external",
)

# Devices whose names contain one of these are
# never picked as his ears.

MIC_BLACKLIST_HINTS = (
    "stereo mix",
    "loopback",
)


def _is_external_mic_name(name):
    lowered = (name or "").lower()

    # Bluetooth hands-free devices (headsets,
    # earbuds, soundbars) carry narrowband,
    # echo-prone audio - never auto-prefer
    # them. Sir can still pin one explicitly
    # with 'use microphone 29'.

    if "hands-free" in lowered:
        return False

    return any(
        hint in lowered
        for hint in EXTERNAL_MIC_HINTS
    )


def _device_matches_saved_name(
        device, saved_name):
    # The name is stored possibly truncated
    # (sounddevice limits names to 31 chars);
    # match either direction.

    if not saved_name:
        return False

    live_name = (device["name"] or "").strip()

    stored = saved_name.strip()

    return (
        live_name.startswith(stored)
        or stored.startswith(live_name)
    )


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

    usable = [
        (index, device)
        for index, device in devices
        if not any(
            hint in (device["name"] or "").lower()
            for hint in MIC_BLACKLIST_HINTS
        )
    ]

    # 1. An external mic, found by name.

    for index, device in usable:
        if _is_external_mic_name(
                device["name"]):
            return index, device["name"]

    # 2. A previously saved working device.

    saved_id = settings_store.get_setting(
        "mic_device_id"
    )

    saved_name = settings_store.get_setting(
        "mic_device_name"
    )

    if saved_id is not None:
        for index, device in usable:
            if index == saved_id:
                return index, device["name"]

    if saved_name:
        for index, device in usable:
            if _device_matches_saved_name(
                    device, saved_name):
                return index, device["name"]

    # 2. The Windows default input.

    try:
        default_id = sd.query_devices(
            kind="input"
        )["index"]

        for index, device in usable:
            if index == default_id:
                return index, device["name"]

    except Exception:
        pass

    # 4. A fully-named Realtek array device
    #    (the working twin on this laptop).

    for index, device in usable:
        if device["name"].strip() == (
            "Microphone Array (Realtek(R) Audio)"
        ):
            return index, device["name"]

    # 5. Anything else that can capture.

    for index, device in usable:
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
                f"[SHADOW EARS] Microphone opened: "
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


def warmup_microphone(force=False):
    # Eat the garbled warm-up window once per
    # session. If real speech is already being
    # recognized, the ears are fine and we
    # finish early. A REBUILT stream (after a
    # failure) must always re-warm: the new
    # stream enters the dead zone again.

    if warmup_done and not force:
        return

    if recognizer is None or audio_queue is None:
        return

    print(
        "[SHADOW EARS] Warming up the microphone "
        "(the array needs a few seconds to "
        "settle)..."
    )

    # The first seconds of warm-up are pure
    # room noise: capture them and teach the
    # noise suppressor what this room sounds
    # like when nobody speaks.

    noise_frames = []

    noise_samples_needed = 16000 * 3

    noise_samples_collected = 0

    deadline = time.time() + WARMUP_SECONDS

    while time.time() < deadline:

        try:
            data = audio_queue.get(timeout=0.5)

        except Exception:
            continue

        if (
            not noise_suppression.has_profile()
            and noise_samples_collected
            < noise_samples_needed
        ):
            import numpy as np_module

            samples = np_module.frombuffer(
                data,
                dtype=np_module.int16
            ).astype(np_module.float32)

            noise_frames.append(samples)

            noise_samples_collected += len(
                samples
            )

            if (
                noise_samples_collected
                >= noise_samples_needed
            ):
                noise_suppression.learn_from_noise(
                    noise_frames
                )

        try:
            if recognizer.AcceptWaveform(data):
                text = json.loads(
                    recognizer.Result()
                ).get("text", "")

                if text:
                    # Already hearing real speech.
                    break

        except Exception:
            continue

    # Drop everything collected during warm-up
    # so no garbage leaks into the first listen.

    flush_audio_queue()

    globals()["warmup_done"] = True

    print("[SHADOW EARS] Warm-up complete. Ears ready.")


def setup_stt():
    global model
    global recognizer
    global wake_recognizer
    global mic_stream
    global audio_queue
    global input_ready
    global input_channels
    global effective_down_factor

    if not VOSK_AVAILABLE:
        print(
            "[SHADOW EARS] vosk is not installed. "
            "Voice input is disabled."
        )
        return False

    if not SOUNDDEVICE_AVAILABLE:
        print(
            "[SHADOW EARS] sounddevice is not installed. "
            "Voice input is disabled."
        )
        return False

    # Reuse a healthy warm stream across
    # listens. Lesson from 2026-09-24 testing:
    # REOPENING the microphone puts this SST
    # array back into its garbled warm-up
    # window every time. A stream that stays
    # open becomes reliable once it has warmed
    # up. So keep the stream while it is alive,
    # and rebuild everything only after a
    # failure (self-healing).

    stream_alive = (
        mic_stream is not None
        and mic_stream.active
        and audio_queue is not None
        and model is not None
    )

    if stream_alive:

        # Ears already running: refresh only the
        # recognizer so no stale audio state
        # carries over between listens.

        recognizer = KaldiRecognizer(
            model,
            SAMPLE_RATE
        )

        return True

    # No healthy stream: build everything fresh.

    _reset_stream()

    model_path = _choose_model_dir()

    if model_path is None:
        print(
            "[SHADOW EARS] No speech model folder found. "
            f"Looked for: {', '.join(PREFERRED_MODELS)}"
        )
        return False

    try:
        # The heavy model loads once per session;
        # the recognizer is recreated every listen
        # so no stale audio state carries over.

        if model is None:
            print(
                "[SHADOW EARS] Loading speech model: "
                f"{os.path.basename(model_path)}..."
            )

            model = Model(model_path)

            # A fresh model invalidates the old
            # grammar recognizer.

            wake_recognizer = None

        recognizer = KaldiRecognizer(
            model,
            SAMPLE_RATE
        )

        device_id, device_name = _choose_input_device()

        if device_id is None:
            print(
                "[SHADOW EARS] No usable microphone found."
            )
            return False

        if not _open_stream(device_id):
            print(
                "[SHADOW EARS] Could not open "
                "microphone with any known format."
            )

            return False

        # Remember the working microphone by ID
        # AND NAME: the name survives USB devices
        # plugging in and reshuffling the indexes.

        settings_store.set_setting(
            "mic_device_id",
            device_id
        )

        settings_store.set_setting(
            "mic_device_name",
            device_name
        )

        input_ready = True

        print(
            f"[SHADOW EARS] Microphone ready: "
            f"{device_name} "
            f"(device {device_id})"
        )

        # Discard the garbled warm-up window so
        # the first command on THIS stream is
        # heard clearly. Always: even rebuilt
        # streams re-enter the dead zone.

        warmup_microphone(force=True)

        return True

    except Exception as error:
        print(f"[SHADOW EARS] Could not start microphone: {error}")
        mic_stream = None
        recognizer = None
        model = None
        input_ready = False
        return False


def list_input_devices_text():
    # One call, anywhere: what ears can he
    # reach right now, and which one he is
    # wearing. Used by 'shadow mic' in the
    # terminal and by voice routes.

    import sounddevice as sd

    try:
        current = sd.query_devices(
            kind="input"
        )["index"]

    except Exception:
        current = None

    saved_id = settings_store.get_setting(
        "mic_device_id"
    )

    lines = ["Microphones I can reach, sir:"]

    found_any = False

    for index, device in _list_input_devices():
        found_any = True

        marks = []

        if index == saved_id:
            marks.append("my current ear")

        if index == current:
            marks.append("Windows default")

        if _is_external_mic_name(
                device["name"]):
            marks.append("external")

        suffix = (
            "  <- " + ", ".join(marks)
            if marks
            else ""
        )

        lines.append(
            f"- [{index}] {device['name']}"
            f"{suffix}"
        )

    if not found_any:
        lines.append(
            "- (none found - is anything "
            "plugged in?)"
        )

    return "\n".join(lines)


def switch_mic_device(device_id=None):
    # Hot-swap his ears while he is running:
    # close the current stream, optionally pin
    # a specific device id, and let setup_stt()
    # reopen (which re-warms the mic itself).
    # device_id None = clear the pin and let
    # normal preference rules choose (external
    # mic wins if one is plugged in).

    global mic_stream
    global input_ready
    global recognizer

    if device_id is not None:
        devices = _list_input_devices()

        names = [
            device["name"]
            for index, device in devices
            if index == device_id
        ]

        if not names:
            return (
                f"Sir, there is no microphone "
                f"number {device_id} right now. "
                "Say 'list microphones' to see "
                "what I can reach."
            )

        settings_store.set_setting(
            "mic_device_id",
            device_id
        )

        settings_store.set_setting(
            "mic_device_name",
            names[0]
        )

    else:
        settings_store.set_setting(
            "mic_device_id",
            None
        )

        settings_store.set_setting(
            "mic_device_name",
            None
        )

    try:
        if mic_stream is not None:
            mic_stream.close()

    except Exception:
        pass

    mic_stream = None
    input_ready = False
    recognizer = None

    if setup_stt():
        # setup_stt persisted the actual choice;
        # report it from the live state.

        chosen = settings_store.get_setting(
            "mic_device_name"
        )

        return (
            "Ears switched, sir. I am now "
            f"listening through: {chosen}."
        )

    return (
        "I could not open that microphone, "
        "sir. My ears are set to pick the "
        "best device again on the next "
        "listen."
    )


def auto_switch_to_external_mic():
    # Called when sir plugs a new mic in:
    # if an external device is present and he
    # is NOT already on it, switch and report.
    # Returns the spoken result, or None when
    # there was nothing to do.

    devices = _list_input_devices()

    external = [
        (index, device["name"])
        for index, device in devices
        if _is_external_mic_name(
            device["name"])
    ]

    if not external:
        return None

    if settings_store.get_setting(
            "mic_device_id") in (
            index for index, name in external
    ):
        return None

    index, name = external[0]

    result = switch_mic_device(index)

    return (
        f"New ears detected - {name}. "
        + result
    )


def external_mic_present():
    # Returns (index, name) of the first
    # external microphone he can see right
    # now, or None when it is built-in ears
    # only.

    for index, device in (
            _list_input_devices()):

        if _is_external_mic_name(
                device["name"]):
            return index, device["name"]

    return None


def _remember_audio(chunk):
    # Keep the last few seconds of processed
    # audio for one-breath command recovery.
    # Called from the audio callback, so it
    # must be fast and never raise.

    global audio_history_samples

    try:
        audio_history.append(chunk)

        audio_history_samples += len(chunk) // 2

        max_samples = int(
            AUDIO_HISTORY_SECONDS * SAMPLE_RATE
        )

        while audio_history_samples > max_samples:
            dropped = audio_history.popleft()

            audio_history_samples -= (
                len(dropped) // 2
            )

    except Exception:
        pass


def audio_callback(indata, frames, time_info, status):
    # The mic delivers audio at INPUT_RATE
    # (usually clean mono from the driver).
    # Resample to SAMPLE_RATE for the recognizer
    # using linear interpolation, which smooths
    # instead of folding high frequencies down.

    if effective_down_factor == 1 and input_channels == 1:
        processed = noise_suppression.process_block(
            bytes(indata)
        )

        _remember_audio(processed)

        audio_queue.put(processed)
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

    # Noise suppression sits after resampling
    # and before auto-gain: subtract the room
    # first, then amplify what survives.

    out_bytes = np_module.clip(
        out,
        -32768,
        32767
    ).astype(np_module.int16).tobytes()

    processed = noise_suppression.process_block(
        out_bytes
    )

    out = np_module.frombuffer(
        processed,
        dtype=np_module.int16
    ).astype(np_module.float32)

    # Adaptive gain: adapt only on real audio,
    # never on silence, so room noise is not
    # amplified into fake words.

    global current_gain
    global window_peak_rms

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
        # gain up VERY quickly so the FIRST word
        # is recognized (a slow ramp was clipping
        # quiet openings down to noise), but come
        # back down gently so quiet speech stays
        # amplified.

        if wanted > current_gain:
            current_gain = (
                0.25 * current_gain + 0.75 * wanted
            )

        else:
            # Loud input: duck almost instantly.
            # 2026-09-25 lesson: a slow release
            # here amplified sir's close-up voice
            # into hard clipping, and clipped audio
            # decodes as [unk] instead of SHADOW.
            # Quiet-speech continuity is unaffected:
            # this branch only runs when the input
            # is genuinely loud (rms > target).

            current_gain = (
                0.2 * current_gain + 0.8 * wanted
            )

    # Per-block limiter: never let a loud block
    # through at full adaptive gain. Peaks in
    # speech reach ~4x the RMS, so anything
    # above ~9000 post-gain is heading into the
    # clip ceiling.

    block_gain = current_gain

    if rms * block_gain > 7500.0:
        block_gain = 7500.0 / rms

    if rms > window_peak_rms:
        window_peak_rms = rms

    # Loud is loud, in any window: remember the
    # moment so cross-window attempts still pass
    # the loudness gates.

    if rms > 2000.0:
        global last_loud_moment

        last_loud_moment = time.time()

    out = out * block_gain

    final_bytes = (
        np_module.clip(
            out,
            -32768,
            32767
        ).astype(np_module.int16).tobytes()
    )

    _remember_audio(final_bytes)

    audio_queue.put(final_bytes)


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


def listen_for_command(max_seconds=7, _retried=False):
    global mic_stream

    if not setup_stt():
        return ""

    # Drop anything the microphone captured
    # before this listen started, such as the
    # tail of SHADOW's own last sentence.

    flush_audio_queue()

    time.sleep(0.1)

    recognizer.Reset()

    # Measure time by the real clock. Counting
    # converted audio samples is unreliable: the
    # native multi-channel stream is mixed down,
    # so sample counts do not match real seconds.

    deadline = time.time() + max_seconds

    silent_rounds = 0

    got_audio = False

    # Collect EVERY finished fragment instead of
    # returning on the first one. 2026-09-25
    # lesson: vosk often finalizes a tiny false
    # start ("the") while sir is still mid-
    # sentence, and returning at that instant
    # threw away the rest of the command.

    heard_parts = []

    # After real speech ends, keep listening
    # this much longer: vosk needs a moment of
    # silence to finalize the tail of a
    # sentence, and quiet speakers trail off.

    grace_seconds = 2.0

    grace_deadline = None

    # Pre-set so the exception paths below can
    # never hit an unbound variable.

    spoken = ""

    try:
        while time.time() < deadline:

            # Grace timer runs on the wall clock,
            # independent of whether audio blocks
            # keep arriving (they always do: the
            # mic streams silence too).

            if (
                grace_deadline is not None
                and time.time() >= grace_deadline
            ):
                break

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

            got_audio = True

            silent_rounds = 0

            if recognizer.AcceptWaveform(data):

                final_part = json.loads(
                    recognizer.Result()
                ).get("text", "")

                if final_part:
                    print(
                        f"[SHADOW EARS] command part: "
                        f"{final_part}"
                    )

                    heard_parts.append(final_part)

                    # First real words: stretch the
                    # window so a slow command still
                    # fits, then arm the trailing
                    # grace timer. Every further
                    # fragment re-arms it.

                    if len(heard_parts) == 1:
                        deadline = max(
                            deadline,
                            time.time() + 10.0,
                        )

                    grace_deadline = (
                        time.time() + grace_seconds
                    )

        # Window done (or a natural pause after
        # speech): flush whatever was still in
        # the recognizer so a trailing phrase is
        # never lost.

        tail = json.loads(
            recognizer.FinalResult()
        ).get("text", "")

        if tail:
            print(f"[SHADOW EARS] command tail: {tail}")

            heard_parts.append(tail)

        spoken = " ".join(heard_parts).strip()

        if spoken and is_noise_command(spoken):
            # A lone function word ("this", "the")
            # after the beep is degraded speech,
            # not a command: treat it as silence so
            # the brain never answers fluff and the
            # chime tells sir to retry.

            print(
                "[SHADOW EARS] only noise heard; "
                "treating it as silence."
            )

            spoken = ""

        if spoken:
            return spoken

    except queue.Empty:
        print(
            "[SHADOW EARS] Microphone was quiet. "
            "Try speaking a bit louder."
        )

        _reset_stream()

    except Exception as error:
        print(f"[SHADOW EARS] Listening error: {error}")

        _reset_stream()

        if not _retried:
            return listen_for_command(
                max_seconds,
                _retried=True
            )

        return ""

    # Nothing heard on a healthy stream? Only
    # rebuild when the stream gave NO audio at
    # all. Audio without speech just means
    # sir stayed quiet; rebuilding a healthy
    # stream costs ~12 s of deaf warm-up.

    if not spoken and not _retried and not got_audio:
        print(
            "[SHADOW EARS] No audio at all; "
            "rebuilding the microphone..."
        )

        _reset_stream()

        return listen_for_command(
            max_seconds,
            _retried=True
        )

    if not spoken and not _retried:
        print(
            "[SHADOW EARS] Audio but no clear words; "
            "keeping the warm stream."
        )

    return spoken


def flush_audio_queue():
    # Drop everything the microphone already
    # heard. Used after SHADOW speaks so he
    # cannot wake himself up with his own
    # voice.

    # Also forget the one-breath history: him
    # own spoken sentences land in the buffer
    # too, and must never be re-heard as a
    # command.

    flush_audio_history()

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
    # Longest wake variants first so nothing
    # is left behind ("hey Shadow" -> "", not
    # "hey ...").

    if not text:
        return False, ""

    lowered = text.lower().strip()

    for wake in sorted(
        WAKE_WORDS,
        key=len,
        reverse=True
    ):
        if lowered.startswith(wake):
            rest = text[
                len(wake):
            ].strip(" ,.!?\t")

            # Fillers and [unk] marks do not count
            # as a command: an "empty" result sends
            # the caller to the beep flow instead
            # of feeding the brain garbage.

            rest = _clean_command(rest)

            if is_noise_command(rest):
                # Name confirmed, but what follows
                # is a lone function word (or
                # nothing): not a command. The
                # caller's beep flow takes over.

                return True, ""

            return True, rest

    return False, text


def flush_audio_history():
    # Forget the buffered audio. Used after
    # he speaks: his own voice must never
    # be re-heard as a one-breath command.

    global audio_history_samples

    audio_history.clear()

    audio_history_samples = 0


def _clean_command(text):
    # Drop leading and trailing filler tokens
    # so TV noise and hesitations around the
    # real command cannot masquerade as one.

    tokens = text.split()

    while tokens and (
        tokens[0].lower() in FILLER_WORDS
    ):
        tokens.pop(0)

    while tokens and (
        tokens[-1].lower() in FILLER_WORDS
    ):
        tokens.pop()

    return " ".join(tokens)


def _is_bare_address(lowered_text):
    # True when the text is ONLY address words
    # and unknown-token marks: "hey", "yo hey",
    # "[unk] hey", "ok [unk]". Live-tuning
    # lesson 2026-09-25: when sir's name
    # syllables arrive degraded (distance, TV),
    # the grammar emits exactly these - the
    # address word with the name lost. That is
    # still an attempt and must wake him.

    tokens = lowered_text.split()

    if not tokens or len(tokens) > 4:
        return False

    return all(
        token in ADDRESS_WORDS or token == "[unk]"
        for token in tokens
    )


def is_noise_command(text):
    # True when the heard text cannot be a
    # real command: pure fillers ("the") or a
    # single function word ("this"). Multi-
    # word phrases always pass - "what time
    # is it" contains "is" and survives.

    if not text:
        return True

    tokens = _clean_command(text).split()

    if not tokens:
        return True

    return (
        len(tokens) == 1
        and tokens[0] in NOISE_SINGLE_WORDS
    )


def _rehear_history(seconds=4.0):
    # One-breath recovery: re-hear the last
    # few seconds of buffered audio with the
    # FULL vocabulary (no grammar). The wake
    # grammar only knows his names, so the
    # command in "SHADOW what time is it"
    # arrives there as "[unk]" - this pass
    # hears the real words. Returns
    # (name_found, command).

    # seconds: how much audio to decode. The
    # one-breath path uses 4 s (the name is
    # already found; only the words after it
    # matter). The second-chance net uses the
    # full 6 s buffer: the name often sits at
    # the leading edge, and the fresh
    # recognizer's ivector adaptation needs
    # lead-in context before it decodes the
    # first word correctly (live-tuning
    # lesson 2026-09-25: 4 s net probes kept
    # reading "the" for real attempts).

    if model is None or not audio_history:
        return False, ""

    allowed = int(seconds * SAMPLE_RATE)

    chunks = []

    taken = 0

    for chunk in reversed(audio_history):

        if taken >= allowed:
            break

        chunks.append(chunk)

        taken += len(chunk) // 2

    chunks.reverse()

    if not chunks:
        return False, ""

    # DEBUG EVIDENCE: dump the exact audio the
    # re-hear pass receives, so a garbled
    # decode can be listened to afterwards.
    # Opt-in only (set SHADOW_DEBUG_PROBE=1):
    # rewriting a WAV on every probe meant
    # disk churn on every wake word for a
    # diagnosis that is already closed.

    if os.environ.get("SHADOW_DEBUG_PROBE"):

        try:
            import wave as wave_module

            with wave_module.open(
                "shadow_probe.wav",
                "wb",
            ) as wav_file:
                wav_file.setnchannels(1)

                wav_file.setsampwidth(2)

                wav_file.setframerate(
                    SAMPLE_RATE
                )

                wav_file.writeframes(
                    b"".join(chunks)
                )

        except Exception:
            pass

    rehear_recognizer = KaldiRecognizer(
        model,
        SAMPLE_RATE,
    )

    rehear_text = ""

    for chunk in chunks:

        try:
            if rehear_recognizer.AcceptWaveform(
                chunk
            ):
                piece = json.loads(
                    rehear_recognizer.Result()
                ).get("text", "")

                if piece:
                    rehear_text = (
                        rehear_text + " " + piece
                    ).strip()

        except Exception:

            continue

    try:
        tail = json.loads(
            rehear_recognizer.FinalResult()
        ).get("text", "")

    except Exception:

        tail = ""

    if tail:
        rehear_text = (
            rehear_text + " " + tail
        ).strip()

    if not rehear_text:
        return False, ""

    print(
        "[SHADOW EARS] full-vocab re-hear: "
        f"{rehear_text}"
    )

    lowered = rehear_text.lower()

    for wake in sorted(
        WAKE_WORDS,
        key=len,
        reverse=True,
    ):
        position = lowered.find(wake)

        if position == -1:
            continue

        # Fillers around the command (TV chatter
        # in the gap after his names, hesitations)
        # are stripped so "the" or "[unk]" can
        # never reach the brain as a command.
        # Empty result = name only: the caller
        # falls back to the beep.

        command = _clean_command(
            rehear_text[
                position + len(wake):
            ].strip(" ,.!?\t")
        )

        return True, command

    # The name garbled differently in this
    # pass: no reliable command to extract.

    return False, ""


def listen_for_wake_word(max_seconds=30, _retried=False):
    # Listen continuously. Return as soon as the
    # wake word is heard: (True, command_after_wake)
    # or (False, "") if nothing was heard.

    # Uses the GRAMMAR recognizer: it can only
    # hear his names, so the name always wins
    # over common words.

    global mic_stream
    global wake_recognizer

    if not setup_stt():
        return False, ""

    if wake_recognizer is None and model is not None:
        wake_recognizer = KaldiRecognizer(
            model,
            SAMPLE_RATE,
            WAKE_GRAMMAR,
        )

    flush_audio_queue()

    if wake_recognizer is not None:
        wake_recognizer.Reset()

    # Same wall-clock rule as listen_for_command:
    # the budget must mean real seconds.

    deadline = time.time() + max_seconds

    silent_rounds = 0

    last_partial = ""

    # Any audio at all this window means the
    # stream is alive. Lesson from 2026-09-25:
    # rebuilding a HEALTHY stream costs ~12 s
    # of deaf warm-up, so he used to miss the
    # wake word one time in three. Rebuild only
    # when the stream gave us nothing.

    got_audio = False

    # ONE-BREATH protocol: when the grammar
    # catches his names, do NOT return at once.
    # The command after the name shows up here
    # only as [unk] (the grammar knows names
    # only), so he waits for the phrase to
    # end, then re-hears the buffered audio
    # with the FULL vocabulary to recover the
    # real command words.

    one_breath_deadline = None

    # SECOND-CHANCE NET cadence: probe the
    # buffer every 5 s during the window when
    # loud audio appeared. The buffer holds
    # 6 s, so a 5 s cadence guarantees every
    # attempt is still inside the buffer for
    # at least one probe - an attempt at
    # second 5 of 30 used to be unrecoverable
    # (window-end probe only saw the last 4 s).

    next_net_check = time.time() + 5.0

    # Declared up top: the mid-window probe
    # reads this, and the end-of-window block
    # assigns it. Python forbids a use before
    # the global statement in the same scope.

    global window_peak_rms

    try:
        while time.time() < deadline:

            remaining = deadline - time.time()

            wait = max(0.05, min(1.0, remaining))

            # One-breath quiet timer: once him
            # name was heard, 1.5 s of room noise
            # (re-armed by every new grammar event)
            # means the phrase is over - commit
            # and recover the command.

            if (
                one_breath_deadline is not None
                and time.time() >= one_breath_deadline
            ):
                _, command = _rehear_history()

                if is_noise_command(command):
                    return True, ""

                return True, command

            try:
                data = audio_queue.get(timeout=wait)

            except queue.Empty:
                silent_rounds += 1

                if silent_rounds >= 5:
                    # Nothing at all for ~5 seconds:
                    # the stream is probably dead.

                    raise

                continue

            got_audio = True

            silent_rounds = 0

            # Mid-window net probe: the grammar
            # heard nothing yet (no one-breath
            # armed) but the room got loud - re-
            # hear the recent buffer with the
            # full vocabulary and look for the
            # name there.

            if (
                one_breath_deadline is None
                and time.time() >= next_net_check
                and (
                    time.time() - last_loud_moment
                    < 10.0
                )
            ):
                next_net_check = (
                    time.time() + 5.0
                )

                name_found, command = _rehear_history(
                    seconds=6.0
                )

                if name_found:
                    print(
                        "[SHADOW EARS] wake word recovered "
                        "by the second-chance net."
                    )

                    if is_noise_command(command):
                        return True, ""

                    return True, command

            if wake_recognizer is None:
                continue

            if wake_recognizer.AcceptWaveform(data):

                text = json.loads(
                    wake_recognizer.Result()
                ).get("text", "")

                if not text:
                    continue

                # Show finished phrases as well, so
                # the log reveals exactly what the
                # recognizer guesses for the wake
                # word (sir says SHADOW, the model
                # may write something else).

                print(f"[SHADOW EARS] final: {text}")

                found, rest = strip_wake_word(text)

                if found:
                    # Arm the one-breath quiet timer
                    # instead of firing immediately:
                    # real words may follow the name.

                    one_breath_deadline = (
                        time.time() + 1.5
                    )

                    continue

            else:
                # NEW: also check the partial (in-
                # progress) phrase. Short commands in
                # a noisy room often never produce a
                # final result, but the wake word is
                # usually already visible in the
                # partial text. Checking it makes the
                # wake trigger much more responsive.

                try:
                    partial = json.loads(
                        wake_recognizer.PartialResult()
                    ).get("partial", "")

                except Exception:
                    continue

                if not partial:
                    continue

                # Show what the ears receive so a
                # silent failure (no audio at all)
                # can be told apart from a missed
                # wake word (audio recognized, but
                # never matching "Shadow").

                if partial != last_partial:
                    print(f"[SHADOW EARS] heard: {partial}")

                    last_partial = partial

                lowered_partial = partial.lower()

                for wake in WAKE_WORDS:
                    position = lowered_partial.find(wake)

                    if position == -1:
                        continue

                    # Name seen mid-phrase: (re)arm
                    # the quiet timer and let the
                    # phrase finish before the
                    # full-vocabulary re-hear.

                    one_breath_deadline = (
                        time.time() + 1.5
                    )

                    break

                # Bare-address rescue: the grammar
                # heard "hey"/"yo"/"ok" (+ maybe
                # [unk]) but no name. With a genuinely
                # loud source that is sir starting a
                # phrase - the name got clipped. Treat
                # it as an attempt. TV chatter says
                # these words too but much quieter
                # (~700-1400 RMS vs 2000+ up close),
                # so the loudness gate keeps the TV
                # from waking him.

                if (
                    one_breath_deadline is None
                    and (
                        time.time() - last_loud_moment
                        < 10.0
                    )
                    and _is_bare_address(lowered_partial)
                ):
                    print(
                        "[SHADOW EARS] address without a "
                        "clear name - assuming sir, "
                        "waiting for the command."
                    )

                    one_breath_deadline = (
                        time.time() + 1.5
                    )

        # Time window ended: report how loud
        # the room was, so a silent failure and
        # a quiet voice look different in the
        # log.

        # Capture BEFORE the reset: the
        # second-chance net below needs the
        # real peak, and an earlier version
        # reset first - so the net could never
        # fire (live-tuning lesson 2026-09-25:
        # an 8068-loudness attempt sailed
        # through a dead net).

        window_peak = window_peak_rms

        print(
            "[SHADOW EARS] window loudness: "
            f"{int(window_peak)}"
        )

        window_peak_rms = 0.0

        # Window over with a one-breath still
        # armed: recover the command before
        # giving up.

        if one_breath_deadline is not None:
            _, command = _rehear_history()

            if is_noise_command(command):
                return True, ""

            return True, command

        if wake_recognizer is None:
            return False, ""

        text = json.loads(
            wake_recognizer.Result()
        ).get("text", "")

        found, rest = strip_wake_word(text)

        if found:
            return True, rest

        # SECOND-CHANCE NET: loud audio but the
        # grammar matched nothing at all. 2026-09-25:
        # a fast loud "SHADOW what time is it" can
        # decode to nothing in the name-only
        # grammar. Re-hear the buffer with the
        # full vocabulary and look for the name
        # there instead.

        if got_audio and window_peak > 1500.0:
            name_found, command = _rehear_history(
                seconds=6.0
            )

            if name_found:
                print(
                    "[SHADOW EARS] wake word recovered "
                    "by the second-chance net."
                )

                if is_noise_command(command):
                    return True, ""

                return True, command

        # Nothing heard at all? Rebuild the
        # microphone ONLY if the stream was
        # truly silent (no audio blocks at all).
        # A window with audio but no wake word
        # just means sir did not say it yet:
        # the healthy stream is reused instantly
        # on the next listen.

        if not got_audio and not _retried:
            print(
                "[SHADOW EARS] No audio at all; "
                "rebuilding the microphone..."
            )

            _reset_stream()

            return listen_for_wake_word(
                max_seconds,
                _retried=True
            )

        return False, ""

    except queue.Empty:
        print(
            "[SHADOW EARS] Microphone was quiet. "
            "Try speaking a bit louder."
        )

        wake_recognizer = None

        _reset_stream()

        if not _retried:
            return listen_for_wake_word(
                max_seconds,
                _retried=True
            )

        return False, ""

    except Exception as error:
        print(f"[SHADOW EARS] Listening error: {error}")

        wake_recognizer = None

        _reset_stream()

        if not _retried:
            return listen_for_wake_word(
                max_seconds,
                _retried=True
            )

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
    print("SHADOW WAKE WORD TEST")
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
