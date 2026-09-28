import json
import os
import sys
import urllib.request

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
)

import dashboard_server

# A scratch port so the suite never fights
# the real SHADOW process for 8766.

dashboard_server.SERVER_PORT = 8799


def _get(path):
    with urllib.request.urlopen(
        f"http://localhost:8799{path}",
        timeout=10,
    ) as response:
        return response.status, response.read()


def _post(path, payload):
    request = urllib.request.Request(
        f"http://localhost:8799{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(
        request, timeout=60
    ) as response:
        return response.status, json.loads(
            response.read().decode("utf-8"))


def test_page_serves():
    dashboard_server.start_server()

    code, body = _get("/")

    assert code == 200

    assert b"SHADOW" in body

    assert b"/api/state" in body or (
        "api/state" in body.decode("utf-8")
    )


def test_state_api_shape():
    code, raw = _get("/api/state")

    state = json.loads(raw.decode("utf-8"))

    for key in ("status", "reminders",
                "lessons", "skills",
                "last_heard"):
        assert key in state, (
            f"state missing {key}"
        )

    assert "ear" in state["status"]

    assert "brain" in state["status"]


def test_404_is_clean():
    try:
        _get("/nope")

        raise AssertionError(
            "unknown path returned 200"
        )

    except urllib.error.HTTPError as error:
        assert error.code == 404


def test_chat_goes_through_brain():
    # This exercises the REAL get_response -
    # a local skill, so no Ollama needed and
    # the reply is deterministic.

    code, data = _post(
        "/api/chat", {"text": "battery"})

    reply = data.get("reply", "")

    assert reply, "empty reply"

    assert "percent" in reply.lower(), reply


def test_empty_chat_rejected():
    try:
        _post("/api/chat", {"text": "  "})

        raise AssertionError(
            "empty chat accepted"
        )

    except urllib.error.HTTPError as error:
        assert error.code == 400


def test_streaming_chat_endpoint():
    # The streaming endpoint returns JSON
    # lines: {piece}, ..., {done, reply}.
    # A brain question is used so pieces
    # actually stream; the done frame must
    # always carry the full reply, even when
    # a skill answers instantly (no pieces).

    request = urllib.request.Request(
        "http://localhost:8799/api/chat/stream",
        data=json.dumps(
            {"text": "who are you"}).encode(),
        headers={
            "Content-Type":
            "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(
        request, timeout=180
    ) as response:
        lines = [
            line for line in response.read(
            ).decode("utf-8").splitlines()
            if line.strip()
        ]

    events = [json.loads(line) for line in lines]

    assert events[-1].get("done") is True, (
        events[-1]
    )

    assert "SHADOW" in events[-1][
        "reply"], events[-1]

    # Brain replies stream sentence pieces.

    assert any(
        "piece" in event for event in events
    ), "no streamed pieces"


def test_stream_done_frame_always_present():
    # A skill answer is instant: zero pieces,
    # but the done frame must still deliver
    # the full reply.

    request = urllib.request.Request(
        "http://localhost:8799/api/chat/stream",
        data=json.dumps(
            {"text": "battery"}).encode(),
        headers={
            "Content-Type":
            "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(
        request, timeout=30
    ) as response:
        lines = [
            line for line in response.read(
            ).decode("utf-8").splitlines()
            if line.strip()
        ]

    events = [json.loads(line) for line in lines]

    assert events[-1].get("done") is True

    assert "percent" in events[-1][
        "reply"].lower()


def test_reminder_write_api():
    code, data = _post(
        "/api/reminders/add",
        {"text": "test the plants in 30 "
         "minutes"},
    )

    assert data.get("ok") is True, data

    assert data["task"] == "test the plants"

    # The parsed time must be soon, not junk.

    from datetime import datetime, timedelta

    fire = datetime.strptime(
        data["fire_at"], "%Y-%m-%d %H:%M:%S")

    assert datetime.now() < fire < (
        datetime.now() + timedelta(hours=1)
    )

    # No time -> honest 400, never a guess.

    try:
        _post("/api/reminders/add",
              {"text": "be famous"})

        raise AssertionError(
            "timeless reminder accepted"
        )

    except urllib.error.HTTPError as error:
        assert error.code == 400

    # Delete by task text.

    code, data = _post(
        "/api/reminders/delete",
        {"task": "test the plants"},
    )

    assert data.get("removed") == 1


def test_lesson_write_api():
    code, data = _post(
        "/api/lessons/add",
        {"text": "suite probe lesson"},
    )

    assert data.get("ok") is True, data

    code, data = _post(
        "/api/lessons/delete",
        {"text": "suite probe lesson"},
    )

    assert data.get("removed") == 1


def test_weather_line_gated():
    # The briefing weather line must respect
    # the gate: gated -> None, never an
    # internet call.

    import importlib

    import settings

    importlib.reload(settings)

    settings.SETTINGS_FILE = os.path.join(
        os.path.dirname(
            os.path.abspath(__file__)),
        "_scratch_settings.json",
    )

    if os.path.exists(
            settings.SETTINGS_FILE):
        os.remove(settings.SETTINGS_FILE)

    importlib.reload(settings)

    import online_mode

    online_mode.settings_store = settings

    assert (
        online_mode.briefing_weather_line()
        is None
    ), "weather line fired while gated"

    if os.path.exists(
            settings.SETTINGS_FILE):
        os.remove(settings.SETTINGS_FILE)


def main():
    failures = 0

    try:
        for test in (
            test_page_serves,
            test_state_api_shape,
            test_404_is_clean,
            test_chat_goes_through_brain,
            test_empty_chat_rejected,
            test_streaming_chat_endpoint,
            test_stream_done_frame_always_present,
            test_reminder_write_api,
            test_lesson_write_api,
            test_weather_line_gated,
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
        try:
            dashboard_server.stop_server()

        except Exception:
            pass

    return failures


if __name__ == "__main__":
    raise SystemExit(main())
