import os
import sys
from datetime import datetime, timedelta

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
)

import reminders

SCRATCH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "_scratch_reminders.json",
)


def fresh_store():
    reminders.REMINDERS_FILE = SCRATCH

    if os.path.exists(SCRATCH):
        os.remove(SCRATCH)

    reminders.load_reminders()


def test_in_minutes_parsing():
    parsed = reminders.parse_reminder(
        "in 20 minutes remind me to drink water"
    )

    assert parsed is not None, "leading form failed"

    assert parsed["task"] == "drink water"

    fire = datetime.strptime(
        parsed["fire_at"],
        "%Y-%m-%d %H:%M:%S",
    )

    delta = fire - datetime.now()

    assert 19 * 60 < delta.total_seconds() <= (
        21 * 60
    ), f"odd fire time: {delta}"


def test_trailing_in_parsing():
    parsed = reminders.parse_reminder(
        "remind me to stretch my legs in 5 min"
    )

    assert parsed is not None

    assert parsed["task"] == (
        "stretch my legs"
    )


def test_number_words():
    parsed = reminders.parse_reminder(
        "in ten minutes remind me to check the oven"
    )

    assert parsed is not None

    fire = datetime.strptime(
        parsed["fire_at"], "%Y-%m-%d %H:%M:%S"
    )

    delta = fire - datetime.now()

    assert 9 * 60 < delta.total_seconds() <= (
        11 * 60
    )


def test_clock_parsing_future():
    parsed = reminders.parse_reminder(
        "remind me to call home at 23:59"
    )

    assert parsed is not None

    fire = datetime.strptime(
        parsed["fire_at"], "%Y-%m-%d %H:%M:%S"
    )

    assert fire > datetime.now()


def test_daily_recurring():
    parsed = reminders.parse_reminder(
        "every day at 7 remind me to check my timetable"
    )

    assert parsed is not None, "daily form failed"

    assert parsed["recurring"]["kind"] == "daily"

    assert parsed["hours"] == 7


def test_every_hour_recurring():
    parsed = reminders.parse_reminder(
        "every hour remind me to drink water"
    )

    assert parsed is not None

    assert parsed["recurring"]["kind"] == "hours"


def test_bare_refusal():
    # No time given: he must refuse honestly,
    # not invent one.

    assert reminders.parse_reminder(
        "remind me to drink water"
    ) is None

    assert reminders.parse_reminder(
        "what a lovely day"
    ) is None


def test_store_persists():
    fresh_store()

    parsed = reminders.parse_reminder(
        "in 30 minutes remind me to flip the pages"
    )

    reminders.add_reminder(parsed)

    # Simulate restart.

    reminders.load_reminders()

    tasks = [
        r["task"] for r in (
            reminders._reminders)
    ]

    assert (
        "flip the pages" in tasks
    ), "reminder lost on restart"


def test_recurring_reschedules():
    fresh_store()

    parsed = reminders.parse_reminder(
        "every hour remind me to drink water"
    )

    reminders.add_reminder(parsed)

    reminders._check_and_fire()

    # A recurring reminder must still exist,
    # rescheduled into the future - not be
    # consumed like a one-shot.

    tasks = [
        r["task"] for r in (
            reminders._reminders)
    ]

    assert "drink water" in tasks

    fire = datetime.strptime(
        reminders._reminders[0]["fire_at"],
        "%Y-%m-%d %H:%M:%S",
    )

    assert fire > datetime.now()


def test_one_shot_fires_and_vanishes():
    fresh_store()

    fired = []

    reminders._fire_callback = (
        lambda task, reminder: fired.append(task)
    )

    past = (
        datetime.now() - timedelta(seconds=10)
    ).strftime("%Y-%m-%d %H:%M:%S")

    reminders.add_reminder({
        "id": 1,
        "task": "the oven",
        "fire_at": past,
        "created": past,
    })

    reminders._check_and_fire()

    assert fired == ["the oven"], fired

    assert reminders._reminders == []


def test_cancel():
    fresh_store()

    parsed = reminders.parse_reminder(
        "in 15 minutes remind me to walk the dog"
    )

    reminders.add_reminder(parsed)

    removed = reminders.cancel_reminder("dog")

    assert removed == 1

    assert reminders._reminders == []


def main():
    failures = 0

    try:
        for test in (
            test_in_minutes_parsing,
            test_trailing_in_parsing,
            test_number_words,
            test_clock_parsing_future,
            test_daily_recurring,
            test_every_hour_recurring,
            test_bare_refusal,
            test_store_persists,
            test_recurring_reschedules,
            test_one_shot_fires_and_vanishes,
            test_cancel,
        ):
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
        if os.path.exists(SCRATCH):
            os.remove(SCRATCH)

    return failures


if __name__ == "__main__":
    raise SystemExit(main())
