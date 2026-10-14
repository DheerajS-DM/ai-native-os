"""sidebar.py — PyQt6 sidebar communicating with Nexus agent via Unix socket."""

from __future__ import annotations

import sys
import os
import base64
import json
import socket
import threading
import subprocess
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QLabel, QPushButton, QProgressBar,
    QSystemTrayIcon, QMenu, QMessageBox, QFrame, QFileDialog,
    QDialog, QSlider
)
from PyQt6.QtGui import QAction, QDragEnterEvent, QDropEvent
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread, qInstallMessageHandler, QtMsgType

from stats import snapshot
from logger import get_logger, setup_global_exception_handler

setup_global_exception_handler("sidebar")
log = get_logger("sidebar")

SOCKET_PATH = "/tmp/nexus.sock"

def _qt_message_handler(msg_type: QtMsgType, context, message: str):
    """Forward internal Qt debug/warning/critical messages into Nexus logs."""
    if msg_type == QtMsgType.QtDebugMsg:
        log.debug("[Qt] %s (file: %s:%s)", message, context.file, context.line)
    elif msg_type == QtMsgType.QtInfoMsg:
        log.info("[Qt] %s", message)
    elif msg_type == QtMsgType.QtWarningMsg:
        log.warning("[Qt] %s (file: %s:%s)", message, context.file, context.line)
    elif msg_type == QtMsgType.QtCriticalMsg:
        log.error("[Qt Critical] %s (file: %s:%s)", message, context.file, context.line)
    elif msg_type == QtMsgType.QtFatalMsg:
        log.critical("[Qt Fatal] %s (file: %s:%s)", message, context.file, context.line)

# ── Dynamic Cgroups Resource Allocator Dialog ───────────

class CgroupDialog(QDialog):
    def __init__(self, parent=None, current_pct=70):
        super().__init__(parent)
        self.setWindowTitle("⚙ Cgroups v2 Resource Allocator")
        self.setFixedSize(380, 240)
        self.setStyleSheet("""
            QDialog        { background: #161b22; color: #c9d1d9; font-family: 'Inter', 'Segoe UI', sans-serif; }
            QLabel         { color: #c9d1d9; font-size: 12px; }
            QLabel#header  { color: #58a6ff; font-size: 14px; font-weight: bold; }
            QLabel#sub     { color: #8b949e; font-size: 11px; }
            QSlider::groove:horizontal { height: 6px; background: #30363d; border-radius: 3px; }
            QSlider::sub-page:horizontal { background: #238636; border-radius: 3px; }
            QSlider::handle:horizontal { background: #58a6ff; width: 16px; margin-top: -5px; margin-bottom: -5px; border-radius: 8px; }
            QPushButton    { background: #238636; border: none; border-radius: 6px; padding: 7px 14px; font-weight: 600; color: #ffffff; }
            QPushButton:hover { background: #2ea043; }
            QPushButton#cancel { background: #21262d; border: 1px solid #30363d; color: #8b949e; }
            QPushButton#cancel:hover { background: #30363d; color: #c9d1d9; }
        """)
        self.target_pct = current_pct

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        hdr = QLabel("⚛ Cgroups v2 RAM Allocator")
        hdr.setObjectName("header")
        layout.addWidget(hdr)

        sub = QLabel("Dynamically adjust kernel memory ceiling for AI OS processes (/sys/fs/cgroup/nexus).")
        sub.setObjectName("sub")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        self.val_label = QLabel(f"Limit: {self.target_pct}% of Host RAM")
        self.val_label.setStyleSheet("color: #58a6ff; font-weight: bold; font-size: 13px;")
        layout.addWidget(self.val_label)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(20, 95)
        self.slider.setValue(self.target_pct)
        self.slider.setTickInterval(5)
        self.slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self.slider)

        layout.addStretch()

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        apply_btn = QPushButton("Apply Dynamic Limit")
        apply_btn.clicked.connect(self.accept)
        btn_row.addWidget(apply_btn)

        layout.addLayout(btn_row)

    def _on_slider_changed(self, val: int):
        self.target_pct = val
        self.val_label.setText(f"Limit: {val}% of Host RAM")

# ── Socket Client (threaded) ────────────────────────────

class SocketClient(QThread):
    message_received = pyqtSignal(dict)
    connected = pyqtSignal()
    disconnected = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._sock: Optional[socket.socket] = None
        self._running = False

    def connect_to_agent(self):
        if self._running:
            return
        log.debug("Attempting to connect to agent socket at %s...", SOCKET_PATH)
        try:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.connect(SOCKET_PATH)
            self._running = True
            log.info("Socket client successfully connected to %s", SOCKET_PATH)
            self.connected.emit()
            self.start()
        except Exception as e:
            log.debug("Socket client connection failed (agent not up yet?): %s", e)
            self._running = False
            self.disconnected.emit()

    def run(self):
        log.info("SocketClient reader thread started")
        buf = b""
        while self._running and self._sock:
            try:
                data = self._sock.recv(4096)
                if not data:
                    log.info("SocketClient received EOF from server")
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line.strip():
                        try:
                            msg = json.loads(line.decode())
                            log.debug("SocketClient parsed incoming payload type: %s", msg.get("type"))
                            self.message_received.emit(msg)
                        except Exception as e:
                            log.warning("SocketClient failed to parse JSON line: %s", e)
            except Exception as e:
                if self._running:
                    log.error("SocketClient socket read error: %s", e, exc_info=True)
                break
        self._running = False
        self.disconnected.emit()
        log.info("SocketClient reader thread terminated")

    def send(self, msg: dict):
        if self._sock and self._running:
            try:
                data = json.dumps(msg) + "\n"
                log.debug("SocketClient sending payload: %.120s", data.strip())
                self._sock.sendall(data.encode())
            except Exception as e:
                log.error("SocketClient send error: %s", e)
                self._running = False
                self.disconnected.emit()
        else:
            log.warning("Cannot send message, socket client not connected (running=%s)", self._running)

    def close(self):
        log.info("Closing SocketClient...")
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception as e:
                log.debug("Socket close error: %s", e)
        self.wait(1000)
        log.info("SocketClient closed.")

class StatsWorker(QThread):
    stats_updated = pyqtSignal(dict)
    
    def run(self):
        try:
            import stats
            s = stats.snapshot()
            self.stats_updated.emit(s)
        except Exception as e:
            log.error("StatsWorker execution failed: %s", e, exc_info=True)

# ── Sidebar Widget ───────────────────────────────────────

class NexusSidebar(QWidget):
    def __init__(self):
        super().__init__()
        self.client = SocketClient()
        self.pending_image_path: Optional[str] = None
        self.is_always_on_top = True

        self._setup_window()
        self._setup_ui()
        self._setup_timers()
        self._connect_socket()

    def _setup_window(self):
        self.setWindowTitle("AI Native OS")
        self._apply_window_flags()
        self.setAcceptDrops(True)
        screen_obj = QApplication.primaryScreen()
        if screen_obj is None:
            self.setGeometry(0, 0, 460, 1080)
        else:
            screen = screen_obj.geometry()
            w = 460
            self.setGeometry(screen.width() - w, 0, w, screen.height())
        self.setStyleSheet("""
            QWidget        { background: #0d1117; color: #c9d1d9; font-family: 'Inter', 'Segoe UI', 'Ubuntu', 'Sans-Serif'; }
            QTextEdit      { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
                             padding: 10px; font-size: 13px; line-height: 1.4; }
            QLineEdit      { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
                             padding: 9px 12px; font-size: 13px; color: #f0f6fc; }
            QLineEdit:focus { border-color: #58a6ff; }
            QPushButton    { background: #238636; border: none; border-radius: 6px;
                             padding: 7px 12px; font-weight: 600; color: #ffffff; }
            QPushButton:hover { background: #2ea043; }
            QPushButton#secondary { background: #21262d; border: 1px solid #30363d; color: #8b949e; }
            QPushButton#secondary:hover { background: #30363d; color: #c9d1d9; }
            QPushButton#os_btn { background: #1f2937; border: 1px solid #374151; color: #60a5fa; font-weight: bold; }
            QPushButton#os_btn:hover { background: #374151; color: #93c5fd; }
            QPushButton#danger { background: #da3633; color: #ffffff; }
            QPushButton#danger:hover { background: #f85149; }
            QProgressBar   { background: #161b22; border: 1px solid #30363d; border-radius: 4px;
                             text-align: center; color: #8b949e; font-size: 11px; height: 16px; }
            QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                             stop:0 #238636, stop:1 #58a6ff); border-radius: 3px; }
            QLabel         { font-size: 11px; color: #8b949e; }
            QLabel#title   { font-size: 15px; font-weight: bold; color: #58a6ff; }
            QLabel#status  { font-size: 10px; color: #8b949e; }
            QFrame#divider { background: #30363d; max-height: 1px; }
        """)

    def _apply_window_flags(self):
        flags = Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        if self.is_always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def _toggle_always_on_top(self):
        self.is_always_on_top = not self.is_always_on_top
        self._apply_window_flags()
        self.show()
        if self.is_always_on_top:
            self.pin_btn.setText("📌")
            self.pin_btn.setToolTip("Always on Top: ON (click to unpin)")
        else:
            self.pin_btn.setText("📍")
            self.pin_btn.setToolTip("Always on Top: OFF (click to pin)")

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        # ── Title Bar ──
        title_row = QHBoxLayout()
        title = QLabel("⚛ AI Native OS")
        title.setObjectName("title")
        title_row.addWidget(title)

        credit = QLabel("by Dheeraj & Dhruv")
        credit.setStyleSheet("font-size: 10px; color: #6e7681; font-style: italic; margin-left: 4px;")
        title_row.addWidget(credit)
        title_row.addStretch()

        self.conn_dot = QLabel("● Offline")
        self.conn_dot.setObjectName("status")
        self.conn_dot.setStyleSheet("color: #da3633;")
        title_row.addWidget(self.conn_dot)

        self.pin_btn = QPushButton("📌")
        self.pin_btn.setObjectName("secondary")
        self.pin_btn.setFixedSize(28, 28)
        self.pin_btn.setToolTip("Toggle Always on Top")
        self.pin_btn.clicked.connect(self._toggle_always_on_top)
        title_row.addWidget(self.pin_btn)

        min_btn = QPushButton("—")
        min_btn.setObjectName("secondary")
        min_btn.setFixedSize(28, 28)
        min_btn.setToolTip("Minimize Sidebar")
        min_btn.clicked.connect(self.showMinimized)
        title_row.addWidget(min_btn)

        close_btn = QPushButton("✕")
        close_btn.setObjectName("secondary")
        close_btn.setFixedSize(28, 28)
        close_btn.setToolTip("Hide to Tray")
        close_btn.clicked.connect(self.hide)
        title_row.addWidget(close_btn)
        layout.addLayout(title_row)

        # ── Live Telemetry / Stats Panel ──
        self.stats_label = QLabel("Initializing metrics…")
        self.stats_label.setWordWrap(True)
        layout.addWidget(self.stats_label)

        self.mem_bar = QProgressBar()
        self.mem_bar.setRange(0, 100)
        self.mem_bar.setFormat("cgroup RAM: %p%")
        layout.addWidget(self.mem_bar)

        # ── OS Workspace Action Launchers ──
        os_row = QHBoxLayout()
        
        term_btn = QPushButton("📟 Terminal")
        term_btn.setObjectName("os_btn")
        term_btn.setToolTip("Open native Linux Bash terminal on desktop")
        term_btn.clicked.connect(self._launch_terminal)
        os_row.addWidget(term_btn)

        files_btn = QPushButton("📁 Files")
        files_btn.setObjectName("os_btn")
        files_btn.setToolTip("Open Thunar Linux file manager on desktop")
        files_btn.clicked.connect(self._launch_files)
        os_row.addWidget(files_btn)

        cgroup_btn = QPushButton("⚙ Allocator")
        cgroup_btn.setObjectName("os_btn")
        cgroup_btn.setToolTip("Open Cgroups v2 dynamic resource manager")
        cgroup_btn.clicked.connect(self._open_cgroup_dialog)
        os_row.addWidget(cgroup_btn)

        layout.addLayout(os_row)

        div = QFrame()
        div.setObjectName("divider")
        layout.addWidget(div)

        # ── Chat & Output Area ──
        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        layout.addWidget(self.chat, stretch=1)

        # ── Image attachment indicator (if dropped/chosen) ──
        self.attach_label = QLabel("")
        self.attach_label.setStyleSheet("color: #58a6ff; font-size: 11px;")
        self.attach_label.hide()
        layout.addWidget(self.attach_label)

        # ── Quick Actions Row ──
        btn_row = QHBoxLayout()
        img_btn = QPushButton("📷 Image")
        img_btn.setObjectName("secondary")
        img_btn.clicked.connect(self._choose_image)
        btn_row.addWidget(img_btn)

        clear_btn = QPushButton("🧹 Clear")
        clear_btn.setObjectName("secondary")
        clear_btn.clicked.connect(self._clear_chat)
        btn_row.addWidget(clear_btn)

        unlock_btn = QPushButton("🔓 Unlock")
        unlock_btn.setObjectName("secondary")
        unlock_btn.clicked.connect(self._unlock_safeguard)
        btn_row.addWidget(unlock_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # ── User Input Row ──
        input_row = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Ask AI OS, type /run <cmd>, or drop an image…")
        self.input_field.returnPressed.connect(self._on_send)
        input_row.addWidget(self.input_field)

        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self._on_send)
        input_row.addWidget(send_btn)
        layout.addLayout(input_row)

        self.setLayout(layout)

    def _setup_timers(self):
        log.debug("Setting up background telemetry and watchdog timers...")
        self.stats_thread: Optional[StatsWorker] = None
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self._request_stats)
        self.stats_timer.start(2000)

        self.reconnect_timer = QTimer(self)
        self.reconnect_timer.timeout.connect(self._check_connection)
        self.reconnect_timer.start(3000)

    def _request_stats(self):
        if self.stats_thread is not None and self.stats_thread.isRunning():
            return
        self.stats_thread = StatsWorker()
        self.stats_thread.stats_updated.connect(self._update_stats)
        self.stats_thread.start()

    def _connect_socket(self):
        log.info("Connecting sidebar signals to socket client...")
        self.client.message_received.connect(self._on_agent_message)
        self.client.connected.connect(self._on_connected)
        self.client.disconnected.connect(self._on_disconnected)
        self.client.connect_to_agent()

    def _check_connection(self):
        if not self.client._running:
            log.debug("Reconnection watchdog: socket not running. Retrying connect...")
            self.client.connect_to_agent()

    def _on_connected(self):
        log.info("Sidebar state changed: ONLINE")
        self.conn_dot.setText("● Online")
        self.conn_dot.setStyleSheet("color: #2ea043;")

    def _on_disconnected(self):
        log.info("Sidebar state changed: OFFLINE")
        self.conn_dot.setText("● Offline")
        self.conn_dot.setStyleSheet("color: #da3633;")

    # ── OS Workspace Actions ─────────────────────────────

    def _launch_terminal(self):
        log.info("User requested terminal launch on desktop")
        terms = ["xfce4-terminal", "tilix", "gnome-terminal", "x-terminal-emulator", "xterm"]
        for t in terms:
            try:
                subprocess.Popen([t], env=os.environ)
                self._append("OS", f"Launched terminal (<code>{t}</code>) on desktop.", "#58a6ff")
                return
            except FileNotFoundError:
                continue
        self._append("⚠ Notice", "No GUI terminal found. Install via: <code>sudo apt install -y xfce4-terminal</code>", "#f85149")

    def _launch_files(self):
        log.info("User requested file manager launch on desktop")
        fms = ["thunar", "nautilus", "pcmanfm"]
        for f in fms:
            try:
                subprocess.Popen([f, str(Path.home())], env=os.environ)
                self._append("OS", f"Launched file manager (<code>{f}</code>) on desktop.", "#58a6ff")
                return
            except FileNotFoundError:
                continue
        try:
            subprocess.Popen(["xdg-open", str(Path.home())], env=os.environ)
            self._append("OS", "Launched file explorer via xdg-open.", "#58a6ff")
        except Exception as e:
            self._append("⚠ Notice", f"Could not launch file manager: {e}", "#f85149")

    def _open_cgroup_dialog(self):
        log.info("Opening Cgroup Allocator Dialog...")
        dlg = CgroupDialog(self, current_pct=70)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_pct = dlg.target_pct
            log.info("User requested new cgroup percentage: %d%%", new_pct)
            self._append("Cgroups", f"Reallocating kernel memory ceiling to <b>{new_pct}%</b>...", "#58a6ff")
            self.client.send({"type": "set_cgroup", "percent": new_pct})

    # ── Drag and Drop Support for Images ─────────────────

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            log.debug("dragEnterEvent accepted with URLs")
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            log.info("dropEvent received file: %s", file_path)
            if file_path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                self._set_attached_image(file_path)
                break

    def _choose_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Image", str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.webp)"
        )
        if path:
            log.info("Image chosen via file dialog: %s", path)
            self._set_attached_image(path)

    def _set_attached_image(self, path: str):
        self.pending_image_path = path
        fname = Path(path).name
        log.info("Image attached: %s (%s)", fname, path)
        self.attach_label.setText(f"📎 Attached image: {fname} (will send with next message)")
        self.attach_label.show()

    # ── Stats Update ─────────────────────────────────────

    def _update_stats(self, s: dict):
        max_ram = max(s.get("ram_max_mb", 1), 1)
        cur_ram = s.get("ram_current_mb", 0)
        ram_pct = int(100 * cur_ram / max_ram)
        self.mem_bar.setValue(min(ram_pct, 100))

        vram_total = s.get("vram_total_mb", 0)
        vram_used = s.get("vram_used_mb", 0)
        gpu_temp = s.get("gpu_temp_c", 0)
        cpu_temp = s.get("cpu_temp_c", 0)
        tokens_total = s.get("tokens_total", 0)

        parts = [
            f"RAM: {cur_ram}/{max_ram}MB",
            f"VRAM: {vram_used}/{vram_total}MB" if vram_total else "VRAM: N/A",
            f"CPU: {cpu_temp}°C" + (f" | GPU: {gpu_temp}°C" if gpu_temp else ""),
            f"Tokens: {tokens_total:,}"
        ]
        self.stats_label.setText("  •  ".join(parts))

    # ── Chat I/O ─────────────────────────────────────────

    def _clear_chat(self):
        log.info("User triggered Clear Chat action")
        self.chat.clear()
        self.client.send({"type": "clear_context"})

    def _unlock_safeguard(self):
        log.info("User triggered Unlock Safeguard action")
        self.client.send({"type": "unlock"})

    def _on_send(self):
        text = self.input_field.text().strip()
        log.info("User hit Send (input text: '%.60s...', attached image: %s)", text, self.pending_image_path)
        if not text and not self.pending_image_path:
            return

        if text == "/clear":
            self._clear_chat()
            self.input_field.clear()
            return

        if text == "/unlock":
            self._unlock_safeguard()
            self.input_field.clear()
            return

        if text.startswith("/run ") or text.startswith("/sh "):
            cmd = text.split(" ", 1)[1].strip()
            if cmd:
                self._append("You (Shell)", f"<code>{cmd}</code>", "#58a6ff")
                self.client.send({"type": "direct_command", "command": cmd})
                self.input_field.clear()
                return

        display_text = text or "(Image query)"
        if self.pending_image_path:
            img_name = Path(self.pending_image_path).name
            self._append("You", f"{display_text} [📷 {img_name}]", "#58a6ff")

            # Read and encode image
            try:
                with open(self.pending_image_path, "rb") as f:
                    b64_data = base64.b64encode(f.read()).decode("utf-8")
                log.info("Sending multimodal chat message with attached image %s (base64 length: %d)", self.pending_image_path, len(b64_data))
                self.client.send({
                    "type": "chat_multimodal",
                    "text": display_text,
                    "media": [{"type": "image", "data": b64_data}],
                })
            except Exception as e:
                log.error("Failed to read image %s: %s", self.pending_image_path, e, exc_info=True)
                self._append("❌ Error", f"Failed to read image: {e}", "#f85149")

            self.pending_image_path = None
            self.attach_label.hide()
        else:
            self._append("You", text, "#58a6ff")
            self.client.send({"type": "chat", "text": text})

        self.input_field.clear()

    def _on_agent_message(self, msg: dict):
        t = msg.get("type")
        log.info("Sidebar handling incoming agent message type '%s'", t)
        if t == "reply":
            self._append("Nexus", msg.get("text", ""), "#7ee787")
            usage = msg.get("usage", {})
            if usage:
                p = usage.get("prompt_tokens", 0)
                c = usage.get("completion_tokens", 0)
                self._append("Usage", f"Prompt: {p} tokens · Completion: {c} tokens", "#6e7681")
        elif t == "confirm":
            self._show_confirm(msg.get("command", ""), msg.get("reason", ""))
        elif t == "cmd_result":
            out = msg.get("output", "")
            cmd = msg.get("command", "")
            self._append(f"Result `{cmd}`", f"<pre>{out}</pre>", "#e3b341")
        elif t == "blocked":
            cmd = msg.get("command", "")
            reason = msg.get("reason", "")
            self._append("⛔ Blocked", f"<code>{cmd}</code><br/>{reason}", "#f85149")
        elif t == "executing":
            cmd = msg.get("command", "")
            self._append("⚙ Running", f"<code>{cmd}</code>", "#8b949e")
        elif t == "info":
            self._append("ℹ Info", msg.get("text", ""), "#8b949e")
        elif t == "error":
            self._append("❌ Error", msg.get("text", ""), "#f85149")

    def _show_confirm(self, command: str, reason: str):
        log.info("Displaying confirmation dialog for command: '%s' (Reason: %s)", command, reason)
        reply = QMessageBox.question(
            self,
            "Confirm Action",
            f"The assistant requests permission to execute:\n\n{command}\n\nReason: {reason}\n\nProceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        approved = (reply == QMessageBox.StandardButton.Yes)
        log.info("User clicked confirmation dialog: %s", "YES" if approved else "NO")
        self.client.send({"type": "confirm_response", "approved": approved})
        if approved:
            self._append("✅ Approved", f"<code>{command}</code>", "#58a6ff")
        else:
            self._append("❌ Rejected", f"<code>{command}</code>", "#da3633")

    def _append(self, sender: str, text: str, color: str):
        self.chat.append(
            f'<div style="margin-bottom: 6px;">'
            f'<span style="color:{color}; font-weight:bold;">{sender}:</span> '
            f'<span style="color:#c9d1d9;">{text}</span>'
            f'</div>'
        )
        sb = self.chat.verticalScrollBar()
        sb.setValue(sb.maximum())

    def closeEvent(self, event):
        log.info("Sidebar closeEvent triggered. Shutting down worker threads and socket client.")
        if hasattr(self, "stats_thread") and self.stats_thread and self.stats_thread.isRunning():
            self.stats_thread.quit()
            self.stats_thread.wait(500)
        self.client.close()
        super().closeEvent(event)

# ── System Tray & Main ───────────────────────────────────

def main():
    log.info("==================================================")
    log.info("Starting Nexus Sidebar (PID: %d)...", os.getpid())
    log.info("==================================================")
    qInstallMessageHandler(_qt_message_handler)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    sidebar = NexusSidebar()
    sidebar.show()
    log.info("Sidebar window shown. Geometry: %s", sidebar.geometry())

    if QSystemTrayIcon.isSystemTrayAvailable():
        log.info("Initializing system tray icon...")
        tray = QSystemTrayIcon(app)
        tray.setToolTip("AI Native OS by Dheeraj and Dhruv")

        menu = QMenu()
        toggle_act = QAction("Toggle Sidebar", menu)
        toggle_act.triggered.connect(lambda: sidebar.setVisible(not sidebar.isVisible()))
        menu.addAction(toggle_act)

        term_act = QAction("Launch Terminal", menu)
        term_act.triggered.connect(sidebar._launch_terminal)
        menu.addAction(term_act)

        files_act = QAction("Launch File Manager", menu)
        files_act.triggered.connect(sidebar._launch_files)
        menu.addAction(files_act)

        cgroup_act = QAction("Resource Allocator", menu)
        cgroup_act.triggered.connect(sidebar._open_cgroup_dialog)
        menu.addAction(cgroup_act)

        menu.addSeparator()
        quit_act = QAction("Quit", menu)
        quit_act.triggered.connect(app.quit)
        menu.addAction(quit_act)

        tray.setContextMenu(menu)
        tray.show()
        tray.activated.connect(
            lambda reason: sidebar.setVisible(not sidebar.isVisible())
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None
        )
        log.info("System tray initialized and visible.")
    else:
        log.warning("System tray is not available on this display server.")

    exit_code = app.exec()
    log.info("Sidebar application event loop exited with code %d", exit_code)
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
