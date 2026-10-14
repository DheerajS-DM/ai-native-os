"""sidebar.py — PyQt6 sidebar communicating with Nexus agent via Unix socket."""

from __future__ import annotations

import sys
import os
import base64
import json
import socket
import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QLabel, QPushButton, QProgressBar,
    QSystemTrayIcon, QMenu, QMessageBox, QFrame, QFileDialog
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
                    line_str = line.decode().strip()
                    if not line_str:
                        continue
                    try:
                        msg = json.loads(line_str)
                        log.debug("SocketClient incoming packet: %.120s", line_str)
                        self.message_received.emit(msg)
                    except json.JSONDecodeError as e:
                        log.warning("SocketClient JSON parse error for packet: %s (%s)", line_str, e)
            except Exception as e:
                log.warning("SocketClient recv loop exception: %s", e)
                break
        self._running = False
        log.info("SocketClient reader loop ended, emitting disconnected signal")
        self.disconnected.emit()

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

        self._setup_window()
        self._setup_ui()
        self._setup_timers()
        self._connect_socket()

    def _setup_window(self):
        self.setWindowTitle("AI Native OS")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAcceptDrops(True)
        screen_obj = QApplication.primaryScreen()
        if screen_obj is None:
            self.setGeometry(0, 0, 440, 1080)
        else:
            screen = screen_obj.geometry()
            w = 440
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

        hide_btn = QPushButton("—")
        hide_btn.setObjectName("secondary")
        hide_btn.setFixedSize(28, 28)
        hide_btn.clicked.connect(self.hide)
        title_row.addWidget(hide_btn)
        layout.addLayout(title_row)

        # ── Live Telemetry / Stats Panel ──
        self.stats_label = QLabel("Initializing metrics…")
        self.stats_label.setWordWrap(True)
        layout.addWidget(self.stats_label)

        self.mem_bar = QProgressBar()
        self.mem_bar.setRange(0, 100)
        self.mem_bar.setFormat("cgroup RAM: %p%")
        layout.addWidget(self.mem_bar)

        div = QFrame()
        div.setObjectName("divider")
        layout.addWidget(div)

        # ── Chat Area ──
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
        self.input_field.setPlaceholderText("Ask Nexus or type command (drop image here)…")
        self.input_field.returnPressed.connect(self._on_send)
        input_row.addWidget(self.input_field)

        send_btn = QPushButton("▶")
        send_btn.setFixedSize(38, 38)
        send_btn.clicked.connect(self._on_send)
        input_row.addWidget(send_btn)
        layout.addLayout(input_row)

        self.setLayout(layout)

    def _setup_timers(self):
        log.debug("Setting up sidebar telemetry and reconnection timers...")
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._fetch_stats)
        self._stats_timer.start(2000)
        self.stats_worker = None
        self._fetch_stats()

        # Reconnection watchdog timer
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.timeout.connect(self._check_connection)
        self._reconnect_timer.start(4000)
        log.info("Timers initialized (stats: 2000ms, watchdog: 4000ms)")

    def _fetch_stats(self):
        if self.stats_worker is None or not self.stats_worker.isRunning():
            self.stats_worker = StatsWorker()
            self.stats_worker.stats_updated.connect(self._update_stats)
            self.stats_worker.finished.connect(self.stats_worker.deleteLater)
            self.stats_worker.start()

    def _connect_socket(self):
        log.info("Connecting socket client signals and initiating connection...")
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
        if self.stats_worker and self.stats_worker.isRunning():
            self.stats_worker.quit()
            self.stats_worker.wait(500)
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
