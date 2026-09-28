import json
import socket
import sys
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

# Reminder auto-open bookkeeping: which
# reminder ids have already raised a
# browser tab, so one reminder never
# opens a tab twice (checks fire every
# 5 seconds until deleted).

_revealed_ids = set()

# One-shot banner text shown at the top of
# the page after a reveal.

_banner = None

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
    import shadow_skills

    skills, errors = (
        shadow_skills.load_all_skills()
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
    # from shadow.log's current session.

    import os

    log_file = os.path.join(
        os.path.dirname(
            os.path.abspath(__file__)
        ),
        "shadow.log",
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
                        "[SHADOW EARS] command part: "
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

    global _banner

    state = {
        "status": _gather_status(),
        "reminders": _gather_reminders(),
        "lessons": _gather_lessons(),
        "last_heard": _gather_last_heard(),
        "banner": _banner,
    }

    state.update(_gather_skills())

    # A banner is shown once, then cleared:
    # the page that needed it has it.

    _banner = None

    return state


PAGE_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="30">
<title>SHADOW - Dashboard</title>
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
  .shadow { background:#161b22; border:1px solid #30363d; }
  form { display:flex; gap:8px; }
  input[type=text] { flex:1; background:#21262d; color:#e6edf3;
                     border:1px solid #30363d; border-radius:6px;
                     padding:8px; }
  button { background:#1f6feb; color:#fff; border:none;
           border-radius:6px; padding:8px 14px; }
  .err { color:#f85149; font-size:0.85em; }
  .del { color:#f85149; text-decoration:none; font-weight:bold;
         margin-left:8px; float:right; }
  .card form { display:flex; gap:6px; margin-top:8px; }
  .card input[type=text] { font-size:0.9em; padding:6px 8px; }
  .card button { font-size:0.9em; padding:6px 12px; }
</style>
</head>
<body>
<header>
  <span>SHADOW &mdash; Dashboard</span>
  <span id="dot" class="bad">checking&hellip;</span>
</header>
<div id="grid">
  <div class="card" id="card-status"><h2>Status</h2><div id="status">...</div></div>
  <div class="card" id="card-reminders"><h2>Reminders</h2><div id="reminders">...</div>
    <form onsubmit="event.preventDefault();addReminder();return false;">
      <input type="text" id="reminder-entry" placeholder="e.g. drink water in 20 minutes">
      <button>Remind</button>
    </form>
  </div>
  <div class="card" id="card-lessons"><h2>Lessons</h2><div id="lessons">...</div>
    <form onsubmit="event.preventDefault();addLesson();return false;">
      <input type="text" id="lesson-entry" placeholder="e.g. I prefer short answers">
      <button>Teach</button>
    </form>
  </div>
  <div class="card"><h2>Skills</h2><div id="skills">...</div></div>
  <div class="card"><h2>Last heard</h2><div id="heard">...</div></div>
  <div class="card" id="chatbox"><h2>Chat (goes through his real brain)</h2>
    <div id="chat"></div>
    <form onsubmit="return sendMsg()">
      <input type="text" id="entry" placeholder="Talk to SHADOW..."
             autocomplete="off">
      <button>Send</button>
    </form>
  </div>
</div>
<script>
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML;}

function render(s){
  const dot=document.getElementById('dot');

  if (s.banner){
    let bar=document.getElementById('banner');
    if(!bar){
      bar=document.createElement('div');
      bar.id='banner';
      bar.style.cssText='background:#9e6a03;color:#fff;padding:10px 16px;font-weight:600;';
      document.body.insertBefore(bar, document.getElementById('grid'));
    }
    bar.textContent=s.banner;
  }

  function delBtn(kind,label){
    return ' <a href="#" class="del" onclick="'+kind+'(\''+label.replace(/'/g,"\\'")+'\');return false;">\u00d7</a>';
  }
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
    rem.map(r=>'<div class="item"><span class="when">'+esc(r.when)+'</span><br>'+esc(r.task)+delBtn('delReminder',r.task)+'</div>').join(''):
    '<span class="muted">none - say &quot;remind me to ...&quot;</span>';

  const les=s.lessons||[];
  document.getElementById('lessons').innerHTML= les.length?
    les.slice(0,8).map(l=>'<div class="item">'+esc(l.text)+delBtn('delLesson',l.text)+'</div>').join(''):
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

// ---- live streaming chat ----

function sendMsg(){
  const entry=document.getElementById('entry');
  const text=entry.value.trim();
  if(!text) return false;
  addMsg('user',text);
  entry.value='';

  const chat=document.getElementById('chat');
  const live=document.createElement('div');
  live.className='msg shadow';
  live.textContent='\u2026';
  chat.appendChild(live);
  chat.scrollTop=chat.scrollHeight;

  fetch('/api/chat/stream',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({text:text})})
    .then(response=>{
      const reader=response.body.getReader();
      const decoder=new TextDecoder();
      let buffer='';
      function pump(){
        return reader.read().then(({done,value})=>{
          if(done){ return; }
          buffer+=decoder.decode(value,{stream:true});
          const lines=buffer.split('\n');
          buffer=lines.pop();
          for(const line of lines){
            if(!line.trim()) continue;
            try{
              const event=JSON.parse(line);
              if(event.piece){
                live.textContent =
                  (live.textContent==='\u2026'?'':live.textContent)
                  + event.piece;
                chat.scrollTop=chat.scrollHeight;
              }
              if(event.done){
                live.textContent=event.reply;
              }
            }catch(e){}
          }
          return pump();
        });
      }
      return pump();
    })
    .catch(()=>{ live.textContent='(connection lost, sir)'; });
  return false;
}

// ---- write actions ----

function addReminder(){
  const box=document.getElementById('reminder-entry');
  const text=box.value.trim();
  if(!text) return;
  fetch('/api/reminders/add',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({text:text})})
    .then(r=>r.json())
    .then(d=>{
      box.value='';
      if(d.error){ flash('card-reminders',d.error); }
      else { flash('card-reminders', 'Set: '+d.task); poll(); }
    });
}

function delReminder(task){
  fetch('/api/reminders/delete',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({task:task})})
    .then(()=>poll());
}

function addLesson(){
  const box=document.getElementById('lesson-entry');
  const text=box.value.trim();
  if(!text) return;
  fetch('/api/lessons/add',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({text:text})})
    .then(r=>r.json())
    .then(d=>{
      box.value='';
      if(d.error){ flash('card-lessons',d.error); }
      else { flash('card-lessons', 'Lesson taken, sir.'); poll(); }
    });
}

function delLesson(text){
  fetch('/api/lessons/delete',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({text:text})})
    .then(()=>poll());
}

function flash(cardId,message){
  const card=document.getElementById(cardId);
  let note=card.querySelector('.flash');
  if(!note){ note=document.createElement('div'); note.className='flash muted'; card.appendChild(note); }
  note.textContent=message;
  setTimeout(()=>{ note.textContent=''; }, 6000);
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
        # Keep the dashboard out of shadow.log.

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
            # Reuse the LIVE brain (shadow.py
            # running as __main__ under the
            # autostart launcher) instead of
            # re-importing: importing the module
            # here would re-execute its top level
            # - including the stdout setup, which
            # crashes when stdout is already his
            # log tee. Fall back to the import
            # only when he runs standalone (tests).

            brain = sys.modules.get("__main__")

            if not hasattr(brain, "get_response"):
                import shadow

                brain = shadow

            reply = brain.get_response(text)

            history.append(
                {"who": "user", "text": text})

            history.append(
                {"who": "shadow",
                 "text": reply})

            del history[:-40]

        self._send_json({"reply": reply})

    def do_GET(self):
        global _banner

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
        # Chat needs the length handling too,
        # so all POSTs share the body read.

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

        if self.path == "/api/chat":
            self._chat(data)

            return

        if self.path == "/api/chat/stream":
            self._chat_stream(data)

            return

        if self.path == "/api/reminders/add":
            self._add_reminder(data)

            return

        if self.path == "/api/reminders/delete":
            self._delete_reminder(data)

            return

        if self.path == "/api/lessons/add":
            self._add_lesson(data)

            return

        if self.path == "/api/lessons/delete":
            self._delete_lesson(data)

            return

        self._send_json(
            {"error": "not found"}, 404)

    def _chat_stream(self, data):
        # Live chat: the reply streams to the
        # browser sentence by sentence (the
        # page is the output device - nothing
        # is spoken aloud), through the same
        # brain, gates, and history as his
        # voice. Format: JSON lines, each
        # {"piece": ...}, then {"done": true,
        # "reply": full}.

        text = str(
            data.get("text", "")
        ).strip()[:MAX_MESSAGE_CHARS]

        if not text:
            self._send_json(
                {"error": "empty message"}, 400
            )

            return

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "application/x-ndjson",
        )

        self.send_header(
            "Cache-Control",
            "no-cache",
        )

        self.end_headers()

        pieces = []

        def on_piece(piece):
            pieces.append(piece)

            try:
                line = json.dumps(
                    {"piece": piece}) + "\n"

                self.wfile.write(
                    line.encode("utf-8"))

                self.wfile.flush()

            except Exception:
                pass

        with brain_lock:
            # Live brain first (see the note in
            # _chat): re-importing would run his
            # top level again and crash under
            # pythonw.

            brain = sys.modules.get("__main__")

            if not hasattr(brain, "chat_streaming_to_dashboard"):
                import shadow

                brain = shadow

            reply = (
                brain
                .chat_streaming_to_dashboard(
                    text, on_piece)
            )

            history.append(
                {"who": "user", "text": text})

            history.append(
                {"who": "shadow",
                 "text": reply})

            del history[:-40]

        try:
            closing = json.dumps({
                "done": True,
                "reply": reply,
            }) + "\n"

            self.wfile.write(
                closing.encode("utf-8"))

            self.wfile.flush()

        except Exception:
            pass

    def _add_reminder(self, data):
        text = str(
            data.get("text", "")
        ).strip()[:300]

        if not text:
            self._send_json(
                {"error": "empty reminder"},
                400)

            return

        import reminders

        parsed = reminders.parse_reminder(
            text)

        if parsed is None:
            self._send_json({
                "error":
                "could not find a time in "
                "that - try 'in 20 minutes' "
                "or 'at 7 pm'",
            }, 400)

            return

        reminders.add_reminder(parsed)

        self._send_json({
            "ok": True,
            "task": parsed["task"],
            "fire_at": parsed.get(
                "fire_at", "recurring"),
        })

    def _delete_reminder(self, data):
        task = str(
            data.get("task", "")
        ).strip()

        if not task:
            self._send_json(
                {"error": "no task given"},
                400)

            return

        import reminders

        removed = (
            reminders.cancel_reminder(task)
        )

        self._send_json(
            {"ok": True,
             "removed": removed})

    def _add_lesson(self, data):
        text = str(
            data.get("text", "")
        ).strip()[:500]

        if not text:
            self._send_json(
                {"error": "empty lesson"},
                400)

            return

        import memory_manager

        lesson = (
            memory_manager.add_lesson(text)
        )

        self._send_json({
            "ok": True,
            "text": lesson["text"],
            "added": lesson["added"],
        })

    def _delete_lesson(self, data):
        text = str(
            data.get("text", "")
        ).strip()

        if not text:
            self._send_json(
                {"error": "no lesson given"},
                400)

            return

        import memory_manager

        removed = (
            memory_manager.remove_lessons(
                text)
        )

        self._send_json(
            {"ok": True,
             "removed": removed})


def _lan_ip_fallback():
    # Unused placeholder for symmetry with the
    # phone server; the dashboard is loopback
    # only by design.

    return "127.0.0.1"


def reveal(focus=None, note=None):
    # Raise the dashboard in sir's browser -
    # used when a reminder fires, so a
    # reminder is never missed even with the
    # speakers muted. Deduped per note: the
    # same reminder firing again (recurring
    # checks) does not spawn tab after tab.

    global _banner

    if note:
        if note in _revealed_ids:
            return

        _revealed_ids.add(note)

        if len(_revealed_ids) > 100:
            _revealed_ids.clear()

        _banner = note

    try:
        url = f"http://localhost:{SERVER_PORT}"

        if focus:
            url += "#/" + focus

        webbrowser.open(url)

    except Exception:
        pass


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
        "[SHADOW DASHBOARD] ON - "
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
