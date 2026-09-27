import queue
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont

sys.stdout.reconfigure(errors="replace")
sys.stderr.reconfigure(errors="replace")

# The brain. Importing Shadow loads memory,
# settings, and the voice stack exactly like
# the terminal version does.

import Shadow
from voice_output import stop_speech, set_muted, play_ear_cone

# ---------------- LOOK ----------------

BG = "#0d1117"
PANEL = "#161b22"
TEXT = "#e6edf3"
MUTED = "#8b949e"
ACCENT_DIM = "#1f6feb"
USER_COLOR = "#7ee787"
ERR_COLOR = "#ff7b72"
STATUS_ONLINE = "#3fb950"
STATUS_THINKING = "#f0883e"
STATUS_LISTENING = "#d2a8ff"
STATUS_OFFLINE = "#f85149"

FONT_FAMILY = "Segoe UI"

# Every worker thread reports back through this
# queue; only the main thread touches widgets.

ui_queue = queue.Queue()


class ShadowGUI:
    def __init__(self, root):
        self.root = root

        # One brain worker at a time; the closing
        # flag stops background threads cleanly.

        self.busy = threading.Event()
        self.closing = threading.Event()

        self.ears_ready = False
        self.ears_warming = False

        self.wake_thread = None
        self.wake_mode = False

        self.status_text = tk.StringVar(value="Starting...")

        self._build_fonts()
        self._build_window()

        # One timer polls the UI queue.

        self.root.after(50, self._drain_ui_queue)

        threading.Thread(
            target=self._startup_worker,
            daemon=True
        ).start()

    # ---------------- WINDOW ----------------

    def _build_fonts(self):
        self.font_body = tkfont.Font(
            family=FONT_FAMILY, size=10
        )
        self.font_name = tkfont.Font(
            family=FONT_FAMILY, size=10, weight="bold"
        )
        self.font_muted = tkfont.Font(
            family=FONT_FAMILY, size=9
        )
        self.font_input = tkfont.Font(
            family=FONT_FAMILY, size=10
        )

    def _build_window(self):
        root = self.root

        root.title("Shadow - Personal AI Companion")
        root.geometry("820x640")
        root.minsize(600, 480)
        root.configure(bg=BG)

        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(1, weight=1)

        # ---- Toolbar: quick action buttons ----

        toolbar = tk.Frame(root, bg=PANEL)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew")

        self.voice_chat_button = tk.Button(
            toolbar,
            text="🎙 Voice chat",
            font=self.font_name,
            bg="#21262d",
            fg=TEXT,
            activebackground="#2d333b",
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            padx=10,
            command=self._toggle_voice_chat,
        )
        self.voice_chat_button.pack(
            side="left", padx=(12, 6), pady=6
        )

        self.briefing_button = tk.Button(
            toolbar,
            text="☀ Briefing",
            font=self.font_name,
            bg="#21262d",
            fg=TEXT,
            activebackground="#2d333b",
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            padx=10,
            command=self._on_briefing,
        )
        self.briefing_button.pack(side="left", padx=6, pady=6)

        self.stop_speech_button = tk.Button(
            toolbar,
            text="⏹ Stop speaking",
            font=self.font_name,
            bg="#21262d",
            fg=TEXT,
            activebackground="#2d333b",
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            padx=10,
            command=self._on_stop_speaking,
        )
        self.stop_speech_button.pack(side="left", padx=6, pady=6)

        self.eyes_button = tk.Button(
            toolbar,
            text="👁 Eyes",
            font=self.font_name,
            bg="#21262d",
            fg=TEXT,
            activebackground="#2d333b",
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            padx=10,
            command=self._on_eyes,
        )
        self.eyes_button.pack(side="left", padx=6, pady=6)

        # ---- Chat area ----

        self.chat = tk.Text(
            root,
            wrap="word",
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            borderwidth=0,
            highlightthickness=0,
            padx=16,
            pady=12,
            cursor="arrow",
            state="disabled",
            font=self.font_body,
        )
        self.chat.grid(row=1, column=0, sticky="nsew")

        self.chat.tag_configure(
            "Shadow",
            foreground=TEXT,
            font=self.font_body,
        )
        self.chat.tag_configure(
            "user",
            foreground=USER_COLOR,
            font=self.font_body,
        )
        self.chat.tag_configure(
            "system",
            foreground=MUTED,
            font=self.font_muted,
        )
        self.chat.tag_configure(
            "muted",
            foreground=MUTED,
            font=self.font_muted,
        )
        self.chat.tag_configure(
            "err",
            foreground=ERR_COLOR,
            font=self.font_body,
        )
        self.chat.tag_configure(
            "mono",
            foreground=TEXT,
            font=("Consolas", 9),
        )

        # Scrollbar (auto-hides when not needed).

        self.scrollbar = tk.Scrollbar(
            root,
            command=self.chat.yview,
            width=10,
        )
        self.scrollbar.grid(row=1, column=1, sticky="ns")
        self.chat.configure(
            yscrollcommand=self._on_chat_scroll
        )

        # ---- Bottom bar ----

        bar = tk.Frame(root, bg=PANEL)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        bar.grid_columnconfigure(3, weight=1)

        # Status indicator: colored dot + text.

        self.status_dot = tk.Canvas(
            bar,
            width=12,
            height=14,
            bg=PANEL,
            highlightthickness=0,
        )
        self.status_dot.grid(row=0, column=0, padx=(16, 4), pady=8)

        self.status_label = tk.Label(
            bar,
            textvariable=self.status_text,
            bg=PANEL,
            fg=MUTED,
            font=self.font_muted,
        )
        self.status_label.grid(row=0, column=1, padx=(0, 12))

        # Microphone button: press once, speak.

        self.mic_button = tk.Button(
            bar,
            text="🎤",
            font=("Segoe UI Emoji", 13),
            bg="#21262d",
            fg=TEXT,
            activebackground="#2d333b",
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            width=3,
            command=self._on_mic_pressed,
        )
        self.mic_button.grid(row=0, column=2, padx=(0, 8), pady=8)

        # Typing box.

        self.entry = tk.Entry(
            bar,
            bg="#21262d",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=self.font_input,
        )
        self.entry.grid(row=0, column=3, sticky="ew", padx=(0, 8), pady=8)
        self.entry.bind("<Return>", self._on_send)
        self.entry.focus_set()

        # Send button.

        self.send_button = tk.Button(
            bar,
            text="Send",
            font=self.font_name,
            bg=ACCENT_DIM,
            fg="white",
            activebackground="#388bfd",
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            padx=14,
            command=self._on_send,
        )
        self.send_button.grid(row=0, column=4, padx=(0, 16), pady=8)

    def _on_chat_scroll(self, first, last):
        # Auto-hide the scrollbar when all content
        # fits without scrolling.

        try:
            if float(first) <= 0.0 and float(last) >= 1.0:
                if self.scrollbar.grid_info():
                    self.scrollbar.grid_remove()
            else:
                self.scrollbar.grid()
        except tk.TclError:
            pass

    # ---------------- THREAD-SAFE UI ----------------

    def _post(self, fn, *args):
        ui_queue.put((fn, args))

    def _drain_ui_queue(self):
        try:
            while True:
                fn, args = ui_queue.get_nowait()
                ui_queue.task_done()
                try:
                    fn(*args)
                except tk.TclError:
                    pass
        except queue.Empty:
            pass

        if not self.closing.is_set():
            self.root.after(50, self._drain_ui_queue)

    def _append_chat(self, text, tag):
        # Briefings may contain an ASCII QR code:
        # those lines need a monospaced font to
        # stay scannable, everything else keeps
        # the normal font.

        needs_mono = (
            tag == "Shadow"
            and "█" in text
        )

        def apply():
            self.chat.configure(state="normal")

            self.chat.insert(
                "end",
                text + "\n\n",
                "mono" if needs_mono else tag,
            )

            self.chat.see("end")
            self.chat.configure(state="disabled")

        self._post(apply)

    def _update_status(self, text, color):
        def apply():
            self.status_text.set(text)
            self.status_dot.delete("all")
            self.status_dot.create_oval(
                1, 1, 11, 11, fill=color, outline=""
            )

        self._post(apply)

    def _set_busy_ui(self, busy):
        state = "disabled" if busy else "normal"

        def apply():
            self.entry.config(state=state)
            self.send_button.config(
                state=state,
                text="..." if busy else "Send"
            )
            self.mic_button.config(
                state="disabled" if busy else "normal"
            )
            if not busy:
                self.entry.focus_set()

        self._post(apply)

    def _set_ready(self):
        self._update_status("Ready", STATUS_ONLINE)

    def _set_thinking(self):
        self._update_status("Thinking...", STATUS_THINKING)

    # ---------------- WORKERS ----------------

    def _startup_worker(self):
        if Shadow.check_ollama_status():
            self._update_status("Ready", STATUS_ONLINE)
        else:
            self._update_status("Ollama offline", STATUS_OFFLINE)
            self._append_chat(
                "Ollama is not running, sir. Start Ollama, "
                "then send me a message - I will reconnect "
                "automatically.",
                "system",
            )

        user_name = Shadow.memory_manager.get_user_name()

        if user_name:
            greeting = f"Shadow online. Hello, {user_name} sir."
        else:
            greeting = "Shadow online. Hello sir."

        self._append_chat(greeting, "Shadow")

        if Shadow.voice_enabled:
            self._request_ears_warmup()

    def _request_ears_warmup(self):
        # Prepare the microphone once, in the
        # background, so the first mic press is fast.

        if self.ears_ready or self.ears_warming:
            return

        self.ears_warming = True

        def warm():
            try:
                ok = Shadow.setup_stt()
            except Exception:
                ok = False

            self.ears_warming = False
            self.ears_ready = ok

            if ok:
                self._update_status("Mic ready", STATUS_ONLINE)
            else:
                self._update_status(
                    "Mic unavailable", STATUS_OFFLINE
                )

        threading.Thread(target=warm, daemon=True).start()

    # ---------------- MIC (one-shot) ----------------

    def _on_mic_pressed(self):
        # One press = one command.

        if self.busy.is_set():
            return

        self._set_busy_ui(True)
        self._update_status(
            "Listening... (speak now)", STATUS_LISTENING
        )

        def listen():
            try:
                heard = Shadow.listen_for_command(7)
            except Exception:
                heard = ""

            if self.closing.is_set():
                return

            if not heard:
                self._update_status("Ready", STATUS_ONLINE)
                self._append_chat(
                    "(I did not hear anything, sir.)",
                    "system",
                )
                self._set_busy_ui(False)
                return

            self._post(self._handle_heard, heard)

        threading.Thread(target=listen, daemon=True).start()

    def _handle_heard(self, heard):
        # Main thread: show what was heard, then
        # start the reply worker.

        self.entry.delete(0, "end")
        self.entry.insert(0, "You (voice): " + heard)
        self.entry.xview_moveto(1.0)

        self.root.after(
            400, lambda: self._run_user_text(heard)
        )

    # ---------------- SENDING ----------------

    def _on_send(self, event=None):
        text = self.entry.get().strip()

        if not text or self.busy.is_set():
            return

        self.entry.delete(0, "end")
        self._run_user_text(text)

    def _run_user_text(self, text):
        if self.busy.is_set():
            return

        lowered = text.lower().strip()

        # GUI-native handling: typing 'voice chat'
        # must never reach the terminal's
        # interactive voice loop inside the brain
        # thread.

        if lowered == "voice chat":
            self._start_wake_monitor()
            return

        if lowered in (
            "stop listening",
            "wake word off",
        ):
            if self.wake_mode:
                self._stop_wake_monitor()

            else:
                self._append_chat(
                    "Voice chat is not on right now, sir.",
                    "system",
                )

            return

        # A fresh user message always clears a
        # previous 'stop speaking' mute.

        set_muted(False)

        self.busy.set()
        self._set_busy_ui(True)

        self._append_chat("You: " + text, "user")
        self._set_thinking()

        threading.Thread(
            target=self._reply_worker,
            args=(text,),
            daemon=True,
        ).start()

    def _reply_worker(self, text):
        # The single brain call. All UI contact
        # goes through _post / _append_chat.

        try:
            reply = Shadow.get_response(text)

            if self.closing.is_set():
                return

            spoken = (
                Shadow.reply_already_spoken
                and Shadow.voice_enabled
            )

            self._post(self._show_reply, reply, spoken)

        except Exception as error:
            self._post(
                self._show_reply,
                "Something went wrong: " + str(error),
                False,
                True,
            )

    def _show_reply(self, reply, spoken, error=False):
        # Main thread: display the reply and free
        # the UI for the next message.

        tag = "err" if error else "Shadow"

        self._append_chat("Shadow: " + reply, tag)

        if spoken:
            self._append_chat(
                "(spoken while generating)", "muted"
            )

        self.busy.clear()
        self._set_busy_ui(False)
        self._set_ready()
        self.entry.focus_set()

    # ---------------- TOOLBAR ACTIONS ----------------

    def _toggle_voice_chat(self):
        if self.wake_mode:
            self._stop_wake_monitor()

        else:
            self._start_wake_monitor()

    def _reset_voice_chat_button(self):
        # Safe to call from any thread via _post.

        self.wake_mode = False

        try:
            self.voice_chat_button.config(
                text="🎙 Voice chat"
            )

        except tk.TclError:
            pass

    def _on_briefing(self):
        if self.busy.is_set() or self.wake_mode:
            return

        self.entry.delete(0, "end")
        self._run_user_text("good morning")

    def _on_eyes(self):
        # One click: capture the screen, read it,
        # and describe it - the same flow as typing
        # 'what do you see'.

        if self.busy.is_set() or self.wake_mode:
            return

        self.entry.delete(0, "end")
        self._run_user_text("what do you see")

    def _on_stop_speaking(self):
        # Mute future sentences and drop whatever
        # is still queued. The sentence currently
        # being spoken by Windows finishes; the
        # next user message unmutes him.

        set_muted(True)
        stop_speech()
        self._append_chat(
            "(stopped speaking)", "system"
        )

    # ---------------- WAKE WORD MONITOR ----------------

    def _start_wake_monitor(self):
        # Mode 2: hands-free. Runs until the user
        # says 'stop listening' or closes the window.

        if self.wake_thread and self.wake_thread.is_alive():
            return

        self.wake_mode = True
        set_muted(False)
        self._set_busy_ui(True)
        self._update_status("Say 'Shadow'...", STATUS_LISTENING)
        self.voice_chat_button.config(
            text="⏹ Stop voice chat"
        )

        self._append_chat(
            "Wake word monitor ON. Say 'Shadow' and then "
            "your command, or just 'Shadow' and wait for "
            "the beep. Say 'stop listening' to turn it off.",
            "system",
        )

        self.wake_thread = threading.Thread(
            target=self._wake_worker,
            daemon=True,
        )
        self.wake_thread.start()

    def _wake_worker(self):
        if not Shadow.setup_stt():
            self._post(
                self._append_chat,
                "I could not open the microphone, sir.",
                "system",
            )
            self._post(self._set_busy_ui, False)
            self._post(self._set_ready)
            self._post(self._reset_voice_chat_button)
            return

        self.ears_ready = True

        while not self.closing.is_set() and self.wake_mode:

            if self.busy.is_set():
                # A reply is being generated; wait for
                # it to finish before listening again.

                time.sleep(0.3)
                continue

            found, command = Shadow.listen_for_wake_word(10)

            if self.closing.is_set() or not self.wake_mode:
                return

            if found:
                if command:
                    self._post(
                        self._post_wake_command, command
                    )

                else:
                    # Bare wake word: ask for the command.

                    Shadow.speak("Yes sir?")
                    Shadow.wait_until_speech_done()
                    Shadow.flush_audio_queue()

                    self._update_status(
                        "Listening... (speak now)",
                        STATUS_LISTENING,
                    )

                    heard = Shadow.listen_for_command(7)

                    if not heard:
                        # Same subtle signal as autostart
                        # mode: the name arrived, the
                        # command did not.

                        play_ear_cone()

                    if (
                        heard
                        and not self.closing.is_set()
                        and self.wake_mode
                    ):
                        self._post(
                            self._post_wake_command, heard
                        )

    def _post_wake_command(self, heard):
        # Main thread: show the heard command, then
        # run it through the brain.

        if self.busy.is_set():
            return

        lowered = heard.lower().strip()

        self._append_chat("You (voice): " + heard, "user")

        if lowered in ("wake word off", "stop listening"):
            self._stop_wake_monitor()
            return

        set_muted(False)

        self.busy.set()
        self._set_thinking()

        threading.Thread(
            target=self._reply_worker,
            args=(heard,),
            daemon=True,
        ).start()

    def _stop_wake_monitor(self):
        self.wake_mode = False
        self.voice_chat_button.config(
            text="🎙 Voice chat"
        )
        self._append_chat(
            "Wake word monitor OFF. Type a message or "
            "press the mic button to talk to me.",
            "system",
        )
        self._set_busy_ui(False)
        self._set_ready()

    # ---------------- CLOSE ----------------

    def _on_close(self):
        self.closing.set()
        self.wake_mode = False

        try:
            Shadow.close_stt()
        except Exception:
            pass

        try:
            from voice_output import stop_speech
            stop_speech()
        except Exception:
            pass

        self.root.destroy()


def run():
    root = tk.Tk()

    app = ShadowGUI(root)

    root.protocol("WM_DELETE_WINDOW", app._on_close)

    root.mainloop()


if __name__ == "__main__":
    run()
