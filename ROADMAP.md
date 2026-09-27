# Week Two — Where Shadow Goes Next

Week one (Sep 23–27) built him: ears, brain, hands, voice, memory,
skills, self-updates, and a persona. Week two is about making him
**anticipate** — a butler's real skill is acting before he is asked.

Three candidate directions, evaluated against his hardware (8 GB,
i3), his safety rules (online gate), and what compounds with what is
already built.

---

## Option A — Routines & Timers ⭐ RECOMMENDED

*"Shadow, remind me to drink water every hour."*
*"Shadow, wake me at 7 with the briefing."*
*"Shadow, every evening at 9, summarize what I did today."*

A background scheduler thread: voice-set reminders, recurring
routines, timed actions. Composes with **everything he already has**
(briefing, skills, lessons, computer control) and fits 8 GB easily —
it is a loop and a JSON file, not a model.

- Effort: small-medium. Risk: low.
- Payoff: he becomes proactive — the single biggest personality leap
  available.
- Build order: one-shot reminders → recurring routines → "what's on
  my schedule today" morning tie-in.

## Option B — The Dashboard

*"Shadow, open your dashboard."* A local web page (localhost like the
phone server) showing battery, his last-heard log, lessons, skills,
upcoming reminders, live chat, and the ear diagnostics.

- Effort: medium. Risk: low (read-only view first).
- Payoff: superb visibility and demo value.
- Natural order: build **after** routines so there is something
  worth showing. The scheduler's JSON becomes the dashboard's feed.

## Option C — Voice Biometrics ("knows who is speaking")

Match the speaker before obeying: only sir's voice triggers
computer control; a roommate's "shut down" gets refused politely.

- Effort: large. Risk: high (models are heavy; far-field accuracy on
  the SST array is exactly the problem the mic war documented).
- Payoff: real security layer — but blocked until the external mic
  arrives, because distance decoding is the weak point.

---

## The recommendation, in one line

**A then B:** routines first (he anticipates), then the dashboard to
make his inner life visible — and revisit biometrics only after the
USB mic upgrade lands.

## Also queued from this session

- [ ] Distance study on the built-in array → save the baseline
      numbers (`python mic_test_now.py distance`, him stopped)
- [ ] External mic purchase (Snowball iCE or USB PnP), then a new
      distance study → the "after" table
- [ ] Colab fine-tune once ~2 weeks of chat history is banked
- [ ] Optional: strip the "Shadow" wake word entirely
