import time
import json
import queue as q

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
    print("=== RATE MATRIX SWEEP ===")
    print(f"{len(CONFIGS)} configs x {SEGMENT_SECONDS:.0f}s = "
          f"about {len(CONFIGS) * SEGMENT_SECONDS + 10:.0f} seconds")
    print()
    print("Starting in 5 seconds...")
    time.sleep(5)
    print()
    print('>>> COUNT NON-STOP: "one two three four five six..." <<<')
    print(">>> LOUD, CLOSE, until you see DONE - do not pause! <<<")
    print()

    results = []

    for i, (device_id, rate, channels) in enumerate(CONFIGS):
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
