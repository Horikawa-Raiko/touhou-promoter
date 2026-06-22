"""监听面板 — 常驻右侧的嵌入式 QQ 风格消息监听与回复面板

取代原来的独立 ListenerWindow 弹窗，直接嵌入主窗口右侧面板。

特性：
- QQ 聊天风格气泡，含群名/发送者/时间/内容
- 点击消息选中并锁定回复目标群
- 底部回复条：目标选择 + 文本输入 + 发送按钮
- 深色/浅色主题跟随
- 缓存本次发送周期的所有命中消息
"""

import os
import re
import base64
from datetime import datetime
from typing import Optional, Callable

from PyQt6.QtCore import Qt, QTimer, QDateTime, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap
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
)


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _render_cq_as_html(raw_message: str, self_nick: str = "") -> str:
    """将 CQ 码消息渲染为 QQ 风格的 HTML"""

    def replace_cq(m: re.Match) -> str:
        cq_type = m.group(1)
        params_str = m.group(2)
        params = {}
        for part in params_str.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                params[k.strip()] = v.strip()
        if cq_type == "at":
            qq = params.get("qq", "")
            if qq == "all":
                label = "全体成员"
            elif self_nick and qq != "all":
                label = self_nick
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
                 "user_id")

    def __init__(self, ts: float, gid: str, gname: str, nick: str, raw: str,
                 uid: str = ""):
        self.timestamp = ts
        self.group_id = gid
        self.group_name = gname
        self.sender_nick = nick
        self.raw_message = raw
        self.user_id = uid


class ListenerPanel(QWidget):
    """嵌入式监听面板 — 替换独立的 ListenerWindow"""

    reply_requested = pyqtSignal(str, str)
    """请求回复 (group_id, text) — 由 main_window 处理发送"""

    def __init__(self, parent=None, dark_mode: bool = True, self_nick: str = ""):
        super().__init__(parent)
        self._dark = dark_mode
        self._self_nick = self_nick
        self._messages: list[ListenMessage] = []
        self._selected_gid: str = ""
        self._msg_widgets: dict[int, QWidget] = {}
        self._selected_idx: int = -1

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

        # ===== 回复栏 =====
        reply_widget = QWidget()
        reply_widget.setObjectName("lp_reply_bar")
        reply_widget.setFixedHeight(40)
        rl = QHBoxLayout(reply_widget)
        rl.setContentsMargins(8, 4, 8, 4)
        rl.setSpacing(6)

        self._reply_target = QComboBox()
        self._reply_target.setMinimumWidth(140)
        self._reply_target.setSizePolicy(
            self._reply_target.sizePolicy().horizontalPolicy(),
            self._reply_target.sizePolicy().verticalPolicy()
        )
        self._reply_target.setToolTip("选择回复目标群")
        self._reply_target.currentIndexChanged.connect(self._on_reply_target_changed)
        rl.addWidget(self._reply_target)

        self._reply_input = QLineEdit()
        self._reply_input.setPlaceholderText("输入回复...")
        self._reply_input.returnPressed.connect(self._on_send_reply)
        rl.addWidget(self._reply_input, 1)

        self._reply_send_btn = QPushButton("发送")
        self._reply_send_btn.setFixedWidth(50)
        self._reply_send_btn.clicked.connect(self._on_send_reply)
        self._reply_send_btn.setEnabled(False)
        rl.addWidget(self._reply_send_btn)

        layout.addWidget(reply_widget)

    # ── 公开 API ──

    def add_message(self, group_id: str, group_name: str, sender_nick: str,
                    raw_message: str, timestamp: float | None = None,
                    user_id: str = ""):
        """添加一条命中消息并渲染气泡"""
        import time

        ts = timestamp or time.time()
        msg = ListenMessage(ts, group_id, group_name, sender_nick, raw_message, user_id)
        idx = len(self._messages)
        self._messages.append(msg)

        bubble = self._build_bubble(msg, idx)
        # 插入到 stretch 之前
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, bubble)

        self._count_label.setText(f"{len(self._messages)} 条")
        self._update_reply_targets()

        # 滚到底部
        QTimer.singleShot(50, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def clear(self):
        """清空所有消息"""
        self._messages.clear()
        self._msg_widgets.clear()
        self._selected_idx = -1
        self._selected_gid = ""
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
        msg = ListenMessage(time.time(), group_id, group_name, "我", text, "")
        idx = len(self._messages)
        self._messages.append(msg)
        bubble = self._build_own_bubble(msg)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, bubble)
        self._count_label.setText(f"{len(self._messages)} 条")
        QTimer.singleShot(50, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def set_dark_mode(self, dark: bool):
        self._dark = dark
        self._apply_theme()
        # 重建所有气泡
        self._msg_widgets.clear()
        while self._msg_layout.count() > 1:
            item = self._msg_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, msg in enumerate(self._messages):
            bubble = self._build_bubble(msg, i)
            self._msg_layout.insertWidget(self._msg_layout.count() - 1, bubble)
        # 高亮恢复
        if self._selected_idx >= 0 and self._selected_idx in self._msg_widgets:
            self._highlight_bubble(self._selected_idx)

    # ── 内部渲染 ──

    def _build_bubble(self, msg: ListenMessage, idx: int) -> QWidget:
        """构建接收消息气泡"""
        dt = QDateTime.fromSecsSinceEpoch(int(msg.timestamp))
        time_str = dt.toString("HH:mm:ss")

        bg = "#1c2a3a" if self._dark else "#e8f0fe"
        text_color = "#e6edf3" if self._dark else "#1f2328"
        meta_color = "#8b949e" if self._dark else "#656d76"
        border = "#30363d" if self._dark else "#d0d7de"

        html = _render_cq_as_html(msg.raw_message, self._self_nick)
        name = msg.group_name or msg.group_id

        bubble_html = (
            f'<div style="background:{bg};border:1px solid {border};'
            f'border-radius:10px;padding:8px 12px;cursor:pointer">'
            f'<div style="color:{meta_color};font-size:11px;margin-bottom:3px">'
            f'<b>群 {_escape_html(name)}</b>'
            f'</div>'
            f'<div style="color:{text_color};font-size:13px;line-height:1.5">'
            f'{html}</div>'
            f'<div style="color:{meta_color};font-size:10px;margin-top:4px;'
            f'display:flex;justify-content:space-between">'
            f'<span>{_escape_html(msg.sender_nick)}</span>'
            f'<span>{time_str}</span>'
            f'</div>'
            f'</div>'
        )

        w = QWidget()
        w.setCursor(Qt.CursorShape.PointingHandCursor)
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 2, 0, 2)
        label = QLabel(bubble_html)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(label)

        # 绑定点击事件
        w.mousePressEvent = lambda e, i=idx: self._on_bubble_clicked(i)
        self._msg_widgets[idx] = w

        return w

    def _build_own_bubble(self, msg: ListenMessage) -> QWidget:
        """构建自己的回复气泡（绿色，右对齐）"""
        dt = QDateTime.fromSecsSinceEpoch(int(msg.timestamp))
        time_str = dt.toString("HH:mm:ss")

        bg = "#1a3d1a" if self._dark else "#d4f5d4"
        text_color = "#e6edf3" if self._dark else "#1f2328"
        meta_color = "#8b949e" if self._dark else "#656d76"
        border = "#2d5a2d" if self._dark else "#a3d9a3"

        html = _escape_html(msg.raw_message).replace("\n", "<br>")

        bubble_html = (
            f'<div style="background:{bg};border:1px solid {border};'
            f'border-radius:10px;padding:8px 12px">'
            f'<div style="color:{text_color};font-size:13px;line-height:1.5">'
            f'{html}</div>'
            f'<div style="color:{meta_color};font-size:10px;margin-top:4px;'
            f'display:flex;justify-content:space-between">'
            f'<span>我 → {_escape_html(msg.group_name or msg.group_id)}</span>'
            f'<span>{time_str}</span>'
            f'</div>'
            f'</div>'
        )

        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(32, 2, 0, 2)
        label = QLabel(bubble_html)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(label)
        return w

    # ── 交互 ──

    def _on_bubble_clicked(self, idx: int):
        """点击气泡 → 高亮选中 + 设置回复目标"""
        if idx >= len(self._messages):
            return
        self._highlight_bubble(idx)
        msg = self._messages[idx]
        self._selected_gid = msg.group_id
        self._selected_idx = idx
        # 更新下拉框
        for i in range(self._reply_target.count()):
            if self._reply_target.itemData(i) == msg.group_id:
                self._reply_target.setCurrentIndex(i)
                break
        self._reply_send_btn.setEnabled(True)

    def _highlight_bubble(self, idx: int):
        """给指定索引的气泡加高亮边框"""
        highlight = "#58a6ff"
        for i, w in self._msg_widgets.items():
            label = w.findChild(QLabel)
            if label:
                html = label.text()
                if i == idx:
                    html = html.replace(
                        'border-radius:10px;',
                        f'border:2px solid {highlight};border-radius:10px;'
                    )
                    html = html.replace(
                        'border:1px solid ',
                        f'border:2px solid {highlight};'
                    )
                    # 简化：直接替换第一个 style 属性
                    import re as _re
                    html = _re.sub(
                        r'(style=")[^"]*(")',
                        lambda m, h=highlight: m.group(1)
                        + m.group(0)[7:-1].replace(
                            'border:1px solid #30363d',
                            f'border:2px solid {h}'
                        ).replace(
                            'border:1px solid #d0d7de',
                            f'border:2px solid {h}'
                        ).replace(
                            'border:1px solid #30363d',
                            f'border:2px solid {h}'
                        )
                        + m.group(2),
                        html
                    )
                else:
                    # 恢复普通边框
                    pass
                label.setText(html)

    def _on_reply_target_changed(self, idx: int):
        """下拉框选择改变"""
        if idx < 0:
            return
        gid = self._reply_target.itemData(idx)
        self._selected_gid = gid
        # 找到对应消息并高亮
        for i, msg in enumerate(self._messages):
            if msg.group_id == gid:
                self._highlight_bubble(i)
                self._selected_idx = i
                break
        self._reply_send_btn.setEnabled(bool(gid))

    def _on_send_reply(self):
        """发送回复"""
        text = self._reply_input.text().strip()
        if not text or not self._selected_gid:
            return
        group_name = ""
        for msg in self._messages:
            if msg.group_id == self._selected_gid:
                group_name = msg.group_name
                break
        self.reply_requested.emit(self._selected_gid, text)
        group_name = ""
        for msg in self._messages:
            if msg.group_id == self._selected_gid:
                group_name = msg.group_name
                break
        self.add_own_reply(self._selected_gid, group_name or self._selected_gid, text)
        self._reply_input.clear()

    def _update_reply_targets(self):
        """更新回复目标下拉框（显示群名而非群号）"""
        seen: dict[str, str] = {}
        current_gid = self._selected_gid
        for msg in self._messages:
            if msg.group_id and msg.group_id not in seen:
                label = msg.group_name or msg.group_id
                seen[msg.group_id] = label
        # 保留现有条目，只添加新的
        existing_ids = {self._reply_target.itemData(i)
                        for i in range(self._reply_target.count())}
        for gid, label in seen.items():
            if gid not in existing_ids:
                display = label if label and label != gid else f"群 {gid}"
                self._reply_target.addItem(display, gid)
        # 恢复选中
        if current_gid:
            for i in range(self._reply_target.count()):
                if self._reply_target.itemData(i) == current_gid:
                    self._reply_target.setCurrentIndex(i)
                    break

    # ── 主题 ──

    def _apply_theme(self):
        bg = "#0d1117" if self._dark else "#ffffff"
        header_bg = "#161b22" if self._dark else "#f6f8fa"
        border = "#30363d" if self._dark else "#d0d7de"
        text_color = "#e6edf3" if self._dark else "#1f2328"
        meta_color = "#8b949e" if self._dark else "#656d76"

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
        """)
