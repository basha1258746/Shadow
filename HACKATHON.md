# SHADOW — Nebius x NVIDIA Global AI Hackathon kit

Submission target: **Personal AI Track** · nebiusglobalaihackathon.devpost.com
Submission period closes **October 30, 2026, 10:00 am PT**.

---

## 1. Why SHADOW fits the Personal AI Track

The track asks for "an always-on, private assistant that works for you while
keeping your data under your control … persistent memory, reusable skills,
access to the tools and information you choose, and the ability to carry out
tasks across your daily workflows." SHADOW is that description, implemented:

- **Always-on** — boots with the laptop, wakes to his name from across the
  room, fires reminders in his own voice, reads the morning briefing on the
  first boot of each day.
- **Private** — every word, memory, reminder, and lesson lives on the
  laptop (`memory.json`, `reminders.json` are gitignored, yours alone). The
  online gate and the cloud brain are both **OFF by default**: he never
  touches the internet unless told to, and even then only the words of the
  current request leave the machine. Cloud brain or local brain is a spoken
  switch, per moment, not a subscription.
- **Persistent memory** — three stores (personal facts, projects, lessons)
  plus a lessons channel: "learn that X" is honored from then on, injected
  into every system prompt.
- **Reusable skills** — drop-in `skills/*.json` files teach new commands
  without code, re-read on every request (borrowed from Stanford's
  __OPENSHADOW__).
- **Daily workflows** — one-shot and recurring reminders, **routines that
  act** ("every day at 9 read the briefing and my reminders" → the briefing
  is actually read aloud), dashboard and phone chat through the same brain,
  verified system tools (battery, wifi, documents, screen).

## 2. The two hackathon requirements, mapped

| Requirement | Where it lives |
|---|---|
| Runtime call to **Nebius Token Factory** | `nebius_brain.py` → `POST {base}/chat/completions` on `https://api.tokenfactory.us-central1.nebius.com/v1`, SSE streaming, opt-in via `nebius on`, automatic fallback to local Ollama |
| At least one **NVIDIA open source model** | **Nemotron 3** family: `nvidia/nemotron-3-nano-30b` (fast lane) + `nvidia/nemotron-3-super-120b-a12b` (deep lane), routed per-message |
| Bonus: runtime **Tavily** call | `online_mode.py::_tavily_search` — web search runs Tavily-first when a key is stored, keyless DuckDuckGo/Wikipedia fallback otherwise |

Model IDs and the endpoint are settings-overridable (`nebius_fast_model`,
`nebius_deep_model`, `nebius_base_url`) so a catalog rename is a settings
fix, not a code fix.

## 3. Written explanation: how SHADOW was significantly updated
### during the Submission Period (Aug 26 – Oct 30, 2026)

SHADOW existed before the Submission Period as a local-only assistant.
During the period he was rebuilt into a cloud-capable, hackathon-track
Personal AI. In the sponsor's own tools:

1. **Nebius Token Factory integration (new)** — a complete second brain:
   `nebius_brain.py` speaks the OpenAI-compatible chat-completions protocol
   with SSE streaming, written stdlib-only to match the project's
   zero-dependency philosophy. Sentences are spoken as they arrive — the
   streaming behavior is byte-identical between cloud and local brains.
2. **NVIDIA Nemotron routing (new)** — a per-message model router sends
   everyday chat to Nemotron 3 Nano and reasoning-heavy questions
   (trigger words or prompt length) to Nemotron 3 Super — the exact
   Nano/Super split the Best Apps track description recommends, applied to
   the Personal AI track. Private `<think>` reasoning is stripped in
   transit on both brains.
3. **Secrets architecture (new)** — `secrets.json` (gitignored) plus
   environment-variable support; keys are set by voice
   (`set nebius key <key>`, `set tavily key <key>`), never echoed back,
   never committed; regression-tested (`test_secrets_never_in_settings_file`).
4. **Fallback contract (new)** — the cloud brain is one failure away from
   local at all times: missing key, HTTP error, or dead network → `None` →
   Ollama answers. Regression-tested with mocked HTTP servers
   (`tests/test_cloud_brain.py`, 8 tests; full suite now 54).
5. **Tavily web search (new)** — runtime Tavily API call for real web
   results with spoken source attribution, silently falling back to the
   keyless path.
6. **Immediately before/during the period** — the rebrand and persona
   rebuild (Shadow → Shadow, baked butler model), the drop-in skills system,
   self-updates with spoken changelog, the localhost dashboard as a
   control surface with streaming chat, reminders & acting routines, and
   the gated online mode — the whole Personal-AI feature set the track
   rewards.

## 4. Demo video script (< 3 minutes, no copyrighted music)

1. **0:00–0:25 Cold open, fully offline.** Laptop on battery, wifi icon
   off. "SHADOW" → beep → "good morning". He greets by name, reads the
   briefing: date, battery, one lesson.
2. **0:25–0:55 The private toolkit.** "remind me to stretch in 2 minutes"
   (later: it fires in his voice while we talk); "my skills"; "battery";
   open the dashboard — reminders added from the page appear in his voice.
3. **0:55–1:40 Cloud brain on.** "nebius on" → "nebius status" (endpoint,
   models, key found). Ask something simple → answered (Nano lane). Ask
   "why does a cantilever beam fail, and compare the failure modes" →
   visibly deeper answer (Super lane). Show `nebius off` → "local brain".
4. **1:40–2:10 The wire dies.** Kill the wifi while the cloud brain is on,
   ask again — he answers anyway (fallback), announcing the local brain.
   The point: private by default, cloud when chosen, never dependent.
5. **2:10–2:40 Tavily & wrap.** "online on" → "search the web for
   tomorrow's ISRO launch" → Tavily answer with sources. Close on the
   dashboard, one line of positioning: "My data never left this room
   unless I told it to."

Before recording: scrub the screen — no real memory contents, real
reminders, real timetable, real names. Fresh demo user profile.

## 5. Submission-day checklist

- [ ] **Devpost**: "Join Hackathon" on nebiusglobalaihackathon.devpost.com
      (free Devpost account). Verify eligibility (18+, India OK).
- [ ] **Nebius Builder Program**: join for Token Factory/Tavily credits.
- [ ] **Keys**: Nebius Token Factory key (+ Tavily key for the bonus).
      Store via `set nebius key` / `set tavily key` or env vars.
- [ ] **Privacy pass on repo before flipping public** (see §6).
- [ ] **GitHub About**: add `apache-2.0` license tag + topic
      `personal-ai` (the license must be visible in About).
- [ ] **Devpost form**: demo URL (dashboard video or live), text
      description (adapt §1), public repo URL, video URL (YouTube,
      public, < 3 min), track = **Personal AI**, feedback section
      (adapt §7), the updated-during-period explanation (§3).
- [ ] **Judges can run it**: README Quick Start must stand alone
      (Ollama optional? No — local brain needs it; cloud brain alone
      also works with just a key, document that clearly).

## 6. Privacy pass before going public (done / to do)

- [x] `memory.json`, `settings.json` untracked (personal facts, city, mic
      name) — disk copies untouched; fresh installs get defaults.
- [x] `skills/college-timetable.json` replaced with a clearly-labelled
      sample (real class schedule was tracked).
- [x] `secrets.json` gitignored from birth; keys never in settings.
- [ ] **History scrub before the repo goes public** — old versions of
      `memory.json`/`settings.json` (containing personal facts) remain in
      git history. Options, in order of preference:
      1. `git filter-repo --path memory.json --path settings.json
         --invert-paths` (rewrites history; needs force-push; private
         repo so no collaborators affected) — keeps the commit story.
      2. Fresh public repo with one clean commit + same files (loses the
         history; simplest; zero risk).
      Chief decides; nothing goes public without an explicit go.
- [x] Training examples (`training/butler_examples.jsonl`) checked —
      synthetic butler lines, clean.
- [ ] README screenshots (if any are added for the submission): fresh
      demo data only.

## 7. Feedback section notes (for the "Most Valuable Feedback" $100)

- Token Factory: OpenAI-compatibility meant zero new client code — the
  whole integration is one stdlib module. Wish list: a `models` listing
  endpoint documented alongside the router; clearer per-model context
  limits in the catalog.
- Nemotron 3: the Nano/Super split is a real production pattern — one
  persona, two depths; the think-tag stripping parallels Qwen3 and worked
  identically. Wish list: document `<think>` behavior per model on the
  model page.
- Builder Program credits: made the free-tier experiment possible on a
  student budget — the pay-as-you-go pricing page should show a worked
  "personal assistant" example cost.

## 8. What winning looks like (judging criteria fit)

- **Technological Implementation** — dual-brain streaming architecture,
  per-message model routing, mocked-wire test coverage, zero-dependency
  discipline on an 8 GB laptop.
- **Design** — a complete product: voice, dashboard, phone, memory,
  reminders that act, self-updates; confirmation gates everywhere.
- **Potential Impact** — private AI for people who *cannot* use cloud
  assistants (hostel wifi, restrictive networks, privacy-sensitive
  professions); one 8 GB laptop is the entire requirement.
- **Quality of the Idea** — "the cloud is a settings switch" is the
  thesis: local-first as the default, Nemotron as the upgrade, fallback
  as a contract — not a demo-day patch.
