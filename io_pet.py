"""
Io Pet - A minimal desktop companion inspired by Dota's Io
A glowing orb that lives on your screen and can chat with you

Features:
    - Voice input (Whisper STT) and output (Edge TTS)
    - Context-aware (knows what app you're using)
    - Agent mode (LocalAgent API) with Chat fallback (Ollama)
    - Autostart support

Usage:
    python io_pet.py          # Normal start
    pythonw io_pet.py         # Silent start (no console)
    start.vbs                 # Double-click to start silently

Requirements:
    pip install -r requirements.txt
"""

import sys
import os
import math
import threading
import requests
import json
from datetime import datetime

# 窗口追踪通过 LocalAgent API 实现（跨平台）
# 不再需要 pywin32 或 xdotool

# Voice module (optional)
try:
    from voice import VoiceModule
    HAS_VOICE = True
except ImportError:
    HAS_VOICE = False
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QTextEdit,
    QVBoxLayout, QHBoxLayout, QPushButton, QMenu, QDialog,
    QListWidget, QListWidgetItem
)
from PyQt5.QtCore import Qt, QTimer, QPointF, pyqtSignal, QPoint
from PyQt5.QtGui import QPainter, QColor, QRadialGradient, QFont

# 历史记录文件路径
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_history.json")


def load_history():
    """加载聊天历史"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []


def save_history(history):
    """保存聊天历史"""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except:
        pass


class HistoryWindow(QDialog):
    """聊天历史记录窗口"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("聊天历史")
        self.setFixedSize(500, 400)
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setStyleSheet("""
            QDialog {
                background-color: rgba(30, 30, 50, 240);
            }
        """)

        layout = QVBoxLayout(self)

        # 标题
        title = QLabel("📜 聊天历史记录")
        title.setStyleSheet("color: #e0e8ff; font-size: 16px; font-weight: bold; padding: 10px;")
        layout.addWidget(title)

        # 历史列表
        self.history_list = QListWidget()
        self.history_list.setStyleSheet("""
            QListWidget {
                background-color: rgba(40, 40, 60, 200);
                color: #e0e8ff;
                border: none;
                border-radius: 10px;
                padding: 5px;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid rgba(100, 150, 255, 50);
            }
            QListWidget::item:selected {
                background-color: rgba(74, 111, 165, 150);
            }
            QScrollBar:vertical {
                background: rgba(50, 50, 70, 150);
                width: 8px;
            }
            QScrollBar::handle:vertical {
                background: rgba(100, 150, 255, 150);
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.history_list)

        # 按钮区
        btn_layout = QHBoxLayout()

        clear_btn = QPushButton("🗑️ 清空历史")
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #8a4a4a;
                color: white;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #aa5a5a; }
        """)
        clear_btn.clicked.connect(self._clear_history)
        btn_layout.addWidget(clear_btn)

        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a6fa5;
                color: white;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #5a8fd5; }
        """)
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

        self._load_history()

    def _load_history(self):
        """加载并显示历史记录"""
        self.history_list.clear()
        history = load_history()

        for entry in reversed(history):  # 最新的在前
            time_str = entry.get("time", "")
            user_msg = entry.get("user", "")
            ai_msg = entry.get("ai", "")

            item_text = f"🕐 {time_str}\n👤 {user_msg}\n🤖 {ai_msg}"
            item = QListWidgetItem(item_text)
            self.history_list.addItem(item)

    def _clear_history(self):
        """清空历史记录"""
        save_history([])
        self.history_list.clear()


class ChatBubble(QWidget):
    """A chat bubble that appears above Io"""

    # Signals for thread-safe UI updates
    response_ready = pyqtSignal(str)
    voice_text_ready = pyqtSignal(str)
    code_confirm_ready = pyqtSignal(str, dict)  # (response_text, pending_code)

    def __init__(self, parent_pet):
        super().__init__()
        self.parent_pet = parent_pet
        self.voice_module = VoiceModule(language="zh", tts_engine="edge") if HAS_VOICE else None
        self.is_recording = False
        self.pending_code = None  # 存储待确认的代码

        # Window settings
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(380)

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)

        # Response area (scrollable)
        self.response_label = QTextEdit()
        self.response_label.setPlainText("点击我开始聊天！")
        self.response_label.setReadOnly(True)
        self.response_label.setMinimumHeight(120)
        self.response_label.setMaximumHeight(200)
        self.response_label.setStyleSheet("""
            QTextEdit {
                background-color: rgba(30, 30, 50, 220);
                color: #e0e8ff;
                border-radius: 15px;
                padding: 12px;
                font-size: 14px;
                border: none;
            }
            QScrollBar:vertical {
                background: rgba(50, 50, 70, 150);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(100, 150, 255, 150);
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        layout.addWidget(self.response_label)

        # Input area
        input_layout = QHBoxLayout()

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("说点什么...")
        self.input_field.setStyleSheet("""
            QLineEdit {
                background-color: rgba(50, 50, 70, 220);
                color: white;
                border: 1px solid #4a6fa5;
                border-radius: 10px;
                padding: 8px;
                font-size: 13px;
            }
        """)
        self.input_field.returnPressed.connect(self.send_message)
        input_layout.addWidget(self.input_field)

        # Voice button (microphone)
        self.voice_btn = QPushButton("🎤")
        self.voice_btn.setFixedSize(35, 35)
        self.voice_btn.setStyleSheet("""
            QPushButton {
                background-color: #5a4a8a;
                color: white;
                border-radius: 17px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #7a6aaa;
            }
        """)
        self.voice_btn.clicked.connect(self.toggle_voice_input)
        self.voice_btn.setEnabled(HAS_VOICE)
        self.voice_btn.setToolTip("语音输入" if HAS_VOICE else "语音功能不可用")
        input_layout.addWidget(self.voice_btn)

        self.send_btn = QPushButton("→")
        self.send_btn.setFixedSize(35, 35)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a6fa5;
                color: white;
                border-radius: 17px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5a8fd5;
            }
        """)
        self.send_btn.clicked.connect(self.send_message)
        input_layout.addWidget(self.send_btn)

        layout.addLayout(input_layout)

        # Confirmation buttons (for code execution approval)
        self.confirm_layout = QHBoxLayout()
        self.confirm_btn = QPushButton("✓ 执行")
        self.confirm_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a8a5a;
                color: white;
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #5aaa6a; }
        """)
        self.confirm_btn.clicked.connect(self._on_confirm_execute)

        self.cancel_btn = QPushButton("✗ 取消")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #8a4a4a;
                color: white;
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #aa5a5a; }
        """)
        self.cancel_btn.clicked.connect(self._on_cancel_execute)

        self.confirm_layout.addWidget(self.confirm_btn)
        self.confirm_layout.addWidget(self.cancel_btn)
        layout.addLayout(self.confirm_layout)

        # 默认隐藏确认按钮
        self.confirm_btn.hide()
        self.cancel_btn.hide()

        # Close button
        self.close_btn = QPushButton("×")
        self.close_btn.setFixedSize(20, 20)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #888;
                border: none;
                font-size: 16px;
            }
            QPushButton:hover {
                color: white;
            }
        """)
        self.close_btn.clicked.connect(self.hide)
        self.close_btn.move(self.width() - 25, 5)

        self.adjustSize()

        # Connect signals for thread-safe UI updates
        self.response_ready.connect(self._update_response)
        self.voice_text_ready.connect(self._on_voice_text)
        self.code_confirm_ready.connect(self._show_code_confirm)

    def toggle_voice_input(self):
        """Start or stop voice recording"""
        if not self.voice_module:
            return

        if self.is_recording:
            # Stop recording manually
            self.voice_module.stop_recording()
            self.response_label.setPlainText("正在转录...")
            self.voice_btn.setStyleSheet("""
                QPushButton {
                    background-color: #5a8a4a;
                    color: white;
                    border-radius: 17px;
                    font-size: 14px;
                }
            """)
            return

        self.is_recording = True
        self.voice_btn.setStyleSheet("""
            QPushButton {
                background-color: #aa4444;
                color: white;
                border-radius: 17px;
                font-size: 14px;
            }
        """)
        self.response_label.setPlainText("🎤 正在录音...")

        # Record in background thread
        thread = threading.Thread(target=self._record_voice)
        thread.daemon = True
        thread.start()

    def _record_voice(self):
        """Record and transcribe voice in background"""
        try:
            text = self.voice_module.voice_input(verbose=False)
            if text:
                self.voice_text_ready.emit(text)
            else:
                self.voice_text_ready.emit("")
        except Exception:
            self.voice_text_ready.emit("")

    def _on_voice_text(self, text):
        """Handle transcribed voice text"""
        self.is_recording = False
        self.voice_btn.setStyleSheet("""
            QPushButton {
                background-color: #5a4a8a;
                color: white;
                border-radius: 17px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #7a6aaa;
            }
        """)

        if text:
            self.input_field.setText(text)
            self.send_message()  # Auto-send
        else:
            self.response_label.setPlainText("没听清，再说一次？")

    def send_message(self):
        """Send message to local LLM"""
        text = self.input_field.text().strip()
        if not text:
            return

        self.input_field.clear()
        self.response_label.setPlainText("思考中...")

        thread = threading.Thread(target=self._call_llm, args=(text,))
        thread.daemon = True
        thread.start()

    def _update_response(self, text):
        """Update response label (called from main thread via signal)"""
        self.response_label.setPlainText(text)

    def _show_code_confirm(self, response_text, pending_code):
        """显示代码确认 UI"""
        self.pending_code = pending_code
        # 显示响应 + 待执行代码预览
        code_preview = pending_code.get("code", "")[:100]  # 预览前100字符
        display_text = f"[Agent] {response_text}\n\n📋 待执行代码:\n{code_preview}..."
        self.response_label.setPlainText(display_text)
        # 显示确认按钮
        self.confirm_btn.show()
        self.cancel_btn.show()
        self.adjustSize()

    def _on_confirm_execute(self):
        """用户点击确认执行"""
        if not self.pending_code:
            return

        try:
            response = requests.post(
                "http://localhost:8000/execute",
                json={
                    "language": self.pending_code["language"],
                    "code": self.pending_code["code"]
                },
                timeout=120
            )
            if response.status_code == 200:
                result = response.json()
                output = result.get("output", "无输出")
                self.response_label.setPlainText(f"[Agent] 执行完成:\n{output}")
            else:
                self.response_label.setPlainText("执行失败")
        except Exception as e:
            self.response_label.setPlainText(f"执行出错: {str(e)[:50]}")

        self._hide_confirm_buttons()
        if self.voice_module:
            self.voice_module.speak_async("执行完成")

    def _on_cancel_execute(self):
        """用户点击取消"""
        self.pending_code = None
        self._hide_confirm_buttons()
        self.response_label.setPlainText("[Agent] 已取消执行")

    def _hide_confirm_buttons(self):
        """隐藏确认按钮"""
        self.confirm_btn.hide()
        self.cancel_btn.hide()
        self.pending_code = None
        self.adjustSize()

    def _call_llm(self, prompt):
        """调用 LocalAgent API（内置路由），Ollama 作为备用"""
        context = self.parent_pet.get_context()
        context_info = f"\n当前状态：{context}" if context else ""

        system_prompt = f"""你是可爱的桌面宠物助手Io，连接着LocalAgent系统。
你的能力：浏览器控制、网页搜索、文件读写、执行命令、窗口控制、OCR识别。
用户请求操作时，生成相应的Python代码来完成任务。
回复简短（50字以内），轻松可爱。{context_info}"""

        answer = None
        pending_code = None
        mode = "chat"

        # 调用 LocalAgent API（内部处理路由）
        try:
            full_message = f"{system_prompt}\n\n用户: {prompt}"
            response = requests.post(
                "http://localhost:8000/chat",
                json={"message": full_message, "stream": False, "auto_run": False},
                timeout=120
            )
            if response.status_code == 200:
                result = response.json()
                answer = result.get("response", "")
                pending_code = result.get("pending_code")
                mode = result.get("mode", "chat")
        except:
            pass  # Fall through to Ollama

        # Fallback: 直接用 Ollama
        if not answer:
            mode = "fallback"
            try:
                response = requests.post(
                    "http://localhost:11434/api/chat",
                    json={
                        "model": "qwen2.5:1.5b",  # 小模型更快
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt}
                        ],
                        "stream": False,
                        "options": {"temperature": 0.7, "num_predict": 100}
                    },
                    timeout=30
                )
                if response.status_code == 200:
                    result = response.json()
                    answer = result.get("message", {}).get("content", "")
            except:
                self.response_ready.emit("无法连接\n请确保服务正在运行")
                return

        # 发送结果
        if answer:
            # 保存到历史记录
            history = load_history()
            history.append({
                "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "user": prompt,
                "ai": answer[:200]  # 只保存前200字符
            })
            # 只保留最近100条
            if len(history) > 100:
                history = history[-100:]
            save_history(history)

            if pending_code and mode == "agent":
                # Agent 想执行代码 → 显示确认 UI
                self.code_confirm_ready.emit(answer, pending_code)
                if self.voice_module:
                    self.voice_module.speak_async("我想执行一些代码，请确认")
            else:
                # 普通回答
                mode_label = {"chat": "[Chat]", "agent": "[Agent]", "fallback": "[Backup]"}.get(mode, "")
                self.response_ready.emit(f"{mode_label} {answer}")
                if self.voice_module:
                    self.voice_module.speak_async(answer)
        else:
            self.response_ready.emit("嗯...我不知道该说什么")

    def position_above_pet(self):
        """Position bubble above the pet"""
        pet_pos = self.parent_pet.pos()
        pet_size = self.parent_pet.size()

        x = pet_pos.x() + pet_size.width() // 2 - self.width() // 2
        y = pet_pos.y() - self.height() - 10

        # Keep on screen
        screen = QApplication.primaryScreen().geometry()
        x = max(10, min(x, screen.width() - self.width() - 10))
        y = max(10, y)

        self.move(x, y)


class IoPet(QWidget):
    """A glowing orb desktop pet"""

    clicked_signal = pyqtSignal()

    def __init__(self):
        super().__init__()

        # Window settings
        self.setWindowTitle("Io")
        self.setFixedSize(150, 150)

        # Make window frameless and transparent
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool  # Hides from taskbar
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        # Orb properties
        self.base_radius = 30
        self.current_radius = self.base_radius
        self.breath_phase = 0.0  # For breathing animation
        self.glow_intensity = 0.8

        # Colors (Io's signature blue-white glow)
        self.core_color = QColor(220, 240, 255)      # White-blue core
        self.glow_color = QColor(100, 180, 255, 150) # Blue glow
        self.outer_glow = QColor(60, 120, 200, 50)   # Faint outer glow

        # Animation timer
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self.animate)
        self.animation_timer.start(33)  # ~30 FPS

        # Drag support
        self.drag_position = None
        self.is_dragging = False

        # Chat bubble
        self.chat_bubble = ChatBubble(self)

        # Window activity tracking
        self.current_app = ""
        self.current_title = ""
        self.activity_timer = QTimer()
        self.activity_timer.timeout.connect(self._update_activity)
        self.activity_timer.start(3000)  # Check every 3 seconds

        # Center on screen
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - 200, screen.height() - 250)

    def animate(self):
        """Update animation state"""
        self.breath_phase += 0.07
        if self.breath_phase > 2 * math.pi:
            self.breath_phase = 0
        # Radius oscillates ±20% for visible breathing effect
        self.current_radius = self.base_radius * (1 + 0.2 * math.sin(self.breath_phase))

        self.update()  # Trigger repaint

    def _update_activity(self):
        """Track current active window (通过 LocalAgent API)"""
        try:
            response = requests.get("http://localhost:8000/context", timeout=1)
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    self.current_title = data.get("title", "")
                    self.current_app = data.get("app", "")
        except Exception:
            pass  # LocalAgent 未运行时静默忽略

    def get_context(self):
        """Get current activity context for LLM"""
        if self.current_app and self.current_title:
            title = self.current_title[:50] + "..." if len(self.current_title) > 50 else self.current_title
            return f"用户正在使用 {self.current_app}，窗口：{title}"
        elif self.current_app:
            return f"用户正在使用 {self.current_app}"
        return ""

    def paintEvent(self, event):
        """Draw the glowing orb"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        center = QPointF(self.width() / 2, self.height() / 2)

        # Draw outer glow (largest, most transparent)
        outer_gradient = QRadialGradient(center, self.current_radius * 2)
        outer_gradient.setColorAt(0, self.outer_glow)
        outer_gradient.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setBrush(outer_gradient)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(center, self.current_radius * 2, self.current_radius * 2)

        # Draw middle glow
        mid_gradient = QRadialGradient(center, self.current_radius * 1.3)
        mid_gradient.setColorAt(0, self.glow_color)
        mid_gradient.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setBrush(mid_gradient)
        painter.drawEllipse(center, self.current_radius * 1.3, self.current_radius * 1.3)

        # Draw core (brightest)
        core_gradient = QRadialGradient(center, self.current_radius)
        core_gradient.setColorAt(0, self.core_color)
        core_gradient.setColorAt(0.5, self.glow_color)
        core_gradient.setColorAt(1, QColor(self.glow_color.red(), self.glow_color.green(), self.glow_color.blue(), 0))
        painter.setBrush(core_gradient)
        painter.drawEllipse(center, self.current_radius, self.current_radius)

    def mousePressEvent(self, event):
        """Start dragging"""
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            self.is_dragging = False

    def mouseMoveEvent(self, event):
        """Handle dragging"""
        if self.drag_position is not None:
            self.is_dragging = True
            self.move(event.globalPos() - self.drag_position)
            # Update bubble position if visible
            if self.chat_bubble.isVisible():
                self.chat_bubble.position_above_pet()

    def mouseReleaseEvent(self, event):
        """Handle click (if not dragging) or stop dragging"""
        if event.button() == Qt.LeftButton:
            if not self.is_dragging:
                # This was a click, not a drag - toggle chat bubble
                self.toggle_chat()
            self.drag_position = None
            self.is_dragging = False

    def toggle_chat(self):
        """Show or hide the chat bubble"""
        if self.chat_bubble.isVisible():
            self.chat_bubble.hide()
        else:
            self.chat_bubble.position_above_pet()
            self.chat_bubble.show()
            self.chat_bubble.input_field.setFocus()

    def _get_startup_path(self):
        """Get the path to the startup file (跨平台)"""
        if sys.platform == 'win32':
            startup_folder = os.path.join(
                os.environ["APPDATA"],
                "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
            )
            return os.path.join(startup_folder, "IoPet.vbs")
        else:
            # Linux: ~/.config/autostart/
            autostart_dir = os.path.expanduser("~/.config/autostart")
            os.makedirs(autostart_dir, exist_ok=True)
            return os.path.join(autostart_dir, "iopet.desktop")

    def _is_autostart_enabled(self):
        """Check if autostart is enabled"""
        return os.path.exists(self._get_startup_path())

    def _toggle_autostart(self):
        """Enable or disable autostart (跨平台)"""
        startup_file = self._get_startup_path()

        if self._is_autostart_enabled():
            # Remove autostart
            os.remove(startup_file)
        else:
            if sys.platform == 'win32':
                # Windows: Create VBS script
                if getattr(sys, 'frozen', False):
                    exe_path = sys.executable
                    script = f'CreateObject("WScript.Shell").Run """{exe_path}""", 0, False'
                else:
                    script_path = os.path.abspath(__file__)
                    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
                    script = f'CreateObject("WScript.Shell").Run """{pythonw}"" ""{script_path}""", 0, False'
                with open(startup_file, "w", encoding="utf-8") as f:
                    f.write(script)
            else:
                # Linux: Create .desktop file
                script_path = os.path.abspath(__file__)
                python_path = sys.executable
                desktop_content = f"""[Desktop Entry]
Type=Application
Name=IoPet
Comment=Desktop Pet Companion
Exec={python_path} {script_path}
Icon=applications-games
Terminal=false
Categories=Utility;
StartupNotify=false
X-GNOME-Autostart-enabled=true
"""
                with open(startup_file, "w", encoding="utf-8") as f:
                    f.write(desktop_content)

    def _show_history(self):
        """显示聊天历史窗口"""
        history_window = HistoryWindow(self)
        history_window.exec_()

    def contextMenuEvent(self, event):
        """Right-click menu"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: rgba(30, 30, 50, 220);
                color: white;
                border: 1px solid #4a6fa5;
                border-radius: 5px;
                padding: 5px;
            }
            QMenu::item:selected {
                background-color: #4a6fa5;
            }
        """)

        # History
        history_action = menu.addAction("📜 查看历史")
        menu.addSeparator()

        # Autostart toggle
        autostart_text = "✓ 开机自启" if self._is_autostart_enabled() else "开机自启"
        autostart_action = menu.addAction(autostart_text)
        menu.addSeparator()
        quit_action = menu.addAction("退出 Io")

        action = menu.exec_(event.globalPos())

        if action == history_action:
            self._show_history()
        elif action == autostart_action:
            self._toggle_autostart()
        elif action == quit_action:
            self.chat_bubble.close()
            self.close()


def main():
    app = QApplication(sys.argv)
    pet = IoPet()
    pet.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
