import importlib
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
)

HERE = os.path.dirname(os.path.abspath(__file__))

SCRATCH_SETTINGS = os.path.join(
    HERE, "_scratch_nebius_settings.json"
)

SCRATCH_SECRETS = os.path.join(
    HERE, "_scratch_nebius_secrets.json"
)


def fresh_stores():
    # Reload both stores first (resets their
    # globals), then point them at scratch
    # files - NEVER at his real settings.json
    # or secrets.json. Mirrors the order rule
    # from test_memory_and_settings.

    import settings

    importlib.reload(settings)

    settings.SETTINGS_FILE = SCRATCH_SETTINGS
    settings.SECRETS_FILE = SCRATCH_SECRETS

    for path in (SCRATCH_SETTINGS, SCRATCH_SECRETS):
        if os.path.exists(path):
            os.remove(path)

    settings.load_settings()

    import nebius_brain

    importlib.reload(nebius_brain)

    import online_mode

    importlib.reload(online_mode)

    return settings, nebius_brain, online_mode


# ---------------- MOCK SERVERS ----------------

class _SSEHandler(BaseHTTPRequestHandler):

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(
            self.headers.get("Content-Length", 0)
        )

        body = json.loads(
            self.rfile.read(length).decode("utf-8")
        )

        # A mock Token Factory: it checks the
        # bearer key the REAL client sends and
        # answers in the REAL wire format.

        auth = self.headers.get(
            "Authorization", ""
        )

        if not auth.startswith("Bearer test-key"):
            self.send_response(401)

            self.end_headers()

            return

        model = body.get("model", "")

        stream = body.get("stream", False)

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/event-stream" if stream
            else "application/json",
        )

        self.end_headers()

        if not stream:
            payload = json.dumps({
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content":
                            "Cloud reply from "
                            + model + ", sir.",
                    }
                }]
            }).encode("utf-8")

            self.wfile.write(payload)

            return

        # Streamed answer: token chunks the way
        # the OpenAI-compatible SSE wire sends
        # them, then [DONE].

        pieces = ["Half past ", "ten, sir."]

        for piece in pieces:
            event = json.dumps({
                "choices": [{
                    "delta": {
                        "content": piece
                    }
                }]
            })

            self.wfile.write(
                f"data: {event}\n\n".encode(
                    "utf-8"
                )
            )

        self.wfile.write(
            b"data: [DONE]\n\n"
        )


class _TavilyHandler(BaseHTTPRequestHandler):

    def log_message(self, *args):
        pass

    def do_POST(self):
        auth = self.headers.get(
            "Authorization", ""
        )

        if not auth.startswith("Bearer tav-test"):
            self.send_response(401)

            self.end_headers()

            return

        payload = json.dumps({
            "answer":
                "The test answer, sir.",
            "results": [
                {"title": "Result One",
                 "content": "one"},
                {"title": "Result Two",
                 "content": "two"},
            ],
        }).encode("utf-8")

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "application/json",
        )

        self.send_header(
            "Content-Length",
            str(len(payload)),
        )

        self.end_headers()

        self.wfile.write(payload)


_servers = {}


def start_servers():
    if _servers:
        return

    nebius_server = HTTPServer(
        ("127.0.0.1", 0), _SSEHandler
    )

    tavily_server = HTTPServer(
        ("127.0.0.1", 0), _TavilyHandler
    )

    for server in (
        nebius_server, tavily_server
    ):
        thread = threading.Thread(
            target=server.serve_forever,
            daemon=True,
        )

        thread.start()

    _servers["nebius"] = nebius_server
    _servers["tavily"] = tavily_server


def stop_servers():
    for server in _servers.values():
        server.shutdown()

        server.server_close()

    _servers.clear()


# ---------------- TESTS ----------------

def test_off_by_default(settings, nb, om):
    assert nb.enabled() is False

    assert settings.get_setting(
        "nebius_enabled"
    ) is False


def test_model_routing(settings, nb, om):
    # Everyday chat -> fast model. Deep
    # trigger words and long prompts ->
    # the big reasoner.

    fast = nb._model_for("fast")
    deep = nb._model_for("deep")

    assert nb.pick_model("what time is it") == fast

    assert nb.pick_model(
        "why does the bridge collapse"
    ) == deep

    assert nb.pick_model(
        "x" * 300
    ) == deep


def test_streaming_via_token_factory(
        settings, nb, om):
    start_servers()

    port = _servers["nebius"]
    port = port.server_address[1]

    settings.set_setting(
        "nebius_base_url",
        f"http://127.0.0.1:{port}/v1",
    )

    settings.set_secret(
        "nebius_api_key", "test-key"
    )

    settings.set_setting("nebius_enabled", True)

    sentences = []

    answer = nb.ask_nebius_streaming(
        [{"role": "user",
          "content": "what time is it"}],
        on_sentence=sentences.append,
    )

    assert answer == "Half past ten, sir.", (
        f"streamed answer wrong: {answer!r}"
    )

    assert sentences == ["Half past ten, sir."], (
        f"sentence split wrong: {sentences!r}"
    )

    settings.set_setting(
        "nebius_base_url", None
    )


def test_missing_key_returns_none(
        settings, nb, om):
    settings.set_secret("nebius_api_key", "")

    os.environ.pop("NEBIUS_API_KEY", None)

    assert nb.resolve_api_key() is None

    assert nb.ask_nebius(
        [{"role": "user", "content": "hi"}]
    ) is None


def test_streaming_falls_back_on_error(
        settings, nb, om):
    # A dead endpoint returns None so the
    # local brain takes over - the core
    # fallback contract.

    settings.set_secret(
        "nebius_api_key", "test-key"
    )

    settings.set_setting(
        "nebius_base_url",
        "http://127.0.0.1:1/v1",
    )

    answer = nb.ask_nebius_streaming(
        [{"role": "user", "content": "hi"}],
        on_sentence=lambda text: None,
    )

    assert answer is None

    settings.set_setting(
        "nebius_base_url", None
    )


def test_tavily_search(settings, nb, om):
    start_servers()

    port = _servers["tavily"]
    port = port.server_address[1]

    om.TAVILY_SEARCH_URL = (
        f"http://127.0.0.1:{port}/search"
    )

    om.settings_store.set_secret(
        "tavily_api_key", "tav-test"
    )

    # The gate still applies: search only
    # runs when online mode is ON.

    om.settings_store.set_setting(
        "online_enabled", True
    )

    # Hermetic: break every keyless fetch so
    # the ONLY way this search can succeed is
    # through the Tavily branch. Otherwise a
    # transient mock hiccup would silently
    # fall back to the real DuckDuckGo and
    # the assertion would fail confusingly.

    def _no_internet(url):
        raise OSError("hermetic test")

    original_fetch = om._fetch_json

    om._fetch_json = _no_internet

    try:
        reply = om.web_search_text("test topic")

    finally:
        om._fetch_json = original_fetch

    assert "via Tavily" in reply, (
        f"tavily branch failed, reply was: "
        f"{reply!r}"
    )

    assert "test answer" in reply

    om.settings_store.set_secret(
        "tavily_api_key", ""
    )


def test_search_falls_back_without_key(
        settings, nb, om):
    # No key: the search must not touch
    # Tavily at all - it drops to the
    # keyless path (mocked away here by an
    # unreachable DDG; we only assert that
    # the Tavily branch was skipped
    # gracefully).

    om.TAVILY_SEARCH_URL = (
        "http://127.0.0.1:1/search"
    )

    om.settings_store.set_secret(
        "tavily_api_key", ""
    )

    os.environ.pop("TAVILY_API_KEY", None)

    assert om.resolve_tavily_key() is None

    assert om._tavily_search("x") is None


def test_secrets_never_in_settings_file(
        settings, nb, om):
    # The whole point of secrets.json: keys
    # are written there, never into the
    # settings file that once was tracked.

    settings.set_secret(
        "nebius_api_key", "test-key"
    )

    stored = json.load(
        open(SCRATCH_SETTINGS, encoding="utf-8")
    )

    assert "nebius_api_key" not in stored

    secrets = json.load(
        open(SCRATCH_SECRETS, encoding="utf-8")
    )

    assert secrets["nebius_api_key"] == "test-key"


def main():
    settings, nb, om = fresh_stores()

    tests = [
        test_off_by_default,
        test_model_routing,
        test_streaming_via_token_factory,
        test_missing_key_returns_none,
        test_streaming_falls_back_on_error,
        test_tavily_search,
        test_search_falls_back_without_key,
        test_secrets_never_in_settings_file,
    ]

    failures = 0

    try:
        for test in tests:
            try:
                test(settings, nb, om)

                print(f"PASS {test.__name__}")

            except AssertionError as error:
                failures += 1

                print(
                    f"FAIL {test.__name__}: "
                    f"{error}"
                )

            except Exception as error:
                failures += 1

                print(
                    f"FAIL {test.__name__}: "
                    f"unexpected {type(error).__name__}: "
                    f"{error}"
                )

    finally:
        stop_servers()

        for path in (SCRATCH_SETTINGS,
                     SCRATCH_SECRETS):
            if os.path.exists(path):
                os.remove(path)

    return failures


if __name__ == "__main__":
    raise SystemExit(main())
