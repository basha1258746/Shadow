import os
import shutil
from datetime import datetime

BACKUP_DIR = "backups"

# Everything that makes SHADOW SHADOW.

BACKUP_FILES = [
    "shadow.py",
    "document_reader.py",
    "app_control.py",
    "file_control.py",
    "system_info.py",
    "voice_output.py",
    "voice_input.py",
    "settings.py",
    "backup.py",
    "memory.json",
    "settings.json",
    "test.txt"
]

MAX_BACKUPS = 10


def _new_snapshot_dir(label=None):
    stamp = datetime.now().strftime(
        "%Y-%m-%d_%H-%M-%S"
    )

    if label:
        name = f"backup_{stamp}_{label}"

    else:
        name = f"backup_{stamp}"

    dest = os.path.join(BACKUP_DIR, name)

    os.makedirs(dest, exist_ok=True)

    return dest


def create_backup(label=None):
    # Copy every project file into a new
    # timestamped folder. Returns
    # (path, copied_count, missing_files).

    dest = _new_snapshot_dir(label)

    copied = 0
    missing = []

    for file_name in BACKUP_FILES:

        if os.path.exists(file_name):
            shutil.copy2(
                file_name,
                os.path.join(dest, file_name)
            )

            copied += 1

        else:
            missing.append(file_name)

    prune_backups()

    return dest, copied, missing


def list_backups():
    # Newest first.

    if not os.path.isdir(BACKUP_DIR):
        return []

    names = [
        name
        for name in os.listdir(BACKUP_DIR)
        if name.startswith("backup_")
        and os.path.isdir(
            os.path.join(BACKUP_DIR, name)
        )
    ]

    names.sort(reverse=True)

    return names


def prune_backups(keep=MAX_BACKUPS):
    # Delete the oldest snapshots beyond the
    # keep limit so the folder stays small.

    names = list_backups()

    for old_name in names[keep:]:
        shutil.rmtree(
            os.path.join(BACKUP_DIR, old_name),
            ignore_errors=True
        )


def resolve_backup(identifier=None):
    # Find a snapshot by: nothing (newest),
    # a number ("2" = second newest), or any
    # part of its name ("15-30").

    names = list_backups()

    if not names:
        return None

    if not identifier or identifier == "latest":
        return names[0]

    identifier = str(identifier).strip()

    if identifier.isdigit():
        index = int(identifier)

        if 1 <= index <= len(names):
            return names[index - 1]

        return None

    for name in names:
        if identifier in name:
            return name

    return None


def restore_backup(identifier=None):
    # Restore a snapshot. SAFETY: the current
    # state is backed up first, so a restore
    # can always be undone.

    snapshot = resolve_backup(identifier)

    if snapshot is None:
        return None

    safety_path, _, _ = create_backup(
        label="before_restore"
    )

    source = os.path.join(BACKUP_DIR, snapshot)

    restored = []

    for file_name in os.listdir(source):
        shutil.copy2(
            os.path.join(source, file_name),
            file_name
        )

        restored.append(file_name)

    return snapshot, restored, safety_path


# ---------- TEXT HELPERS FOR SHADOW ----------

def create_backup_text():
    print("[SHADOW TOOL: Creating backup...]")

    path, copied, missing = create_backup()

    lines = [
        f"Backup created, sir.",
        f"Location: {path}",
        f"Files saved: {copied}"
    ]

    if missing:
        lines.append(
            f"Skipped (not found): "
            f"{', '.join(missing)}"
        )

    return "\n".join(lines)


def list_backups_text():
    names = list_backups()

    if not names:
        return (
            "No backups yet, sir. "
            "Say 'backup now' to create one."
        )

    lines = [
        f"I have {len(names)} backup(s), sir "
        f"(newest first, keeping {MAX_BACKUPS}):",
        ""
    ]

    for index, name in enumerate(names, 1):
        lines.append(f"{index}. {name}")

    lines.append("")
    lines.append(
        "Restore with: 'restore backup 1' "
        "or 'restore backup latest'."
    )

    return "\n".join(lines)


def restore_backup_text(identifier=None):
    print("[SHADOW TOOL: Restoring backup...]")

    result = restore_backup(identifier)

    if result is None:
        return (
            "I could not find that backup, sir. "
            "Say 'list backups' to see what exists."
        )

    snapshot, restored, safety_path = result

    return (
        f"Restored snapshot: {snapshot}\n"
        f"Files restored: {len(restored)}\n\n"
        f"Your previous state was saved first: "
        f"{safety_path}\n"
        f"(So you can undo this restore.)"
    )


if __name__ == "__main__":
    print("SHADOW BACKUP TEST")
    print("-" * 40)

    path, copied, missing = create_backup()

    print(f"Created: {path}")
    print(f"Files copied: {copied}")

    if missing:
        print(f"Missing: {missing}")

    print()
    print("Snapshots now:")

    for name in list_backups():
        print("-", name)
