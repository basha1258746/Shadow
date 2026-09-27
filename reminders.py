import json
import os
import re
import threading
import time
from datetime import datetime, timedelta

# ---------------- Shadow REMINDERS ----------------
#
# Week two, option A phase one: he starts
# anticipating. Chief sets reminders by
# voice; a daemon thread checks them every
# 5 seconds and fires them through a
# callback Shadow.py provides (so the
# announcement goes out of his actual
# mouth, with all the speaking machinery).
#
# Store: reminders.json (gitignored),
# persistent across restarts - a reminder
# set tonight still fires tomorrow.

REMINDERS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "reminders.json",
)

CHECK_INTERVAL = 5

MAX_REMINDERS = 50

_reminders = []

_lock = threading.Lock()

_scheduler_started = False

_fire_callback = None

_routine_executor = None


def set_routine_executor(executor):
    # Registered by Shadow.py at boot: the
    # function that RUNS routine tasks
    # (briefing reads, reminder roundups).
    # Lives there because routines need his
    # voice, his briefing, his everything.

    global _routine_executor

    _routine_executor = executor


# ---------------- TIME PARSING ----------------

NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2,
    "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "fifteen": 15,
    "twenty": 20, "thirty": 30,
    "forty five": 45, "forty-five": 45,
    "sixty": 60, "ninety": 90,
}

WEEKDAYS = (
    "monday", "tuesday", "wednesday",
    "thursday", "friday", "saturday",
    "sunday",
)


def _parse_duration(text):
    # "20 minutes" / "2 hours" / "an hour and
    # a half" style. Returns seconds or None.

    text = text.strip().lower()

    match = re.match(
        r"^(\d+|one|two|three|four|five|six|"
        r"seven|eight|nine|ten|fifteen|twenty|"
        r"thirty|an|a)\s*"
        r"(minute|minutes|min|min|hour|hours|"
        r"hr|hrs|second|seconds|secs?)$",
        text,
    )

    if not match:
        return None

    amount_word = match.group(1)

    amount = NUMBER_WORDS.get(
        amount_word
    )

    if amount is None:
        try:
            amount = int(amount_word)

        except ValueError:
            return None

    unit = match.group(2)

    if unit.startswith("h"):
        return amount * 3600

    if unit.startswith("m"):
        return amount * 60

    return amount


def _parse_clock(text):
    # "at 7", "at 7:30", "at 19:45",
    # "at 7 pm" -> (hours, minutes) or None.

    text = text.strip().lower()

    match = re.match(
        r"^at\s+(\d{1,2})(?::(\d{2}))?\s*"
        r"(am|pm)?(?:\s+today)?$",
        text,
    )

    if not match:
        return None

    hours = int(match.group(1))

    minutes = int(match.group(2) or 0)

    meridiem = match.group(3)

    if meridiem == "pm" and hours < 12:
        hours += 12

    if meridiem == "am" and hours == 12:
        hours = 0

    if not (0 <= hours <= 23):
        return None

    return hours, minutes


def parse_reminder(text):
    # The front door: free text in, a
    # reminder dict out, or None when the
    # text is not a reminder he understands.
    #
    #   in 20 minutes remind me to X
    #   remind me to X in 20 minutes
    #   at 7 pm remind me to X
    #   remind me to X at 19:30
    #   every hour remind me to X
    #   every day at 7 remind me to X
    #   every monday at 9 remind me to X
    #   remind me to X

    lowered = text.strip().lower()

    recurring = None

    work = lowered

    every_match = re.match(
        r"^every\s+(\w+)\s+(.*)$", work
    )

    if every_match:
        unit = every_match.group(1)

        work = every_match.group(2).strip()

        if unit in ("hour", "hour,"):
            recurring = {"kind": "hours",
                         "every": 1}

        elif unit in ("day", "day,"):
            recurring = {"kind": "daily"}

        elif unit in WEEKDAYS:
            recurring = {
                "kind": "weekly",
                "weekday": WEEKDAYS.index(
                    unit
                ),
            }

        else:
            return None

    task = None

    when_seconds = None

    when_clock = None

    # "in N <unit> ..." (leading form).

    lead = re.match(
        r"^in\s+(.+?)\s+(remind me to|remind "
        r"me|remind)\s+(.+)$",
        work,
    )

    # "... remind me to X in N <unit>"
    # (trailing form).

    trail = re.search(
        r"\s+in\s+(\d+|one|two|three|four|five|"
        r"six|seven|eight|nine|ten|fifteen|"
        r"twenty|thirty)\s*"
        r"(minutes?|mins?|hours?|hrs?|seconds?|"
        r"secs?)$",
        work,
    )

    clock = re.search(
        r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*"
        r"(am|pm)?\b",
        work,
    )

    if lead:
        when_seconds = _parse_duration(
            lead.group(1)
        )

        if when_seconds is not None:
            task = lead.group(3)

    if task is None and trail and not (
            recurring):
        body = work[:trail.start()].strip()

        body = re.sub(
            r"^(remind me to|remind me|remind)\s+",
            "",
            body,
        )

        seconds = _parse_duration(
            trail.group(1) + " "
            + trail.group(2)
        )

        if seconds and body:
            when_seconds = seconds

            task = body

    if task is None and recurring and (
            recurring["kind"] == "daily"):
        # With or without "remind": routine
        # syntax ("every day at 9 read the
        # briefing") has no remind word, so
        # the task is whatever follows the
        # clock.

        clock_match = re.match(
            r"^at\s+(\d{1,2})(?::(\d{2}))?\s*"
            r"(am|pm)?\s+(?:(?:remind me "
            r"to|remind me|remind)\s+)?(.+)$",
            work,
        )

        if clock_match:
            when_clock = _parse_clock(
                "at " + clock_match.group(1)
                + (":"
                   + clock_match.group(2)
                   if clock_match.group(2)
                   else "")
                + (" "
                   + clock_match.group(3)
                   if clock_match.group(3)
                   else "")
            )

            if when_clock:
                task = clock_match.group(4)

    if task is None and recurring and (
            recurring["kind"] == "weekly"):
        clock_match = re.match(
            r"^at\s+(\d{1,2})(?::(\d{2}))?\s*"
            r"(am|pm)?\s+(?:(?:remind me "
            r"to|remind me|remind)\s+)?(.+)$",
            work,
        )

        if clock_match:
            when_clock = _parse_clock(
                "at " + clock_match.group(1)
                + (":"
                   + clock_match.group(2)
                   if clock_match.group(2)
                   else "")
                + (" "
                   + clock_match.group(3)
                   if clock_match.group(3)
                   else "")
            )

            if when_clock:
                task = clock_match.group(4)

    if task is None and not recurring and (
            clock):
        body = work[:clock.start()].strip()

        body = re.sub(
            r"^(remind me to|remind me|remind)\s+",
            "",
            body,
        )

        parsed_clock = _parse_clock(
            clock.group(0).strip()
        )

        if parsed_clock and body:
            when_clock = parsed_clock

            task = body

    if task is None and recurring:
        # Recurring without a clock ("every
        # hour remind me to X") or weekly
        # without a time: the rest of the
        # sentence is the task. Hourly math
        # uses the reschedule step; weekly
        # defaults to 09:00 via the reminder
        # defaults.
        #
        # ROUTINE syntax ("every day at 9
        # read the briefing...") has no
        # "remind" word: strip a leading
        # "at HH:MM (am|pm)?" instead and
        # the rest is the task.

        body = re.sub(
            r"^(remind me to|remind me|remind)\s+",
            "",
            work,
        ).strip()

        if not body:
            body = re.sub(
                r"^at\s+\d{1,2}(?::\d{2})?\s*"
                r"(am|pm)?\s+",
                "",
                work,
            ).strip()

        if body:
            task = body

    if task is None:
        # Bare "remind me to X" is not a
        # time; refuse honestly rather than
        # guess.

        return None

    task = task.strip().rstrip(".,!?")

    if not task:
        return None

    reminder = {
        "id": int(time.time() * 1000) % (
            1 << 40
        ),
        "task": task,
        "created": datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        ),
    }

    # Week-two capstone: known ROUTINE
    # tasks run at fire time instead of
    # being spoken - the briefing is read
    # aloud, due reminders are listed, etc.

    if task.lower() in (
            "read the briefing",
            "read my briefing",
            "the briefing",
            "briefing",
            "read the briefing and my reminders",
            "read my reminders and the briefing",
            "the briefing and my reminders",
            "read the briefing and reminders",
            "briefing and reminders",
            "read my reminders",
            "my reminders",
            "the reminders",
            "reminders",
    ):
        reminder["routine"] = True

    if recurring:
        reminder["recurring"] = recurring

        if recurring["kind"] == "daily":
            reminder["hours"] = (
                when_clock[0]
                if when_clock else 9
            )

            reminder["minutes"] = (
                when_clock[1]
                if when_clock else 0
            )

            # First fire time: without it the
            # scheduler skips the reminder
            # forever (nothing is ever "due").

            reminder["fire_at"] = (
                _next_daily_fire(
                    reminder["hours"],
                    reminder["minutes"],
                ).strftime(
                    "%Y-%m-%d %H:%M:%S")
            )

        elif recurring["kind"] == "weekly":
            reminder["hours"] = (
                when_clock[0]
                if when_clock else 9
            )

            reminder["minutes"] = (
                when_clock[1]
                if when_clock else 0
            )

            reminder["fire_at"] = (
                _next_weekly_fire(
                    reminder["hours"],
                    reminder["minutes"],
                    recurring["weekday"],
                ).strftime(
                    "%Y-%m-%d %H:%M:%S")
            )

        else:
            # Hourly recurrence: first fire is
            # one interval out.

            reminder["fire_at"] = (
                datetime.now()
                + timedelta(
                    hours=recurring.get(
                        "every", 1))
            ).strftime("%Y-%m-%d %H:%M:%S")

        return reminder

    if when_seconds is not None:
        reminder["fire_at"] = (
            datetime.now()
            + timedelta(seconds=when_seconds)
        ).strftime("%Y-%m-%d %H:%M:%S")

        return reminder

    if when_clock is not None:
        target = datetime.now().replace(
            hour=when_clock[0],
            minute=when_clock[1],
            second=0,
            microsecond=0,
        )

        if target <= datetime.now():
            target += timedelta(days=1)

        reminder["fire_at"] = (
            target.strftime(
                "%Y-%m-%d %H:%M:%S")
        )

        return reminder

    return None


# ---------------- STORE ----------------

def load_reminders():
    global _reminders

    try:
        with open(
                REMINDERS_FILE, "r",
                encoding="utf-8") as f:
            _reminders = json.load(f)

    except Exception:
        _reminders = []

    return _reminders


def save_reminders():
    try:
        with open(
                REMINDERS_FILE, "w",
                encoding="utf-8") as f:
            json.dump(
                _reminders, f, indent=4)

    except Exception:
        pass


def _next_weekly_fire(hours, minutes, weekday):
    # Next datetime matching that weekday
    # and time (today counts if not yet
    # past).

    now = datetime.now()

    days_ahead = (weekday - now.weekday()) % 7

    candidate = now.replace(
        hour=hours,
        minute=minutes,
        second=0,
        microsecond=0,
    ) + timedelta(days=days_ahead)

    if candidate <= now:
        candidate += timedelta(days=7)

    return candidate


def _next_daily_fire(hours, minutes):
    now = datetime.now()

    candidate = now.replace(
        hour=hours,
        minute=minutes,
        second=0,
        microsecond=0,
    )

    if candidate <= now:
        candidate += timedelta(days=1)

    return candidate


def add_reminder(reminder):
    with _lock:
        load_reminders()

        _reminders.append(reminder)

        while len(_reminders) > MAX_REMINDERS:
            _reminders.pop(0)

        save_reminders()

    return reminder


def _reschedule_recurring(reminder):
    kind = reminder.get("recurring", {})

    if kind.get("kind") == "hours":
        reminder["fire_at"] = (
            datetime.now()
            + timedelta(
                hours=kind.get("every", 1))
        ).strftime("%Y-%m-%d %H:%M:%S")

    elif kind.get("kind") == "daily":
        reminder["fire_at"] = (
            _next_daily_fire(
                reminder.get("hours", 9),
                reminder.get("minutes", 0),
            ).strftime("%Y-%m-%d %H:%M:%S")
        )

    elif kind.get("kind") == "weekly":
        reminder["fire_at"] = (
            _next_weekly_fire(
                reminder.get("hours", 9),
                reminder.get("minutes", 0),
                kind.get("weekday", 0),
            ).strftime("%Y-%m-%d %H:%M:%S")
        )


def list_reminders_text():
    with _lock:
        load_reminders()

        if not _reminders:
            return (
                "You have no reminders, sir. "
                "Say 'remind me to ...' and "
                "I will hold the thought."
            )

        lines = [
            f"Your reminders, sir "
            f"({len(_reminders)}):"
        ]

        for reminder in sorted(
                _reminders,
                key=lambda r: r.get(
                    "fire_at", "9999")):
            recurring = reminder.get(
                "recurring")

            when = reminder.get(
                "fire_at", "?")

            if recurring:
                kind = recurring.get("kind")

                if kind == "hours":
                    every = recurring.get(
                        "every", 1)

                    when = (
                        f"every {every} hour"
                        + ("s" if every != 1
                           else "")
                    )

                elif kind == "daily":
                    when = (
                        f"daily at "
                        f"{reminder.get('hours', 9):02d}:"
                        f"{reminder.get('minutes', 0):02d}"
                    )

                elif kind == "weekly":
                    when = (
                        "every "
                        + WEEKDAYS[
                            recurring.get(
                                "weekday", 0)
                        ].title()
                        + f" at "
                        f"{reminder.get('hours', 9):02d}:"
                        f"{reminder.get('minutes', 0):02d}"
                    )

            else:
                when = when[:16].replace(
                    "T", " "
                )

            lines.append(
                f"- {when}: "
                f"{reminder['task']}"
            )

        return "\n".join(lines)


def cancel_reminder(keyword):
    with _lock:
        load_reminders()

        keyword = keyword.strip().lower()

        kept = []

        removed = 0

        for reminder in _reminders:
            if keyword in reminder[
                    "task"].lower():
                removed += 1

            else:
                kept.append(reminder)

        _reminders[:] = kept

        if removed:
            save_reminders()

    return removed


# ---------------- SCHEDULER ----------------

def _scheduler_loop():
    while True:
        try:
            _check_and_fire()

        except Exception:
            pass

        time.sleep(CHECK_INTERVAL)


def _check_and_fire():
    now = datetime.now()

    with _lock:
        load_reminders()

        due = []

        for reminder in _reminders:
            fire_at = reminder.get("fire_at")

            if not fire_at:
                continue

            try:
                fire_time = datetime.strptime(
                    fire_at,
                    "%Y-%m-%d %H:%M:%S",
                )

            except ValueError:
                continue

            if fire_time <= now:
                due.append(reminder)

        for reminder in due:
            if reminder.get("recurring"):
                _reschedule_recurring(
                    reminder
                )

            else:
                _reminders.remove(reminder)

        if due:
            save_reminders()

    for reminder in due:
        if reminder.get("routine"):
            # Routine tasks run instead of being
            # spoken. The executor lives in
            # Shadow.py (it needs the briefing);
            # registered at boot via
            # set_routine_executor.

            try:
                if _routine_executor:
                    _routine_executor(
                        reminder["task"],
                        reminder,
                    )

            except Exception:
                pass

            continue

        if _fire_callback:
            try:
                _fire_callback(
                    reminder["task"],
                    reminder,
                )

            except Exception:
                pass


def start_scheduler(fire_callback):
    # Called once from Shadow.py at boot.
    # The callback receives (task_text,
    # reminder_dict) and speaks it however
    # it likes.

    global _scheduler_started
    global _fire_callback

    _fire_callback = fire_callback

    load_reminders()

    if _scheduler_started:
        return

    _scheduler_started = True

    thread = threading.Thread(
        target=_scheduler_loop,
        daemon=True,
    )

    thread.start()
