import json
import os
import re
import urllib.error
import urllib.request

import settings as settings_store

# ---------------- NEBIUS CLOUD BRAIN ----------------
#
# SHADOW's second brain: NVIDIA's open Nemotron
# models served by Nebius Token Factory, spoken
# to through their OpenAI-compatible API.
#
# Design contract (the part sir should hold us
# to):
#
#   1. OFF by default. Local Ollama remains the
#      default brain; the cloud is opt-in
#      ("nebius on") and the choice persists.
#   2. One failure away from local. Any problem
#      - missing key, dead network, API error -
#      makes these functions return None and
#      shadow.py hands the baton to Ollama. He
#      never goes mute because the wire did.
#   3. The key is never spoken, logged, or
#      committed. It lives in the environment
#      (NEBIUS_API_KEY) or secrets.json, which
#      is gitignored. Status text never echoes
#      it.
#   4. Two models, one persona. Everyday chat
#      goes to the small fast Nemotron; heavy
#      questions ("why", "explain", long
#      prompts) are routed to the bigger
#      reasoner. Both receive the exact same
#      butler system prompt, so the voice does
#      not change - only the depth of thought.
#
# Everything is stdlib-only, like the rest of
# him. The base URL and both model IDs are
# settings-overridable so a model rename on
# Nebius' side is a settings fix, not a code
# fix.

TOKEN_FACTORY_URL = (
    "https://api.tokenfactory.us-central1.nebius.com/v1"
)

NEBIUS_ENABLED_KEY = "nebius_enabled"

NEBIUS_URL_KEY = "nebius_base_url"

NEBIUS_FAST_MODEL_KEY = "nebius_fast_model"

NEBIUS_DEEP_MODEL_KEY = "nebius_deep_model"

FAST_MODEL_DEFAULT = "nvidia/nemotron-3-nano-30b"

DEEP_MODEL_DEFAULT = (
    "nvidia/nemotron-3-super-120b-a12b"
)

REQUEST_TIMEOUT = 120

STREAM_TIMEOUT = 300

MAX_TOKENS = 2048

# Words that mark a question worth the big
# model. Matched as whole words only, so
# "plan" in "explanation" does not trigger.

DEEP_TRIGGER_WORDS = {
    "why", "explain", "prove", "derive",
    "compare", "analyze", "analyse", "design",
    "plan", "strategy", "research", "elaborate",
    "justify", "optimize", "evaluate", "versus",
    "tradeoff", "trade-offs", "outline", "vs",
}

# Prompts longer than this go deep too -
# length is a decent proxy for difficulty.

DEEP_LENGTH_THRESHOLD = 280

_last_error = None


# ---------------- SETTINGS GLUE ----------------

def enabled():
    return bool(
        settings_store.get_setting(NEBIUS_ENABLED_KEY)
    )


def set_enabled(value):
    settings_store.set_setting(
        NEBIUS_ENABLED_KEY, bool(value)
    )

    if value:
        return (
            "Cloud brain ON, sir. I will think with "
            "NVIDIA's Nemotron on Nebius Token "
            "Factory - and quietly fall back to my "
            "local brain if the wire goes down."
        )

    return (
        "Cloud brain OFF, sir. I am entirely your "
        "laptop's again."
    )


def resolve_api_key():
    # Environment first (the documented path),
    # secrets.json second. Never returned in
    # any user-facing text.

    env_key = os.environ.get("NEBIUS_API_KEY")

    if env_key and env_key.strip():
        return env_key.strip()

    try:
        stored = (
            settings_store.get_secret(
                "nebius_api_key"
            )
            or ""
        ).strip()

    except Exception:
        return None

    return stored or None


def _base_url():
    return (
        settings_store.get_setting(NEBIUS_URL_KEY)
        or TOKEN_FACTORY_URL
    ).rstrip("/")


def _model_for(kind):
    key = (
        NEBIUS_FAST_MODEL_KEY
        if kind == "fast"
        else NEBIUS_DEEP_MODEL_KEY
    )

    default = (
        FAST_MODEL_DEFAULT
        if kind == "fast"
        else DEEP_MODEL_DEFAULT
    )

    return (
        settings_store.get_setting(key)
        or default
    )


def pick_model(text):
    # The Nano/Super split the hackathon track
    # description itself recommends: fast small
    # calls for everyday chat, the bigger
    # reasoner when the question deserves it.

    text_lower = (text or "").lower()

    words = set(
        re.findall(r"[a-z']+", text_lower)
    )

    if words & DEEP_TRIGGER_WORDS:
        return _model_for("deep")

    if len(text_lower) >= DEEP_LENGTH_THRESHOLD:
        return _model_for("deep")

    return _model_for("fast")


# ---------------- REQUEST HELPERS ----------------

def _headers(api_key, streaming):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    if streaming:
        headers["Accept"] = "text/event-stream"

    return headers


def _payload(messages, model, stream):
    return json.dumps({
        "model": model,
        "messages": messages,
        "stream": stream,
        "max_tokens": MAX_TOKENS,
    }).encode("utf-8")


def _remember_error(message):
    global _last_error

    _last_error = str(message)

    print(f"[SHADOW NEBIUS] {message}")


def _strip_thinking(text):
    # Nemotron (like Qwen3) may share its private
    # reasoning. The user pays for the answer,
    # not the rehearsal.

    return re.sub(
        r"<think>.*?</think>",
        "",
        text,
        flags=re.DOTALL,
    ).strip()


# ---------------- PUBLIC: NON-STREAMING ----------------

def ask_nebius(messages):
    # One-shot completion. Returns the reply
    # text, or None on any failure so the local
    # brain can take over.

    api_key = resolve_api_key()

    if not api_key:
        _remember_error(
            "no API key - set NEBIUS_API_KEY or "
            "say 'set nebius key <key>'"
        )

        return None

    request = urllib.request.Request(
        _base_url() + "/chat/completions",
        data=_payload(
            messages, _model_for("fast"), False
        ),
        headers=_headers(api_key, False),
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request, timeout=REQUEST_TIMEOUT
        ) as response:
            result = json.loads(
                response.read().decode("utf-8")
            )

    except urllib.error.HTTPError as error:
        _remember_error(
            f"HTTP {error.code} from Token Factory"
        )

        return None

    except Exception as error:
        _remember_error(
            f"cloud unreachable: {error}"
        )

        return None

    try:
        answer = (
            result["choices"][0]["message"]["content"]
            or ""
        ).strip()

    except (KeyError, IndexError, TypeError):
        _remember_error(
            "unexpected response shape from "
            "Token Factory"
        )

        return None

    answer = _strip_thinking(answer)

    return answer or None


# ---------------- PUBLIC: STREAMING ----------------

def _parse_sse_chunk(line):
    # One Server-Sent-Events line from the
    # OpenAI-compatible stream. Returns
    # ("delta", text), ("done", None) or None.

    line = line.strip()

    if not line or line.startswith(":"):
        return None

    if not line.startswith("data:"):
        return None

    data = line[5:].strip()

    if data == "[DONE]":
        return ("done", None)

    try:
        chunk = json.loads(data)

    except json.JSONDecodeError:
        return None

    choices = chunk.get("choices") or []

    if not choices:
        return None

    delta = choices[0].get("delta") or {}

    # reasoning_content (if the model sends it)
    # is deliberately ignored - private
    # thinking never reaches the speakers.

    return ("delta", delta.get("content") or "")


# The next two helpers mirror shadow.py's own
# streaming filters (kept local to avoid a
# circular import): <think> tag removal while
# tokens arrive, and sentence-at-a-time
# emission so his mouth starts moving before
# the answer finishes generating.

_ABBREVIATION_WORDS = (
    "mr", "mrs", "ms", "dr", "st",
    "vs", "etc", "approx"
)


def _extract_stream_text(piece, state):
    text = state["pending"] + piece

    state["pending"] = ""

    output = ""

    while text:
        if state["in_think"]:
            end_index = text.find("</think>")

            if end_index != -1:
                text = text[
                    end_index + len("</think>"):
                ]

                state["in_think"] = False

                continue

            keep = _partial_suffix_length(
                text, "</think>"
            )

            if keep:
                state["pending"] = text[-keep:]

            return output

        start_index = text.find("<think>")

        if start_index != -1:
            output += text[:start_index]

            text = text[
                start_index + len("<think>"):
            ]

            state["in_think"] = True

            continue

        keep = _partial_suffix_length(
            text, "<think>"
        )

        if keep:
            output += text[:-keep]

            state["pending"] = text[-keep:]

        else:
            output += text

        return output

    return output


def _partial_suffix_length(text, tag):
    max_check = min(len(text), len(tag) - 1)

    for length in range(max_check, 0, -1):
        if tag.startswith(text[-length:]):
            return length

    return 0


def _looks_like_abbreviation(text):
    stripped = text.rstrip()

    if not stripped or stripped[-1] != ".":
        return False

    last_word = stripped.rstrip(".").split()[-1:]

    if not last_word:
        return False

    word = last_word[0].lower()

    return word in _ABBREVIATION_WORDS or (
        word.isdigit()
    )


def _emit_ready_sentences(state, on_sentence):
    # Hand over every complete sentence in the
    # buffer. "Complete" ends in . ! or ?
    # followed by whitespace - and not an
    # abbreviation like "Dr." or "3.".

    buffer_text = state["sentence_buffer"]

    emitted = []

    while True:
        boundary = None

        for index, char in enumerate(buffer_text):
            if char not in ".!?":
                continue

            if index + 1 >= len(buffer_text):
                # Punctuation at the very end of
                # what has arrived so far: wait for
                # more text to confirm the space.

                break

            if buffer_text[
                    index + 1
            ] not in " \n\t":
                continue

            prefix = buffer_text[:index + 1]

            if _looks_like_abbreviation(prefix):
                continue

            boundary = index

            break

        if boundary is None:
            break

        sentence = buffer_text[:boundary + 1]

        buffer_text = buffer_text[boundary + 1:]

        sentence = sentence.strip()

        if sentence:
            emitted.append(sentence)

    state["sentence_buffer"] = buffer_text

    for sentence in emitted:
        on_sentence(sentence)


def ask_nebius_streaming(messages, on_sentence):
    # Streams from Token Factory and calls
    # on_sentence() as each sentence completes.
    # Returns the full visible text, or None if
    # the cloud could not be reached at all.

    api_key = resolve_api_key()

    if not api_key:
        _remember_error(
            "no API key - set NEBIUS_API_KEY or "
            "say 'set nebius key <key>'"
        )

        return None

    request = urllib.request.Request(
        _base_url() + "/chat/completions",
        data=_payload(
            messages,
            pick_model(messages[-1]["content"]),
            True,
        ),
        headers=_headers(api_key, True),
        method="POST",
    )

    full_text = []

    stream_state = {
        "in_think": False,
        "pending": "",
        "sentence_buffer": "",
    }

    try:
        with urllib.request.urlopen(
            request, timeout=STREAM_TIMEOUT
        ) as response:
            for raw_line in response:
                kind, piece = (
                    _parse_sse_chunk(
                        raw_line.decode("utf-8")
                    )
                    or (None, None)
                )

                if kind == "done":
                    break

                if kind != "delta" or not piece:
                    continue

                normal = _extract_stream_text(
                    piece, stream_state
                )

                if not normal:
                    continue

                full_text.append(normal)

                stream_state[
                    "sentence_buffer"
                ] += normal

                _emit_ready_sentences(
                    state=stream_state,
                    on_sentence=on_sentence,
                )

    except urllib.error.HTTPError as error:
        _remember_error(
            f"HTTP {error.code} from Token Factory"
        )

        # Partial audio already spoken plus a
        # fresh local answer would double-talk;
        # only fall back when nothing was said.

        if full_text:
            return _strip_thinking(
                "".join(full_text)
            )

        return None

    except Exception as error:
        _remember_error(
            f"cloud unreachable: {error}"
        )

        if full_text:
            return _strip_thinking(
                "".join(full_text)
            )

        return None

    remaining = stream_state[
        "sentence_buffer"
    ].strip()

    if remaining:
        on_sentence(remaining)

        stream_state["sentence_buffer"] = ""

    return _strip_thinking("".join(full_text))


# ---------------- STATUS & KEY MANAGEMENT ----------------

def status_text():
    api_key = resolve_api_key()

    if api_key:
        where = (
            "environment variable"
            if os.environ.get("NEBIUS_API_KEY")
            else "secrets.json"
        )

        key_line = f"API key: found ({where})"
    else:
        key_line = (
            "API key: MISSING - say 'set nebius "
            "key <key>' or set NEBIUS_API_KEY"
        )

    lines = [
        "Nebius cloud brain: "
        + ("ON" if enabled() else "OFF (default)"),
        key_line,
        f"Endpoint: {_base_url()}",
        "Fast model: "
        + _model_for("fast")
        + " (everyday chat)",
        "Deep model: "
        + _model_for("deep")
        + " (hard questions)",
        "Fallback: local Ollama brain takes "
        "over automatically if the cloud is "
        "unreachable",
    ]

    if _last_error:
        lines.append(f"Last error: {_last_error}")

    return "\n".join(lines)


def set_key_text(key_value):
    key_value = (key_value or "").strip()

    if not key_value:
        return (
            "Give me the key, sir: 'set nebius "
            "key <key>'. It goes into secrets."
            "json, which never leaves this "
            "machine."
        )

    settings_store.set_secret(
        "nebius_api_key", key_value
    )

    return (
        "Nebius key saved, sir - stored only in "
        "secrets.json on this laptop. Say "
        "'nebius on' when you want me to think "
        "in the cloud."
    )


def clear_key_text():
    settings_store.set_secret(
        "nebius_api_key", ""
    )

    return (
        "Nebius key cleared, sir. The cloud "
        "brain has nothing to speak with now."
    )
