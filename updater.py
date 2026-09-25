import json
import os
import subprocess

REPO_DIR = os.path.dirname(os.path.abspath(__file__))

STATE_FILE = os.path.join(REPO_DIR, "last_update.json")

# Keep this many commit subjects in the state:
# enough for her to summarize the last update
# without ever dumping a wall of text.

MAX_CHANGES = 8


def _git(*args):
    # Run a git command inside her repo and
    # return cleaned stdout. Raises with the
    # git error message on failure.

    raw = subprocess.run(
        ["git", *args],
        cwd=REPO_DIR,
        capture_output=True,
        text=True,
        timeout=90,
    )

    if raw.returncode != 0:
        raise RuntimeError(
            raw.stderr.strip()
            or f"git {' '.join(args)} failed"
        )

    return raw.stdout.strip()


def _load_state():
    try:
        with open(
            STATE_FILE, "r", encoding="utf-8"
        ) as state_file:
            return json.load(state_file)

    except Exception:
        return {}


def _save_state(state):
    try:
        with open(
            STATE_FILE, "w", encoding="utf-8"
        ) as state_file:
            json.dump(state, state_file, indent=4)

    except Exception:
        pass


def _clean_subjects(lines):
    # Commit subjects minus common noise, and
    # never more than MAX_CHANGES: she speaks
    # the summary, she does not recite git.

    cleaned = []

    for line in lines:
        subject = line.split(":", 1)[-1].strip()

        subject = subject.rstrip(".").strip()

        if subject and subject not in cleaned:
            cleaned.append(subject)

    return cleaned[:MAX_CHANGES]


def check_for_updates():
    # Fetch and compare without touching the
    # working tree. Returns (behind_count,
    # subjects) for the un-pulled commits.

    _git("fetch", "origin")

    local = _git("rev-parse", "HEAD")

    remote = _git("rev-parse", "origin/main")

    if local == remote:
        return 0, []

    subjects = _git(
        "log",
        f"{local}..{remote}",
        "--pretty=%s",
    ).splitlines()

    return len(subjects), _clean_subjects(subjects)


def pull_updates():
    # The actual self-update: stash nothing,
    # refuse anything risky, and prefer a
    # clean fast-forward. Refuses when chief
    # has uncommitted changes that would
    # collide (his work is never discarded).
    # Returns (updated: bool, subjects, note).

    _git("fetch", "origin")

    local = _git("rev-parse", "HEAD")

    remote = _git("rev-parse", "origin/main")

    if local == remote:
        return (
            False,
            [],
            "already up to date",
        )

    subjects = _git(
        "log",
        f"{local}..{remote}",
        "--pretty=%s",
    )

    subject_list = _clean_subjects(
        subjects.splitlines()
    )

    try:
        _git("pull", "--ff-only", "origin", "main")

    except Exception:
        return (
            False,
            [],
            "update blocked - local changes would "
            "conflict; chief must commit or stash "
            "them first",
        )

    state = {
        "last_commit": remote,
        "last_subjects": subject_list,
        "last_note": "updated",
    }

    _save_state(state)

    return True, subject_list, "updated"


def get_boot_update_news():
    # The boot check: compare against origin
    # without pulling. Announce-once per
    # release, per chief's request - say it
    # with the morning briefing, not every
    # boot. Returns (behind, subjects).

    try:
        behind, subjects = (
            check_for_updates()
        )

    except Exception:
        # No internet / no GitHub: stay quiet,
        # chief never hears a boot error.

        return 0, []

    state = _load_state()

    if behind <= 0:
        # All caught up - the old pending
        # marker has served its purpose.

        if state.get("last_note") == (
                "pending announcement"):
            set_last_note("up to date")

        return 0, []

    fingerprint = (
        str(behind) + "|" + "".join(subjects)
    )

    if state.get("last_note") == (
            "pending announcement") and (
            state.get("last_fingerprint") == (
                fingerprint)):
        # Same pile as last boot: already
        # offered, chief declined - hush.

        return 0, []

    state["last_fingerprint"] = fingerprint

    state["last_note"] = (
        "pending announcement"
)

    _save_state(state)

    return behind, subjects


def get_pending_announcement():
    # The announcement flag: after a pull (or a
    # restart that landed new code), the NEXT
    # wake reads this once and clears it, so
    # she never repeats herself.

    state = _load_state()

    if state.get("announced"):
        return []

    subjects = state.get("last_subjects") or []

    if not subjects:
        return []

    state["announced"] = True

    _save_state(state)

    return subjects


def mark_announced():
    state = _load_state()

    state["announced"] = True

    _save_state(state)


def set_last_note(note):
    # Called after a successful boot so the
    # state always reflects the newest code.

    state = _load_state()

    try:
        state["last_commit"] = _git("rev-parse", "HEAD")

    except Exception:
        pass

    state["last_note"] = note

    _save_state(state)
