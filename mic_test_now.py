import time
import json
import queue as q
import sys

import numpy as np
import sounddevice as sd
from vosk import Model, KaldiRecognizer

MODEL = "vosk-model-small-en-us-0.15"

model = Model(MODEL)

NUMBER_WORDS = (
    "one", "two", "three", "four", "five",
    "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen",
    "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen", "twenty", "thirty", "forty", "fifty"
)

SEGMENT_SECONDS = 4.0

# ---------------- DISTANCE STUDY ----------------
#
# The 2026-09-25 diagnosis showed the SST
# array decodes fine up close but falls
# apart at chief's normal seat. This study
# maps HOW her pickup really falls with
# distance, so we know exactly how far her
# ears reach and when an external mic
# becomes mandatory.
#
#   python mic_test_now.py distance
#
# Run it with Shadow STOPPED - she holds the
# microphone exclusively and a live test
# would find the device already in use.

DISTANCES = (
    (0.3, "30 cm (leaning at the hinge)"),
    (0.6, "60 cm (right in front of her)"),
    (1.0, "1 m (edge of the desk)"),
    (1.5, "1.5 m (normal chair distance)"),
    (2.5, "2.5 m (across the room)"),
)

SPEAK_SECONDS = 5.0

NOISE_SECONDS = 2.0

SPEAK_LINE = "Shadow, what time is it"


# Verdict bands, calibrated against her
# live gates: RMS 2000 is where she calls
# the room "loud", 3000 is her auto-gain
# target for comfortable speech.

def classify_distance(speech_rms, noise_rms, words):
    import math

    snr = 20.0 * math.log10(
        speech_rms / max(noise_rms, 1.0)
    )

    if speech_rms < 300 or snr < 4:
        return snr, "DEAD ZONE"

    if snr >= 15 and words >= 2:
        return snr, "COMFORT ZONE"

    if snr >= 8:
        return snr, "USABLE"

    return snr, "STRAIN ZONE"


def _capture_seconds(
        device_id, rate, channels, seconds):
    # Record `seconds` of audio and return
    # (raw_bytes, overall_rms). Overall RMS
    # across the WHOLE capture - one number
    # per sample, comparable between runs.

    import numpy as np

    audio_q = q.Queue()

    def cb(indata, frames, time_info, status):
        audio_q.put(bytes(indata))

    try:
        stream = sd.RawInputStream(
            samplerate=rate,
            blocksize=8000,
            dtype="int16",
            channels=channels,
            device=device_id,
            callback=cb,
        )

        stream.start()

    except Exception:
        return None, 0

    collected = []

    t0 = time.time()

    while time.time() - t0 < seconds:
        try:
            collected.append(
                audio_q.get(timeout=0.3)
            )

        except q.Empty:
            continue

    try:
        stream.stop()
        stream.close()

    except Exception:
        pass

    raw = b"".join(collected)

    if not raw:
        return None, 0

    samples = np.frombuffer(
        raw, dtype=np.int16
    ).astype(np.float32)

    rms = float(
        np.sqrt(np.mean(samples ** 2))
    )

    return raw, rms


def _pick_study_device():
    # Choose her most likely ear: known-good
    # device indexes on this laptop first,
    # then the Windows default. The winner
    # must actually open mono @ 48 kHz.

    import sounddevice as sd

    candidates = [1, 9, 5, 11]

    try:
        candidates.append(
            sd.query_devices(
                kind="input"
            )["index"]
        )

    except Exception:
        pass

    seen = set()

    for device_id in candidates:
        if device_id in seen:
            continue

        seen.add(device_id)

        raw, rms = _capture_seconds(
            device_id, 48000, 1, 0.5
        )

        if raw is not None:
            return device_id

    return None


def run_distance_study():
    print("=== RMS vs DISTANCE STUDY ===")
    print()

    device_id = _pick_study_device()

    if device_id is None:
        print("No microphone could be opened.")
        print("Stop Shadow first, then retry.")
        return

    name = sd.query_devices(
        device_id
    )["name"]

    print(f"Testing ear: device {device_id}")
    print(f"  {name}")
    print()
    print("Speak the line LOUD and CLEAR,")
    print('like a wake-word command:')
    print(f'  "{SPEAK_LINE}"')
    print("- repeat it until the capture ends.")
    print()

    rows = []

    for metres, label in DISTANCES:
        print("-" * 55)
        print(f"Distance: {label}")

        input(
            "  Sit at this distance, then "
            "press Enter..."
        )

        print(
            f"  Stay SILENT for "
            f"{NOISE_SECONDS:.0f}s"
            " (measuring room noise)..."
        )

        time.sleep(1.0)

        noise_raw, noise_rms = (
            _capture_seconds(
                device_id, 48000, 1,
                NOISE_SECONDS,
            )
        )

        print(
            f"  Now SPEAK for "
            f"{SPEAK_SECONDS:.0f}s: "
            f'"{SPEAK_LINE}"'
        )

        speech_raw, speech_rms = (
            _capture_seconds(
                device_id, 48000, 1,
                SPEAK_SECONDS,
            )
        )

        if speech_raw is None:
            print("  (capture failed)")

            rows.append(
                (metres, label, 0, noise_rms,
                 0.0, 0, "FAILED")
            )

            continue

        text = transcribe(speech_raw, 48000)

        words = score_text(text)

        snr, verdict = classify_distance(
            speech_rms, noise_rms, words
        )

        print(
            f"  speech RMS {speech_rms:.0f} | "
            f"noise RMS {noise_rms:.0f} | "
            f"SNR {snr:.1f} dB"
        )

        print(f'  heard: "{text}"')

        print(f"  VERDICT: {verdict}")

        rows.append(
            (metres, label, speech_rms,
             noise_rms, snr, words, verdict)
        )

    print()
    print("=" * 55)
    print("SUMMARY - her real pickup map")
    print("=" * 55)
    print(
        f"{'distance':<28}{'speech':>7}{'noise':>7}"
        f"{'SNR dB':>8}{'words':>6}  verdict"
    )

    for metres, label, speech_rms, noise_rms, snr, words, verdict in rows:
        short = label.split(" (")[0]

        print(
            f"{short:<28}{speech_rms:>7.0f}"
            f"{noise_rms:>7.0f}{snr:>8.1f}"
            f"{words:>6}  {verdict}"
        )

    print()

    comfort = [
        metres for metres, label, speech_rms,
        noise_rms, snr, words, verdict in rows
        if verdict == "COMFORT ZONE"
    ]

    any_usable = [
        metres for metres, label, speech_rms,
        noise_rms, snr, words, verdict in rows
        if verdict in ("COMFORT ZONE", "USABLE")
    ]

    loudest_noise = max(
        (row[3] for row in rows), default=0
    )

    if loudest_noise > 1500:
        print(
            f"Note: room noise hit RMS "
            f"{loudest_noise:.0f} - that is loud "
            "even for her. Retest somewhere "
            "quieter if results look odd."
        )

        print()

    if comfort:
        print(
            f"Her ears are COMFORTABLE up to "
            f"{max(comfort):.1f} m. Sit inside "
            "that and she hears you."
        )

    elif any_usable:
        print(
            "No true comfort zone - at best she "
            f"manages {max(any_usable):.1f} m, "
            "with missed words likely. An "
            "external mic is recommended."
        )

    else:
        print(
            "She could not reliably hear you at "
            "ANY distance today. The built-in "
            "array has hit its physical limit - "
            "an external mic is now mandatory."
        )

    print()
    print(
        "Wire the winner in with 'Shadow mic' - "
        "she pins the best device by name and "
        "re-tests automatically on boot."
    )

# Every plausible native format for the SST array
# twins, across both candidate devices.

CONFIGS = (
    (9, 48000, 1),
    (9, 44100, 1),
    (9, 16000, 1),
    (9, 96000, 1),
    (9, 48000, 2),
    (1, 48000, 1),
    (1, 44100, 1),
    (1, 16000, 1),
)


def resample_to_16k(x, input_rate):
    if input_rate == 16000:
        return x

    ratio = input_rate / 16000.0
    new_len = int(len(x) / ratio)
    pos = np.arange(new_len) * ratio

    low = np.clip(pos.astype(int), 0, len(x) - 1)
    frac = pos - low
    high = np.clip(low + 1, 0, len(x) - 1)

    return x[low] * (1.0 - frac) + x[high] * frac


def transcribe(raw, input_rate):
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)

    if len(x) < input_rate // 2:
        return ""

    y = resample_to_16k(x, input_rate)
    y = np.clip(y, -32768, 32767).astype(np.int16)

    rec = KaldiRecognizer(model, 16000)
    rec.AcceptWaveform(y.tobytes())

    return json.loads(rec.FinalResult()).get("text", "")


def capture(device_id, rate, channels):
    audio_q = q.Queue()

    def cb(indata, frames, time_info, status):
        audio_q.put(bytes(indata))

    try:
        stream = sd.RawInputStream(
            samplerate=rate,
            blocksize=8000,
            dtype="int16",
            channels=channels,
            device=device_id,
            callback=cb,
        )
        stream.start()

    except Exception:
        return None, 0

    collected = []
    peak = 0
    t0 = time.time()

    while time.time() - t0 < SEGMENT_SECONDS:
        try:
            data = audio_q.get(timeout=0.3)
        except q.Empty:
            continue

        collected.append(data)
        samples = np.frombuffer(
            data, dtype=np.int16
        ).astype(np.float32)

        rms = float(np.sqrt(np.mean(samples ** 2)))
        peak = max(peak, int(rms))

    try:
        stream.stop()
        stream.close()
    except Exception:
        pass

    return b"".join(collected), peak


def score_text(text):
    words = text.lower().split()
    return sum(1 for w in words if w in NUMBER_WORDS)


def main():
    mode = (
        sys.argv[1].lower()
        if len(sys.argv) > 1
        else ""
    )

    if mode == "distance":
        run_distance_study()

        return

    if mode:
        print(f"Unknown mode: {mode}")
        print("Usage:")
        print("  python mic_test_now.py")
        print("      rate-matrix sweep (default)")
        print("  python mic_test_now.py distance")
        print("      RMS vs distance pickup study")
        print()
        print("Stop Shadow first - she holds the mic.")
        return

    # Default: the rate-matrix sweep. Auto-pick
    # the device (the winner must open mono @
    # 48 kHz) instead of trusting hardcoded
    # indexes that reshuffle when USB gear
    # comes and goes.

    print("=== RATE MATRIX SWEEP ===")

    device_id = _pick_study_device()

    if device_id is None:
        print("No microphone could be opened.")
        print("Stop Shadow first, then retry.")
        return

    name = sd.query_devices(device_id)["name"]

    print(f"Testing ear: device {device_id}")
    print(f"  {name}")

    # One (rate, channels) matrix, applied to
    # whichever device won - duplicates from
    # the old twin list collapse away.

    seen = set()

    configs = []

    for _, rate, channels in CONFIGS:
        key = (rate, channels)

        if key in seen:
            continue

        seen.add(key)

        configs.append(
            (device_id, rate, channels)
        )

    print(f"{len(configs)} configs x {SEGMENT_SECONDS:.0f}s = "
          f"about {len(configs) * SEGMENT_SECONDS + 10:.0f} seconds")
    print()
    print("Starting in 5 seconds...")
    time.sleep(5)
    print()
    print('>>> COUNT NON-STOP: "one two three four five six..." <<<')
    print(">>> LOUD, CLOSE, until you see DONE - do not pause! <<<")
    print()

    results = []

    for i, (dev_id, rate, channels) in enumerate(configs):
        label = (f"dev {device_id} @ {rate}Hz "
                 f"{channels}ch")

        raw, peak = capture(device_id, rate, channels)

        if raw is None:
            print(f"  [{i + 1}/{len(CONFIGS)}] {label}: "
                  "(cannot open)")
            results.append((device_id, rate, channels, 0, "", 0))
            continue

        text = transcribe(raw, rate)
        words = score_text(text)

        print(f"  [{i + 1}/{len(CONFIGS)}] {label}: "
              f'"{text}"  (words={words}, peak={peak})')

        results.append(
            (device_id, rate, channels, words, text, peak)
        )

    print()
    print("DONE COUNTING - thank you, baa!")
    print()
    print("=== RESULTS ===")

    best = max(results, key=lambda r: r[3])

    for device_id, rate, channels, words, text, peak in results:
        marker = "  <-- HEARD YOU" if words >= 2 else ""
        print(f"  dev {device_id} @ {rate}Hz {channels}ch: "
              f"{words} words, peak {peak}{marker}")

    print()
    if best[3] >= 2:
        print(f"WINNER: dev {best[0]} @ {best[1]}Hz "
              f"{best[2]}ch")
        print(f'heard: "{best[4]}"')
    else:
        print("No config heard you today. That means the")
        print("mic enhancement layer changed on Windows.")
        print("Next fix must be in Windows Sound settings.")


if __name__ == "__main__":
    main()
