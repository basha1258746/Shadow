import json
import os
from datetime import datetime

MEMORY_FILE = "memory.json"

MEMORY_VERSION = 2

MAX_PERSONAL_FACTS = 100

MAX_PROJECT_NOTES = 100

MAX_DOCUMENT_MEMORIES = 50

# Corrections and knowledge chief teaches
# with 'learn that ...'. Capped so the
# system prompt cannot grow without end.

MAX_LESSONS = 50

# The in-memory store. Shape:
# {
#   "version": 2,
#   "personal": {"user_name": str, "facts": [entry]},
#   "projects": {"name": [entry]},
#   "documents": [entry],
#   "lessons": [entry]
# }
#
# entry = {"text": str, "added": "YYYY-MM-DD HH:MM", "source": str}

memory = {}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _new_entry(text, source="user"):
    return {
        "text": text,
        "added": _now(),
        "source": source
    }


def _empty_memory():
    return {
        "version": MEMORY_VERSION,
        "personal": {
            "user_name": None,
            "facts": []
        },
        "projects": {},
        "documents": [],
        "lessons": []
    }


def load_memory():
    global memory

    memory = _empty_memory()

    if not os.path.exists(MEMORY_FILE):
        return memory

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as file:
            stored = json.load(file)

    except Exception as error:
        print(f"[SHADOW MEMORY] Could not read memory: {error}")
        return memory

    # Migration: the old flat format had
    # "user_name" and "facts" at the top level.

    if stored.get("version") != MEMORY_VERSION:

        old_name = stored.get("user_name")

        old_facts = stored.get("facts", [])

        for fact in old_facts:

            if isinstance(fact, str):
                memory["personal"]["facts"].append(
                    _new_entry(fact, source="migrated")
                )

            elif isinstance(fact, dict) and "text" in fact:
                fact["source"] = fact.get(
                    "source", "migrated"
                )
                memory["personal"]["facts"].append(fact)

        if old_name:
            memory["personal"]["user_name"] = old_name

        print(
            "[SHADOW MEMORY] Old memory format "
            "migrated to the new 3-store format."
        )

        save_memory()

        return memory

    # Already the new format: copy carefully.

    personal = stored.get("personal", {})

    memory["personal"]["user_name"] = personal.get(
        "user_name"
    )

    memory["personal"]["facts"] = personal.get(
        "facts", []
    )

    memory["projects"] = stored.get(
        "projects", {}
    )

    memory["documents"] = stored.get(
        "documents", []
    )

    memory["lessons"] = stored.get(
        "lessons", []
    )

    return memory


def save_memory():
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as file:
            json.dump(memory, file, indent=4)

    except Exception as error:
        print(f"[SHADOW MEMORY] Could not save: {error}")


# ---------------- PERSONAL ----------------

def set_user_name(name):
    memory["personal"]["user_name"] = name

    save_memory()


def get_user_name():
    return memory["personal"].get("user_name")


def add_personal_fact(text):
    fact = _new_entry(text)

    facts = memory["personal"]["facts"]

    facts.append(fact)

    while len(facts) > MAX_PERSONAL_FACTS:
        facts.pop(0)

    save_memory()

    return fact


def get_personal_facts():
    return memory["personal"]["facts"]


def add_lesson(text):
    # A lesson is a correction or a piece of
    # knowledge chief taught him explicitly
    # ('learn that ...'). Every future reply
    # sees it in the system prompt.

    lesson = _new_entry(text, source="lesson")

    lessons = memory.setdefault("lessons", [])

    # Re-teaching the same thing moves it to
    # the top instead of duplicating it.

    lowered = text.strip().lower()

    lessons[:] = [
        l for l in lessons
        if l["text"].strip().lower() != lowered
    ]

    lessons.append(lesson)

    while len(lessons) > MAX_LESSONS:
        lessons.pop(0)

    save_memory()

    return lesson


def get_lessons():
    return memory.get("lessons", [])


def remove_lessons(keyword):
    keyword = keyword.strip().lower()

    lessons = memory.get("lessons", [])

    kept = []
    removed = 0

    for lesson in lessons:
        if keyword in lesson["text"].lower():
            removed += 1

        else:
            kept.append(lesson)

    memory["lessons"] = kept

    if removed:
        save_memory()

    return removed


def get_lessons_for_prompt():
    # Plain strings, newest last, for the
    # system prompt.

    return [
        lesson["text"]
        for lesson in memory.get("lessons", [])
    ]


def lessons_summary_text():
    lessons = get_lessons()

    if not lessons:
        return (
            "You have not taught me any "
            "lessons yet, sir. Say 'learn "
            "that ...' and I will remember "
            "it in every reply."
        )

    lines = [
        f"My lessons, sir "
        f"({len(lessons)} taught):",
        "",
    ]

    for lesson in reversed(lessons):
        lines.append(
            f"- {lesson['text']} "
            f"(taught {lesson['added']})"
        )

    lines.append("")
    lines.append(
        "Say 'forget lesson <word>' to "
        "remove one."
    )

    return "\n".join(lines)


def remove_personal_facts(keyword):
    keyword = keyword.strip().lower()

    kept = []
    removed = 0

    for fact in memory["personal"]["facts"]:

        if keyword in fact["text"].lower():
            removed += 1

        else:
            kept.append(fact)

    memory["personal"]["facts"] = kept

    if removed:
        save_memory()

    return removed


def personal_summary_text():
    # The familiar "what do you remember" answer.

    user_name = get_user_name()

    facts = get_personal_facts()

    if not user_name and not facts:
        return ""

    lines = ["Here is what I remember, sir:", ""]

    if user_name:
        lines.append(f"Your name: {user_name}")

    if facts:
        lines.append("Things you asked me to remember:")

        for fact in facts:
            lines.append(f"- {fact['text']}")

    return "\n".join(lines)


# ---------------- PROJECTS ----------------

def _project_key(project):
    return project.strip().lower()


def add_project_note(project, note):
    key = _project_key(project)

    projects = memory["projects"]

    if key not in projects:
        projects[key] = []

    projects[key].append(_new_entry(note))

    while len(projects[key]) > MAX_PROJECT_NOTES:
        projects[key].pop(0)

    save_memory()


def list_project_names():
    return sorted(memory["projects"].keys())


def get_project_notes(project):
    return memory["projects"].get(
        _project_key(project)
    )


def projects_summary_text(project):
    notes = get_project_notes(project)

    if notes is None:
        return None

    display = project.strip() or "general"

    if not notes:
        return f"No notes for '{display}' yet, sir."

    lines = [
        f"Notes about '{display}' "
        f"({len(notes)} total):",
        ""
    ]

    for index, note in enumerate(notes, 1):
        lines.append(f"{index}. {note['text']}")

    return "\n".join(lines)


# ---------------- DOCUMENTS ----------------

def add_document_memory(title, path, summary):
    # Remember a document SHADOW has read, so it
    # can be found again in later sessions.

    memory["documents"].append({
        "title": title,
        "path": path,
        "summary": summary,
        "added": _now()
    })

    while len(memory["documents"]) > MAX_DOCUMENT_MEMORIES:
        memory["documents"].pop(0)

    save_memory()


def get_document_memories():
    # Newest first.

    return list(reversed(memory["documents"]))


def find_document_memory(path):
    path_lower = path.lower()

    for document in memory["documents"]:

        if document["path"].lower() == path_lower:
            return document

    return None


# ---------------- REPORT ----------------

def knowledge_report_text():
    # The full "what do you know about me" report.

    user_name = get_user_name()

    facts = get_personal_facts()

    projects = memory["projects"]

    documents = memory["documents"]

    lines = [
        "Here is everything I know about you, sir:",
        f"(as of {datetime.now().strftime('%Y-%m-%d %H:%M')})",
        ""
    ]

    # PERSONAL

    lines.append("PERSONAL")

    if user_name:
        lines.append(f"- Your name: {user_name}")

    else:
        lines.append("- I do not know your name yet.")

    if facts:
        lines.append(
            f"- {len(facts)} thing(s) you asked me "
            f"to remember:"
        )

        for index, fact in enumerate(facts, 1):
            added = fact.get("added") or "date unknown"

            lines.append(
                f"  {index}. {fact['text']} "
                f"(added {added})"
            )

    else:
        lines.append(
            "- No personal facts stored yet."
        )

    lines.append("")

    # PROJECTS

    lines.append(
        f"PROJECTS ({len(projects)})"
    )

    if projects:

        for key, notes in sorted(projects.items()):
            lines.append(
                f"- {key}: {len(notes)} note(s)"
            )

            for note in notes[-3:]:
                lines.append(f"    * {note['text']}")

            if len(notes) > 3:
                lines.append(
                    f"    ... and "
                    f"{len(notes) - 3} older note(s)"
                )

    else:
        lines.append(
            "- No project notes yet. Tell me things "
            "like: remember project shadow: added voice"
        )

    lines.append("")

    # DOCUMENTS

    lines.append(
        f"DOCUMENTS ({len(documents)})"
    )

    if documents:

        for document in documents[:5]:
            lines.append(
                f"- {document['title']} "
                f"(read {document['added']})"
            )

        if len(documents) > 5:
            lines.append(
                f"  ... and {len(documents) - 5} more."
            )

    else:
        lines.append(
            "- No documents remembered yet."
        )

    lines.append("")

    lines.append(
        "Your memory stays on this laptop, sir. "
        "Say 'forget that ...' to remove a personal fact."
    )

    return "\n".join(lines)


def briefing_memory_lines():
    # Short memory recap for the morning briefing.

    lines = []

    user_name = get_user_name()

    facts = get_personal_facts()

    project_count = len(memory["projects"])

    document_count = len(memory["documents"])

    if user_name:
        lines.append(f"- Your name is {user_name}")

    if facts:
        lines.append(
            f"- You asked me to remember "
            f"{len(facts)} thing(s):"
        )

        for fact in facts[:3]:
            lines.append(f"  * {fact['text']}")

        if len(facts) > 3:
            lines.append(
                f"  ... and {len(facts) - 3} more."
            )

    if project_count:
        lines.append(
            f"- I hold notes on {project_count} "
            f"project(s)."
        )

    if document_count:
        lines.append(
            f"- I remember {document_count} "
            f"document(s) we read."
        )

    if not lines:
        lines.append("- My memory is empty so far.")

    return lines


if __name__ == "__main__":
    print("SHADOW MEMORY MANAGER TEST")
    print("-" * 40)

    load_memory()

    print("User:", get_user_name())
    print("Facts:", len(get_personal_facts()))
    print("Projects:", list_project_names())
    print("Documents:", len(get_document_memories()))
