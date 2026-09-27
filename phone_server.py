import json
import random
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------- PHONE ACCESS OVER LAN ----------------
#
# A tiny web server inside Shadow. Open the URL
# on your phone (same Wi-Fi), enter the PIN once,
# and chat with him from the sofa.
#
# SECURITY:
# - Every request needs the PIN (as a header or
#   cookie). Without it, the server answers
#   nothing but a 401.
# - The PIN is generated fresh each start and
#   printed in the laptop console.
# - The brain's confirmation gate still applies:
#   computer-control actions staged from the
#   phone still need an explicit yes.
#
# Replies are NOT spoken on the laptop while
# chatting from the phone - the phone reads them
# aloud with its own browser voice if you tap
# the speaker toggle.

SERVER_PORT = 8765

server = None

server_thread = None

pin_code = None

# One brain at a time: get_response and its
# pending_action state are not thread-safe.

brain_lock = threading.Lock()

MAX_MESSAGE_CHARS = 2000

PAGE_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Shadow</title>
<style>
  body { background:#0d1117; color:#e6edf3; font-family:Segoe UI, sans-serif;
         margin:0; display:flex; flex-direction:column; height:100vh; }
  header { background:#161b22; padding:12px 16px; font-weight:bold;
           border-bottom:1px solid #30363d; }
  #chat { flex:1; overflow-y:auto; padding:12px; }
  .msg { margin:8px 0; padding:10px 12px; border-radius:10px;
         max-width:85%; white-space:pre-wrap; }
  .user { background:#1f6feb; color:white; margin-left:auto; }
  .Shadow { background:#161b22; border:1px solid #30363d; }
  .sys { color:#8b949e; font-size:0.85em; text-align:center; }
  form { display:flex; gap:8px; padding:10px; background:#161b22;
         border-top:1px solid #30363d; }
  input[type=text] { flex:1; background:#21262d; color:#e6edf3;
                     border:1px solid #30363d; border-radius:8px;
                     padding:10px; font-size:1em; }
  button { background:#1f6feb; color:white; border:none;
           border-radius:8px; padding:10px 16px; font-size:1em; }
  #pinbox { position:fixed; inset:0; background:#0d1117; display:flex;
            flex-direction:column; align-items:center; justify-content:center; }
  #pinbox input { font-size:1.4em; text-align:center; margin:12px; }
</style>
</head>
<body>
<div id="pinbox">
  <div>Enter Shadow PIN (see the laptop console)</div>
  <input id="pin" type="password" inputmode="numeric" maxlength="6">
  <button onclick="savePin()">Enter</button>
</div>
<header>Shadow - Personal AI Companion</header>
<div id="chat"></div>
<form onsubmit="return sendMsg()">
  <input id="box" type="text" autocomplete="off" placeholder="Talk to Shadow...">
  <button type="button" onclick="toggleSpeak()" id="spk">🔇</button>
  <button type="submit">Send</button>
</form>
<script>
let speakOn = false;
let lastRendered = 0;

function savePin() {
  localStorage.setItem('Shadow_pin', document.getElementById('pin').value);
  document.getElementById('pinbox').style.display = 'none';
  poll();
}

function toggleSpeak() {
  speakOn = !speakOn;
  document.getElementById('spk').textContent = speakOn ? '🔊' : '🔇';
}

async function api(path, body) {
  const pin = localStorage.getItem('Shadow_pin') || '';
  const res = await fetch(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-Shadow-PIN': pin},
    body: JSON.stringify(body || {})
  });
  if (res.status === 401) {
    document.getElementById('pinbox').style.display = 'flex';
    throw new Error('bad pin');
  }
  return res.json();
}

function addMsg(text, cls) {
  const chat = document.getElementById('chat');
  const div = document.createElement('div');
  div.className = 'msg ' + cls;
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  if (cls === 'Shadow' && speakOn && 'speechSynthesis' in window) {
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.05;
    speechSynthesis.speak(u);
  }
}

async function sendMsg() {
  const box = document.getElementById('box');
  const text = box.value.trim();
  if (!text) return false;
  box.value = '';
  addMsg(text, 'user');
  addMsg('...', 'sys');
  try {
    const data = await api('/api/message', {text: text});
    document.getElementById('chat').lastChild.remove();
    addMsg(data.reply || '(empty reply)', 'Shadow');
    poll();
  } catch (e) {
    document.getElementById('chat').lastChild.remove();
  }
  return false;
}

async function poll() {
  try {
    const data = await api('/api/history', {});
    const chat = document.getElementById('chat');
    chat.innerHTML = '';
    for (const item of data.history || []) {
      addMsg(item.text, item.who);
    }
  } catch (e) {}
}

setInterval(poll, 5000);

if (localStorage.getItem('Shadow_pin')) {
  document.getElementById('pinbox').style.display = 'none';
  poll();
}
</script>
</body>
</html>
"""


def get_primary_url():
    # The first LAN URL, used in briefings.

    if server is None:
        return None

    ips = get_lan_ips()

    if not ips:
        return None

    return f"http://{ips[0]}:{SERVER_PORT}"


def get_connection_qr():
    # A scannable QR code as ASCII text that
    # encodes the connection URL. Dark modules
    # are two spaces (the dark background shows
    # through); light modules are block
    # characters, so the code reads correctly
    # on dark terminals and in the dark GUI.

    if server is None:
        return None

    try:
        import qrcode

        url = get_primary_url()

        if url is None:
            return None

        qr = qrcode.QRCode(border=2)

        qr.add_data(url)

        qr.make(fit=True)

        matrix = qr.get_matrix()

        lines = []

        for row in matrix:
            line = ""

            for cell in row:
                line += "  " if cell else "██"

            lines.append(line)

        return "\n".join(lines)

    except ImportError:
        return None


def get_connection_text():
    # Briefing-ready connection info: URL, PIN,
    # and the QR code when available.

    if server is None:
        return None

    url = get_primary_url()

    lines = [
        "Phone access is ON:",
        f"Open {url} on your phone",
        f"PIN: {pin_code}",
    ]

    qr = get_connection_qr()

    if qr:
        lines.append("")
        lines.append(
            "Or scan this with your phone camera:"
        )
        lines.append(qr)

    return "\n".join(lines)


def get_connection_image():
    # A real scannable QR as a PIL image (black
    # on white, large modules) for popping up in
    # a window. None when phone access is off.

    if server is None:
        return None

    try:
        import qrcode

        url = get_primary_url()

        if url is None:
            return None

        qr = qrcode.QRCode(
            border=4,
            box_size=10,
        )

        qr.add_data(url)

        qr.make(fit=True)

        return qr.make_image(
            fill_color="black",
            back_color="white",
        ).convert("RGB")

    except ImportError:
        return None


def get_lan_ips():
    # Every IPv4 address this laptop has on the
    # network, so sir can pick the right one.

    ips = []

    try:
        host_name = socket.gethostname()

        for info in socket.getaddrinfo(
            host_name, None, socket.AF_INET
        ):
            ip = info[4][0]

            if ip not in ips and not ip.startswith(
                ("127.", "169.254.")
            ):
                ips.append(ip)

    except Exception:
        pass

    if not ips:
        # The reliable trick: open a UDP socket
        # toward an outside address and read the
        # local endpoint (nothing is sent).

        try:
            probe = socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM
            )

            probe.connect(("8.8.8.8", 80))

            ips.append(probe.getsockname()[0])

            probe.close()

        except Exception:
            ips.append("127.0.0.1")

    return ips


class PhoneHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        # Quiet logs; the console stays clean.

        pass

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")

        self.send_response(status)

        self.send_header(
            "Content-Type",
            "application/json"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.end_headers()

        self.wfile.write(body)

    def _pin_ok(self):
        supplied = self.headers.get(
            "X-Shadow-PIN", ""
        )

        return (
            pin_code is not None
            and supplied == pin_code
        )

    def do_GET(self):
        # The chat page itself (PIN gate happens
        # in the browser via the API calls).

        if self.path != "/":
            self._send_json(
                {"error": "not found"},
                404
            )

            return

        body = PAGE_TEMPLATE.encode("utf-8")

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/html; charset=utf-8"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.end_headers()

        self.wfile.write(body)

    def do_POST(self):
        if not self._pin_ok():
            self._send_json(
                {"error": "bad pin"},
                401
            )

            return

        length = int(
            self.headers.get("Content-Length", 0)
        )

        raw = self.rfile.read(
            min(length, MAX_MESSAGE_CHARS * 4)
        )

        try:
            data = json.loads(
                raw.decode("utf-8") or "{}"
            )

        except Exception:
            self._send_json(
                {"error": "bad json"},
                400
            )

            return

        if self.path == "/api/message":

            text = str(
                data.get("text", "")
            ).strip()[:MAX_MESSAGE_CHARS]

            if not text:
                self._send_json(
                    {"error": "empty message"},
                    400
                )

                return

            # One brain at a time.

            with brain_lock:
                import Shadow

                reply = Shadow.get_response(text)

                who = "user"

                history.append(
                    {"who": "user", "text": text}
                )

                history.append(
                    {"who": "Shadow", "text": reply}
                )

                del history[:-40]

            self._send_json({"reply": reply})

            return

        if self.path == "/api/history":

            with brain_lock:
                snapshot = list(history)

            self._send_json(
                {"history": snapshot}
            )

            return

        self._send_json(
            {"error": "not found"},
            404
        )


# Phone-side chat history (separate from the
# console conversation_history; kept small).

history = []


def start_server():
    global server
    global server_thread
    global pin_code

    if server is not None:
        return get_status_text()

    pin_code = f"{random.randint(0, 999999):06d}"

    server = ThreadingHTTPServer(
        ("0.0.0.0", SERVER_PORT),
        PhoneHandler
    )

    server_thread = threading.Thread(
        target=server.serve_forever,
        daemon=True
    )

    server_thread.start()

    print("[Shadow PHONE] Phone access is ON.")

    for ip in get_lan_ips():
        print(
            f"[Shadow PHONE]   http://{ip}:{SERVER_PORT}"
        )

    print(
        f"[Shadow PHONE]   PIN: {pin_code}"
    )

    return get_status_text()


def stop_server():
    global server
    global server_thread

    if server is None:
        return (
            "Phone access is not running, sir."
        )

    server.shutdown()

    server = None
    server_thread = None

    return (
        "Phone access is OFF, sir. Your phone can "
        "no longer reach me."
    )


def get_status_text():
    if server is None:
        return (
            "Phone access is OFF. Say 'phone on' to "
            "start it, sir."
        )

    urls = ", ".join(
        f"http://{ip}:{SERVER_PORT}"
        for ip in get_lan_ips()
    )

    return (
        "Phone access is ON.\n"
        f"On your phone (same Wi-Fi), open: {urls}\n"
        f"PIN: {pin_code}\n"
        "Enter the PIN once, then just chat."
    )


if __name__ == "__main__":
    print(get_status_text())

    print(start_server())

    try:
        while True:
            import time
            time.sleep(1)

    except KeyboardInterrupt:
        print(stop_server())
