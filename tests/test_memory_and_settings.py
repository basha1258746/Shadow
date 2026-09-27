import importlib
import os
import sys

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
)

SCRATCH_MEMORY = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "_scratch_memory.json",
)

SCRATCH_SETTINGS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "_scratch_settings.json",
)


def fresh_memory_store(reset=True):
    # IMPORTANT: reload first (it resets the
    # module's globals), THEN point it at the
    # scratch file, THEN load. Getting this
    # order wrong would test against his real
    # memory.json.
    #
    # reset=False simulates a RESTART: the
    # file survives, the process does not.

    import memory_manager

    importlib.reload(memory_manager)

    memory_manager.MEMORY_FILE = (
        SCRATCH_MEMORY
    )

    if reset and os.path.exists(
            SCRATCH_MEMORY):
        os.remove(SCRATCH_MEMORY)

    memory_manager.load_memory()

    return memory_manager


def fresh_settings_store():
    import settings

    importlib.reload(settings)

    settings.SETTINGS_FILE = (
        SCRATCH_SETTINGS
    )

    if os.path.exists(SCRATCH_SETTINGS):
        os.remove(SCRATCH_SETTINGS)

    settings.load_settings()

    return settings


def test_lessons_store():
    memory_manager = fresh_memory_store()

    memory_manager.add_lesson(
        "I prefer short answers"
    )

    memory_manager.add_lesson(
        "I prefer short answers"
    )

    lessons = memory_manager.get_lessons()

    assert len(lessons) == 1, (
        f"duplicate lesson stored: "
        f"{len(lessons)}"
    )

    assert memory_manager.remove_lessons(
        "short answers"
    ) == 1

    assert (
        memory_manager.get_lessons() == []
    )


def test_lessons_cap():
    memory_manager = fresh_memory_store()

    for i in range(60):
        memory_manager.add_lesson(
            f"lesson number {i}"
        )

    assert (
        len(memory_manager.get_lessons())
        <= memory_manager.MAX_LESSONS
    )


def test_lessons_survive_reload():
    # The promise: lessons survive a restart
    # (a reload + load is exactly a restart).

    memory_manager = fresh_memory_store(
        reset=True
    )

    memory_manager.add_lesson(
        "the gateway subject is thermodynamics"
    )

    # Restart: same file, fresh process.

    memory_manager = fresh_memory_store(
        reset=False
    )

    texts = [
        lesson["text"]
        for lesson in (
            memory_manager.get_lessons())
    ]

    assert (
        "the gateway subject is "
        "thermodynamics" in texts
    ), f"lesson lost on restart: {texts}"


def test_online_gate_defaults_off():
    fresh_settings_store()

    import online_mode

    # THE safety promise: a fresh install
    # never reaches the internet uninvited.

    assert (
        online_mode.is_online_enabled()
        is False
    ), "online mode defaulted ON"

    reply = online_mode.weather_text("")

    assert "off" in reply.lower()


def test_online_city_persists():
    settings = fresh_settings_store()

    import online_mode

    online_mode.settings_store = settings

    reply = online_mode.set_city_text(
        "MyCity"
    )

    assert "MyCity" in reply

    assert (
        settings.get_setting(
            online_mode.ONLINE_CITY_KEY
        )
        == "MyCity"
    )


def main():
    failures = 0

    try:
        for test in (
            test_lessons_store,
            test_lessons_cap,
            test_lessons_survive_reload,
            test_online_gate_defaults_off,
            test_online_city_persists,
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
        for path in (
            SCRATCH_MEMORY,
            SCRATCH_SETTINGS,
        ):
            if os.path.exists(path):
                os.remove(path)

    return failures


if __name__ == "__main__":
    raise SystemExit(main())
