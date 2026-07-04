"""监听面板 — 常驻右侧的嵌入式 QQ 风格消息监听与回复面板

取代原来的独立 ListenerWindow 弹窗，直接嵌入主窗口右侧面板。

特性：
- QQ 聊天风格气泡（含头像占位），接收蓝色 / 自己绿色
- 右键气泡 → 回复此人（显示引用条）/ @此人（输入框 @标签）
- 右键头像 → @此人
- 回复时输入框上方显示被引用消息的缩略条
- 一次只能回复/@一个人
- 点击气泡/回复/@时群聊下拉框自动切换
- 深色/浅色主题跟随
"""

import os
import re
import base64
from datetime import datetime
from typing import Optional, Callable

from PyQt6.QtCore import Qt, QTimer, QDateTime, QPoint, QRect, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap, QMouseEvent
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QComboBox,
    QLineEdit,
    QFrame,
    QMenu,
    QTextEdit,
)


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _render_cq_as_html(raw_message: str, self_nick: str = "", self_id: str = "") -> str:
    """将 CQ 码消息渲染为 QQ 风格的 HTML"""

    def replace_cq(m: re.Match) -> str:
        cq_type = m.group(1)
        params_str = m.group(2)
        params = {}
        for part in params_str.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                params[k.strip()] = v.strip()
        if cq_type == "reply":
            return '<span style="color:#58a6ff;font-size:11px;border:1px solid #58a6ff;border-radius:4px;padding:0 4px;margin-right:4px">回复</span>'
        if cq_type == "at":
            qq = params.get("qq", "")
            if qq == "all":
                label = "全体成员"
            elif self_id and qq == self_id:
                label = self_nick or qq
            else:
                label = qq
            return f'<span style="color:#58a6ff;font-weight:bold">@{label}</span>'
        if cq_type == "image":
            file_path = params.get("file", "")
            url = params.get("url", "")
            if file_path and os.path.isfile(file_path):
                try:
                    with open(file_path, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode()
                    ext = os.path.splitext(file_path)[1].lower()
                    mime_map = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg",
                                ".gif": "gif", ".webp": "webp"}
                    mime = mime_map.get(ext, "png")
                    return (
                        f'<img src="data:image/{mime};base64,{b64}" '
                        f'style="max-width:180px;border-radius:8px;margin:4px 0">'
                    )
                except Exception:
                    pass
            if url:
                return (
                    f'<img src="{_escape_html(url)}" '
                    f'style="max-width:180px;border-radius:8px;margin:4px 0">'
                )
            return '<span style="color:#8b949e">[图片]</span>'
        if cq_type == "face":
            return f'<span style="color:#d29922">[表情{params.get("id","")}]</span>'
        return _escape_html(m.group(0))

    html = re.sub(r"\[CQ:(\w+),([^\]]+)\]", replace_cq, _escape_html(raw_message))
    return html.replace("\n", "<br>")


class ListenMessage:
    """一条监听命中的消息"""
    __slots__ = ("timestamp", "group_id", "group_name", "sender_nick", "raw_message",
                 "user_id", "message_id")

    def __init__(self, ts: float, gid: str, gname: str, nick: str, raw: str,
                 uid: str = "", msg_id: str = ""):
        self.timestamp = ts
        self.group_id = gid
        self.group_name = gname
        self.sender_nick = nick
        self.raw_message = raw
        self.user_id = uid
        self.message_id = msg_id


class ListenerPanel(QWidget):
    """嵌入式监听面板 — 替换独立的 ListenerWindow"""

    reply_requested = pyqtSignal(str, str)
    """请求回复 (group_id, text) — 由 main_window 处理发送"""

    def __init__(self, parent=None, dark_mode: bool = True, self_nick: str = "", self_id: str = ""):
        super().__init__(parent)
        self._dark = dark_mode
        self._self_nick = self_nick
        self._self_id = self_id
        self._messages: list[ListenMessage] = []
        self._selected_gid: str = ""
        self._msg_widgets: dict[int, QWidget] = {}
        self._selected_idx: int = -1
        self._reply_target_msg: Optional[ListenMessage] = None   # 正在回复的消息
        self._at_target_msg: Optional[ListenMessage] = None      # 正在 @ 的消息

        self._build_ui()
        self._apply_theme()

    # ── UI 构建 ──

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ===== 顶栏 =====
        header = QWidget()
        header.setFixedHeight(36)
        header.setObjectName("lp_header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 4, 8, 4)
        title = QLabel("消息监听")
        title_font = QFont()
        title_font.setPointSize(10)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setObjectName("lp_title")
        hl.addWidget(title)
        hl.addStretch()
        self._count_label = QLabel("0 条")
        self._count_label.setObjectName("lp_count")
        hl.addWidget(self._count_label)
        self._clear_btn = QPushButton("清空")
        self._clear_btn.setFixedHeight(22)
        self._clear_btn.clicked.connect(self.clear)
        hl.addWidget(self._clear_btn)
        layout.addWidget(header)

        # ===== 消息滚动区 =====
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setObjectName("lp_scroll")

        self._container = QWidget()
        self._container.setObjectName("lp_container")
        self._msg_layout = QVBoxLayout(self._container)
        self._msg_layout.setContentsMargins(8, 8, 8, 8)
        self._msg_layout.setSpacing(4)
        self._msg_layout.addStretch()
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll, 1)

        # ===== 分隔线 =====
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        # ===== 引用预览条 =====
        self._quote_bar = QWidget()
        self._quote_bar.setObjectName("lp_quote_bar")
        self._quote_bar.setFixedHeight(28)
        self._quote_bar.setVisible(False)
        ql = QHBoxLayout(self._quote_bar)
        ql.setContentsMargins(10, 2, 8, 2)
        ql.setSpacing(6)
        self._quote_icon = QLabel("↩")
        self._quote_icon.setObjectName("lp_quote_icon")
        self._quote_icon.setFixedWidth(16)
        ql.addWidget(self._quote_icon)
        self._quote_label = QLabel("")
        self._quote_label.setObjectName("lp_quote_text")
        self._quote_label.setWordWrap(False)
        self._quote_label.setMaximumWidth(220)
        ql.addWidget(self._quote_label)
        ql.addStretch()
        self._quote_cancel = QPushButton("×")
        self._quote_cancel.setObjectName("lp_tag_cancel")
        self._quote_cancel.setFixedSize(22, 22)
        self._quote_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._quote_cancel.clicked.connect(self._cancel_reply_target)
        ql.addWidget(self._quote_cancel)
        layout.addWidget(self._quote_bar)

        # ===== AT 标签条 =====
        self._at_bar = QWidget()
        self._at_bar.setObjectName("lp_at_bar")
        self._at_bar.setFixedHeight(28)
        self._at_bar.setVisible(False)
        al = QHBoxLayout(self._at_bar)
        al.setContentsMargins(10, 2, 8, 2)
        al.setSpacing(6)
        at_icon = QLabel("@")
        at_icon.setObjectName("lp_at_icon")
        at_icon.setFixedWidth(16)
        al.addWidget(at_icon)
        self._at_label = QLabel("")
        self._at_label.setObjectName("lp_at_text")
        self._at_label.setWordWrap(False)
        self._at_label.setMaximumWidth(220)
        al.addWidget(self._at_label)
        al.addStretch()
        at_cancel = QPushButton("×")
        at_cancel.setObjectName("lp_tag_cancel")
        at_cancel.setFixedSize(22, 22)
        at_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        at_cancel.clicked.connect(self._cancel_at_target)
        al.addWidget(at_cancel)
        layout.addWidget(self._at_bar)

        # ===== 回复栏 =====
        reply_widget = QWidget()
        reply_widget.setObjectName("lp_reply_bar")
        reply_widget.setFixedHeight(40)
        rl = QHBoxLayout(reply_widget)
        rl.setContentsMargins(8, 4, 8, 4)
        rl.setSpacing(6)

        self._reply_target = QComboBox()
        self._reply_target.setMinimumWidth(140)
        self._reply_target.setToolTip("选择回复目标群")
        self._reply_target.currentIndexChanged.connect(self._on_reply_target_changed)
        rl.addWidget(self._reply_target)

        self._reply_input = QLineEdit()
        self._reply_input.setPlaceholderText("输入回复...")
        self._reply_input.returnPressed.connect(self._on_send_reply)
        self._reply_input.textChanged.connect(self._on_reply_input_changed)
        rl.addWidget(self._reply_input, 1)

        self._reply_send_btn = QPushButton("发送")
        self._reply_send_btn.setFixedWidth(50)
        self._reply_send_btn.clicked.connect(self._on_send_reply)
        self._reply_send_btn.setEnabled(False)
        rl.addWidget(self._reply_send_btn)

        layout.addWidget(reply_widget)

        # ===== 悬浮大文本框 =====
        self._fulltext_preview = QTextEdit(self)
        self._fulltext_preview.setReadOnly(True)
        self._fulltext_preview.setFrameStyle(QFrame.Shape.NoFrame)
        self._fulltext_preview.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._fulltext_preview.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._fulltext_preview.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._fulltext_preview.setVisible(False)
        self._fulltext_preview.setObjectName("lp_fulltext_preview")

    # ── 公开 API ──

    def set_bot_info(self, self_id: str, self_nick: str):
        """更新 bot 自己的 QQ 号和昵称（登录成功后调用）"""
        changed = self._self_id != self_id or self._self_nick != self_nick
        self._self_id = self_id
        self._self_nick = self_nick
        if changed and self._messages:
            self._rebuild_all_bubbles()

    def add_message(self, group_id: str, group_name: str, sender_nick: str,
                    raw_message: str, timestamp: float | None = None,
                    user_id: str = "", message_id: str = "",
                    sender_user_id: str = ""):
        """添加一条命中消息并渲染气泡"""
        import time

        ts = timestamp or time.time()
        uid = user_id or sender_user_id
        msg = ListenMessage(ts, group_id, group_name, sender_nick, raw_message, uid, message_id)
        idx = len(self._messages)
        self._messages.append(msg)

        bubble = self._build_bubble(msg, idx)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, bubble)

        self._count_label.setText(f"{len(self._messages)} 条")
        self._update_reply_targets()

        QTimer.singleShot(50, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def clear(self):
        """清空所有消息"""
        self._messages.clear()
        self._msg_widgets.clear()
        self._selected_idx = -1
        self._selected_gid = ""
        self._reply_target_msg = None
        self._at_target_msg = None
        self._quote_bar.setVisible(False)
        self._at_bar.setVisible(False)
        while self._msg_layout.count() > 0:
            item = self._msg_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._msg_layout.addStretch()
        self._count_label.setText("0 条")
        self._reply_target.clear()
        self._reply_send_btn.setEnabled(False)

    def add_own_reply(self, group_id: str, group_name: str, text: str):
        """添加一条自己的回复气泡（右侧绿色）"""
        import time
        msg = ListenMessage(time.time(), group_id, group_name, "我", text, "", "")
        idx = len(self._messages)
        self._messages.append(msg)
        bubble = self._build_own_bubble(msg)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, bubble)
        self._count_label.setText(f"{len(self._messages)} 条")
        QTimer.singleShot(50, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def _rebuild_all_bubbles(self):
        """重建所有气泡（bot 信息变更时调用）"""
        self._msg_widgets.clear()
        while self._msg_layout.count() > 1:
            item = self._msg_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, msg in enumerate(self._messages):
            if msg.sender_nick == "我":
                bubble = self._build_own_bubble(msg)
            else:
                bubble = self._build_bubble(msg, i)
            self._msg_layout.insertWidget(self._msg_layout.count() - 1, bubble)
        if self._selected_idx >= 0 and self._selected_idx in self._msg_widgets:
            self._highlight_bubble(self._selected_idx)

    def set_dark_mode(self, dark: bool):
        self._dark = dark
        self._apply_theme()
        self._msg_widgets.clear()
        while self._msg_layout.count() > 1:
            item = self._msg_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, msg in enumerate(self._messages):
            if msg.sender_nick == "我":
                bubble = self._build_own_bubble(msg)
            else:
                bubble = self._build_bubble(msg, i)
            self._msg_layout.insertWidget(self._msg_layout.count() - 1, bubble)
        if self._selected_idx >= 0 and self._selected_idx in self._msg_widgets:
            self._highlight_bubble(self._selected_idx)

    # ── 内部渲染 ──

    def _build_bubble(self, msg: ListenMessage, idx: int) -> QWidget:
        """构建接收消息气泡 — QQ 风格带头像占位"""
        dt = QDateTime.fromSecsSinceEpoch(int(msg.timestamp))
        time_str = dt.toString("HH:mm:ss")

        bubble_bg = "#1e4a6e" if self._dark else "#c6e2ff"
        text_color = "#e6edf3" if self._dark else "#1f2328"
        meta_color = "#8b949e" if self._dark else "#656d76"
        avatar_bg = "#4a90d9" if self._dark else "#58a6ff"

        html = _render_cq_as_html(msg.raw_message, self._self_nick, self._self_id)
        name = msg.group_name or msg.group_id

        avatar_char = _escape_html(msg.sender_nick[0]) if msg.sender_nick else "群"

        w = QWidget()
        w.setCursor(Qt.CursorShape.PointingHandCursor)
        w.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        w.customContextMenuRequested.connect(lambda pos, i=idx: self._on_bubble_context_menu(pos, i))
        outer = QHBoxLayout(w)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(8)

        # 头像占位
        avatar = QLabel(avatar_char)
        avatar.setFixedSize(36, 36)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            f"background:{avatar_bg};border-radius:4px;color:#fff;"
            f"font-weight:bold;font-size:15px"
        )
        avatar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        avatar.customContextMenuRequested.connect(lambda pos, i=idx: self._on_avatar_context_menu(pos, i))
        outer.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)

        # 右侧内容
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(3)

        # 发送者 · 群名
        header = QLabel(
            f'<span style="color:{meta_color};font-size:11px">'
            f'{_escape_html(msg.sender_nick)} · {_escape_html(name)}'
            f'</span>'
        )
        header.setTextFormat(Qt.TextFormat.RichText)
        cl.addWidget(header)

        # 气泡
        bubble = QLabel(
            f'<div style="color:{text_color};font-size:13px;line-height:1.5">'
            f'{html}</div>'
        )
        bubble.setWordWrap(True)
        bubble.setTextFormat(Qt.TextFormat.RichText)
        bubble.setStyleSheet(
            f"background:{bubble_bg};border:2px solid transparent;"
            f"border-radius:10px;padding:6px 10px"
        )
        cl.addWidget(bubble)

        # 时间
        time_label = QLabel(
            f'<span style="color:{meta_color};font-size:10px">{time_str}</span>'
        )
        time_label.setTextFormat(Qt.TextFormat.RichText)
        cl.addWidget(time_label)

        outer.addWidget(content)
        outer.addStretch()

        # 保存气泡 label 引用用于高亮
        w._bubble_label = bubble

        # 绑定点击事件
        w.mousePressEvent = lambda e, i=idx: self._on_bubble_mouse_press(e, i)
        self._msg_widgets[idx] = w

        return w

    def _build_own_bubble(self, msg: ListenMessage) -> QWidget:
        """构建自己的回复气泡 — QQ 风格绿色右对齐"""
        dt = QDateTime.fromSecsSinceEpoch(int(msg.timestamp))
        time_str = dt.toString("HH:mm:ss")

        bubble_bg = "#1e6e4a" if self._dark else "#b8f0c8"
        text_color = "#e6edf3" if self._dark else "#1f2328"
        meta_color = "#8b949e" if self._dark else "#656d76"
        avatar_bg = "#2ea043" if self._dark else "#3fb950"

        name = msg.group_name or msg.group_id
        text = _escape_html(msg.raw_message).replace("\n", "<br>")

        w = QWidget()
        outer = QHBoxLayout(w)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(8)

        # 左侧占位（把内容推到右边）
        outer.addStretch()

        # 内容（右对齐）
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(3)

        # 发送者 · 群名
        header = QLabel(
            f'<span style="color:{meta_color};font-size:11px">'
            f'我 · {_escape_html(name)}'
            f'</span>'
        )
        header.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.setTextFormat(Qt.TextFormat.RichText)
        cl.addWidget(header)

        # 气泡
        bubble = QLabel(
            f'<div style="color:{text_color};font-size:13px;line-height:1.5">'
            f'{text}</div>'
        )
        bubble.setWordWrap(True)
        bubble.setTextFormat(Qt.TextFormat.RichText)
        bubble.setStyleSheet(
            f"background:{bubble_bg};border:2px solid transparent;"
            f"border-radius:10px;padding:6px 10px"
        )
        cl.addWidget(bubble)

        # 时间
        time_label = QLabel(
            f'<span style="color:{meta_color};font-size:10px">{time_str}</span>'
        )
        time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        time_label.setTextFormat(Qt.TextFormat.RichText)
        cl.addWidget(time_label)

        outer.addWidget(content)

        # 头像（右侧）
        avatar = QLabel("我")
        avatar.setFixedSize(36, 36)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            f"background:{avatar_bg};border-radius:4px;color:#fff;"
            f"font-weight:bold;font-size:15px"
        )
        outer.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)

        return w

    # ── 交互 ──

    def _on_bubble_mouse_press(self, event: QMouseEvent, idx: int):
        """气泡点击（左键选中，右键交给 contextMenu）"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_bubble_clicked(idx)

    def _on_bubble_clicked(self, idx: int):
        """点击气泡 → 高亮选中 + 设置回复目标"""
        if idx >= len(self._messages):
            return
        self._highlight_bubble(idx)
        msg = self._messages[idx]
        self._selected_gid = msg.group_id
        self._selected_idx = idx
        self._switch_group_dropdown(msg.group_id)
        self._reply_send_btn.setEnabled(True)

    def _on_bubble_context_menu(self, pos, idx: int):
        """气泡右键菜单"""
        if idx >= len(self._messages):
            return
        msg = self._messages[idx]
        menu = QMenu(self)
        reply_action = menu.addAction("↩ 回复此人")
        at_action = menu.addAction("@ 提及此人")
        action = menu.exec(self._msg_widgets[idx].mapToGlobal(pos))
        if action == reply_action:
            self._set_reply_target(msg)
        elif action == at_action:
            self._set_at_target(msg)

    def _on_avatar_context_menu(self, pos, idx: int):
        """头像右键菜单 — 只有 @此人"""
        if idx >= len(self._messages):
            return
        msg = self._messages[idx]
        menu = QMenu(self)
        at_action = menu.addAction("@ 提及此人")
        action = menu.exec(self._msg_widgets[idx].mapToGlobal(pos))
        if action == at_action:
            self._set_at_target(msg)

    def _strip_cq(self, raw: str) -> str:
        """去掉 CQ 码只留纯文本"""
        return re.sub(r"\[CQ:[^\]]+\]", "", raw).strip()

    def _set_reply_target(self, msg: ListenMessage):
        """设置回复目标 + 显示引用条和 @ 条 + 切换群聊"""
        self._reply_target_msg = msg
        # 回复时自动 @ 同一个人
        if self._at_target_msg is not msg:
            self._set_at_bar(msg)

        # 引用条
        plain = self._strip_cq(msg.raw_message)
        summary = _escape_html(plain[:30])
        if len(plain) > 30:
            summary += "..."
        sender = _escape_html(msg.sender_nick)
        self._quote_label.setText(f"回复 {sender}: {summary}")
        self._quote_bar.setVisible(True)

    def _set_at_target(self, msg: ListenMessage):
        """设置 @ 目标 + 显示 @ 标签 + 切换群聊（独立于回复引用）"""
        self._at_target_msg = msg
        self._set_at_bar(msg)

        # 自动选群 + 高亮
        self._selected_gid = msg.group_id
        self._switch_group_dropdown(msg.group_id)
        for i, m in enumerate(self._messages):
            if m is msg:
                self._highlight_bubble(i)
                self._selected_idx = i
                break
        self._reply_send_btn.setEnabled(True)

    def _set_at_bar(self, msg: ListenMessage):
        """显示 @ 标签条"""
        nick = _escape_html(msg.sender_nick)
        self._at_label.setText(f"@{nick}")
        self._at_bar.setVisible(True)

        # 自动选群 + 高亮
        self._selected_gid = msg.group_id
        self._switch_group_dropdown(msg.group_id)
        for i, m in enumerate(self._messages):
            if m is msg:
                self._highlight_bubble(i)
                self._selected_idx = i
                break
        self._reply_send_btn.setEnabled(True)

    def _cancel_reply_target(self):
        """取消回复目标（同时取消 @）"""
        self._reply_target_msg = None
        self._at_target_msg = None
        self._quote_bar.setVisible(False)
        self._at_bar.setVisible(False)

    def _cancel_at_target(self):
        """只取消 @，保留引用"""
        self._at_target_msg = None
        self._at_bar.setVisible(False)

    def _on_reply_input_changed(self, text: str):
        """输入超过20字时在回复栏上方悬浮显示完整文本"""
        if len(text) > 20:
            self._fulltext_preview.setPlainText(text)
            self._position_fulltext_preview()
            self._fulltext_preview.setVisible(True)
            self._fulltext_preview.raise_()
        else:
            self._fulltext_preview.setVisible(False)

    def _position_fulltext_preview(self):
        """将悬浮预览定位到输入框下方，向下扩展遮挡日志区"""
        mw = self.window()
        if self._fulltext_preview.parent() != mw:
            self._fulltext_preview.setParent(mw)
            self._fulltext_preview.show()
            self._apply_preview_style()

        # 固定宽度，让 QTextEdit document 按此宽度换行后取高度
        w = self.width() - 16
        self._fulltext_preview.setFixedWidth(w)
        self._fulltext_preview.document().setTextWidth(w - 20)  # 减去 padding
        doc = self._fulltext_preview.document()
        doc_h = int(doc.size().height())
        h = min(doc_h + 14, 200)
        self._fulltext_preview.setFixedHeight(max(h, 32))

        # 定位在输入框正下方，跟 ListenerPanel 左端对齐
        pt = self.mapTo(mw, QPoint(0, self.height()))
        self._fulltext_preview.move(pt.x() + 8, pt.y() + 2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fulltext_preview.isVisible():
            self._position_fulltext_preview()

    def _switch_group_dropdown(self, gid: str):
        """切换群聊下拉框到指定群"""
        for i in range(self._reply_target.count()):
            if self._reply_target.itemData(i) == gid:
                self._reply_target.setCurrentIndex(i)
                return

    def _highlight_bubble(self, idx: int):
        """给指定索引的气泡加蓝色边框高亮"""
        highlight_bg = "#1a4a7a" if self._dark else "#c6e2ff"
        highlight_border = "#58a6ff"
        normal_bg = "#1e4a6e" if self._dark else "#c6e2ff"
        for i, w in self._msg_widgets.items():
            bubble_label = getattr(w, '_bubble_label', None)
            if not bubble_label:
                continue
            if i == idx:
                bubble_label.setStyleSheet(
                    f"background:{highlight_bg};border:2px solid {highlight_border};"
                    f"border-radius:10px;padding:6px 10px"
                )
            else:
                bubble_label.setStyleSheet(
                    f"background:{normal_bg};border:2px solid transparent;"
                    f"border-radius:10px;padding:6px 10px"
                )

    def _on_reply_target_changed(self, idx: int):
        """下拉框选择改变"""
        if idx < 0:
            return
        gid = self._reply_target.itemData(idx)
        self._selected_gid = gid
        for i, msg in enumerate(self._messages):
            if msg.group_id == gid:
                self._highlight_bubble(i)
                self._selected_idx = i
                break
        self._reply_send_btn.setEnabled(bool(gid))

    def _on_send_reply(self):
        """发送回复 — 构造带 CQ 码的消息"""
        text = self._reply_input.text().strip()
        if not text or not self._selected_gid:
            return

        group_name = ""
        for msg in self._messages:
            if msg.group_id == self._selected_gid:
                group_name = msg.group_name
                break

        # 构造消息前缀
        prefix = ""
        if self._reply_target_msg and self._reply_target_msg.message_id:
            prefix += f"[CQ:reply,id={self._reply_target_msg.message_id}]"
        if self._at_target_msg and self._at_target_msg.user_id:
            prefix += f"[CQ:at,qq={self._at_target_msg.user_id}] "

        full_text = prefix + text
        self.reply_requested.emit(self._selected_gid, full_text)

        # 显示自己的回复气泡
        self.add_own_reply(self._selected_gid, group_name or self._selected_gid, text)

        # 清理状态
        self._reply_input.clear()
        self._reply_target_msg = None
        self._at_target_msg = None
        self._quote_bar.setVisible(False)
        self._at_bar.setVisible(False)

    def _update_reply_targets(self):
        """更新回复目标下拉框（显示群名而非群号）"""
        seen: dict[str, str] = {}
        current_gid = self._selected_gid
        for msg in self._messages:
            if msg.group_id and msg.group_id not in seen:
                label = msg.group_name or msg.group_id
                seen[msg.group_id] = label
        existing_ids = {self._reply_target.itemData(i)
                       for i in range(self._reply_target.count())}
        for gid, label in seen.items():
            if gid not in existing_ids:
                display = label if label and label != gid else f"群 {gid}"
                self._reply_target.addItem(display, gid)
        if current_gid:
            for i in range(self._reply_target.count()):
                if self._reply_target.itemData(i) == current_gid:
                    self._reply_target.setCurrentIndex(i)
                    break

    # ── 主题 ──

    def _apply_preview_style(self):
        """直接给悬浮预览设置样式（不受父组件 QSS 继承影响）"""
        bg = "#0d1117" if self._dark else "#ffffff"
        border = "#30363d" if self._dark else "#d0d7de"
        text_color = "#e6edf3" if self._dark else "#1f2328"
        self._fulltext_preview.setStyleSheet(
            f"background: {bg}; color: {text_color};"
            f"border: 1px solid {border}; border-radius: 6px;"
            f"padding: 6px 10px; font-size: 12px;"
        )

    def _apply_theme(self):
        bg = "#0d1117" if self._dark else "#ffffff"
        header_bg = "#161b22" if self._dark else "#f6f8fa"
        border = "#30363d" if self._dark else "#d0d7de"
        text_color = "#e6edf3" if self._dark else "#1f2328"
        meta_color = "#8b949e" if self._dark else "#656d76"
        quote_bg = "rgba(88, 166, 255, 0.12)" if self._dark else "rgba(88, 166, 255, 0.15)"
        at_bg = "rgba(249, 117, 131, 0.12)" if self._dark else "rgba(249, 117, 131, 0.15)"
        cancel_hover = "#3a3a3a" if self._dark else "#d0d0d0"
        cancel_color = "#999999" if self._dark else "#666666"
        cancel_hover_color = "#ffffff" if self._dark else "#000000"

        self.setStyleSheet(f"""
            QWidget#lp_header {{
                background: {header_bg};
                border-bottom: 1px solid {border};
            }}
            QLabel#lp_title {{
                color: {text_color};
                background: transparent;
            }}
            QLabel#lp_count {{
                color: {meta_color};
                background: transparent;
                font-size: 11px;
            }}
            QScrollArea#lp_scroll, QWidget#lp_container {{
                background: {bg};
                border: none;
            }}
            QWidget#lp_reply_bar {{
                background: {header_bg};
                border-top: 1px solid {border};
            }}
            QWidget#lp_quote_bar {{
                background: {quote_bg};
                border-bottom: 1px solid {border};
            }}
            QWidget#lp_at_bar {{
                background: {at_bg};
                border-bottom: 1px solid {border};
            }}
            QLabel#lp_quote_icon {{
                color: #58a6ff;
                font-size: 14px;
                background: transparent;
            }}
            QLabel#lp_quote_text {{
                color: {meta_color};
                font-size: 12px;
                background: transparent;
            }}
            QLabel#lp_at_icon {{
                color: #f97583;
                font-size: 14px;
                font-weight: bold;
                background: transparent;
            }}
            QLabel#lp_at_text {{
                color: {meta_color};
                font-size: 12px;
                background: transparent;
            }}
            QPushButton#lp_tag_cancel {{
                border: none;
                border-radius: 11px;
                background: transparent;
                color: {cancel_color};
                font-size: 16px;
                font-weight: bold;
                padding: 0;
                min-width: 22px;
                min-height: 22px;
            }}
            QPushButton#lp_tag_cancel:hover {{
                background: {cancel_hover};
                color: {cancel_hover_color};
            }}
            QLineEdit {{
                border: 1px solid {border};
                border-radius: 6px;
                padding: 4px 8px;
                background: {bg};
                color: {text_color};
            }}
            QComboBox {{
                border: 1px solid {border};
                border-radius: 6px;
                padding: 2px 6px;
                background: {bg};
                color: {text_color};
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QPushButton {{
                border: 1px solid {border};
                border-radius: 6px;
                padding: 4px 10px;
                background: {header_bg};
                color: {text_color};
            }}
            QPushButton:hover {{
                background: {"#21262d" if self._dark else "#e1e4e8"};
            }}
            QTextEdit#lp_fulltext_preview {{
                background: {bg};
                color: {text_color};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
            }}
        """)
        if self._fulltext_preview.isVisible():
            self._apply_preview_style()
