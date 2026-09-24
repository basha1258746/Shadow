# Shadow 💜 (formerly Shadow)

A **local-first AI companion** for Windows — she hears you, talks with you, sees your screen, reads your documents, remembers you, controls your PC *with permission*, and answers your phone. Everything runs **on your laptop**. No cloud, no API keys, no subscriptions.

> Built for one 8 GB laptop (Intel i3-1315U, Windows 10) — proof that a real assistant doesn't need a datacenter.

---

## ✨ What she can do

| Ability | How to use it |
|---|---|
| 🧠 **Local brain** | Just talk to her — Qwen3 (1.7B) via Ollama, fully offline |
| 🎙 **Hears you** | `voice chat` → say **"Shadow"** → hands-free conversation (offline Vosk STT) |
| 🗣 **Talks to you** | Sentence-by-sentence speech while she thinks; `speak faster` / `slower` |
| 👁 **Sees your screen** | `what do you see` / `look at my screen and <question>` / GUI 👁 Eyes button |
| 👀 **Watches a window** | `watch notepad` → announces + summarizes content changes |
| 🖱 **Controls the PC** | `click`, `scroll down 5`, `type hello`, `press enter` — **always asks yes/no first** |
| 📄 **Reads documents** | `read pdf C:\path\file.pdf` → OCR included → semantic (meaning-based) Q&A |
| 🧬 **Semantic search** | Finds answers by *meaning*, not keywords (local embeddings via `all-minilm`) |
| 💜 **Remembers you** | `remember that ...`, project notes, `what do you know about me` |
| ☀ **Morning briefing** | `good morning` → greeting, memory recap, date, system status |
| 📱 **Answers your phone** | `phone on` → open the printed URL on your phone, enter the PIN, chat from anywhere on your Wi-Fi |
| 🖥 **Desktop GUI** | `python Shadow.py gui` → chat window, mic button, toolbar, status dot |
| 🛟 **Disaster-proof** | `backup now` / `list backups` / `restore backup 1` + full git history |

---

## 🚀 Quick start

### 1. Install prerequisites

- **Python 3.10+** (developed on 3.14) — `winget install Python.Python.3.14`
- **Ollama** — https://ollama.com, then:
  ```
  ollama pull qwen3:1.7b
  ollama pull all-minilm
  ```
- **Tesseract OCR** — https://github.com/UB-Mannheim/tesseract/wiki (install to the default `C:\Program Files\Tesseract-OCR`)

### 2. Install Python packages

```
pip install vosk sounddevice numpy pyttsx3 pywin32 Pillow pymupdf pytesseract pyautogui pygetwindow
```

### 3. Download a speech model

```
curl -L -o vosk-model-en-us-0.22-lgraph.zip https://alphacephei.com/vosk/models/vosk-model-en-us-0.22-lgraph.zip
```
Extract the folder next to the code (128 MB, best accuracy-per-megabyte; the tiny 40 MB `vosk-model-small-en-us-0.15` works too — she picks automatically and falls back gracefully).

### 4. Run her

```
python Shadow.py          # terminal + voice
python Shadow.py gui      # desktop window
```

Then: `voice chat` → say **"Shadow"** → talk. 💬

---

## 🗂 Architecture

```
Shadow/
├── Shadow.py            # Brain: routing, prompts, streaming, tools
├── gui.py               # Tkinter desktop window (toolbar, mic, status)
├── voice_input.py       # Ears: mic handling, warm-up, wake word, STT
├── voice_output.py      # Mouth: sentence-streamed TTS, mute, speed
├── noise_suppression.py # Spectral gating, learns your room at startup
├── memory_manager.py    # Personal / projects / documents stores
├── semantic_search.py   # Meaning-based document search (all-minilm)
├── document_reader.py   # PDF/TXT/MD + OCR + shared safe OCR
├── screen_vision.py     # On-demand screenshot → OCR → description
├── window_watcher.py    # Polls one window, announces changes
├── computer_control.py  # Allowlist parser: mouse/keyboard with confirmation
├── phone_server.py      # PIN-protected LAN web chat
├── system_info.py       # Verified hardware facts (never LLM-guessed)
├── app_control.py       # Open apps/folders by name
├── file_control.py      # List folders
├── backup.py            # Timestamped snapshots + restore
├── settings.py          # Persisted settings
├── mic_test_now.py      # Mic calibration sweep (self-healing helper)
├── vision_session.py    # Timed screen-observation diary
├── memory.json          # Her long-term memory
└── settings.json        # Your preferences
```

**AI models (all local):** `qwen3:1.7b` (conversation) · `all-minilm` (embeddings) · `vosk-model-en-us-0.22-lgraph` (speech-to-text) · Tesseract (OCR)

---

## 🛡 Safety design

1. **Allowlist-only computer control** — the LLM cannot invent actions; only fixed, parsed commands exist ("delete all my files" is rejected at parse time)
2. **Confirmation gate** — every mouse/keyboard action is staged and needs an explicit **yes**; any other message voids it
3. **Failsafe** — slam the mouse into the top-left corner → instant emergency stop
4. **On-demand vision only** — screenshots happen only when you ask; nothing is saved to disk
5. **Phone access is PIN-gated** — fresh PIN per session, 401 on every request without it, LAN-only by design
6. **Never guesses hardware** — system facts come from verified Python tools
7. **Backup + git** — `backup now` snapshots everything; the repo history protects the code

---

## 🎛 All chat commands

```
help                      what do you see           watch notepad
good morning              look at my screen and ?   watch status / stop watching
system information        move mouse to center      phone on / phone status / phone off
open notepad / chrome     click / double click      voice on / voice off
show files in downloads   scroll down 5             speak faster / slower / normal
read pdf <full path>      type hello                noise on / noise off
summarize the document    press enter               semantic on / semantic off
close document            remember that ...         backup now / list backups / restore backup 1
my name is ...            remember project x: ...   show settings
what do you know about me show project x            listen  (one spoken command)
what do you remember      forget that ...           voice chat  (hands-free mode)
```

---

## 🔧 The microphone war stories

This laptop's SST microphone array taught us everything the hard way — if her ears misbehave on *your* hardware, these are the lessons baked into the code:

- **Warm-up dead zone** — the first ~12 s of any session capture loud-but-garbled audio; she warms up at startup so her *first* listen works
- **Never re-open a settled stream** — reopening resets the dead zone; healthy streams are reused and rebuilt only on failure
- **Open the mic natively (1 ch @ 48 kHz)** — the driver mixes the array cleanly; manual multi-channel downmix folds ultrasonic garbage into the speech band
- **Self-healing retries** — a failed listen triggers one rebuild + re-warm
- **`python mic_test_now.py`** — count out loud for ~40 s; she tests every mic config and re-picks her best ear automatically

---

## 🗺 Roadmap

- [x] Core brain, tools, documents, memory
- [x] Voice: STT, TTS, wake word, noise suppression
- [x] Desktop GUI with toolbar
- [x] Computer control with confirmation gate
- [x] Screen vision + window watcher
- [x] Phone access over LAN
- [ ] Online mode (web search / weather behind an explicit switch)
- [ ] Multi-window watching
- [ ] Installer + logging

---

## 📜 Notes

- Built iteratively with an AI coding agent — every commit is a real feature or a real bug hunt
- She is honest about being an AI: warm, playful — but no pretending to be human
- Repo name stays **Shadow** for history; she answers to Shadow (and still answers to "Shadow" 💙)

*Made with patience, one microphone bug at a time.*
