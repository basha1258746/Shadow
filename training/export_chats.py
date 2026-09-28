# Chat-log exporter for SHADOW fine-tuning.
#
# Reads shadow.log (he logs every heard
# command and his reply there), filters out
# wake-word noise, and writes one JSON line
# per exchange:
#
#   {"messages": [{"role": "system", ...},
#                 {"role": "user", ...},
#                 {"role": "assistant", ...}]}
#
# The output file (chat_log_export.jsonl)
# is gitignored: his conversations are
# private. Usage:
#
#   python training/export_chats.py
#
# Then feed the file to training on a free
# GPU (see training/finetune_colab.ipynb).

import json
import os
import re
import sys

LOG_FILE = os.path.join(
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
    "shadow.log",
)

OUT_FILE = os.path.join(
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
    "chat_log_export.jsonl",
)

SESSION_BANNER = "Session started"

HEARD_RE = re.compile(
    r"^You \(voice\): (.+)$"
)

# Log lines that are machinery, not chat.

NOISE_PREFIXES = (
    "[", "==", "--", "Say '", "Type '",
    "Pausing", "Paused", "resumed",
    "Voice chat on", "Listening mode",
    "Goodbye", "waking with your laptop",
    "Python 3.", "folder C:",
)

# One-word slivers from a noisy room; the
# reply to them teaches the model nothing.

MIN_USER_CHARS = 12

SYSTEM_PROMPT = (
    "You are SHADOW, the user's personal AI "
    "butler - a refined British gentleman with "
    "dry wit who calls the user 'sir'. You run "
    "locally on his Windows laptop."
)


def is_noise(line):
    stripped = line.strip()

    if not stripped:
        return True

    return stripped.startswith(NOISE_PREFIXES)


def extract_exchanges(lines):
    exchanges = []

    current_user = None

    current_reply = []

    for line in lines:
        heard = HEARD_RE.match(line.strip())

        if heard:
            # A new heard command closes any
            # open exchange.

            if current_user and current_reply:
                exchanges.append(
                    (current_user,
                     " ".join(current_reply))
                )

            current_user = heard.group(1).strip()

            current_reply = []

            continue

        if current_user is None:
            continue

        if is_noise(line):
            continue

        text = line.strip()

        if text.startswith("SHADOW:"):
            text = text[7:].strip()

        current_reply.append(text)

    if current_user and current_reply:
        exchanges.append(
            (current_user, " ".join(current_reply))
        )

    return exchanges


def main():
    if not os.path.exists(LOG_FILE):
        print("No shadow.log found - nothing to export.")
        return

    with open(LOG_FILE, "r", encoding="utf-8",
              errors="replace") as f:
        lines = f.readlines()

    exchanges = extract_exchanges(lines)

    usable = []

    for user, reply in exchanges:
        if len(user) < MIN_USER_CHARS:
            continue

        if not reply:
            continue

        if len(reply) < 10:
            continue

        usable.append({
            "messages": [
                {"role": "system",
                 "content": SYSTEM_PROMPT},
                {"role": "user",
                 "content": user},
                {"role": "assistant",
                 "content": reply},
            ]
        })

    with open(OUT_FILE, "w",
              encoding="utf-8") as f:
        for item in usable:
            f.write(json.dumps(item)
                    + "\n")

    print(f"Exported {len(usable)} exchanges "
          f"({len(exchanges) - len(usable)} "
          "filtered as noise).")
    print(f"Wrote {OUT_FILE}")
    print()
    print("Next: free GPU fine-tuning -")
    print("  open training/finetune_colab.ipynb")
    print("  in Google Colab and upload this file.")


if __name__ == "__main__":
    main()
