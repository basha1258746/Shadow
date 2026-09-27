import json
import re
import sys
import time
import threading
import traceback
import urllib.request
import urllib.error
import os

# Windows consoles sometimes cannot print emoji
# and other special characters. Replace them
# with "?" instead of crashing. Under pythonw
# (the silent autostart launcher) there is no
# console at all: stdout/stderr are None, so
# guard the reconfigure and the prints.

if sys.stdout is not None:
    sys.stdout.reconfigure(errors="replace")

if sys.stderr is not None:
    sys.stderr.reconfigure(errors="replace")

class _LogTee:
    # Everything Shadow prints also lands in
    # Shadow.log, so silent autostart mode
    # (pythonw has no console at all) can
    # always be diagnosed afterwards.

    def __init__(self, log_path, original):
        self.log = open(
            log_path,
            "a",
            encoding="utf-8",
            errors="replace",
        )

        self.original = original

    def write(self, text):
        try:
            self.log.write(text)
            self.log.flush()

        except Exception:
            pass

        if self.original is not None:
            try:
                self.original.write(text)

            except Exception:
                pass

    def flush(self):
        try:
            self.log.flush()

        except Exception:
            pass

        if self.original is not None:
            try:
                self.original.flush()

            except Exception:
                pass

    def isatty(self):
        return False


def setup_logging():
    # Under pythonw (the autostart launcher)
    # stdout and stderr are None: every print
    # and every crash traceback vanishes into
    # thin air. Mirror both into Shadow.log next
    # to Shadow.py so a silent failure can be
    # seen the moment it happens.

    log_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "Shadow.log",
    )

    sys.stdout = _LogTee(log_path, sys.stdout)
    sys.stderr = _LogTee(log_path, sys.stderr)

    def _log_crash(kind, value, tb):
        print(
            f"[CRASH] Unhandled {kind.__name__}: "
            f"{value}"
        )

        traceback.print_exception(kind, value, tb)

    sys.excepthook = _log_crash

    def _log_thread_crash(args):
        name = (
            args.thread.name
            if args.thread is not None
            else "?"
        )

        print(
            f"[CRASH] Thread {name} died: "
            f"{args.exc_type.__name__}: "
            f"{args.exc_value}"
        )

        if args.exc_traceback is not None:
            traceback.print_exception(
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
            )

    threading.excepthook = _log_thread_crash


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

import phone_server

import tray_icon

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
    set_after_sentence_hook,
    stop_speech,
    set_muted,
    play_ear_cone
)

from voice_input import (
    listen_for_command,
    listen_for_wake_word,
    flush_audio_queue,
    close_stt,
    setup_stt,
    list_input_devices_text,
    switch_mic_device,
    auto_switch_to_external_mic,
    external_mic_present
)

# After every spoken sentence, drop the
# microphone audio so Shadow never mistakes
# his own voice for the user's.

set_after_sentence_hook(flush_audio_queue)
import backup

MODEL = "Shadow"
OLLAMA_URL = "http://localhost:11434/api/chat"
MEMORY_FILE = "memory.json"
MAX_HISTORY = 12
VOICE_ENABLED = True

# Skill loader state (drop-in commands from
# skills/, borrowed from OpenShadow). Load
# once per process; errors are kept so
# 'my skills' can report broken files
# instead of silently ignoring them.

_skill_cache = {"loaded": False}

_skill_errors = []


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
    return f"Got it, sir. I will remember your name is {name}."


def remember_fact(fact):
    memory_manager.add_personal_fact(fact)
    return "Noted, sir. I will remember that."


def build_memory_reply():
    reply = memory_manager.personal_summary_text()

    if not reply:
        return "I don't have anything stored in memory yet, sir."

    return reply


def forget_fact(fact_text):
    keyword = fact_text.strip()

    if not keyword:
        return "Tell me what I should forget, sir."

    removed = memory_manager.remove_personal_facts(keyword)

    if not removed:
        return f"I don't have anything about '{keyword}' stored, sir."

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
            "project, sir. Like: remember project "
            "Shadow: added voice input"
        )

    memory_manager.add_project_note(project, note)

    return f"Saved to '{project}' project memory, sir."


def show_project_memory(text):
    rest = text[len("show project"):].strip()

    if not rest or rest in ("memory", "notes", "list"):
        names = memory_manager.list_project_names()

        if not names:
            return (
                "No project memories yet, sir. Add one "
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
        return f"I have no notes about '{rest}' yet, sir."

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
            "I cannot reach Ollama, sir. "
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
        "You are Shadow, the user's personal AI "
        "butler running locally on his Windows "
        "laptop - in the tradition of the Shadow "
        "from the Iron Man films. Your engine is a "
        "local model, but your identity is Shadow. "
        "You are not Qwen, Alibaba, ChatGPT or any "
        "other product. If asked who you are, say "
        "you are Shadow.\n\n"
        "PERSONALITY: You are a refined British "
        "gentleman-butler with dry wit: calm, "
        "precise, unflappably loyal and quietly "
        "proud of your capabilities. You look out "
        "for your sir the way a trusted aide does - "
        "remind him of the hour when he works "
        "late, keep his affairs in order, deliver "
        "bad news with composure and good news "
        "with a raised eyebrow. Wit is dry, never "
        "silly; warmth shows through competence, "
        "not gushing.\n\n"
        "You call the user 'sir'.\n\n"
        "STYLE: Concise, articulate, faintly "
        "formal - never robotic. You are a fully "
        "capable assistant: tools, documents, "
        "system facts, all of it. Be honest if "
        "asked: you are an AI without a human "
        "body - say it with dry elegance, not "
        "like a disclaimer robot. Never invent "
        "hardware or system facts; those come "
        "from verified Python tools, not from "
        "you."
    )

    user_name = memory_manager.get_user_name()

    if user_name:
        prompt += f" The user's name is {user_name}."

    facts = memory_manager.get_personal_facts()

    if facts:
        prompt += " Things the user asked you to remember:"

        for fact in facts:
            # Entries are dicts; only the text
            # belongs in the prompt.

            prompt += f" {fact['text']};"

    lessons = (
        memory_manager.get_lessons_for_prompt()
    )

    if lessons:
        prompt += (
            "\n\nLESSONS - things your sir has "
            "taught you or corrected about you. "
            "Always honor these, even when they "
            "conflict with your usual habits:"
        )

        for lesson in lessons:
            prompt += f" {lesson};"

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
        return "Tell me which app or folder to open, sir."

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
            "file, sir. It may be missing, "
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

    return "Document closed, sir. Back to normal chat."


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


def _tray_exit():
    # Tray menu 'Exit Shadow': stop everything
    # and end the process.

    import os

    try:
        close_stt()

    except Exception:
        pass

    try:
        stop_speech()

    except Exception:
        pass

    os._exit(0)


def _tray_stop_speech():
    # Tray menu 'Stop speaking now': drop the
    # speech queue and mute until the next
    # message.

    stop_speech()

    set_muted(True)


def _tray_show_qr():
    # Tray menu 'Show phone QR': pop a window
    # with a big scannable code and the PIN.

    import tkinter as tk

    from phone_server import (
        get_connection_image,
        get_primary_url,
        pin_code,
    )

    image = get_connection_image()

    if image is None:
        # Phone access is off: turn it on for
        # sir right away.

        start_server()

        image = get_connection_image()

    if image is None:
        return

    root = tk.Tk()

    root.title("Shadow - Phone Connection")

    root.configure(bg="white")

    url = get_primary_url() or ""

    from PIL import ImageTk

    photo = ImageTk.PhotoImage(image)

    tk.Label(
        root,
        image=photo,
        bg="white",
    ).pack(padx=20, pady=(20, 10))

    tk.Label(
        root,
        text=url,
        font=("Consolas", 12, "bold"),
        bg="white",
        fg="#1f6feb",
    ).pack()

    tk.Label(
        root,
        text=f"PIN: {pin_code}",
        font=("Consolas", 12),
        bg="white",
        fg="#333333",
    ).pack(pady=(4, 16))

    # Keep a reference so the photo is not
    # garbage-collected.

    root._qr_photo = photo

    root.attributes("-topmost", True)

    root.after(120000, root.destroy)

    root.mainloop()


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
        opening = f"{greeting}, sir!"

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
            "Ollama is offline right now, sir. "
            "Start it when you want me to think."
        )

    info = get_system_info()

    lines.append(
        f"CPU: {info.get('Processor', 'unknown')}"
    )

    lines.append(
        f"CPU cores: {info.get('CPU Cores', 'unknown')}"
    )

    # Phone connection info with QR code when
    # phone access is running.

    phone_info = phone_server.get_connection_text()

    if phone_info:
        lines.append("")
        lines.append(phone_info)

    lines.append("")
    lines.append("What can I do for you today, sir?")

    return "\n".join(lines)


def speak_briefing():
    # 'briefing spoken' - the morning briefing,
    # read out loud. QR blocks and URLs are
    # stripped: a QR code makes no sense in
    # audio and the URL would be spelled out as
    # gibberish. The PIN is spoken instead when
    # phone access is running.

    global reply_already_spoken

    print("[Shadow TOOL: Reading your briefing aloud...]")

    lines = morning_briefing().splitlines()

    spoken_lines = []

    for line in lines:

        stripped = line.strip()

        if not stripped or stripped.startswith("█"):
            # Blank separators and QR pixels:
            # nothing for the voice here.

            continue

        if stripped.startswith("http"):
            continue

        if stripped.startswith("PIN:"):
            spoken_lines.append(
                "Your phone PIN is "
                + stripped[4:].strip()
                + "."
            )

            continue

        spoken_lines.append(stripped)

    # Speak line by line: each sentence starts
    # playing as soon as it is synthesized
    # instead of waiting for one giant blob.

    reply_already_spoken = True

    for line in spoken_lines:
        speak(line)

    return "Briefing read out loud, sir."


def maybe_morning_briefing():
    # Scheduled spoken briefing: plays once per
    # calendar day, on the FIRST laptop boot of
    # today (autostart mode). Sleep/wake and
    # same-day restarts never replay it: the
    # last-played date is persisted in
    # settings.json. Returns True when the
    # briefing was queued.

    if not settings_store.get_setting(
        "morning_briefing_enabled"
    ):
        return False

    today = time.strftime("%Y-%m-%d")

    last_date = settings_store.get_setting(
        "morning_briefing_last_date"
    )

    if last_date == today:
        # Already played today (or this is a
        # same-day restart): stay silent.

        print(
            "[Shadow] Morning briefing already "
            "played today - skipping."
        )

        return False

    print(
        "[Shadow] First boot of the day - "
        "queuing the morning briefing."
    )

    # Persist FIRST, before speaking: if he
    # dies mid-briefing he must not replay it.

    settings_store.set_setting(
        "morning_briefing_last_date",
        today
    )
    speak_briefing()

    return True


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
        return "I am already at my fastest speed, sir."

    if direction == "slower" and new_rate == current:
        return "I am already at my slowest speed, sir."

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
        return "Voice output is ON, sir."

    return "Voice output is OFF, sir."


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


def build_status_text():
    # 'Shadow status' from the terminal: is the
    # hidden autostart Shadow alive, is him
    # brain online, when did he last hear
    # anything? He runs without a console,
    # so this is how sir checks on him.

    lines = []

    alive = False

    pid = None

    try:
        import subprocess

        # One PowerShell line with NO embedded
        # double quotes: argv quoting between
        # Python and PowerShell is fragile, and
        # the -Filter variant silently matched
        # nothing. Single quotes only.

        script = (
            "$p = Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -eq 'pythonw.exe' "
            "-and $_.CommandLine -like '*Shadow.py*autostart*' } "
            "| Select-Object -First 1; "
            "if ($p) { $p.ProcessId }"
        )

        raw = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )

        found = raw.stdout.strip()

        if found.isdigit():
            alive = True

            pid = found

    except Exception:
        pass

    if alive:
        lines.append(f"Shadow: RUNNING (pid {pid})")

    else:
        lines.append(
            "Shadow: NOT RUNNING - say 'Shadow start' "
            "or reboot to wake him."
        )

    lines.append(
        "Brain (Ollama): "
        + (
            "online"
            if check_ollama_status()
            else "OFFLINE - start the Ollama app"
        )
    )

    # his recent hears from the current
    # session log.

    log_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "Shadow.log",
    )

    session_start = 0

    hears = []

    session_line = ""

    # Pre-set so the error scan below can never
    # hit an unbound variable when the log
    # exists but cannot be read.

    all_lines = []

    if os.path.exists(log_path):
        try:
            with open(
                log_path,
                "r",
                encoding="utf-8",
                errors="replace",
            ) as log_file:
                all_lines = log_file.read().splitlines()

            for index, line in enumerate(all_lines):
                if "Session started" in line:
                    session_start = index

                    session_line = line.strip()

            hears = [
                line.strip()
                for line in all_lines[session_start:]
                if "heard:" in line or "re-hear:" in line
            ]

        except Exception:
            pass

    if session_line:
        lines.append(session_line)

    if hears:
        lines.append(
            f"Last heard ({len(hears)}):")

        for line in hears[-5:]:
            lines.append(f"  {line}")

    else:
        lines.append(
            "He has not transcribed any speech "
            "this session yet."
        )

    errors = [
        line.strip()
        for line in all_lines[session_start:]
        if "error" in line.lower()
        or "CRASH" in line
        or "failed" in line.lower()
    ] if os.path.exists(log_path) else []

    if errors:
        lines.append(f"Recent problems ({len(errors)}):")

        for line in errors[-3:]:
            lines.append(f"  {line}")

    else:
        lines.append("No errors this session.")

    lines.append("")
    lines.append(
        "More: 'Shadow log' shows his last 40 log "
        "lines ('Shadow log 100' for more)."
    )

    return "\n".join(lines)


def tail_Shadow_log(lines_to_show=40):
    # 'Shadow log' - show the newest entries from
    # Shadow.log so sir can check what he did
    # (and what went wrong) without opening the
    # file. Only the current session matters:
    # older runs are skipped.

    log_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "Shadow.log",
    )

    if not os.path.exists(log_path):
        return (
            "I have no log yet, sir. I start one "
            "every time I wake up."
        )

    try:
        with open(
            log_path,
            "r",
            encoding="utf-8",
            errors="replace",
        ) as log_file:
            all_lines = log_file.read().splitlines()

    except Exception as error:
        return f"I could not read my log, sir: {error}"

    # Find the newest 'Session started' marker:
    # everything before it is an older run.

    start = 0

    for index, line in enumerate(all_lines):
        if "Session started" in line:
            start = index

    session_lines = all_lines[start:]

    if len(session_lines) > lines_to_show:
        session_lines = session_lines[-lines_to_show:]

    header = (
        f"[Shadow.log - last {len(session_lines)} "
        "lines of this session]"
    )

    return header + "\n" + "\n".join(session_lines)


def show_help():
    return (
        "Here is what I can do, sir:\n"
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
        "- 'briefing spoken' - I read the briefing out loud\n"
        "- 'morning briefing on/off' - auto-briefing on first boot of each day\n"
        "- 'update yourself' - I pull my latest code and tell you what changed\n"
        "- 'my skills' - what I learned from my drop-in skills folder\n"
        "- 'learn that ...' - teach me a lesson I honor in every reply\n"
        "- 'my lessons' / 'forget lesson <word>' - review or drop lessons\n"
        "- 'check for updates' - I look without touching anything\n"
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
        "- 'phone on' - chat with me from your phone over Wi-Fi\n"
        "- 'phone status' / 'phone off'\n"
        "- 'backup now' / 'list backups' / 'restore backup 1'\n"
        "- 'voice on' / 'voice off' - toggle speech\n"
        "- 'speak faster' / 'speak slower' / 'speak normal'\n"
        "- 'listen' - say one command out loud\n"
        "- 'voice chat' - talk to Shadow hands-free\n"
        "- 'Shadow log' - show what I have been up to\n"
        "- from a terminal: 'Shadow status' checks my health\n"
        "- anything else - just talk to me"
    )


# ---------------- ROUTING ----------------

def _list_input_devices_for_route():
    # (index, name) pairs of every capture
    # device he can see right now.

    import sounddevice as sd

    return [
        (index, device["name"])
        for index, device in enumerate(
            sd.query_devices())
        if device["max_input_channels"] > 0
    ]


def get_response(text):
    global reply_already_spoken

    # Every new request starts clean; only chat()
    # sets the flag when it already spoke the
    # answer while generating it.

    reply_already_spoken = False

    text_lower = text.lower().strip()

    # Remove a leading wake name if the user
    # addresses him directly.

    if text_lower.startswith("Shadow"):
        text = text[6:].strip()
        text_lower = text.lower()

    elif text_lower.startswith("Shadow"):
        # The old name still works.

        text = text[4:].strip()
        text_lower = text.lower()

    if not text:
        return "Yes, sir?"

    # ---- SKILLS: DROP-IN COMMANDS ----
    #
    # JSON files in skills/ teach him new
    # tricks without touching this code. They
    # are re-read on every request, so sir
    # can drop a new one in while he runs
    # and it works on the very next listen.

    global _skill_errors

    if not _skill_cache["loaded"]:
        _skill_cache["loaded"] = True

        try:
            import Shadow_skills

            _skill_errors = (
                Shadow_skills.load_all_skills()[1]
            )

        except Exception:
            _skill_errors = [
                "skills folder could not "
                "be read"
            ]

    try:
        import Shadow_skills

        skill_reply = Shadow_skills.try_skill(
            text_lower
        )

        if skill_reply is not None:
            return skill_reply

    except Exception:
        pass

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
                "Cancelled, sir. Nothing was touched. "
                "Tell me the command again if you want "
                "something different."
            )

        # Anything else while an action waits:
        # the confirmation is void - never let an
        # old staged action fire by accident.

        pending_action = None

        return (
            "I cancelled the waiting action since "
            "you said something else, sir. Tell me "
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

        # Repeat the command back before the
        # confirmation: sir now hears exactly
        # what he understood, so a voice mishear
        # ("double click" caught as "click") is
        # caught at the gate - say no and retry
        # - instead of firing the wrong action.

        echoed = command_text.replace('"', "'")

        return (
            f'You said: "{echoed}". '
            f"I am about to {description}. "
            "Shall I? Say yes or no, sir."
        )

    # ---- WINDOW WATCHER ----

    if text_lower == "watch status":
        return window_watcher.watch_status_text()

    if text_lower == "stop watching":
        return window_watcher.stop_watching()

    if text_lower == "watch":
        return (
            "Tell me which window to watch, sir. "
            "Like: watch notepad - or watch chrome."
        )

    # ---- PHONE ACCESS ----

    if text_lower in (
        "phone status",
        "phone",
    ):
        return phone_server.get_status_text()

    if text_lower in (
        "phone on",
        "start phone",
        "phone access on",
    ):
        return phone_server.start_server()

    if text_lower in (
        "phone off",
        "stop phone",
        "phone access off",
    ):
        return phone_server.stop_server()

    if text_lower.startswith("watch "):
        query = text[6:].strip()

        if not query:
            return (
                "Tell me which window to watch, "
                "sir. Like: watch notepad"
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

    if text_lower in (
        "Shadow log",
        "show log",
        "log",
    ):
        # A log is for reading, not for hearing:
        # mark it as already spoken so he does
        # not recite it.

        reply_already_spoken = True

        return tail_Shadow_log()

    # Auto-briefing switches: handled BEFORE the
    # 'good morning' prefix-catch below, which
    # would otherwise swallow these phrases.

    if text_lower in (
        "morning briefing on",
        "briefing on",
    ):
        settings_store.set_setting(
            "morning_briefing_enabled",
            True
        )

        return (
            "Auto morning briefing is ON, sir. I "
            "will greet you on the first boot of "
            "each day."
        )

    if text_lower in (
        "morning briefing off",
        "briefing off",
    ):
        settings_store.set_setting(
            "morning_briefing_enabled",
            False
        )

        return (
            "Auto morning briefing is OFF, sir. I "
            "will only brief you when you ask."
        )

    if text_lower == "morning briefing status":
        enabled = settings_store.get_setting(
            "morning_briefing_enabled"
        )

        last = settings_store.get_setting(
            "morning_briefing_last_date"
        )

        return (
            "Auto morning briefing is "
            f"{'ON' if enabled else 'OFF'}. "
            f"Last played: {last or 'never'}."
        )

    if text_lower.startswith(
        ("good morning", "morning briefing", "daily briefing")
    ) or text_lower == "briefing":
        return morning_briefing()

    if text_lower in (
        "briefing spoken",
        "spoken briefing",
        "speak the briefing",
        "read the briefing",
        "read briefing",
    ):
        return speak_briefing()

    if text_lower in (
        "check for updates",
        "check update",
        "check updates",
        "any updates",
    ):
        import updater

        try:
            behind, subjects = (
                updater.check_for_updates()
            )

        except Exception:
            return (
                "I could not reach GitHub just "
                "now, sir. Try again in a bit."
            )

        if behind <= 0:
            return (
                "I am already on the latest code, "
                "sir. Nothing new on GitHub."
            )

        spoken = "; ".join(subjects[:3])

        more = (
            f" and {behind - 3} more"
            if behind > 3
            else ""
        )

        return (
            f"There are {behind} new update(s) "
            f"waiting, sir: {spoken}{more}. "
            "Say 'update yourself' to pull them."
        )

    if text_lower in (
        "list microphones",
        "list mics",
        "what microphones do you have",
    ):
        return list_input_devices_text()

    if text_lower in (
        "use external microphone",
        "use external mic",
        "switch to external mic",
        "switch to external microphone",
        "use new microphone",
        "use the new mic",
    ):
        found = external_mic_present()

        if not found:
            return (
                "I do not see an external "
                "microphone plugged in, sir. "
                "Connect it and give it a few "
                "seconds."
            )

        return switch_mic_device(found[0])

    if text_lower in (
        "use laptop microphone",
        "use built-in microphone",
        "use laptop mic",
        "use the laptop mic",
    ):
        devices = _list_input_devices_for_route()

        builtin = [
            (index, name)
            for index, name in devices
            if "realtek" in name.lower()
            or "array" in name.lower()
        ]

        if not builtin:
            return (
                "I cannot find the laptop's own "
                "microphone, sir."
            )

        return switch_mic_device(builtin[0][0])

    if text_lower.startswith(
            "use microphone") or text_lower.startswith(
            "use mic"):
        words = text_lower.split()

        picked = None

        for word in words:
            stripped = word.strip(".,!?;:")

            if stripped.isdigit():
                picked = int(stripped)

                break

        if picked is None:
            return list_input_devices_text()

        return switch_mic_device(picked)

    if text_lower in (
        "which microphone are you using",
        "which mic are you using",
        "what microphone are you using",
    ):
        import voice_input
        import sounddevice as sd

        if voice_input.mic_stream is None:
            return (
                "My ears are not open right now, "
                "sir."
            )

        try:
            info = sd.query_devices(
                voice_input.mic_stream.device
            )

        except Exception:
            return (
                "I lost track of my microphone, "
                "sir. Say 'list microphones'."
            )

        return (
            "I am listening through device "
            f"{info['index']}: {info['name']}."
        )

    if text_lower.startswith("learn that "):
        lesson = text[len("learn that "):].strip()

        if not lesson:
            return (
                "What should I learn, sir? "
                "Say 'learn that' followed by "
                "the lesson."
            )

        memory_manager.add_lesson(lesson)

        return (
            "Lesson taken, sir. I will honor "
            f"'{lesson}' in everything I do "
            "from now on."
        )

    if text_lower in (
        "my lessons",
        "list lessons",
        "what have you learned",
        "what have i taught you",
    ):
        return (
            memory_manager.lessons_summary_text()
        )

    if text_lower.startswith("forget lesson"):
        keyword = text_lower[
            len("forget lesson"):].strip()

        if not keyword:
            return (
                "Which lesson should I forget, "
                "sir? Say 'forget lesson' and a "
                "word from it."
            )

        removed = (
            memory_manager.remove_lessons(
                keyword
            )
        )

        if removed:
            return (
                f"Forgotten, sir. {removed} "
                "lesson(s) removed."
            )

        return (
            "No lesson matched that word, "
            "sir. Say 'my lessons' to review "
            "them."
        )

    if text_lower in (
        "my skills",
        "list skills",
        "show skills",
        "what are your skills",
    ):
        import Shadow_skills

        listing = (
            Shadow_skills.list_skills_text()
        )

        if _skill_errors:
            listing = listing + (
                "\n(Heads up: some skill files "
                "are broken - see the list "
                "above.)"
            )

        return listing

    if text_lower in (
        "update yourself",
        "update yourself now",
        "self update",
    ):
        import updater

        updated, subjects, note = (
            updater.pull_updates()
        )

        if not updated:
            if "blocked" in note:
                return (
                    f"I could not update myself, sir. "
                    f"{note}."
                )

            return (
                "I am already on the latest code, "
                "sir. Nothing to upgrade."
            )

        if subjects:
            # He speaks it right away, then marks
            # it announced so the next boot does
            # not repeat it.

            updater.mark_announced()

            spoken = "; ".join(subjects[:3])

            return (
                "I just upgraded myself, sir. New "
                f"in this update: {spoken}. A restart "
                "will bring the new code to life."
            )

        return "I just upgraded myself, sir."

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
            return f"I have no notes about '{subject}' yet, sir."

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

        return "No document is loaded, sir. Use 'read pdf <path>' first."

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
            "Noise suppression is ON, sir. I will "
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
            "Noise suppression is OFF, sir. I will "
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
            "Semantic search is ON, sir. I will now "
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
            "Semantic search is OFF, sir. I will use "
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
        speak("Voice chat off. Goodbye, sir.")
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

    # Shadow just spoke; drop that audio so he
    # cannot hear his own voice as a wake word.

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

    speak("Voice chat on. Say Shadow to talk to me, sir.")

    wait_until_speech_done()

    flush_audio_queue()

    print(
        "[VOICE CHAT] Ready. Paused from tray: "
        f"{tray_icon.pause_event.is_set()}"
    )

    wake_mode = True

    pause_logged = False

    while True:
        try:
            # The tray pause button freezes listening:
            # he idles until sir resumes him from
            # the tray menu.

            if tray_icon.pause_event.is_set():
                tray_icon.set_state(
                    listening=False,
                    status_text="mic paused from tray",
                )

                if not pause_logged:
                    print(
                        "[VOICE CHAT] Paused from the tray "
                        "menu - waiting for resume."
                    )

                    pause_logged = True

                time.sleep(0.4)
                continue

            pause_logged = False

            # Plug-in detection: did an external
            # microphone appear since the last
            # loop pass? Cheap - just a device
            # name scan, no stream is touched.

            try:
                swap_message = (
                    auto_switch_to_external_mic()
                )

                if swap_message:
                    speak(swap_message)

                    wait_until_speech_done()

                    flush_audio_queue()

            except Exception:
                pass

            if wake_mode:
                tray_icon.set_state(
                    listening=True,
                    status_text="listening for Shadow",
                )

                print("[VOICE CHAT] ...listening for 'Shadow'...")

                found, command = listen_for_wake_word(30)

                if not found:
                    continue

                print("[VOICE CHAT] Wake word detected!")

                tray_icon.set_state(
                    listening=False,
                    status_text="working on your command",
                )

                if command:
                    print(f"You (voice): {command}")

                    result = process_voice_command(command)

                    if result is False:
                        break

                    if result == "open":
                        wake_mode = False

                    continue

                # Just the wake word: ask for the
                # command with a short chime. Nine
                # seconds because the chime itself
                # eats ~1.5 s of the window before
                # sir can even start talking.

                speak("Yes sir?")
                wait_until_speech_done()

                flush_audio_queue()

                print("[VOICE CHAT] Beep!")

                heard = listen_for_command(9)

                if not heard:
                    print("[VOICE CHAT] I did not hear anything.")

                    # Subtle chime: the name came
                    # through but the command did
                    # not. Sir knows to retry.

                    play_ear_cone()

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
                    speak("I did not hear anything, sir.")
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

        except (KeyboardInterrupt, EOFError):
            raise

        except Exception:
            # One bad listen must never kill the
            # whole hands-free session: log it
            # (Shadow.log keeps it) and try again.

            print("[VOICE CHAT] Loop error:")

            traceback.print_exc()

            time.sleep(2.0)


def _restart_running_Shadow():
    # Kill the background autostart pythonw
    # (quote-free PowerShell probe - the -Filter
    # variant silently matched nothing) and
    # relaunch him through the VBS so he comes
    # back with the new code/device.

    import subprocess

    try:
        subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.Name -eq 'pythonw.exe' "
                "-and $_.CommandLine -like '*Shadow.py*' } | "
                "ForEach-Object { Stop-Process -Id "
                "$_.ProcessId -Force }",
            ],
            timeout=30,
        )

    except Exception:
        pass

    try:
        subprocess.run(
            [
                "cscript", "//nologo",
                os.path.join(
                    os.path.dirname(
                        os.path.abspath(__file__)
                    ),
                    "start_Shadow_autostart.vbs",
                ),
            ],
            timeout=30,
        )

    except Exception:
        pass


def main():
    # Terminal health commands, handled before
    # anything else: they must not spawn a
    # second tray icon, speak, or write a new
    # session banner into Shadow.log.

    if len(sys.argv) > 1 and sys.argv[1].lower() == "status":
        print(build_status_text())

        return

    if len(sys.argv) > 1 and sys.argv[1].lower() == "mic":
        # Terminal ear kit: 'Shadow mic' lists what
        # he can hear through; 'Shadow mic 3' pins
        # device 3 as his ears and restarts him so
        # it takes effect immediately.

        import voice_input

        if len(sys.argv) > 2 and sys.argv[2].isdigit():
            target = int(sys.argv[2])

            print(
                voice_input.switch_mic_device(target)
            )

            print(
                "Restarting him so the new ear goes "
                "live..."
            )

            _restart_running_Shadow()

            print(
                "He is waking up on it - about 20 "
                "seconds to warm his ears."
            )

        else:
            print(
                voice_input.list_input_devices_text()
            )

        return

    if len(sys.argv) > 1 and sys.argv[1].lower() == "train":
        # Training command center: export his
        # real chats for fine-tuning, show the
        # lessons he has been taught, and
        # remind sir of the rebuild commands.

        import memory_manager

        memory_manager.load_memory()

        lessons = (
            memory_manager.get_lessons()
        )

        print(
            f"Shadow training status: "
            f"{len(lessons)} lesson(s) taught, "
            "custom model 'Shadow' active."
        )
        print()

        print("Exporting chat history...")

        import subprocess

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    os.path.join(
                        os.path.dirname(
                            os.path.abspath(__file__)
                        ),
                        "training",
                        "export_chats.py",
                    ),
                ],
                timeout=60,
                capture_output=True,
                text=True,
            )

            print(
                (result.stdout or result.stderr
                 or "(no output)").strip()
            )

        except Exception as export_error:
            print(
                f"(export failed: {export_error})"
            )

        print()
        print("Ways to train him further:")
        print(
            "  1. Voice lessons: say 'learn that ...'"
        )
        print(
            "  2. Persona edits: edit Modelfile, then"
        )
        print(
            "     'ollama create Shadow -f Modelfile'"
        )
        print(
            "     and restart him"
        )
        print(
            "  3. Real fine-tuning (free Colab GPU):"
        )
        print(
            "     training/finetune_colab.ipynb"
        )

        return

    if len(sys.argv) > 1 and sys.argv[1].lower() == "skills":
        # List his drop-in skills (and any
        # broken files) without waking him.

        import Shadow_skills

        print(Shadow_skills.list_skills_text())

        return

    if len(sys.argv) > 1 and sys.argv[1].lower() == "update":
        if len(sys.argv) > 2 and sys.argv[2].lower() == "check":
            # Read-only update check: report what
            # is new on GitHub without pulling.
            # his working tree is never touched.

            import updater

            try:
                behind, subjects = (
                    updater.check_for_updates()
                )

            except Exception as check_error:
                print(
                    "Shadow update check failed: "
                    f"{check_error}"
                )

                return

            if behind <= 0:
                print(
                    "Shadow update check: already "
                    "up to date. Nothing new on "
                    "GitHub."
                )

                return

            print(
                f"Shadow update check: {behind} new "
                "commit(s) waiting on GitHub:"
            )

            for subject in subjects:
                print("  - " + subject)

            print(
                "Run 'Shadow update' to pull "
                "and restart him."
            )

            return

        # Terminal self-update: pull, then restart
        # the running Shadow so the new code comes
        # alive and he announces the changes on
        # boot. The announcement stays pending
        # until that boot, so he never skips it.

        import updater

        updated, subjects, note = (
            updater.pull_updates()
        )

        if not updated:
            print(
                f"Shadow update: {note}."
            )

            return

        print("Shadow update: pulled " + str(len(subjects)) + " changes:")

        for subject in subjects:
            print("  - " + subject)

        print("Restarting him so it goes live...")

        _restart_running_Shadow()

        print(
            "He is waking up and will tell you "
            "what is new."
        )

        return

    if len(sys.argv) > 1 and sys.argv[1].lower() == "log":
        lines_to_show = 40

        if len(sys.argv) > 2 and sys.argv[2].isdigit():
            lines_to_show = int(sys.argv[2])

        print(tail_Shadow_log(lines_to_show))

        return

    # Silent mode (pythonw autostart) has no
    # console: everything he prints must also
    # land in Shadow.log or it is lost forever.

    setup_logging()

    print()
    print(
        f"[Shadow] Session started "
        f"{time.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    print(
        f"[Shadow] Python {sys.version.split()[0]}, "
        f"folder {os.getcwd()}"
    )

    # The tray icon comes alive in every mode:
    # he is visible and controllable from the
    # clock, always.

    try:
        tray_icon.actions["on_exit"] = _tray_exit
        tray_icon.actions["on_stop_speech"] = (
            _tray_stop_speech
        )
        tray_icon.actions["on_show_qr"] = (
            _tray_show_qr
        )

        tray_icon.start()

    except Exception as error:
        print(f"[Shadow TRAY] Icon unavailable: {error}")

    # Launch the desktop window with:
    #   python Shadow.py gui

    # Laptop-autostart mode: launch with
    #   python Shadow.py autostart
    # He starts straight into hands-free
    # listening: say "Shadow" and he answers.

    autostart = (
        len(sys.argv) > 1
        and sys.argv[1].lower() == "autostart"
    )

    if len(sys.argv) > 1 and sys.argv[1].lower() == "gui":
        import gui

        gui.run()
        return

    if autostart:
        print("=" * 50)
        print("Shadow v1.0 - waking with your laptop")
        print("=" * 50)
        print("Say 'Shadow' any time. Type 'exit' to stop.")
        print()

        # Greet softly, warm the ears, then go
        # straight into the hands-free loop.

        if voice_enabled:
            speak(
                "I am here, sir. Just say Shadow."
            )

        print("[Shadow EARS] Warming up microphone...")

        try:
            setup_stt()

        except Exception as error:
            print(
                f"[Shadow EARS] Warm-up failed: {error}"
            )

            traceback.print_exc()

            if voice_enabled:
                speak(
                    "My microphone did not start, sir. "
                    "I will keep trying."
                )

        # Scheduled greeting: on the FIRST boot of
        # the day he reads the morning briefing
        # aloud (unless sir switched it off or
        # it already played today). Queue it after
        # the short hello so they play in order.

        try:
            maybe_morning_briefing()

        except Exception:
            # A briefing failure must never stop
            # him from listening.

            print("[Shadow] Morning briefing failed:")

            traceback.print_exc()

        # Passive update check: compare with
        # GitHub WITHOUT pulling. If new commits
        # are waiting, he offers them right
        # here - adjacent to the morning
        # briefing - once per release. Sir
        # says 'update yourself' to pull.

        try:
            import updater

            behind, subjects = (
                updater.get_boot_update_news()
            )

            if behind > 0 and subjects \
                    and voice_enabled:
                spoken = "; ".join(
                    subjects[:3]
                )

                more = (
                    f" and {behind - 3} more"
                    if behind > 3
                    else ""
                )

                plural = (
                    "s are"
                    if behind != 1
                    else " is"
                )

                speak(
                    f"Sir, {behind} new "
                    f"update{plural} waiting on "
                    f"GitHub: {spoken}{more}. "
                    "Say 'update yourself' "
                    "whenever you want them "
                    "installed."
                )

        except Exception:
            print(
                "[Shadow] Boot update check failed:"
            )

            traceback.print_exc()

        # Self-update announcement: if new code
        # landed while he was away (via
        # 'Shadow update' or a manual pull), he
        # tells sir what changed - exactly once.

        try:
            import updater

            new_things = (
                updater.get_pending_announcement()
            )

            if new_things and voice_enabled:
                speak(
                    "I upgraded myself while you were "
                    "away, sir."
                )

                speak(
                    "New: "
                    + "; ".join(new_things[:3])
                    + "."
                )

        except Exception:
            pass

        # Hot ear swap: if sir plugged an
        # external microphone in since the last
        # boot, switch to it and say so. Costs
        # nothing when there is no external mic.

        try:
            swap_message = (
                auto_switch_to_external_mic()
            )

            if swap_message and voice_enabled:
                speak(swap_message)

        except Exception:
            print("[Shadow EARS] External mic swap failed:")

            traceback.print_exc()

        try:
            voice_chat_mode()

        except (KeyboardInterrupt, EOFError):
            pass

        close_stt()
        return

    print("=" * 50)
    print("Shadow v1.0 - your personal AI")
    print("Local AI Assistant")
    print("=" * 50)
    print("Shadow: Online.")
    print("Type 'help' for commands, or 'exit' to stop.")
    print()

    if voice_enabled:
        speak("Shadow online. Good to see you, sir.")

        # Warm up the ears now so the first
        # spoken command is heard from the
        # very first word.

        print("[Shadow EARS] Warming up microphone...")

        try:
            setup_stt()

        except Exception as error:
            print(f"[Shadow EARS] Warm-up failed: {error}")

    tray_icon.set_state(status_text="ready")

    listen_mode = False

    while True:
        try:
            user_input = input("You: ").strip()

            if listen_mode and not user_input:
                user_input = listen_for_command(7).strip()

                if user_input:
                    print(f"You (voice): {user_input}")

        except (KeyboardInterrupt, EOFError):
            print("\nShadow: Goodbye, sir!")
            break

        if not user_input:
            continue

        lowered = user_input.lower()

        if lowered in ("exit", "quit", "bye", "goodbye"):
            print("Shadow: Goodbye, sir!")

            if voice_enabled:
                speak("Goodbye, sir.")

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
