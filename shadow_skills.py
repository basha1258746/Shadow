import json
import os

# ---------------- SHADOW SKILLS ----------------
#
# Borrowed from Stanford's __OPENSHADOW__ (their
# "skills" idea): instead of hard-coding every
# command deep inside get_response, sir can
# drop a small JSON file into skills/ and he
# discovers it on his own. A broken skill can
# never take him down - it just sits ignored,
# and he says so honestly when asked.

SKILLS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "skills",
)

MAX_STEPS = 12

SKILL_DEFAULTS = {
    "version": 1,
    "name": None,
    "description": "",
    "match": [],
    "steps": [],
}


def _skill_files():
    try:
        return sorted(
            f for f in os.listdir(SKILLS_DIR)
            if f.lower().endswith(".json")
        )

    except Exception:
        return []


def _load_skill(path):
    # One file -> (skill dict, error string).
    # Never raises: a bad file returns the
    # error so load_all_skills can report it
    # without touching his listening loop.

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return None, "not a JSON object"

        skill = dict(SKILL_DEFAULTS)

        skill.update(data)

        skill["file"] = os.path.basename(path)

        for key in ("match", "steps"):
            if not isinstance(
                    skill[key], list):
                return None, (
                    f"'{key}' must be a list"
                )

        if not skill["name"]:
            skill["name"] = (
                os.path.basename(path)[:-5]
            )

        if not skill["match"]:
            return None, "no match phrases"

        if not skill["steps"]:
            return None, "no steps"

        if len(skill["steps"]) > MAX_STEPS:
            return None, (
                f"too many steps "
                f"(max {MAX_STEPS})"
            )

        for step in skill["steps"]:
            if not isinstance(step, dict):
                return None, (
                    "every step must be an "
                    "object"
                )

            if "say" not in step and (
                    "run" not in step):
                return None, (
                    "step needs 'say' or 'run'"
                )

        return skill, None

    except Exception as error:
        return None, str(error)


def load_all_skills():
    # Returns (skills, errors). skills is a
    # list of working skill dicts; errors is
    # a list of "file: problem" strings.

    skills = []

    errors = []

    for filename in _skill_files():
        skill, error = _load_skill(
            os.path.join(SKILLS_DIR, filename)
        )

        if error:
            errors.append(
                f"{filename}: {error}"
            )

        else:
            skills.append(skill)

    return skills, errors


def _match_score(skill, text_lower):
    # Best score across the skill's match
    # phrases. 3 = exact, 2 = starts with,
    # 1 = contains, 0 = no match.

    best = 0

    for phrase in skill["match"]:
        phrase = str(phrase).lower().strip()

        if not phrase:
            continue

        if text_lower == phrase:
            return 3

        if text_lower.startswith(phrase):
            best = max(best, 2)

        elif phrase in text_lower:
            best = max(best, 1)

    return best


def _run_step(run):
    # Only shell-safe steps: simple commands,
    # no quotes, no pipes, no redirection.
    # his voice must never become a shell
    # injection.

    import subprocess

    parts = run.split()

    for part in parts:
        if any(
            ch in part
            for ch in "\"'|&<>^%"
        ):
            return None, (
                "refused: quotes/pipes are "
                "not allowed in skill runs"
            )

    try:
        raw = subprocess.run(
            parts,
            capture_output=True,
            text=True,
            timeout=15,
            errors="replace",
        )

    except FileNotFoundError:
        return None, (
            f"'{parts[0]}' is not a command "
            "on this laptop"
        )

    except Exception as error:
        return None, f"failed: {error}"

    out = (raw.stdout or "").strip()

    err = (raw.stderr or "").strip()

    return (out or err or
            f"done (exit {raw.returncode})"), None


def try_skill(text_lower):
    # The hook get_response calls FIRST.
    # Returns the reply string when a skill
    # matched and ran, else None so normal
    # routing proceeds.

    skills, _errors = load_all_skills()

    if not skills:
        return None

    scored = []

    for skill in skills:
        score = _match_score(
            skill, text_lower
        )

        if score > 0:
            scored.append((score, skill))

    if not scored:
        return None

    scored.sort(
        key=lambda pair: pair[0],
        reverse=True,
    )

    best_score, skill = scored[0]

    if best_score < 2:
        # A faint keyword inside a longer
        # sentence is not enough - he only
        # fires on exact or prefix matches.

        return None

    outs = []

    for step in skill["steps"]:
        if "run" in step:
            out, error = _run_step(
                str(step["run"])
            )

            if error:
                return (
                    f"The skill '{skill['name']}' "
                    f"hit a snag, sir: {error}"
                )

            outs.append(out)

        if "say" in step:
            outs.append(str(step["say"]))

        if len(outs) >= MAX_STEPS:
            break

    if not outs:
        return None

    return "\n".join(outs)


def list_skills_text():
    skills, errors = load_all_skills()

    if not skills and not errors:
        return (
            "I have no skills installed, "
            "sir. Drop a JSON file into my "
            "skills folder and I will learn "
            "it on my next listen."
        )

    lines = ["My skills, sir:"]

    for skill in skills:
        trigger = skill["match"][0]

        lines.append(
            f"- {skill['name']}: "
            f"{skill['description']} "
            f"(say '{trigger}')"
        )

    if errors:
        lines.append(
            f"{len(errors)} broken skill "
            "file(s), ignored:"
        )

        for error in errors:
            lines.append(f"  - {error}")

    return "\n".join(lines)


if __name__ == "__main__":
    print(list_skills_text())
