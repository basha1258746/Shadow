import time

import numpy as np

import settings as settings_store

# ---------------- NOISE SUPPRESSION ----------------
#
# Spectral gating: learn what the room sounds
# like when nobody speaks (the warm-up window
# gives us exactly that), then shrink every
# bin that is not clearly above the noise.
# Quiet speech that sits just above the noise
# floor becomes far more visible to the
# speech model.
#
# Pipeline position: after rate conversion,
# before auto-gain. Enabled by default;
# toggle with 'noise on' / 'noise off'.

FFT_SIZE = 1024

HOP = 256

HANN = None

OLA_NORM = None

# Noise profile: mean + std of magnitude per
# FFT bin, learned from warm-up audio.

noise_mean = None

noise_std = None

# A tiny floor so bins are never fully
# zeroed: below the threshold a bin keeps
# this fraction of itself.

MIN_GAIN_FLOOR = 0.08

# How far above the learned noise (in noise
# std devs) a bin must sit to pass fully.

NOISE_SIGMA_FACTOR = 2.0

# Per-bin smoothing so the gate is not
# binary: fast-ish open, slow close.

SMOOTH_UP = 0.4

SMOOTH_DOWN = 0.1

gate_state = None

# Whether suppression is enabled. Setting:
# 'noise_enabled'. Cached briefly so the
# audio callback does not touch disk.

_enabled_cache = None

_cache_time = 0.0


def is_enabled():
    global _enabled_cache
    global _cache_time

    now = time.time()

    if now - _cache_time > 2.0:
        _enabled_cache = bool(
            settings_store.get_setting(
                "noise_enabled"
            )
        )

        _cache_time = now

    return _enabled_cache


def set_enabled(value):
    settings_store.set_setting(
        "noise_enabled",
        bool(value)
    )

    global _enabled_cache

    _enabled_cache = bool(value)

    _cache_time = time.time()


def _get_window():
    global HANN
    global OLA_NORM

    if HANN is None:
        HANN = np.hanning(FFT_SIZE)

        # Measure the overlap-add normalization
        # constant once: with this window and
        # hop, the squared-window sum is
        # constant in steady state.

        total = np.zeros(FFT_SIZE + HOP * 6)

        for start in range(
            0,
            len(total) - FFT_SIZE,
            HOP
        ):
            total[start:start + FFT_SIZE] += (
                HANN ** 2
            )

        OLA_NORM = float(
            np.median(
                total[HOP * 6: HOP * 6 + HOP]
            )
        )

        if OLA_NORM <= 0:
            OLA_NORM = 1.0

    return HANN


def learn_from_noise(frames):
    # Build the room-noise profile from captured
    # warm-up frames (float32 samples at 16 kHz).
    # Returns True on success.

    global noise_mean
    global noise_std
    global gate_state

    window = _get_window()

    mags = []

    for frame in frames:
        if len(frame) < FFT_SIZE:
            continue

        for start in range(
            0,
            len(frame) - FFT_SIZE,
            HOP
        ):
            spec = np.fft.rfft(
                frame[start:start + FFT_SIZE]
                * window
            )

            mags.append(np.abs(spec))

    if not mags:
        return False

    mags = np.array(mags)

    noise_mean = mags.mean(axis=0)

    noise_std = mags.std(axis=0) + 1e-6

    gate_state = None

    print(
        "[SHADOW EARS] Learned the room noise "
        f"profile ({len(mags)} frames)."
    )

    return True


def reset_profile():
    global noise_mean
    global noise_std
    global gate_state

    noise_mean = None
    noise_std = None
    gate_state = None


def has_profile():
    return noise_mean is not None


def process_block(data_bytes):
    # Per-block entry point for the audio
    # callback. Input: raw int16 bytes at 16 kHz
    # mono. Output: suppressed int16 bytes.
    # Passes through when disabled or unlearned.

    global gate_state

    if not is_enabled():
        return data_bytes

    if noise_mean is None:
        return data_bytes

    window = _get_window()

    samples = np.frombuffer(
        data_bytes,
        dtype=np.int16
    ).astype(np.float32)

    if len(samples) < FFT_SIZE:
        return data_bytes

    if gate_state is None:
        gate_state = np.ones(
            len(noise_mean)
        )

    out = np.zeros(
        len(samples),
        dtype=np.float32
    )

    for start in range(
        0,
        len(samples) - FFT_SIZE,
        HOP
    ):
        block = samples[start:start + FFT_SIZE]

        spec = np.fft.rfft(block * window)

        mag = np.abs(spec)

        # How many noise sigmas above the
        # learned floor is this bin?

        excess = (mag - noise_mean) / noise_std

        above = excess > NOISE_SIGMA_FACTOR

        target = np.where(
            above,
            1.0,
            MIN_GAIN_FLOOR
        )

        # Smooth the gate per bin over time.

        gate = np.where(
            target > gate_state,
            SMOOTH_UP * gate_state
            + (1 - SMOOTH_UP) * target,
            SMOOTH_DOWN * gate_state
            + (1 - SMOOTH_DOWN) * target,
        )

        gate_state = gate

        gated = spec * gate

        out[start:start + FFT_SIZE] += (
            np.fft.irfft(gated, n=FFT_SIZE)
        )

    out = out * (1.0 / OLA_NORM)

    out = np.clip(
        out,
        -32768,
        32767
    ).astype(np.int16)

    return out.tobytes()


if __name__ == "__main__":
    print("NOISE SUPPRESSION SELF TEST")

    _get_window()

    # Fake room noise: low-level white noise.
    rng = np.random.default_rng(7)

    frames = [
        (rng.standard_normal(16000) * 40).astype(
            np.float32
        )
        for _ in range(8)
    ]

    ok = learn_from_noise(frames)

    print("profile learned:", ok)

    test = (rng.standard_normal(4096) * 40).astype(
        np.int16
    )

    out = process_block(test.tobytes())

    out_samples = np.frombuffer(
        out, dtype=np.int16
    ).astype(np.float32)

    rms_in = float(np.sqrt(np.mean(test ** 2)))
    rms_out = float(
        np.sqrt(np.mean(out_samples ** 2))
    )

    print(f"noise RMS in: {rms_in:.0f}")
    print(f"noise RMS out: {rms_out:.0f}")
    print(
        "suppression works:",
        rms_out < rms_in * 0.6,
    )
