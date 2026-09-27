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
# the real Shadow process for 8766.

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

    assert b"Shadow" in body

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


def main():
    failures = 0

    try:
        for test in (
            test_page_serves,
            test_state_api_shape,
            test_404_is_clean,
            test_chat_goes_through_brain,
            test_empty_chat_rejected,
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
