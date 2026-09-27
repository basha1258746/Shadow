# Shadow 💙

A **local-first AI companion** for Windows — he hears you, talks with you, sees your screen, reads your documents, remembers you, controls your PC *with permission*, and answers your phone. Everything runs **on your laptop**. No cloud, no API keys, no subscriptions.

> Built for one 8 GB laptop (Intel i3-1315U, Windows 10) — proof that a real assistant doesn't need a datacenter.

---

## ✨ What he can do

| Ability | How to use it |
|---|---|
| 🧠 **Local brain** | Just talk to his — Qwen3 (1.7B) via Ollama, fully offline |
| 🎙 **Hears you** | `voice chat` → say **"Shadow"** → beep → talk. Or skip the beep: **"Shadow what time is it"** in one breath (offline Vosk STT + wake grammar) |
| 🗣 **Talks to you** | Sentence-by-sentence speech while he thinks; `speak faster` / `slower` |
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
Extract the folder next to the code (128 MB, best accuracy-per-megabyte; the tiny 40 MB `vosk-model-small-en-us-0.15` works too — he picks automatically and falls back gracefully).

### 4. Run his

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
├── Shadow.bat             # Terminal command center: status / log / start / stop
├── mic_test_now.py      # Mic calibration sweep (self-healing helper)
├── vision_session.py    # Timed screen-observation diary
├── memory.json          # His long-term memory
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
briefing spoken           Shadow log  (session log)
check for updates         update yourself  (pull + restart)
my skills                 what his skills folder taught him
my lessons                what you taught him with 'learn that'
online on / online off    the internet gate (default OFF)
weather / weather tomorrow   live sky, keyless Open-Meteo
look up <topic>           Wikipedia summary
search the web for <topic>   web answer (falls back to Wikipedia)
```

### The terminal command center — `Shadow` from any folder

`Shadow.bat` is installed on the PATH (a 3-line forwarder in
`%LOCALAPPDATA%\Microsoft\WindowsApps` pointing at the repo's copy — one
source of truth), so these work from **cmd, PowerShell, anywhere**:

```
Shadow status      is he running? brain online? what did he last hear? errors?
Shadow log [N]     his last N log lines of the current session (default 40)
Shadow start       wake his now (same as laptop boot)
Shadow stop        put his to sleep
Shadow skills      his drop-in skills (and any broken files)
Shadow update check    just report what is new on GitHub, pull nothing
Shadow update      pull his latest code and restart his
Shadow             the command list
```

`Shadow status` checks the real autostart process by its command line (quote-free
PowerShell probe — the `-Filter` variant silently matched nothing), pings
Ollama, and summarizes the session: what he last heard and any errors.
The bat prefers his exact Python 3.14 interpreter and falls back to whatever
`python` is on PATH.

### His ears — pick a microphone

`Shadow mic` / say *"Shadow, list microphones"* — shows every ear he can reach and
marks the current one. "Shadow, which mic are you using" reports the live stream
device; "Shadow, use external mic" / "use laptop microphone" hot-swaps without a
restart, and `Shadow mic N` pins device N. A USB mic in his name-preference list
(yeti, snowball, logitech, webcam, speakerphone, headset…) wins over the
built-in array on its own the moment it's plugged in — he announces the swap.
Bluetooth hands-free devices never auto-win (narrowband, echo-prone audio);
pin those by hand: `Shadow mic 29`.

### Self-updates — he upgrades himself

Shadow watches his own GitHub repo (`basha1258746/Shadow`, private). Two ways in,
both safe by design:

- **`Shadow update check`** (or say *"Shadow, check for updates"*) — fetches and
  compares only. He reports how many commits are waiting and what they are.
  His working tree is **never touched** — this is pure window-shopping.
- **`Shadow update`** (or say *"Shadow, update yourself"*) — pulls with
  `--ff-only`, refuses on any conflict (sir's uncommitted work is never
  discarded), restarts his, and he **speaks the changelog on boot**: "I
  upgraded myself while you were away, sir. New: …" — announced once, never
  repeated.
- **Every boot he checks quietly** (fetch + compare, still no pulling) and —
  next to the morning briefing — mentions new commits **once per release**:
  "Sir, 2 new updates are waiting on GitHub: … Say 'update yourself' when you
  want them installed." He won't nag on later boots, and offline boots stay
  silent.

### Online mode — the internet, behind a gate

By default Shadow **never touches the internet**. Say **"online on"** and he
may; **"online off"** slams the gate again. The choice persists in
settings.json and a fresh install always boots gated.

When ON, all lookups are **keyless and free** — no accounts, no API keys:

- **weather** / **weather tomorrow** — Open-Meteo, real data for your city
  (`set my city to <name>` to change it)
- **look up <topic>** — clean Wikipedia summaries via their REST API
- **search the web for <topic>** — DuckDuckGo's instant-answer API, with an
  automatic Wikipedia fallback when the web has nothing

### The regression suite

`python tests/run_all.py` locks his core against future changes: wake-word
vocabulary, the noise gates, skill isolation and injection refusal, the
update state machine (offer once, never nag), lesson persistence, and the
online gate defaulting OFF. 21 tests, zero dependencies, safe to run while
he listens. They already caught one real bug: a fresh install would have
silently lost every settings write.

### Skills — teach him new tricks without coding

Borrowed from Stanford's **OpenShadow** framework: every command he knows
used to live deep in his source. Now `skills/*.json` files are drop-in
lessons — he re-reads the folder on **every request**, so a new file works
on his very next listen, no restart.

```json
{
    "name": "battery",
    "description": "how charged the laptop is right now",
    "match": ["battery", "battery status"],
    "steps": [
        { "run": "powershell -NoProfile -Command (Get-CimInstance Win32_Battery).EstimatedChargeRemaining" },
        { "say": "percent, sir." }
    ]
}
```

- `match` — phrases that trigger it (exact or as a sentence prefix)
- `steps` — in order: `run` a command (output is spoken), `say` fixed text;
  mix freely, max 12 steps
- Say **"my skills"** (or `Shadow skills`) to list what he learned — broken
  files are reported honestly, never silently ignored

Built-ins ship as examples: `battery`, `wifi`, and a `college timetable`
skill sir can edit with his real class schedule. `run` is deliberately
sandboxed: single simple commands only — no quotes, pipes, or redirection —
so his voice can never become a shell injection.

---

## 🔧 The microphone war stories

This laptop's SST microphone array taught us everything the hard way — if his ears misbehave on *your* hardware, these are the lessons baked into the code:

- **Warm-up dead zone** — the first ~12 s of any session capture loud-but-garbled audio; he warms up at startup so his *first* listen works
- **Never re-open a settled stream** — reopening resets the dead zone; healthy streams are reused and rebuilt only on failure
- **Open the mic natively (1 ch @ 48 kHz)** — the driver mixes the array cleanly; manual multi-channel downmix folds ultrasonic garbage into the speech band
- **Self-healing retries** — a dead stream triggers one rebuild + re-warm; a *healthy* stream is never rebuilt (each rebuild costs ~12 s of deafness — that trap once made his miss the wake word one time in three)
- **`python mic_test_now.py`** — count out loud for ~40 s; he tests every mic config and re-picks his best ear automatically

---

## 👂 Ear architecture (how he listens)

His wake word went through four live-tuned layers — each one earned by a real failure in `Shadow.log`:

1. **Name-only wake grammar** — the wake recognizer is restricted to a tiny vocabulary: his names, soundalikes (zoe, sonya, joya…), and `[unk]`. Vosk's full language model kept winning "Shadow" over words like *the*; with the grammar, the name is one of the only legal outputs and wins every time. TV chatter bounces off as `[unk]`.
2. **One-breath commands** — a rolling 6-second audio buffer rides along. When the grammar catches his name, he waits for the phrase to end (~1.5 s of quiet), then **re-hears the buffer with the full vocabulary** and pulls out the command. "Shadow what time is it" → direct answer, no beep. Name alone → the beep flow.
3. **Second-chance net** — every 5 s (and at window end) when the room was loud but the grammar matched nothing, he re-hears the full buffer and looks for his name there. Fast, loud attempts that mangle in the grammar get recovered.
4. **Bare-address rescue** — when his name's syllables arrive degraded (distance, TV), the grammar emits exactly `hey`, `[unk] hey`, `yo hey`. If that happens while the room is genuinely loud, he assumes it's you starting a phrase and waits for the command. TV says "hey" too — but far quieter, so a loudness gate (RMS > 2000) keeps it out.

**Noise gates, both directions:**

- *Before waking:* leading/trailing filler tokens (`the`, `a`, `[unk]`, `hey`, `ok`…) are stripped from anything after his name; pure filler means "name only" → beep, never a garbage command to the brain
- *After the beep:* a lone function word (`this`, `the`, `it`…) is treated as silence → the subtle **ear-cone chime** tells you to retry, instead of the brain answering fluff. Middle words are never touched — "what **the** time is it" survives

**Diagnostics:** everything he prints, hears, or crashes on lands in `Shadow.log` (gitignored) — even under `pythonw` with no console. `Shadow status` summarizes it; `Shadow log` reads it raw.

---

## 🗺 Roadmap

- [x] Core brain, tools, documents, memory
- [x] Voice: STT, TTS, wake word, noise suppression
- [x] Grammar wake word + one-breath commands + second-chance net
- [x] Desktop GUI with toolbar
- [x] Computer control with confirmation gate (now echoing the command back)
- [x] Screen vision + window watcher
- [x] Phone access over LAN
- [x] Diagnostics: Shadow.log + Shadow status/log/start/stop
- [x] Self-updates: Shadow update check / Shadow update, spoken changelog on boot
- [x] Auto morning briefing on first boot of each day
- [x] Drop-in skills system (borrowed from OpenShadow)
- [ ] Online mode (web search / weather behind an explicit switch)

---

## 📜 Notes

- Built iteratively with an AI coding agent — every commit is a real feature or a real bug hunt
- He is honest about being an AI: a refined butler with dry wit — no pretending to be human
- Named for the Shadow of the Iron Man films

*Made with patience, one microphone bug at a time. Say "Shadow" — he's listening (and if the room eats his name, he'll chime).*
