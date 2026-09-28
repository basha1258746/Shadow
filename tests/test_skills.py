import json
import os
import sys

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
)

import shadow_skills

# A unique name: the real skills folder
# ships battery/wifi/timetable, and the
# suite must never collide with them.

SAMPLE = {
    "name": "wristwatch",
    "description": "test skill",
    "match": ["wristwatch"],
    "steps": [
        {"say": "wound, sir."},
    ],
}


def write_skill(data, filename):
    path = os.path.join(
        shadow_skills.SKILLS_DIR, filename
    )

    with open(
            path, "w", encoding="utf-8") as f:
        f.write(json.dumps(data))

    return path


def test_load_and_match():
    path = write_skill(SAMPLE, "t_a.json")

    try:
        skills, errors = (
            shadow_skills.load_all_skills()
        )

        assert not errors, errors

        watches = [
            s for s in skills
            if s["name"] == "wristwatch"
        ]

        assert watches, "sample skill lost"

        reply = shadow_skills.try_skill(
            "wristwatch"
        )

        assert reply == "wound, sir.", (
            reply
        )

    finally:
        os.remove(path)


def test_broken_file_isolated():
    path = os.path.join(
        shadow_skills.SKILLS_DIR, "t_b.json"
    )

    with open(path, "w") as f:
        f.write("{ not json")

    try:
        skills, errors = (
            shadow_skills.load_all_skills()
        )

        assert errors, (
            "broken file was silently ignored"
        )

        assert any(
            "t_b.json" in e for e in errors
        )

        # Working skills still load beside it.

        assert isinstance(skills, list)

    finally:
        os.remove(path)


def test_injection_refused():
    out, error = shadow_skills._run_step(
        'powershell -Command "echo pwned"'
    )

    assert out is None

    assert "refused" in error


def test_pipe_refused():
    out, error = shadow_skills._run_step(
        "dir | more"
    )

    assert out is None

    assert "refused" in error


def test_faint_match_ignored():
    path = write_skill(SAMPLE, "t_c.json")

    try:
        # 'wristwatch' inside a longer
        # sentence must NOT trigger.

        assert (
            shadow_skills.try_skill(
                "tell me a joke about my wristwatch collection"
            )
            is None
        )

    finally:
        os.remove(path)


def test_prefix_match_fires():
    path = write_skill(SAMPLE, "t_d.json")

    try:
        reply = shadow_skills.try_skill(
            "wristwatch status now"
        )

        assert reply == "wound, sir."

    finally:
        os.remove(path)


def main():
    tests = [
        test_load_and_match,
        test_broken_file_isolated,
        test_injection_refused,
        test_pipe_refused,
        test_faint_match_ignored,
        test_prefix_match_fires,
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
