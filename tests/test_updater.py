import json
import os
import shutil
import sys

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
)

import updater

# The state file is real, so every test
# works on a scratch copy and restores it
# afterwards - the running Shadow must
# never notice.

STATE_BACKUP = updater.STATE_FILE + ".testbak"


def setup():
    shutil.copy(
        updater.STATE_FILE, STATE_BACKUP
    )


def teardown():
    if os.path.exists(STATE_BACKUP):
        shutil.copy(
            STATE_BACKUP, updater.STATE_FILE
        )

        os.remove(STATE_BACKUP)


def fake_check(return_value):
    updater.check_for_updates = (
        lambda: return_value
    )


def test_subjects_cleaned():
    raw = [
        "feat: Add weather support.",
        "Add weather support.",
        "  ",
        "fix: Add weather support",
    ]

    cleaned = updater._clean_subjects(raw)

    assert cleaned == [
        "Add weather support"
    ], cleaned


def test_boot_news_first_offer():
    updater._save_state(
        {"last_note": "updated"}
    )

    fake_check(
        (2, ["Feature A", "Feature B"])
    )

    behind, subjects = (
        updater.get_boot_update_news()
    )

    assert behind == 2 and subjects, (
        "first offer was silent"
    )

    state = updater._load_state()

    assert state["last_note"] == (
        "pending announcement"
    )


def test_boot_news_no_nag():
    # Same pile on the next boot: he must
    # stay quiet (the anti-nag promise).

    updater._save_state({
        "last_note": "pending announcement",
        "last_fingerprint": "2|Feature AFeature B",
    })

    fake_check(
        (2, ["Feature A", "Feature B"])
    )

    behind, subjects = (
        updater.get_boot_update_news()
    )

    assert behind == 0 and not subjects


def test_boot_news_rearm_on_new_commit():
    updater._save_state({
        "last_note": "pending announcement",
        "last_fingerprint": "2|Feature AFeature B",
    })

    fake_check(
        (3, ["Feature A", "Feature B",
             "Feature C"])
    )

    behind, _ = (
        updater.get_boot_update_news()
    )

    assert behind == 3, (
        "new commit did not re-arm the offer"
    )


def test_boot_news_clear_when_caught_up():
    updater._save_state({
        "last_note": "pending announcement",
        "last_fingerprint": "2|x",
    })

    fake_check((0, []))

    behind, _ = (
        updater.get_boot_update_news()
    )

    assert behind == 0

    state = updater._load_state()

    assert state["last_note"] != (
        "pending announcement"
    )


def test_pending_announcement_one_shot():
    updater._save_state({
        "last_subjects": ["Change One"],
        "announced": False,
    })

    first = (
        updater.get_pending_announcement()
    )

    second = (
        updater.get_pending_announcement()
    )

    assert first == ["Change One"]

    assert second == [], (
        "announcement repeated itself"
    )


def main():
    setup()

    tests = [
        test_subjects_cleaned,
        test_boot_news_first_offer,
        test_boot_news_no_nag,
        test_boot_news_rearm_on_new_commit,
        test_boot_news_clear_when_caught_up,
        test_pending_announcement_one_shot,
    ]

    failures = 0

    try:
        for test in tests:
            try:
                test()

                print(f"PASS {test.__name__}")

            except AssertionError as error:
                failures += 1

                print(
                    f"FAIL {test.__name__}: "
                    f"{error}"
                )

    finally:
        teardown()

    return failures


if __name__ == "__main__":
    raise SystemExit(main())
