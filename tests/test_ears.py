import os
import sys

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
)

import voice_input


def test_wake_words_present():
    # He must answer to his name, his old
    # name, and the known soundalikes - the
    # 2026-09-24 distance failures taught us
    # every variant matters.

    required = (
        "Shadow", "Shadow", "zoe",
        "sonya", "joya", "jo",
    )

    for word in required:
        assert word in voice_input.WAKE_WORDS, (
            f"wake word lost: {word}"
        )


def test_wake_grammar_covers_words():
    # The one-breath commit path depends on
    # the wake grammar being exactly the
    # wake words plus the unknown token.

    grammar = json_grammar()

    for word in ("Shadow", "Shadow"):
        assert word in grammar, (
            f"grammar lost {word}"
        )

    assert "[unk]" in grammar


def json_grammar():
    grammar_text = voice_input.WAKE_GRAMMAR

    import json

    return json.loads(grammar_text)


def test_filler_strip():
    # Leading/trailing fillers go; the
    # middle survives ("what the time").

    assert (
        voice_input._clean_command(
            "the the"
        )
        == ""
    )

    assert (
        voice_input._clean_command(
            "the Shadow the"
        )
        == "Shadow"
    )

    assert voice_input._clean_command(
        "uh what the time is it um"
    ) == "what the time is it"


def test_noise_commands():
    assert voice_input.is_noise_command("")

    assert voice_input.is_noise_command(
        "the"
    )

    assert voice_input.is_noise_command(
        "[unk]"
    )

    # Real one-word commands pass.

    assert not (
        voice_input.is_noise_command(
            "time"
        )
    )

    assert not (
        voice_input.is_noise_command(
            "stop"
        )
    )


def test_bare_address_rescue():
    assert voice_input._is_bare_address(
        "hey"
    )

    assert voice_input._is_bare_address(
        "[unk] hey"
    )

    assert not voice_input._is_bare_address(
        "hey Shadow what time"
    )


def test_external_mic_name_matching():
    assert voice_input._is_external_mic_name(
        "Blue Snowball USB"
    )

    assert not (
        voice_input._is_external_mic_name(
            "Microphone Array (Realtek)"
        )
    )

    # Bluetooth hands-free gear must never
    # win auto-preference (narrowband,
    # echo-prone) - the 2026-09-27 lesson.

    assert not (
        voice_input._is_external_mic_name(
            "Headset Hands-Free (Redmi Buds 5)"
        )
    )


def main():
    tests = [
        test_wake_words_present,
        test_wake_grammar_covers_words,
        test_filler_strip,
        test_noise_commands,
        test_bare_address_rescue,
        test_external_mic_name_matching,
    ]

    failures = 0

    for test in tests:
        try:
            test()

            print(f"PASS {test.__name__}")

        except AssertionError as error:
            failures += 1

            print(f"FAIL {test.__name__}: {error}")

    return failures


if __name__ == "__main__":
    raise SystemExit(main())
