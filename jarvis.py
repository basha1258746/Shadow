import json
import re
import sys
import time
import urllib.request
import urllib.error
import os

# Windows consoles sometimes cannot print emoji
# and other special characters. Replace them
# with "?" instead of crashing.

sys.stdout.reconfigure(errors="replace")
sys.stderr.reconfigure(errors="replace")

from system_info import get_system_info
from app_control import open_application
from file_control import open_folder, list_folder
from document_reader import (
    read_document,
    split_into_chunks,
    search_chunks
)

import semantic_search

import screen_vision

import computer_control

import window_watcher

# Load saved settings BEFORE the voice modules
# start, so they pick up the stored speed.

import settings as settings_store

settings_store.load_settings()

from voice_output import (
    speak,
    wait_until_speech_done,
    set_speech_rate,
    get_speech_rate,
    DEFAULT_SPEECH_RATE,
    set_after_sentence_hook
)

from voice_input import (
    listen_for_command,
    listen_for_wake_word,
    flush_audio_queue,
    close_stt,
    setup_stt
)

# After every spoken sentence, drop the
# microphone audio so Shadow never mistakes
# her own voice for the user's.

set_after_sentence_hook(flush_audio_queue)
import backup

MODEL = "qwen3:1.7b"
OLLAMA_URL = "http://localhost:11434/api/chat"
MEMORY_FILE = "memory.json"
MAX_HISTORY = 12
VOICE_ENABLED = True


# ---------------- MEMORY ----------------

# Memory now lives in its own module with three
# stores: personal, projects, and documents.

import memory_manager

memory_manager.load_memory()

conversation_history = []

current_document_text = None
current_document_path = None
current_document_chunks = []

voice_enabled = settings_store.get_setting(
    "voice_enabled"
)

# Computer control: when not None, this holds
# a staged action {"action": ..., "description":
# ...} that will ONLY run after the user
# explicitly confirms with yes.

pending_action = None

# True when the current reply was already spoken
# sentence by sentence during generation.

reply_already_spoken = False


def remember_name(name):
    memory_manager.set_user_name(name)
    return f"Got it, baa. I will remember your name is {name}."


def remember_fact(fact):
    memory_manager.add_personal_fact(fact)
    return "Noted, baa. I will remember that."


def build_memory_reply():
    reply = memory_manager.personal_summary_text()

    if not reply:
        return "I don't have anything stored in memory yet, baa."

    return reply


def forget_fact(fact_text):
    keyword = fact_text.strip()

    if not keyword:
        return "Tell me what I should forget, baa."

    removed = memory_manager.remove_personal_facts(keyword)

    if not removed:
        return f"I don't have anything about '{keyword}' stored, baa."

    return f"Done. I forgot {removed} thing(s) about '{keyword}'."


def remember_project_note(text):
    # Format: remember project <name>: <note>

    rest = text[len("remember project"):].strip()

    if ":" in rest:
        project, note = rest.split(":", 1)

        project = project.strip()
        note = note.strip()

    else:
        project = "general"
        note = rest

    if not note:
        return (
            "Tell me what to remember about the "
            "project, baa. Like: remember project "
            "Shadow: added voice input"
        )

    memory_manager.add_project_note(project, note)

    return f"Saved to '{project}' project memory, baa."


def show_project_memory(text):
    rest = text[len("show project"):].strip()

    if not rest or rest in ("memory", "notes", "list"):
        names = memory_manager.list_project_names()

        if not names:
            return (
                "No project memories yet, baa. Add one "
                "with: remember project Shadow: added "
                "voice today"
            )

        lines = ["Projects I hold notes on:", ""]

        for name in names:
            lines.append(f"- {name}")

        lines.append("")
        lines.append(
            "Ask: 'show project <name>' or "
            "'what do you know about <name>'"
        )

        return "\n".join(lines)

    reply = memory_manager.projects_summary_text(rest)

    if reply is None:
        return f"I have no notes about '{rest}' yet, baa."

    return reply


def knowledge_report():
    print("[Shadow TOOL: Collecting everything I know...]")

    return memory_manager.knowledge_report_text()


# ---------------- OLLAMA ----------------

def ask_ollama(messages):
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False
    }

    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))

    except urllib.error.URLError:
        return (
            "I cannot reach Ollama, baa. "
            "Please make sure Ollama is running."
        )

    except Exception as error:
        return f"Error talking to the local model: {error}"

    answer = result.get("message", {}).get("content", "").strip()

    # Qwen3 sometimes outputs its private thinking block.
    # Remove it so the user only sees the real answer.

    answer = re.sub(
        r"<think>.*?</think>",
        "",
        answer,
        flags=re.DOTALL
    ).strip()

    return answer or "..."


# ---- STREAMING HELPERS ----

ABBREVIATION_WORDS = (
    "mr", "mrs", "ms", "dr", "st",
    "vs", "etc", "approx"
)


def _partial_suffix_length(text, tag):
    # How many characters at the end of text form
    # the beginning of tag (for split tags).

    max_check = min(len(text), len(tag) - 1)

    for length in range(max_check, 0, -1):
        if tag.startswith(text[-length:]):
            return length

    return 0


def _extract_stream_text(piece, state):
    # Remove Qwen3 <think> blocks from a streamed
    # piece and return the clean visible text.

    text = state["pending"] + piece
    state["pending"] = ""

    output = ""

    while text:
        if state["in_think"]:
            end_index = text.find("</think>")

            if end_index != -1:
                text = text[end_index + len("</think>"):]
                state["in_think"] = False
                continue

            keep = _partial_suffix_length(
                text,
                "</think>"
            )

            if keep:
                state["pending"] = text[-keep:]

            return output

        start_index = text.find("<think>")

        if start_index != -1:
            output += text[:start_index]
            text = text[start_index + len("<think>"):]
            state["in_think"] = True
            continue

        keep = _partial_suffix_length(text, "<think>")

        if keep:
            output += text[:-keep]
            state["pending"] = text[-keep:]
        else:
            output += text

        return output

    return output


def _looks_like_abbreviation(text):
    # True when text ends with something like
    # "Mr." or "3." which should not end a sentence.

    stripped = text.rstrip()

    if not stripped or stripped[-1] != ".":
        return False

    before = stripped[:-1].rstrip()

    if not before:
        return False

    # Numbered list like "1." or "3."

    if before[-1].isdigit():
        return True

    lowered = before.lower()

    for word in ABBREVIATION_WORDS:
        if lowered.endswith(" " + word) or lowered == word:
            return True

    # Single initial like "J." or "U.D."

    if before[-1].isalpha():
        second_last = before[:-1].rstrip()

        if not second_last or second_last[-1] in ". ":
            return True

    return False


def _emit_ready_sentences(state, on_sentence):
    # Split completed sentences out of the buffer
    # and speak them immediately.

    buffer = state["sentence_buffer"]

    while True:
        cut = -1

        for char in ".!?":
            position = buffer.rfind(char)

            if position > cut:
                cut = position

        if cut != -1:
            candidate = buffer[:cut + 1]

            if _looks_like_abbreviation(candidate):
                break

            if candidate.strip():
                on_sentence(candidate.strip())

            buffer = buffer[cut + 1:].lstrip()
            continue

        # List lines without a period: speak the
        # line if it is reasonably long.

        newline = buffer.rfind("\n")

        if newline != -1 and len(buffer[:newline].strip()) > 40:
            chunk = buffer[:newline].strip()

            if chunk:
                on_sentence(chunk)

            buffer = buffer[newline + 1:]
            continue

        break

    state["sentence_buffer"] = buffer


def ask_ollama_streaming(messages, on_sentence):
    # Stream tokens from Ollama. Every completed
    # sentence is handed to on_sentence() as soon
    # as it is ready. Returns the full text, or
    # None if the connection failed.

    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": True
    }

    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"}
    )

    full_text = []

    stream_state = {
        "in_think": False,
        "pending": "",
        "sentence_buffer": ""
    }

    try:
        with urllib.request.urlopen(
            request,
            timeout=300
        ) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()

                if not line:
                    continue

                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if chunk.get("error"):
                    full_text.append(str(chunk["error"]))
                    break

                piece = chunk.get(
                    "message", {}
                ).get("content", "")

                if piece:
                    normal = _extract_stream_text(
                        piece,
                        stream_state
                    )

                    if normal:
                        full_text.append(normal)

                        stream_state["sentence_buffer"] += normal

                        _emit_ready_sentences(
                            state=stream_state,
                            on_sentence=on_sentence
                        )

                if chunk.get("done"):
                    break

    except Exception:
        return None

    remaining = stream_state["sentence_buffer"].strip()

    if remaining:
        on_sentence(remaining)
        stream_state["sentence_buffer"] = ""

    return "".join(full_text)


def build_system_prompt():
    prompt = (
        "You are Shadow, a local AI assistant running "
        "on the user's Windows laptop. "
        "The underlying engine is a local model, but your "
        "identity is Shadow. You are not Qwen, Alibaba, "
        "ChatGPT or any other product or assistant. "
        "If asked who you are, say you are Shadow. "
        "Be calm, helpful, respectful and concise. "
        "You may casually call the user 'baa'. "
        "Be honest: you do not have consciousness, feelings "
        "or real emotions, and you should say so if asked. "
        "Never guess hardware or system facts; those come "
        "from verified Python tools, not from you."
    )

    user_name = memory_manager.get_user_name()

    if user_name:
        prompt += f" The user's name is {user_name}."

    facts = memory_manager.get_personal_facts()

    if facts:
        prompt += " Things the user asked you to remember:"

        for fact in facts:
            prompt += f" {fact};"

    if current_document_path:
        prompt += (
            f" A document is currently loaded: "
            f"{current_document_path}."
        )

    return prompt


# ---------------- CHAT ----------------

def chat(user_text):
    global reply_already_spoken

    messages = [
        {
            "role": "system",
            "content": build_system_prompt()
        }
    ]

    messages.extend(conversation_history)

    messages.append({
        "role": "user",
        "content": user_text
    })

    spoken_count = {"value": 0}

    def on_sentence(sentence):
        # Speak each sentence the moment it is
        # generated, instead of waiting for the
        # full reply.

        if voice_enabled:
            speak(sentence)
            spoken_count["value"] += 1

    answer = ask_ollama_streaming(messages, on_sentence)

    if answer is None:
        # Streaming failed; fall back to the
        # simple non-streaming request.

        answer = ask_ollama(messages)

        if voice_enabled and spoken_count["value"] == 0:
            speak(answer)

    answer = answer.strip() or "..."

    reply_already_spoken = (
        voice_enabled and spoken_count["value"] > 0
    )

    conversation_history.append({
        "role": "user",
        "content": user_text
    })

    conversation_history.append({
        "role": "assistant",
        "content": answer
    })

    if len(conversation_history) > MAX_HISTORY:
        conversation_history[:] = conversation_history[-MAX_HISTORY:]

    return answer


# ---------------- TOOLS ----------------

def run_system_info_tool():
    print("[Shadow TOOL: Reading system information...]")

    info = get_system_info()

    lines = []

    for key, value in info.items():
        lines.append(f"{key}: {value}")

    return "\n".join(lines)


def run_open_tool(text):
    name = text[5:].strip()

    if name.lower().startswith("folder "):
        name = name[7:].strip()

    if not name:
        return "Tell me which app or folder to open, baa."

    ok, message = open_application(name)

    if ok:
        return message

    ok, folder_message = open_folder(name)

    if ok:
        return folder_message

    return message


def run_list_files_tool(text):
    if " in " in text:
        folder_name = text.split(" in ", 1)[1].strip()
    else:
        folder_name = text.replace("list files", "").strip()

    ok, message = list_folder(folder_name)

    return message


def summarize_current_document():
    summary_text = current_document_text

    max_summary_chars = 20000

    if len(summary_text) > max_summary_chars:
        summary_text = summary_text[:max_summary_chars]

        summary_text += (
            "\n\n[Document summary was "
            "limited to the first 20,000 "
            "characters.]"
        )

    document_prompt = f"""
You are Shadow, a local AI assistant.

The following text was extracted locally
from a PDF document.

Analyze ONLY the information contained
in this document.

Do not invent information.

Do not assume information that is not
explicitly present.

Give a concise and useful summary.

DOCUMENT:
----------------
{summary_text}
----------------

Summarize this document in simple language.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "You are Shadow. "
                "Answer using only the "
                "provided document. "
                "Never invent facts."
            )
        },

        {
            "role": "user",
            "content": document_prompt
        }
    ]

    return ask_ollama(messages)


def run_document_tool(text):

    global current_document_text
    global current_document_path
    global current_document_chunks

    stripped = text.strip()

    if stripped.lower().startswith("read document"):
        file_path = stripped[13:].strip()

    elif stripped.lower().startswith("read md"):
        file_path = stripped[7:].strip()

    else:
        file_path = stripped[8:].strip()

    if not file_path:

        return "Please provide the PDF file path."

    print(
        "[Shadow TOOL: Reading PDF...]"
    )

    document_text = read_document(
        file_path
    )

    # A missing/unsupported file returns None,
    # so check that BEFORE calling .strip().

    if not document_text or not document_text.strip():

        return (
            "I could not read any text from that "
            "file, baa. It may be missing, "
            "unsupported, or the OCR found nothing."
        )

    # Store complete extracted document

    current_document_text = document_text

    current_document_path = file_path

    # Remember this document in long-term
    # document memory so future sessions
    # know we have read it before.

    memory_manager.add_document_memory(
        title=os.path.basename(file_path),
        path=file_path,
        summary=document_text[:200]
    )

    # Create document chunks

    current_document_chunks = split_into_chunks(
        document_text,
        chunk_size=3000
    )

    print(
        "[Shadow TOOL: "
        f"Created {len(current_document_chunks)} "
        "document chunk(s)...]"
    )

    print(
        "[Shadow TOOL: "
        "Sending document to local AI...]"
    )

    summary = summarize_current_document()

    return (
        summary
        + "\n\n[Document loaded. Ask me anything "
        "about it, or type 'close document' to "
        "go back to normal chat.]"
    )


def answer_document_question(question):
    # Meaning-based retrieval when enabled,
    # with automatic keyword fallback inside
    # semantic_search if Ollama is unavailable.

    if settings_store.get_setting("semantic_search"):

        relevant_chunks = semantic_search.semantic_search_chunks(
            current_document_chunks,
            question,
            max_results=3
        )

    else:
        relevant_chunks = search_chunks(
            current_document_chunks,
            question,
            max_results=3
        )

    if relevant_chunks:
        context = "\n\n---\n\n".join(relevant_chunks)

    else:
        context = current_document_text[:3000]

    history_lines = []

    for entry in conversation_history[-4:]:
        role = "User" if entry["role"] == "user" else "Shadow"

        history_lines.append(f"{role}: {entry['content']}")

    recent_chat = "\n".join(history_lines)

    document_prompt = f"""
You are Shadow.

Answer the user's question using ONLY the
document excerpts below.

If the answer is not in the excerpts, say
honestly that you could not find it in the
document.

Do not invent information.

Recent conversation (for follow-up context):
----------------
{recent_chat}
----------------

DOCUMENT EXCERPTS:
----------------
{context}
----------------

Question: {question}
"""

    messages = [
        {
            "role": "system",
            "content": (
                "You are Shadow. "
                "Answer using only the "
                "provided document. "
                "Never invent facts."
            )
        },

        {
            "role": "user",
            "content": document_prompt
        }
    ]

    answer = ask_ollama(messages)

    conversation_history.append({
        "role": "user",
        "content": question
    })

    conversation_history.append({
        "role": "assistant",
        "content": answer
    })

    if len(conversation_history) > MAX_HISTORY:
        conversation_history[:] = conversation_history[-MAX_HISTORY:]

    return answer


def close_document():
    global current_document_text
    global current_document_path
    global current_document_chunks

    current_document_text = None
    current_document_path = None
    current_document_chunks = []

    return "Document closed, baa. Back to normal chat."


def check_ollama_status():
    # Quick check whether the local AI server
    # is answering.

    try:
        status_request = urllib.request.Request(
            "http://localhost:11434/api/version"
        )

        with urllib.request.urlopen(
            status_request,
            timeout=2
        ) as response:
            response.read()

        return True

    except Exception:
        return False


def get_time_greeting():
    hour = time.localtime().tm_hour

    if hour < 12:
        return "Good morning"

    if hour < 17:
        return "Good afternoon"

    return "Good evening"


def morning_briefing():
    print("[Shadow TOOL: Preparing your briefing...]")

    user_name = memory_manager.get_user_name()

    greeting = get_time_greeting()

    if user_name:
        opening = f"{greeting}, {user_name}!"

    else:
        opening = f"{greeting}, baa!"

    today = time.strftime("%A, %d %B %Y")

    lines = [
        opening,
        f"Today is {today}.",
        ""
    ]

    # Memory recap.

    for line in memory_manager.briefing_memory_lines():
        lines.append(line)

    lines.append("")

    # Document status.

    if current_document_text:
        lines.append(
            f"A document is loaded: "
            f"{current_document_path}"
        )

    else:
        lines.append("No document is loaded right now.")

    # System status.

    lines.append("")

    if check_ollama_status():
        lines.append("My brain (Ollama) is online.")

    else:
        lines.append(
            "Ollama is offline right now, baa. "
            "Start it when you want me to think."
        )

    info = get_system_info()

    lines.append(
        f"CPU: {info.get('Processor', 'unknown')}"
    )

    lines.append(
        f"CPU cores: {info.get('CPU Cores', 'unknown')}"
    )

    lines.append("")
    lines.append("What can I do for you today, baa?")

    return "\n".join(lines)


def handle_speed_command(direction):
    current = get_speech_rate()

    if direction == "faster":
        new_rate = current + 30

    elif direction == "slower":
        new_rate = current - 30

    else:
        new_rate = DEFAULT_SPEECH_RATE

    new_rate = set_speech_rate(new_rate)

    if direction == "faster" and new_rate == current:
        return "I am already at my fastest speed, baa."

    if direction == "slower" and new_rate == current:
        return "I am already at my slowest speed, baa."

    return f"Speaking speed set to {new_rate} words per minute."


def handle_voice_command(turn_on):
    global voice_enabled

    voice_enabled = turn_on

    # Remember this for the next session.

    settings_store.set_setting(
        "voice_enabled",
        turn_on
    )

    if turn_on:
        return "Voice output is ON, baa."

    return "Voice output is OFF, baa."


def summarize_window_text(text):
    # Short one-sentence summary of what a
    # watched window now shows. Called by the
    # watcher thread whenever content changes.

    limited = text[:2500]

    prompt = f"""
You are Shadow.

The text below was read from a window the
user asked you to watch. It just changed.

Describe in ONE short sentence what the
window now shows.

WINDOW TEXT:
----------------
{limited}
----------------
"""

    messages = [
        {
            "role": "system",
            "content": (
                "You are Shadow. Summarize the "
                "window content in one short "
                "sentence. Use only the provided "
                "text."
            )
        },

        {
            "role": "user",
            "content": prompt
        }
    ]

    return ask_ollama(messages)


def show_help():
    return (
        "Here is what I can do, baa:\n"
        "- 'system information' - verified PC facts\n"
        "- 'open notepad' / 'open chrome' / 'open downloads'\n"
        "- 'show files in downloads'\n"
        "- 'read pdf <full path>' (OCR included)\n"
        "- then ask questions about the loaded document\n"
        "- 'summarize the document'\n"
        "- 'close document'\n"
        "- 'remember that ...' / 'remember project <name>: ...'\n"
        "- 'what do you know about me' - full memory report\n"
        "- 'show project <name>' - project notes\n"
        "- 'what do you remember' / 'forget that ...'\n"
        "- 'good morning' - daily briefing\n"
        "- 'show settings' - see all my settings\n"
        "- 'semantic on' / 'semantic off' - meaning-based document search\n"
        "- 'what do you see' - look at my screen and describe it\n"
        "- 'look at my screen and <question>' - ask about what is on screen\n"
        "- 'move mouse to center' / 'click' / 'double click' / 'right click'\n"
        "- 'scroll down 5' / 'type hello' / 'press enter'\n"
        "  (computer actions ALWAYS ask yes/no first - say no to cancel;\n"
        "   slam the mouse into the top-left corner for emergency stop)\n"
        "- 'watch notepad' - watch a window, announce changes\n"
        "- 'watch status' / 'stop watching'\n"
        "- 'noise on' / 'noise off' - noise suppression for my ears\n"
        "- 'backup now' / 'list backups' / 'restore backup 1'\n"
        "- 'voice on' / 'voice off' - toggle speech\n"
        "- 'speak faster' / 'speak slower' / 'speak normal'\n"
        "- 'listen' - say one command out loud\n"
        "- 'voice chat' - talk to Shadow hands-free\n"
        "- anything else - just talk to me"
    )


# ---------------- ROUTING ----------------

def get_response(text):
    global reply_already_spoken

    # Every new request starts clean; only chat()
    # sets the flag when it already spoke the
    # answer while generating it.

    reply_already_spoken = False

    text_lower = text.lower().strip()

    # Remove a leading "Shadow" if the user addresses it

    if text_lower.startswith("Shadow"):
        text = text[6:].strip()
        text_lower = text.lower()

    if not text:
        return "Yes, baa?"

    # ---- COMPUTER CONTROL: CONFIRMATION GATE ----

    global pending_action

    lowered_yes = text_lower in (
        "yes", "yep", "yeah", "yup", "sure",
        "ok", "okay", "do it", "confirm",
        "yes please", "go ahead",
    )

    lowered_no = text_lower in (
        "no", "nope", "cancel", "stop",
        "don't", "dont", "never mind",
        "nevermind", "forget it", "abort",
    )

    if pending_action is not None:

        if lowered_yes:
            action = pending_action["action"]
            pending_action = None

            return computer_control.execute_action(
                action
            )

        if lowered_no:
            pending_action = None

            return (
                "Cancelled, baa. Nothing was touched."
            )

        # Anything else while an action waits:
        # the confirmation is void - never let an
        # old staged action fire by accident.

        pending_action = None

        return (
            "I cancelled the waiting action since "
            "you said something else, baa. Tell me "
            "again if you still want it."
        )

    # ---- COMPUTER CONTROL: ACTION TRIGGERS ----

    command_text = text_lower

    if command_text.startswith("computer, "):
        command_text = command_text[
            len("computer, "):].strip()

    action = computer_control.parse_command(
        command_text
    )

    if action is not None:
        description = (
            computer_control.describe_action(action)
        )

        pending_action = {
            "action": action,
            "description": description,
        }

        return (
            f"I am about to {description}. "
            "Shall I? Say yes or no, baa."
        )

    # ---- WINDOW WATCHER ----

    if text_lower == "watch status":
        return window_watcher.watch_status_text()

    if text_lower == "stop watching":
        return window_watcher.stop_watching()

    if text_lower == "watch":
        return (
            "Tell me which window to watch, baa. "
            "Like: watch notepad - or watch chrome."
        )

    if text_lower.startswith("watch "):
        query = text[6:].strip()

        if not query:
            return (
                "Tell me which window to watch, "
                "baa. Like: watch notepad"
            )

        ok, message = window_watcher.start_watching(
            query,
            summarize=summarize_window_text,
            speak_fn=speak,
            voice_on=lambda: voice_enabled,
        )

        return message

    if text_lower in ("help", "what can you do"):
        return show_help()

    if text_lower.startswith(
        ("good morning", "morning briefing", "daily briefing")
    ) or text_lower == "briefing":
        return morning_briefing()

    if text_lower in ("backup", "backup now", "create backup"):
        return backup.create_backup_text()

    if text_lower in ("list backups", "show backups"):
        return backup.list_backups_text()

    if text_lower.startswith("restore backup"):
        identifier = text_lower[
            len("restore backup"):
        ].strip() or None

        return backup.restore_backup_text(identifier)

    if text_lower.startswith("my name is "):
        return remember_name(text[11:].strip().title())

    if text_lower.startswith("remember that "):
        return remember_fact(text[14:].strip())

    if text_lower.startswith("remember project"):
        return remember_project_note(text_lower)

    if text_lower.startswith("show project"):
        return show_project_memory(text_lower)

    if text_lower.startswith(("what do you know about me", "what all do you know about me")):
        return knowledge_report()

    if text_lower.startswith("what do you know about"):
        subject = text_lower[len("what do you know about"):].strip()

        reply = memory_manager.projects_summary_text(subject)

        if reply is None:
            return f"I have no notes about '{subject}' yet, baa."

        return reply

    if "what do you remember" in text_lower:
        return build_memory_reply()

    if text_lower.startswith("forget that "):
        return forget_fact(text[12:].strip())

    if text_lower.startswith(("system information", "system info")):
        return run_system_info_tool()

    if text_lower.startswith("open "):
        return run_open_tool(text_lower)

    if text_lower.startswith(("show files in ", "list files in ")):
        return run_list_files_tool(text_lower)

    if text_lower.startswith(("read pdf", "read txt", "read md", "read document")):
        # The path parser inside run_document_tool also
        # handles a missing space like "read pdfC:\..."

        return run_document_tool(text)

    if text_lower.startswith(("summarize the document", "summarize document", "document summary")):
        if current_document_text:
            return summarize_current_document()

        return "No document is loaded, baa. Use 'read pdf <path>' first."

    if text_lower == "speak faster":
        return handle_speed_command("faster")

    if text_lower == "speak slower":
        return handle_speed_command("slower")

    if text_lower in ("speak normal", "normal speed"):
        return handle_speed_command("normal")

    if text_lower == "speak speed":
        return f"My current speaking speed is {get_speech_rate()} words per minute."

    if text_lower in ("show settings", "settings"):
        return settings_store.get_all_settings_text()

    if text_lower == "voice on":
        return handle_voice_command(True)

    if text_lower == "voice off":
        return handle_voice_command(False)

    if text_lower in (
        "noise on",
        "noise suppression on",
    ):
        import noise_suppression

        noise_suppression.set_enabled(True)

        return (
            "Noise suppression is ON, baa. I will "
            "subtract the room noise before "
            "listening."
        )

    if text_lower in (
        "noise off",
        "noise suppression off",
    ):
        import noise_suppression

        noise_suppression.set_enabled(False)

        return (
            "Noise suppression is OFF, baa. I will "
            "listen to the raw microphone."
        )

    if text_lower in (
        "semantic on",
        "semantic search on"
    ):
        settings_store.set_setting(
            "semantic_search",
            True
        )

        return (
            "Semantic search is ON, baa. I will now "
            "find answers by meaning, not just "
            "matching words."
        )

    if text_lower in (
        "semantic off",
        "semantic search off"
    ):
        settings_store.set_setting(
            "semantic_search",
            False
        )

        return (
            "Semantic search is OFF, baa. I will use "
            "the older keyword matching."
        )

    if text_lower in ("close document", "clear document", "forget document"):
        return close_document()

    if text_lower in (
        "what do you see",
        "look at my screen",
        "look at the screen",
        "describe my screen",
        "describe the screen",
        "read my screen",
        "read the screen",
    ) or text_lower.startswith(
        (
            "what do you see ",
            "look at my screen ",
            "describe my screen ",
            "read my screen ",
        )
    ):
        # Screen vision: capture ONLY on request,
        # OCR it, and let the model describe it.

        question = None

        for trigger in (
            "what do you see",
            "look at my screen",
            "describe my screen",
            "read my screen",
        ):
            if text_lower.startswith(trigger):
                remainder = text[
                    len(trigger):
                ].strip(" ,.?-")

                lowered_remainder = (
                    remainder.lower()
                )

                if lowered_remainder and lowered_remainder not in (
                    "on my screen",
                    "on the screen",
                    "right now",
                    "now",
                ):
                    question = remainder

                    if question.lower().startswith("and "):
                        question = question[4:].strip()

                break

        return screen_vision.describe_screen(
            question
        )

    # If a document is loaded, treat the message as a
    # question about that document.

    if current_document_chunks:
        return answer_document_question(text)

    return chat(text)


# ---------------- MAIN ----------------

def process_voice_command(heard):
    # Returns False when the user wants to leave
    # voice chat, True otherwise.

    lowered = heard.lower().strip()

    if lowered in (
        "exit",
        "stop",
        "exit voice chat",
        "stop listening",
        "goodbye",
        "quit"
    ):
        speak("Voice chat off. Goodbye, baa.")
        wait_until_speech_done()
        return False

    if lowered == "wake word off":
        speak("Wake word off. I will listen after every beep.")
        wait_until_speech_done()
        return "open"

    reply = get_response(heard)

    print(f"Shadow: {reply}")
    print()

    # Let sentence-by-sentence speech finish.

    wait_until_speech_done()

    if voice_enabled and not reply_already_spoken:
        speak(reply)
        wait_until_speech_done()

    # Shadow just spoke; drop that audio so she
    # cannot hear her own voice as a wake word.

    flush_audio_queue()

    return True


def voice_chat_mode():
    print()
    print("[VOICE CHAT] Wake word is ON.")
    print("[VOICE CHAT] Say 'Shadow' to get my attention.")
    print("[VOICE CHAT] Say 'Shadow' then your command,")
    print("[VOICE CHAT] or just 'Shadow' and wait for the beep.")
    print("[VOICE CHAT] Say 'wake word off' for beep mode, or 'exit' to leave.")
    print()

    speak("Voice chat on. Say Shadow to talk to me, baa.")

    wait_until_speech_done()

    flush_audio_queue()

    wake_mode = True

    while True:
        if wake_mode:
            print("[VOICE CHAT] ...listening for 'Shadow'...")

            found, command = listen_for_wake_word(30)

            if not found:
                continue

            print("[VOICE CHAT] Wake word detected!")

            if command:
                print(f"You (voice): {command}")

                result = process_voice_command(command)

                if result is False:
                    break

                if result == "open":
                    wake_mode = False

                continue

            # Just the wake word: ask for the
            # command with a short chime.

            speak("Yes baa?")
            wait_until_speech_done()

            flush_audio_queue()

            print("[VOICE CHAT] Beep!")

            heard = listen_for_command(7)

            if not heard:
                print("[VOICE CHAT] I did not hear anything.")
                continue

            print(f"You (voice): {heard}")

            result = process_voice_command(heard)

            if result is False:
                break

            if result == "open":
                wake_mode = False

        else:
            print("[VOICE CHAT] Beep!")

            heard = listen_for_command(7)

            if not heard:
                print("[VOICE CHAT] I did not hear anything.")
                speak("I did not hear anything, baa.")
                wait_until_speech_done()
                flush_audio_queue()
                continue

            print(f"You (voice): {heard}")

            lowered = heard.lower().strip()

            if lowered == "wake word on":
                speak("Wake word on. Say Shadow to talk to me.")
                wait_until_speech_done()
                flush_audio_queue()

                wake_mode = True
                continue

            result = process_voice_command(heard)

            if result is False:
                break


def main():
    # Launch the desktop window with:
    #   python Shadow.py gui

    if len(sys.argv) > 1 and sys.argv[1].lower() == "gui":
        import gui

        gui.run()
        return

    print("=" * 50)
    print("Shadow v0.12")
    print("Local AI Assistant")
    print("=" * 50)
    print("Shadow: Online.")
    print("Type 'help' for commands, or 'exit' to stop.")
    print()

    if voice_enabled:
        speak("Shadow online. Good to see you, baa.")

        # Warm up the ears now so the first
        # spoken command is heard from the
        # very first word.

        print("[Shadow EARS] Warming up microphone...")

        try:
            setup_stt()

        except Exception as error:
            print(f"[Shadow EARS] Warm-up failed: {error}")

    listen_mode = False

    while True:
        try:
            user_input = input("You: ").strip()

            if listen_mode and not user_input:
                user_input = listen_for_command(7).strip()

                if user_input:
                    print(f"You (voice): {user_input}")

        except (KeyboardInterrupt, EOFError):
            print("\nShadow: Goodbye, baa!")
            break

        if not user_input:
            continue

        lowered = user_input.lower()

        if lowered in ("exit", "quit", "bye", "goodbye"):
            print("Shadow: Goodbye, baa!")

            if voice_enabled:
                speak("Goodbye, baa.")

            break

        if lowered == "listen":
            listen_mode = True

            print("Shadow: Listening mode ON.")
            print("Press Enter to speak, or type normally.")
            print()

            if voice_enabled:
                speak("Listening mode on.")

            continue

        if lowered == "stop listening":
            listen_mode = False
            close_stt()

            print("Shadow: Listening mode OFF.")
            print()

            if voice_enabled:
                speak("Listening mode off.")

            continue

        if lowered == "voice chat":
            voice_chat_mode()
            continue

        reply = get_response(user_input)

        print(f"Shadow: {reply}")
        print()

        if voice_enabled and not reply_already_spoken:
            speak(reply)

    close_stt()


if __name__ == "__main__":
    main()
