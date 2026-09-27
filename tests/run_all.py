# Shadow regression suite runner.
#
#   python tests/run_all.py
#
# Zero dependencies, no pytest needed: each
# module exposes main() returning a failure
# count. Exit code 0 = all green (safe to
# run while he is listening - tests use
# scratch files and never touch his mic).

import os
import sys

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
)

HERE = os.path.dirname(os.path.abspath(__file__))

MODULES = (
    "test_ears",
    "test_skills",
    "test_updater",
    "test_memory_and_settings",
    "test_reminders",
)


def main():
    total_failures = 0

    print("=" * 46)
    print("Shadow regression suite")
    print("=" * 46)

    for module_name in MODULES:
        module = __import__(module_name)

        print(f"-- {module_name}")

        total_failures += (
            module.main() or 0
        )

    print("=" * 46)

    if total_failures:
        print(
            f"FAILED: {total_failures} "
            "test(s) broke."
        )

        return 1

    print("ALL TESTS PASS, sir.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
