import json
import socket
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------- THE DASHBOARD ----------------
#
# Week two, option B: one local web page that
# makes his inner life visible.
#
#   http://localhost:8766
#
# Panels: status (process, brain, ears),
# reminders, lessons, skills, his last-heard
# log, and live chat that goes through the
# SAME brain and confirmation gates as the
# console and the phone.
#
# SECURITY: bind to 127.0.0.1 ONLY - the page
# exists on this laptop, unreachable from the
# network. No PIN needed because no one else
# can get here.

SERVER_PORT = 8766

server = None

server_thread = None

MAX_MESSAGE_CHARS = 2000

# One brain at a time (shared rule with the
# phone server): get_response and its
# pending_action state are not thread-safe.

brain_lock = threading.Lock()

# Dashboard-side chat history (kept small).

history = []


def _gather_status():
    status = {}

    try:
        import settings as settings_store

        status["voice"] = settings_store.get_setting(
            "voice_enabled"
        )

        status["online"] = settings_store.get_setting(
            "online_enabled"
        )

    except Exception:
        status["voice"] = "?"
        status["online"] = "?"

    try:
        import voice_input

        status["ear"] = (
            "listening"
            if voice_input.mic_stream is not None
            and voice_input.mic_stream.active
            else "closed"
        )

    except Exception:
        status["ear"] = "?"

    try:
        import urllib.request

        with urllib.request.urlopen(
            "http://localhost:11434/api/tags",
            timeout=2,
        ) as response:
            status["brain"] = (
                "online" if response.status == 200
                else "down"
            )

    except Exception:
        status["brain"] = "down"

    status["time"] = datetime.now().strftime(
        "%H:%M:%S"
    )

    return status


def _gather_reminders():
    import reminders

    with reminders._lock:
        reminders.load_reminders()

        rows = []

        for reminder in sorted(
                reminders._reminders,
                key=lambda r: r.get(
                    "fire_at", "9999")):
            recurring = reminder.get("recurring")

            if recurring:
                kind = recurring.get("kind")

                if kind == "hours":
                    every = recurring.get("every", 1)

                    when = (
                        f"every {every} hour"
                        + ("s" if every != 1 else "")
                    )

                elif kind == "daily":
                    when = (
                        f"daily at "
                        f"{reminder.get('hours', 9):02d}:"
                        f"{reminder.get('minutes', 0):02d}"
                    )

                else:
                    when = (
                        "every "
                        + reminders.WEEKDAYS[
                            recurring.get("weekday", 0)
                        ].title()
                        + " at "
                        f"{reminder.get('hours', 9):02d}:"
                        f"{reminder.get('minutes', 0):02d}"
                    )

            else:
                when = reminder.get(
                    "fire_at", "?"
                )[:16]

            rows.append(
                {"when": when,
                 "task": reminder["task"]}
            )

    return rows


def _gather_lessons():
    import memory_manager

    with memory_manager._lock if hasattr(
            memory_manager, "_lock"
    ) else _noop():
        lessons = memory_manager.get_lessons()

        return [
            {"text": lesson["text"],
             "added": lesson["added"]}
            for lesson in reversed(lessons)
        ]


class _noop:
    # A null context so the optional lock
    # above stays optional.

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _gather_skills():
    import Shadow_skills

    skills, errors = (
        Shadow_skills.load_all_skills()
    )

    return {
        "skills": [
            {"name": skill["name"],
             "description": skill["description"],
             "trigger": skill["match"][0]}
            for skill in skills
        ],
        "errors": errors,
    }


def _gather_last_heard(limit=8):
    # His most recent transcriptions, parsed
    # from Shadow.log's current session.

    import os

    log_file = os.path.join(
        os.path.dirname(
            os.path.abspath(__file__)
        ),
        "Shadow.log",
    )

    heard = []

    try:
        with open(
                log_file, "r",
                encoding="utf-8",
                errors="replace") as f:
            for line in f:
                line = line.strip()

                if line.startswith(
                        "You (voice): "):
                    heard.append(
                        line[13:]
                    )

                elif line.startswith(
                        "[Shadow EARS] command part: "
                ):
                    heard.append(
                        "(part) "
                        + line[28:]
                    )

    except Exception:
        pass

    return heard[-limit:][::-1]


def gather_state():
    # One snapshot for the page's first paint
    # and the /api/state polling.

    state = {
        "status": _gather_status(),
        "reminders": _gather_reminders(),
        "lessons": _gather_lessons(),
        "last_heard": _gather_last_heard(),
    }

    state.update(_gather_skills())

    return state


PAGE_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="30">
<title>Shadow - Dashboard</title>
<style>
  body { background:#0d1117; color:#e6edf3;
         font-family:Segoe UI, sans-serif; margin:0; }
  header { background:#161b22; padding:14px 20px;
           font-weight:600; font-size:1.1em;
           border-bottom:1px solid #30363d;
           display:flex; justify-content:space-between; }
  #dot { font-size:0.7em; padding:4px 10px;
         border-radius:12px; align-self:center; }
  .ok { background:#1a7f37; } .bad { background:#8b949e; }
  #grid { display:grid; gap:14px; padding:16px;
          grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); }
  .card { background:#161b22; border:1px solid #30363d;
          border-radius:10px; padding:12px 14px; }
  .card h2 { margin:0 0 8px; font-size:0.95em; color:#58a6ff; }
  .card ul { margin:0; padding-left:18px; }
  .card li { margin:4px 0; }
  .muted { color:#8b949e; }
  .item { margin:6px 0; padding:6px 8px; background:#0d1117;
          border-radius:6px; }
  .when { color:#3fb950; font-size:0.85em; }
  #chatbox { grid-column:1 / -1; display:flex; flex-direction:column; }
  #chat { height:220px; overflow-y:auto; background:#0d1117;
          border-radius:6px; padding:8px; margin-bottom:8px; }
  .msg { margin:4px 0; padding:6px 10px; border-radius:8px;
         max-width:80%; white-space:pre-wrap; }
  .user { background:#1f6feb; color:#fff; margin-left:auto; }
  .Shadow { background:#161b22; border:1px solid #30363d; }
  form { display:flex; gap:8px; }
  input[type=text] { flex:1; background:#21262d; color:#e6edf3;
                     border:1px solid #30363d; border-radius:6px;
                     padding:8px; }
  button { background:#1f6feb; color:#fff; border:none;
           border-radius:6px; padding:8px 14px; }
  .err { color:#f85149; font-size:0.85em; }
</style>
</head>
<body>
<header>
  <span>Shadow &mdash; Dashboard</span>
  <span id="dot" class="bad">checking&hellip;</span>
</header>
<div id="grid">
  <div class="card" id="card-status"><h2>Status</h2><div id="status">...</div></div>
  <div class="card"><h2>Reminders</h2><div id="reminders">...</div></div>
  <div class="card"><h2>Lessons</h2><div id="lessons">...</div></div>
  <div class="card"><h2>Skills</h2><div id="skills">...</div></div>
  <div class="card"><h2>Last heard</h2><div id="heard">...</div></div>
  <div class="card" id="chatbox"><h2>Chat (goes through his real brain)</h2>
    <div id="chat"></div>
    <form onsubmit="return sendMsg()">
      <input type="text" id="entry" placeholder="Talk to Shadow..."
             autocomplete="off">
      <button>Send</button>
    </form>
  </div>
</div>
<script>
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML;}

function render(s){
  const dot=document.getElementById('dot');
  const st=s.status||{};
  const parts=[];
  parts.push('ears: '+st.ear);
  parts.push('brain: '+st.brain);
  parts.push('online: '+st.online);
  const healthy = st.ear==='listening' && st.brain==='online';
  dot.textContent=parts.join('  |  ');
  dot.className=healthy?'ok':'bad';
  document.getElementById('status').innerHTML=
    '<div class="item">Ears: '+esc(st.ear)+'</div>'+
    '<div class="item">Brain (Ollama): '+esc(st.brain)+'</div>'+
    '<div class="item">Online gate: '+esc(String(st.online))+'</div>'+
    '<div class="item">Voice: '+esc(String(st.voice))+'</div>'+
    '<div class="item muted">as of '+esc(st.time)+'</div>';

  const rem=s.reminders||[];
  document.getElementById('reminders').innerHTML= rem.length?
    rem.map(r=>'<div class="item"><span class="when">'+esc(r.when)+'</span><br>'+esc(r.task)+'</div>').join(''):
    '<span class="muted">none - say &quot;remind me to ...&quot;</span>';

  const les=s.lessons||[];
  document.getElementById('lessons').innerHTML= les.length?
    '<ul>'+les.slice(0,8).map(l=>'<li>'+esc(l.text)+'</li>').join('')+'</ul>':
    '<span class="muted">none - teach him: &quot;learn that ...&quot;</span>';

  const sk=(s.skills||[]);
  const errs=(s.errors||[]);
  document.getElementById('skills').innerHTML=
    (sk.length?'<ul>'+sk.map(k=>'<li><b>'+esc(k.trigger)+'</b> - '+esc(k.description)+'</li>').join('')+'</ul>':'<span class="muted">none</span>')+
    (errs.length?'<div class="err">'+errs.map(esc).join('<br>')+'</div>':'');

  const hd=s.last_heard||[];
  document.getElementById('heard').innerHTML= hd.length?
    '<ul>'+hd.map(h=>'<li>'+esc(h)+'</li>').join('')+'</ul>':
    '<span class="muted">nothing transcribed yet</span>';
}

function poll(){ fetch('/api/state').then(r=>r.json()).then(render).catch(()=>{}); }

function addMsg(who,text){
  const chat=document.getElementById('chat');
  const div=document.createElement('div');
  div.className='msg '+who;
  div.textContent=text;
  chat.appendChild(div);
  chat.scrollTop=chat.scrollHeight;
}

function sendMsg(){
  const entry=document.getElementById('entry');
  const text=entry.value.trim();
  if(!text) return false;
  addMsg('user',text);
  entry.value='';
  fetch('/api/chat',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({text:text})})
    .then(r=>r.json())
    .then(d=>{ addMsg(d.reply?'Shadow':'user', d.reply||('error: '+(d.error||'?'))); })
    .catch(()=>addMsg('Shadow','(connection lost, sir)'));
  return false;
}

poll();
setInterval(poll, 15000);
document.getElementById('entry').focus();
</script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        # Keep the dashboard out of Shadow.log.

        pass

    def _send_json(self, data, code=200):
        body = json.dumps(data).encode("utf-8")

        self.send_response(code)

        self.send_header(
            "Content-Type",
            "application/json",
        )

        self.send_header(
            "Content-Length",
            str(len(body)),
        )

        self.end_headers()

        self.wfile.write(body)

    def _chat(self, data):
        text = str(
            data.get("text", "")
        ).strip()[:MAX_MESSAGE_CHARS]

        if not text:
            self._send_json(
                {"error": "empty message"}, 400
            )

            return

        with brain_lock:
            import Shadow

            reply = Shadow.get_response(text)

            history.append(
                {"who": "user", "text": text})

            history.append(
                {"who": "Shadow",
                 "text": reply})

            del history[:-40]

        self._send_json({"reply": reply})

    def do_GET(self):
        if self.path == "/":
            body = PAGE_TEMPLATE.encode("utf-8")

            self.send_response(200)

            self.send_header(
                "Content-Type",
                "text/html; charset=utf-8",
            )

            self.send_header(
                "Content-Length",
                str(len(body)),
            )

            self.end_headers()

            self.wfile.write(body)

            return

        if self.path == "/api/state":
            try:
                self._send_json(gather_state())

            except Exception as error:
                self._send_json(
                    {"error": str(error)}, 500
                )

            return

        if self.path == "/api/history":
            with brain_lock:
                snapshot = list(history)

            self._send_json(
                {"history": snapshot})

            return

        self._send_json(
            {"error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/api/chat":
            self._send_json(
                {"error": "not found"}, 404)

            return

        length = int(
            self.headers.get(
                "Content-Length", 0)
        )

        raw = self.rfile.read(
            min(length, MAX_MESSAGE_CHARS * 4)
        )

        try:
            data = json.loads(
                raw.decode("utf-8") or "{}")

        except Exception:
            self._send_json(
                {"error": "bad json"}, 400)

            return

        self._chat(data)


def _lan_ip_fallback():
    # Unused placeholder for symmetry with the
    # phone server; the dashboard is loopback
    # only by design.

    return "127.0.0.1"


def start_server():
    global server
    global server_thread

    if server is not None:
        return get_status_text()

    server = ThreadingHTTPServer(
        ("127.0.0.1", SERVER_PORT),
        DashboardHandler,
    )

    server_thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )

    server_thread.start()

    print(
        "[Shadow DASHBOARD] ON - "
        f"http://localhost:{SERVER_PORT}"
    )

    return get_status_text()


def stop_server():
    global server
    global server_thread

    if server is None:
        return (
            "The dashboard is not running, sir."
        )

    server.shutdown()

    server = None
    server_thread = None

    return "Dashboard closed, sir."


def get_status_text():
    if server is None:
        return (
            "The dashboard is off, sir. Say "
            "'open dashboard' and I will raise "
            "it."
        )

    return (
        "The dashboard is up, sir: "
        f"http://localhost:{SERVER_PORT} "
        "(this laptop only)."
    )


if __name__ == "__main__":
    print(start_server())

    try:
        while True:
            import time

            time.sleep(1)

    except KeyboardInterrupt:
        print(stop_server())
