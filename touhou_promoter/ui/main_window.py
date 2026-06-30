"""主窗口 — QSplitter左右布局，集成登录/群列表/消息编辑/发送控制/日志"""
import os
import platform
import subprocess
import sys
from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QSplitter, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTreeWidget, QTreeWidgetItem, QTextEdit, QPushButton,
    QProgressBar, QPlainTextEdit, QStatusBar, QMessageBox, QGroupBox,
    QFileDialog, QScrollArea, QLineEdit, QMenu, QApplication, QDialog, QFrame,
    QHeaderView,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QIcon

from touhou_promoter.state.app_state import AppState
from touhou_promoter.state.config_manager import ConfigManager
from touhou_promoter.state.send_state import SendStateManager
from touhou_promoter.core.napcat_manager import NapCatManager
from touhou_promoter.core.napcat_bootstrap import ensure_napcat_ready
from touhou_promoter.core.onebot_client import OneBotHTTPClient
from touhou_promoter.core.onebot_adapter import build_intersection
from touhou_promoter.ui.workers import SendWorker, RecallWorker
from touhou_promoter.ui.settings_dialog import SettingsDialog
from touhou_promoter.core.post_send_listener import PostSendListener
from touhou_promoter.ui.listener_panel import ListenerPanel


class NapCatSetupWorker(QThread):
    """在子线程中搜索/下载 NapCat，避免阻塞 GUI"""
    status = pyqtSignal(str)
    progress = pyqtSignal(str, int, int)  # (filename, done, total)
    finished = pyqtSignal(str)            # napcat_root 路径
    failed = pyqtSignal(str)              # 错误信息

    def __init__(self, config_dir: str):
        super().__init__()
        self._config_dir = config_dir

    def run(self):
        try:
            result = ensure_napcat_ready(
                self._config_dir,
                status_cb=lambda msg: self.status.emit(msg),
                progress_cb=lambda fn, done, total: self.progress.emit(fn, done, total),
            )
            if result:
                self.finished.emit(result)
            else:
                self.failed.emit("NapCat 安装失败，请检查网络连接后重试")
        except Exception as e:
            self.failed.emit(str(e))


class GroupDetailWorker(QThread):
    """在后台获取群详情，不阻塞 UI"""
    finished = pyqtSignal(str, str, dict)
    failed = pyqtSignal(str)

    def __init__(self, client, gid, name, parent=None):
        super().__init__(parent)
        self._client = client
        self._gid = gid
        self._name = name

    def run(self):
        try:
            info = self._client.get_group_info(self._gid, no_cache=False)
            self.finished.emit(self._gid, self._name, info)
        except Exception as e:
            self.failed.emit(str(e))


class QuickLoginDialog(QDialog):
    """快速登录账号选择弹窗"""
    def __init__(self, accounts: list, parent=None, show_scan_option: bool = False):
        super().__init__(parent)
        self.setWindowTitle("快速登录")
        self.setMinimumWidth(320)
        self._selected_qq = ""
        self._scan_mode = False
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("检测到以下已缓存账号，点击即可免扫码登录：")
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 13px;")
        layout.addWidget(title)

        for qq, nickname in accounts:
            label = f"{nickname} ({qq})" if nickname else qq
            btn = QPushButton(label)
            btn.setFixedHeight(38)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, q=qq: self._select(q))
            layout.addWidget(btn)

        if show_scan_option:
            scan_btn = QPushButton("扫码登录（不使用缓存账号）")
            scan_btn.setFixedHeight(38)
            scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            scan_btn.setStyleSheet("color: #888; font-size: 12px;")
            scan_btn.clicked.connect(self._select_scan)
            layout.addWidget(scan_btn)

    def _select_scan(self):
        self._scan_mode = True
        self.accept()

    def _select(self, qq: str):
        self._selected_qq = qq
        self.accept()

    def selected_qq(self) -> str:
        return self._selected_qq

    def is_scan_mode(self) -> bool:
        return self._scan_mode


class GetLoginWorker(QThread):
    """OneBot HTTP 就绪后单次获取登录信息"""
    login_done = pyqtSignal(bool, str, str)  # (ok, uid, nickname)

    def run(self):
        try:
            client = OneBotHTTPClient(timeout=5.0)
            info = client.get_login_info()
            uid = str(info.get("user_id", ""))
            nickname = info.get("nickname", "")
            self.login_done.emit(True, uid, nickname)
        except Exception as e:
            self.login_done.emit(False, "", str(e))


class MainWindow(QMainWindow):
    """东方Project一键宣发姬 主窗口"""

    # ── 明亮主题 ──────────────────────────────────────────────────
    # ── 博丽神社巫女 亮色主题（和纸风）──────────────────────────────
    _THEME_LIGHT = """
    /* === 全局 === */
    QMainWindow {
        background: #e8ddd5;
        background-image: url({{asanoha_light}});
    }
    QWidget#main_central {
        background: transparent;
    }
    QSplitter, QSplitter::handle {
        background: transparent;
    }
    QWidget {
        background-color: #f5efe8;
        color: #2a1810;
        font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif;
        font-size: 13px;
    }

    /* === 分组框 === */
    QGroupBox {
        background-color: #ffffff;
        background-image: url({{asanoha_light}});
        border: 1px solid #d4c8b8;
        border-radius: 8px;
        margin-top: 16px;
        padding: 18px 12px 12px 12px;
        font-weight: bold;
        font-size: 13px;
        color: #8a7020;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 14px;
        padding: 0 8px;
        color: #8a7020;
        background: #ffffff;
        border-radius: 3px;
    }

    /* === 消息编辑区补充样式 === */
    QLabel#me_char_count {
        font-size: 10px;
        color: #7a6a5a;
        background: transparent;
        padding: 0;
    }

    /* === 输入框 === */
    QLineEdit {
        border: 1px solid #d4c8b8;
        border-radius: 6px;
        padding: 4px 8px;
        background: #ffffff;
        color: #2a1810;
        font-size: 13px;
    }
    QLineEdit:focus {
        border-color: #c04040;
    }

    /* === 按钮 — 通用 === */
    QPushButton {
        border: 1px solid #d4c8b8;
        border-radius: 5px;
        padding: 6px 14px;
        background: #ffffff;
        color: #6a5040;
        font-size: 12px;
        min-height: 22px;
    }
    QPushButton:hover {
        background: #faf7f3;
        border-color: #c04040;
        color: #2a1810;
    }
    QPushButton:pressed {
        background: #f0ebe4;
        border-color: #d04040;
        color: #2a1810;
    }
    QPushButton:disabled {
        color: #9a8070;
        background: #f5efe8;
        border-color: #d4c8b8;
    }

    /* === 主操作按钮 — 博丽红 === */
    QPushButton#loginBtn {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #d42020, stop:1 #b01010);
        border: 1px solid #b01010;
        border-radius: 5px;
        color: #f0e8e0;
        font-weight: bold;
        font-size: 12px;
        padding: 6px 14px;
        min-height: 22px;
    }
    QPushButton#loginBtn:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #e83838, stop:1 #d42020);
        border-color: #d42020;
    }
    QPushButton#sendBtn {
        border: 1px solid #d42020;
        border-radius: 5px;
        padding: 6px 14px;
        background: #d42020;
        color: #f0e8e0;
        font-weight: bold;
        font-size: 12px;
        min-height: 22px;
    }
    QPushButton#sendBtn:hover {
        background: #e83838;
        border-color: #e83838;
    }
    /* === 登录按钮 — 快登模式（金色） === */
    QPushButton#loginBtn[mode="quick"] {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #b09030, stop:1 #8a7020);
        border-color: #8a7020;
        color: #ffffff;
        font-weight: bold;
    }
    QPushButton#loginBtn[mode="quick"]:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #c9a040, stop:1 #b09030);
    }

    /* === 退出按钮 === */
    QPushButton#logoutBtn {
        background: #ffffff;
        border: 1px solid #c03030;
        border-radius: 6px;
        color: #c03030;
        font-weight: bold;
        font-size: 12px;
        padding: 6px 14px;
    }
    QPushButton#logoutBtn:hover {
        background: #f4e0e0;
        border-color: #e04040;
        color: #e04040;
    }

    /* === 撤回按钮 === */
    QPushButton#recallBtn {
        background: #ffffff;
        border: 1px solid #8a7020;
        border-radius: 5px;
        color: #8a7020;
        font-size: 12px;
        padding: 6px 14px;
    }
    QPushButton#recallBtn:hover {
        background: #f4ecd0;
        border-color: #b09030;
        color: #b09030;
    }

    /* === 快捷登录按钮 === */
    QPushButton[cssClass="quickLogin"] {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #ffffff, stop:1 #faf7f3);
        border: 1px solid #d04040;
        border-radius: 8px;
        color: #8a7020;
        font-weight: bold;
        font-size: 13px;
        text-align: left;
        padding: 10px 14px;
    }
    QPushButton[cssClass="quickLogin"]:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #fff5f5, stop:1 #ffffff);
        border-color: #e62020;
        color: #b09030;
    }

    /* === 输入框 === */
    QTextEdit, QPlainTextEdit {
        border: 1px solid #d4c8b8;
        border-radius: 6px;
        background: #ffffff;
        color: #2a1810;
        padding: 8px;
        font-size: 13px;
        selection-background: #f0d0d0;
        selection-color: #2a1810;
    }
    QTextEdit:focus, QPlainTextEdit:focus {
        border-color: #c04040;
    }

    /* === 树形控件 === */
    QTreeWidget {
        border: 1px solid #d4c8b8;
        border-radius: 6px;
        background: #ffffff;
        alternate-background-color: #f0ebe4;
        outline: none;
        padding: 4px;
        color: #2a1810;
        font-size: 12px;
    }
    QTreeWidget::item {
        padding: 3px 6px;
        border-radius: 3px;
    }
    QTreeWidget::item:selected {
        background: #f0d0d0;
        color: #2a1810;
    }
    QTreeWidget::item:hover:!selected {
        background: #faf7f3;
    }
    QTreeWidget::item:focus {
        outline: none;
    }
    QTreeWidget::indicator {
        width: 15px;
        height: 15px;
    }
    QTreeWidget::indicator:unchecked {
        border: 2px solid #d4c8b8;
        border-radius: 3px;
        background: transparent;
    }
    QTreeWidget::indicator:checked {
        border: none;
        border-radius: 3px;
        background: #d42020;
    }
    QTreeWidget::indicator:indeterminate {
        border: none;
        border-radius: 3px;
        background: #f0c8c8;
    }
    QHeaderView::section {
        background: #ffffff;
        border: none;
        border-bottom: 2px solid #d4c8b8;
        padding: 6px 10px;
        font-weight: bold;
        color: #8a7020;
        font-size: 11px;
    }

    /* === 进度条 === */
    QProgressBar {
        border: 1px solid #d4c8b8;
        border-radius: 4px;
        background: #f0ebe4;
        height: 8px;
        text-align: center;
        font-size: 10px;
        color: #6a5040;
    }
    QProgressBar::chunk {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #d42020, stop:0.5 #c04040, stop:1 #8a2020);
        border-radius: 3px;
    }

    /* === 分割条 === */
    QSplitter::handle {
        background: #d4c8b8;
        width: 2px;
    }

    /* === 状态栏 === */
    QStatusBar {
        background: #ffffff;
        border-top: 1px solid #d4c8b8;
        color: #6a5040;
        padding: 2px 8px;
        font-size: 11px;
    }

    /* === 滚动条 === */
    QScrollBar:vertical {
        background: #e8ddd5;
        width: 9px;
        margin: 2px;
    }
    QScrollBar::handle:vertical {
        background: #c8b8a8;
        border-radius: 4px;
        min-height: 30px;
        margin: 2px;
    }
    QScrollBar::handle:vertical:hover {
        background: #a89888;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
    }
    QScrollBar:horizontal {
        background: #e8ddd5;
        height: 9px;
        margin: 2px;
    }
    QScrollBar::handle:horizontal {
        background: #c8b8a8;
        border-radius: 4px;
        min-width: 30px;
        margin: 2px;
    }
    QScrollBar::handle:horizontal:hover {
        background: #a89888;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0;
    }

    /* === 标签 === */
    QLabel {
        background: transparent;
        color: #6a5040;
        border: none;
    }

    /* === 菜单栏 === */
    QMenuBar {
        background: #ffffff;
        border-bottom: 1px solid #d4c8b8;
        padding: 2px;
        color: #6a5040;
        font-size: 12px;
    }
    QMenuBar::item {
        padding: 4px 12px;
        border-radius: 4px;
    }
    QMenuBar::item:selected {
        background: #f0ebe4;
        color: #8a7020;
    }
    QMenu {
        background: #ffffff;
        border: 1px solid #d4c8b8;
        border-radius: 6px;
        padding: 4px;
    }
    QMenu::item {
        padding: 6px 28px 6px 16px;
        border-radius: 4px;
        color: #2a1810;
    }
    QMenu::item:selected {
        background: #f0d0d0;
    }
    QMenu::separator {
        height: 1px;
        background: #d4c8b8;
        margin: 4px 8px;
    }

    /* === 提示框 === */
    QToolTip {
        background: #ffffff;
        border: 1px solid #d4c8b8;
        border-radius: 4px;
        padding: 4px 8px;
        color: #2a1810;
        font-size: 11px;
    }
    """.strip()
    # ── 博丽神社巫女 深色主题 ──────────────────────────────────────
    _THEME = """
    /* === 全局 === */
    QMainWindow {
        background: #120808;
        background-image: url({{asanoha_dark}});
    }
    QWidget#main_central {
        background: transparent;
    }
    QSplitter, QSplitter::handle {
        background: transparent;
    }
    QWidget {
        background-color: #1a0e0c;
        color: #f0e8e0;
        font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif;
        font-size: 13px;
    }

    /* === 分组框 === */
    QGroupBox {
        background-color: #241614;
        background-image: url({{asanoha_dark}});
        border: 1px solid #4a3030;
        border-radius: 8px;
        margin-top: 16px;
        padding: 18px 12px 12px 12px;
        font-weight: bold;
        font-size: 13px;
        color: #c9a040;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 14px;
        padding: 0 8px;
        color: #c9a040;
        background: #241614;
        border-radius: 3px;
    }

    /* === 消息编辑区补充样式 === */
    QLabel#me_char_count {
        font-size: 10px;
        color: #7a6a5a;
        background: transparent;
        padding: 0;
    }

    /* === 输入框 === */
    QLineEdit {
        border: 1px solid #4a3030;
        border-radius: 6px;
        padding: 4px 8px;
        background: #1a0e0c;
        color: #f0e8e0;
        font-size: 13px;
    }
    QLineEdit:focus {
        border-color: #c04040;
    }

    /* === 按钮 — 通用 === */
    QPushButton {
        border: 1px solid #4a3030;
        border-radius: 5px;
        padding: 6px 14px;
        background: #241614;
        color: #b8a898;
        font-size: 12px;
        min-height: 22px;
    }
    QPushButton:hover {
        background: #2d1c1a;
        border-color: #8b4040;
        color: #f0e8e0;
    }
    QPushButton:pressed {
        background: #1a0e0c;
        border-color: #c04040;
        color: #f0e8e0;
    }
    QPushButton:disabled {
        color: #7a6a5a;
        background: #1a1010;
        border-color: #302020;
    }

    /* === 主操作按钮 — 博丽红 === */
    QPushButton#loginBtn {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #e62020, stop:1 #c01010);
        border: 1px solid #c01010;
        border-radius: 5px;
        color: #f0e8e0;
        font-weight: bold;
        font-size: 12px;
        padding: 6px 14px;
        min-height: 22px;
    }
    QPushButton#loginBtn:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #ff3838, stop:1 #e62020);
        border-color: #e62020;
    }
    QPushButton#loginBtn:pressed {
        background: #b01010;
        border-color: #8b1a1a;
    }
    QPushButton#sendBtn {
        border: 1px solid #e62020;
        border-radius: 5px;
        padding: 6px 14px;
        background: #e62020;
        color: #f0e8e0;
        font-weight: bold;
        font-size: 12px;
        min-height: 22px;
    }
    QPushButton#sendBtn:hover {
        background: #ff3838;
        border-color: #ff3838;
    }
    /* === 登录按钮 — 快登模式（金色） === */
    QPushButton#loginBtn[mode="quick"] {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #c9a040, stop:1 #9a7020);
        border-color: #9a7020;
        color: #1a0e0c;
        font-weight: bold;
    }
    QPushButton#loginBtn[mode="quick"]:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #e0c060, stop:1 #c9a040);
    }

    /* === 退出按钮 — 暖红描边 === */
    QPushButton#logoutBtn {
        background: #241614;
        border: 1px solid #d04040;
        border-radius: 6px;
        color: #d04040;
        font-weight: bold;
        font-size: 12px;
        padding: 6px 14px;
    }
    QPushButton#logoutBtn:hover {
        background: #2d1c1a;
        border-color: #ff6060;
        color: #ff6060;
    }

    /* === 撤回按钮 — 金棕描边 === */
    QPushButton#recallBtn {
        background: #241614;
        border: 1px solid #8a7020;
        border-radius: 5px;
        color: #c9a040;
        font-size: 12px;
        padding: 6px 14px;
    }
    QPushButton#recallBtn:hover {
        background: #2d1c1a;
        border-color: #c9a040;
        color: #e0c060;
    }

    /* === 快捷登录按钮 === */
    QPushButton[cssClass="quickLogin"] {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #2d1c1a, stop:1 #241614);
        border: 1px solid #8b4040;
        border-radius: 8px;
        color: #c9a040;
        font-weight: bold;
        font-size: 13px;
        text-align: left;
        padding: 10px 14px;
    }
    QPushButton[cssClass="quickLogin"]:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #3d2c2a, stop:1 #2d1c1a);
        border-color: #c04040;
        color: #e0c060;
    }

    /* === 输入框 === */
    QTextEdit, QPlainTextEdit {
        border: 1px solid #4a3030;
        border-radius: 6px;
        background: #1a0e0c;
        color: #f0e8e0;
        padding: 8px;
        font-size: 13px;
        selection-background: #3a1018;
        selection-color: #f0e8e0;
    }
    QTextEdit:focus, QPlainTextEdit:focus {
        border-color: #c04040;
    }

    /* === 树形控件 === */
    QTreeWidget {
        border: 1px solid #4a3030;
        border-radius: 6px;
        background: #1a0e0c;
        alternate-background-color: #201210;
        outline: none;
        padding: 4px;
        color: #f0e8e0;
        font-size: 12px;
    }
    QTreeWidget::item {
        padding: 3px 6px;
        border-radius: 3px;
    }
    QTreeWidget::item:selected {
        background: #3a1018;
        color: #f0e8e0;
    }
    QTreeWidget::item:hover:!selected {
        background: #2d1c1a;
    }
    QTreeWidget::item:focus {
        outline: none;
    }
    QTreeWidget::indicator {
        width: 15px;
        height: 15px;
    }
    QTreeWidget::indicator:unchecked {
        border: 2px solid #4a3030;
        border-radius: 3px;
        background: transparent;
    }
    QTreeWidget::indicator:checked {
        border: none;
        border-radius: 3px;
        background: #e62020;
    }
    QTreeWidget::indicator:indeterminate {
        border: none;
        border-radius: 3px;
        background: #8b1a1a;
    }
    QHeaderView::section {
        background: #241614;
        border: none;
        border-bottom: 2px solid #4a3030;
        padding: 6px 10px;
        font-weight: bold;
        color: #c9a040;
        font-size: 11px;
    }

    /* === 进度条 === */
    QProgressBar {
        border: 1px solid #4a3030;
        border-radius: 4px;
        background: #1a0e0c;
        height: 8px;
        text-align: center;
        font-size: 10px;
        color: #b8a898;
    }
    QProgressBar::chunk {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #e62020, stop:0.5 #c04040, stop:1 #8b1a1a);
        border-radius: 3px;
    }

    /* === 分割条 === */
    QSplitter::handle {
        background: #4a3030;
        width: 2px;
    }

    /* === 状态栏 === */
    QStatusBar {
        background: #241614;
        border-top: 1px solid #4a3030;
        color: #b8a898;
        padding: 2px 8px;
        font-size: 11px;
    }

    /* === 滚动条 === */
    QScrollBar:vertical {
        background: #1a1010;
        width: 9px;
        margin: 2px;
    }
    QScrollBar::handle:vertical {
        background: #4a3030;
        border-radius: 4px;
        min-height: 30px;
        margin: 2px;
    }
    QScrollBar::handle:vertical:hover {
        background: #6a4040;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
    }
    QScrollBar:horizontal {
        background: #1a1010;
        height: 9px;
        margin: 2px;
    }
    QScrollBar::handle:horizontal {
        background: #4a3030;
        border-radius: 4px;
        min-width: 30px;
        margin: 2px;
    }
    QScrollBar::handle:horizontal:hover {
        background: #6a4040;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0;
    }

    /* === 标签 === */
    QLabel {
        background: transparent;
        color: #b8a898;
        border: none;
    }

    /* === 菜单栏 === */
    QMenuBar {
        background: #1a0e0c;
        border-bottom: 1px solid #4a3030;
        padding: 2px;
        color: #b8a898;
        font-size: 12px;
    }
    QMenuBar::item {
        padding: 4px 12px;
        border-radius: 4px;
    }
    QMenuBar::item:selected {
        background: #2d1c1a;
        color: #c9a040;
    }
    QMenu {
        background: #241614;
        border: 1px solid #4a3030;
        border-radius: 6px;
        padding: 4px;
    }
    QMenu::item {
        padding: 6px 28px 6px 16px;
        border-radius: 4px;
        color: #f0e8e0;
    }
    QMenu::item:selected {
        background: #3a1018;
    }
    QMenu::separator {
        height: 1px;
        background: #4a3030;
        margin: 4px 8px;
    }

    /* === 提示框 === */
    QToolTip {
        background: #2d1c1a;
        border: 1px solid #8b4040;
        border-radius: 4px;
        padding: 4px 8px;
        color: #f0e8e0;
        font-size: 11px;
    }
    """.strip()

    def __init__(self):
        super().__init__()
        self._state = AppState.instance()
        self._config_mgr = ConfigManager()
        self._napcat: NapCatManager | None = None
        self._onebot: OneBotHTTPClient | None = None
        self._csv_groups: set[str] = set()       # CSV中的群号集合
        self._csv_records: list = []              # CSV解析缓存的GroupRecord列表
        self._joined_groups: set[str] = set()     # bot实际加入的群号
        self._intersection: set[str] = set()      # 交集
        self._send_worker: SendWorker | None = None
        self._recall_worker: RecallWorker | None = None
        self._last_sent_ids: dict[str, str] = {}  # 上次发送的 message_id 映射
        self._nt_timeout_groups: list[str] = []   # NT超时的群名，消息已发出但无可撤回的message_id
        self._post_listener: PostSendListener | None = None
        self._listener_panel: ListenerPanel | None = None
        self._image_paths: list[str] = []  # ordered list of image file paths
        self._b64_to_path: dict[str, str] = {}  # base64 data -> file path mapping
        self._dark_mode = self._config_mgr.config.dark_mode
        self._recalling = False                     # 撤回流程中，抑制 send_interrupted 的 UI 操作
        # OneBot 模式: "managed" = App管理NapCat进程 / "external" = 用户自启动
        self._onebot_mode = getattr(self._config_mgr.config, "onebot_mode", "managed")
        self._onebot_url = getattr(self._config_mgr.config, "onebot_http_url", "http://127.0.0.1:5700")
        self._external_poll_timer: QTimer | None = None
        self._quick_login_accounts: list = []     # 缓存的快登账号
        self._quick_login_attempting = False    # 是否正在尝试快速登录
        self._quick_login_mode = False          # 当前启动是否为快登模式（区分扫码/快登的QQ窗口提示）

        self._log_entries: list[tuple[str, str, str]] = []  # [(msg, level, timestamp), ...]

        self.setWindowTitle("东方Project一键宣发姬")
        icon_path = self._resolve_asset("app_icon.png")
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(1080, 800)
        self.setStyleSheet(self._resolve_theme(self._THEME if self._dark_mode else self._THEME_LIGHT))

        self._build_menu()
        self._build_ui()
        self._build_statusbar()
        self._connect_state_signals()
        self._connect_ui_signals()

        self._append_log("[系统] 东方Project一键宣发姬 已就绪")
        if self._onebot_mode == "external":
            self._append_log(f"[系统] 外部OneBot模式，目标: {self._onebot_url}")
            QTimer.singleShot(500, self._start_external_poll)

        # 自动加载上次打开的CSV
        csv_path = self._config_mgr.config.csv_path
        if csv_path and os.path.isfile(csv_path):
            try:
                from touhou_promoter.core.csv_loader import load_groups
                records = load_groups(csv_path)
                self._csv_records = records
                self._csv_groups = {r.group_id for r in records}
                self._append_log(f"[CSV] 自动加载: {len(records)} 条记录, {len(self._csv_groups)} 个唯一群号")
            except Exception as e:
                self._append_log(f"[CSV] 自动加载失败: {e}")

        # 旧配置迁移：有 last_self_id 但 cached_accounts 为空 → 自动填充
        cached = self._config_mgr.config.cached_accounts
        if (not cached or not any(q for q, _ in cached)) and self._config_mgr.config.last_self_id:
            cached = [[self._config_mgr.config.last_self_id, self._config_mgr.config.last_self_nick]]
            self._config_mgr.config.cached_accounts = cached
            self._config_mgr.save()

    # ================================================================
    # 窗口关闭 → 清理
    # ================================================================
    def closeEvent(self, event):
        """窗口关闭时停止所有后台任务"""
        # 快速停止发送/撤回线程
        if self._send_worker and self._send_worker.isRunning():
            self._send_worker.stop()
            self._send_worker.quit()
            self._send_worker.wait(500)
        if self._recall_worker and self._recall_worker.isRunning():
            self._recall_worker.stop()
            self._recall_worker.quit()
            self._recall_worker.wait(500)

        # 停止监听线程
        self._stop_post_listener()

        # NapCat 清理 — 必须在主线程同步执行，daemon 线程退出时会被强杀
        if self._napcat and self._onebot_mode == "managed":
            self._napcat = None
            for exe in ("QQ.exe", "NapCatWinBootMain.exe"):
                try:
                    subprocess.run(
                        f'taskkill /F /IM {exe}',
                        shell=True, capture_output=True, timeout=3,
                    )
                except Exception:
                    pass

        super().closeEvent(event)

    # ================================================================
    # 菜单栏
    # ================================================================
    def _build_menu(self):
        mb = self.menuBar()

        file_menu = mb.addMenu("文件(&F)")
        file_menu.addAction("加载CSV...", self._on_load_csv)
        file_menu.addAction("退出(&Q)", self.close)

        settings_menu = mb.addMenu("设置(&S)")
        settings_menu.addAction("NapCat路径...", self._on_napcat_path)
        settings_menu.addAction("发送参数...", self._on_send_params)
        settings_menu.addSeparator()
        theme_label = "切换亮色主题" if self._dark_mode else "切换深色主题"
        self._theme_action = settings_menu.addAction(theme_label, self._on_toggle_theme)

        help_menu = mb.addMenu("帮助(&H)")
        help_menu.addAction("关于...", self._on_about)

    # ================================================================
    # 主布局
    # ================================================================
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("main_central")
        self.setCentralWidget(central)

        splitter = QSplitter(Qt.Orientation.Horizontal, central)

        # === 左侧面板 ===
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(8)

        # -- 登录区 --
        login_group = QGroupBox("QQ登录")
        login_layout = QVBoxLayout(login_group)
        login_layout.setSpacing(8)

        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setMinimumSize(160, 160)
        if self._onebot_mode == "external":
            self.qr_label.setText("外部 OneBot 模式\n请在 QQ 中自行启动\nOneBot 服务端")
        else:
            self.qr_label.setText("请点击下方按钮\n启动NapCat并登录")
        self.qr_label.setStyleSheet(
            "border: 2px dashed #6a4040; border-radius: 10px;"
            "font-size: 14px; color: #7a6a5a; background: transparent;"
        )

        self.login_status_label = QLabel("状态: 未登录")
        self.login_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.login_status_label.setStyleSheet("font-size: 11px; color: #7a6a5a; background: transparent;")

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.login_btn = QPushButton(
            "连接外部 OneBot" if self._onebot_mode == "external" else "启动并登录"
        )
        self.login_btn.setObjectName("loginBtn")
        f = self.login_btn.font(); f.setPointSize(10); self.login_btn.setFont(f)
        self.logout_btn = QPushButton("退出登录")
        self.logout_btn.setObjectName("logoutBtn")
        self.logout_btn.hide()
        f = self.logout_btn.font(); f.setPointSize(10); self.logout_btn.setFont(f)
        btn_row.addWidget(self.login_btn)
        btn_row.addWidget(self.logout_btn)

        login_layout.addWidget(self.qr_label)
        login_layout.addWidget(self.login_status_label)
        login_layout.addLayout(btn_row)
        left_layout.addWidget(login_group)

        # -- 群列表区 --
        group_group = QGroupBox("群列表")
        group_layout = QVBoxLayout(group_group)
        group_layout.setSpacing(6)

        self.group_search = QLineEdit()
        self.group_search.setPlaceholderText("搜索群名称或群号...")
        self.group_search.setClearButtonEnabled(True)
        self.group_search.setStyleSheet("padding: 4px 8px; font-size: 12px;")
        group_layout.addWidget(self.group_search)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.select_all_btn = QPushButton("全选")
        self.deselect_all_btn = QPushButton("取消全选")
        self.refresh_groups_btn = QPushButton("刷新交集")
        for b in (self.select_all_btn, self.deselect_all_btn, self.refresh_groups_btn):
            f = b.font(); f.setPointSize(10); b.setFont(f)
        toolbar.addWidget(self.select_all_btn)
        toolbar.addWidget(self.deselect_all_btn)
        toolbar.addWidget(self.refresh_groups_btn)
        self.group_tree = QTreeWidget()
        self.group_tree.setHeaderLabels(["分类 / 群名称"])
        self.group_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.group_tree.header().setStretchLastSection(True)
        self.group_tree.header().setSectionsClickable(False)
        self.group_tree.setAlternatingRowColors(True)
        self.group_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.group_selection_label = QLabel("已选: 0 / 0 群（登录后可刷新交集）")
        self.group_selection_label.setStyleSheet("font-size: 11px; color: #7a6a5a; background: transparent;")
        group_layout.addLayout(toolbar)
        group_layout.addWidget(self.group_tree)
        group_layout.addWidget(self.group_selection_label)
        left_layout.addWidget(group_group, 1)

        splitter.addWidget(left)

        # === 中间：消息编辑器（独立一栏，纵向排版，手机QQ风格）===
        msg_editor = QGroupBox("消息编辑")
        msg_editor.setObjectName("me_group")
        me_layout = QVBoxLayout(msg_editor)
        me_layout.setContentsMargins(10, 20, 10, 10)
        me_layout.setSpacing(6)

        # 字数计数（紧凑放在标题下方）
        self.char_count_label = QLabel("字数: 0")
        self.char_count_label.setObjectName("me_char_count")
        me_layout.addWidget(self.char_count_label)

        # 富文本消息编辑区（文本+图片混排，所见即所得）
        self.message_edit = QTextEdit()
        self.message_edit.setAcceptRichText(True)
        self.message_edit.setPlaceholderText("在此输入消息...\n拖拽图片到编辑区即可插入")
        self.message_edit.textChanged.connect(self._on_message_changed)
        # 拖拽图片支持
        self.message_edit.setAcceptDrops(True)
        self.message_edit.dragEnterEvent = self._on_editor_drag_enter
        self.message_edit.dropEvent = self._on_editor_drop
        me_layout.addWidget(self.message_edit, 1)

        # 按钮栏
        me_btn_row = QHBoxLayout()
        me_btn_row.setSpacing(6)
        self.insert_image_btn = QPushButton("图片")
        self.insert_image_btn.setToolTip("选择图片文件插入到光标位置")
        self.insert_image_btn.clicked.connect(self._on_insert_image)
        me_btn_row.addWidget(self.insert_image_btn)
        me_btn_row.addStretch()
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("sendBtn")
        self.send_btn.clicked.connect(self._on_send_clicked)
        self.recall_btn = QPushButton("撤回")
        self.recall_btn.setObjectName("recallBtn")
        self.recall_btn.clicked.connect(self._on_recall_clicked)
        me_btn_row.addWidget(self.send_btn)
        me_btn_row.addWidget(self.recall_btn)

        # 编辑区右下角叠加标签（浮在文本上方）
        self._editor_overlay = QFrame(self.message_edit.viewport())
        self._editor_overlay.setObjectName("editorOverlay")
        full_info = (
            f"发送间隔 {self._config_mgr.config.send_interval}s，"
            f"每{self._config_mgr.config.batch_pause_every}条暂停"
            f"{self._config_mgr.config.batch_pause_seconds}s"
        )
        short_info = (
            f"间隔{self._config_mgr.config.send_interval}s/"
            f"每{self._config_mgr.config.batch_pause_every}停{self._config_mgr.config.batch_pause_seconds}s"
        )
        self.interval_label = QLabel(short_info)
        self.interval_label.setToolTip(full_info)
        self.interval_label.setStyleSheet("font-size: 10px; color: #7a6a5a; background: transparent;")
        self.target_label = QLabel("目标群: 0")
        self.target_label.setStyleSheet("font-weight: bold; font-size: 11px; color: #c9a040; background: transparent;")
        ol = QHBoxLayout(self._editor_overlay)
        ol.setContentsMargins(8, 2, 8, 3)
        ol.setSpacing(10)
        ol.addStretch()
        ol.addWidget(self.interval_label)
        ol.addWidget(self.target_label)
        self._position_editor_overlay()

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)

        me_layout.addLayout(me_btn_row)
        me_layout.addWidget(self.progress_bar)

        splitter.addWidget(msg_editor)

        # === 右侧：监听面板 + 日志（竖向分割）===
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 4, 4, 4)
        right_layout.setSpacing(4)

        # ── 监听面板 ──
        self._listener_panel = ListenerPanel(dark_mode=self._dark_mode,
                                             self_nick=self._config_mgr.config.last_self_nick,
                                             self_id=self._config_mgr.config.last_self_id)
        self._listener_panel.reply_requested.connect(self._on_listener_reply)
        right_layout.addWidget(self._listener_panel, 1)

        # ── 日志区 ──
        log_group = QGroupBox("发送日志")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(4, 4, 4, 4)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._log_max_lines = 500
        log_layout.addWidget(self.log_view)
        right_layout.addWidget(log_group, 1)

        splitter.addWidget(right)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setCollapsible(2, False)

        left.setMinimumWidth(300)
        msg_editor.setMinimumWidth(340)
        right.setMinimumWidth(350)

        self._main_splitter = splitter
        main_layout = QHBoxLayout(central)
        main_layout.addWidget(splitter)

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, '_main_splitter') and not getattr(self, '_splitter_seeded', False):
            self._splitter_seeded = True
            total = self._main_splitter.width()
            lw = int(total * 0.30)
            mw = int(total * 0.32)
            rw = total - lw - mw
            self._main_splitter.setSizes([lw, mw, rw])
            self._refresh_overlay_theme()

    def _build_statusbar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_online = QLabel("⚪ 离线")
        self.status_qq = QLabel("QQ: -")
        self.status_last_send = QLabel("上次发送: -")
        self.status_bar.addWidget(self.status_online)
        self.status_bar.addWidget(self.status_qq)
        self.status_bar.addPermanentWidget(self.status_last_send)

    # ================================================================
    # AppState 信号 → UI 更新
    # ================================================================
    def _connect_state_signals(self):
        st = self._state
        st.qr_code_ready.connect(self._on_qr_image_ready)
        st.login_status_changed.connect(self._on_login_status_changed)
        st.napcat_status.connect(self._on_napcat_status)
        st.napcat_log_line.connect(self._on_napcat_log_line)
        st.group_intersection_ready.connect(self._on_intersection_ready)
        st.quick_login_accounts.connect(self._on_quick_login_accounts)
        st.login_busy_detected.connect(self._on_login_busy_detected)
        st.onebot_ready.connect(self._on_onebot_ready)
        st.send_started.connect(self._on_send_started)
        st.send_progress.connect(self._on_send_progress)
        st.send_completed.connect(self._on_send_completed)
        st.send_interrupted.connect(self._on_send_interrupted)

    def _on_onebot_ready(self, http_port: int, ws_port: int):
        """OneBot 适配器已就绪 — 立即触发一次登录检测（不等轮询周期）"""
        if getattr(self, "_login_poll_active", False):
            QTimer.singleShot(500, self._start_login_poll)

    def _on_qr_image_ready(self, path: str):
        """NapCat 生成了 QR 码图片"""
        # 不在此处清除 _quick_login_attempting：
        # QR 可能在快登模式的 NapCat 中短暂出现（autoLoginAccount 失败前会
        # 先生成 QR），如果这里清除标记，紧接着 login_busy 到达时
        # _on_login_busy_detected 会误以为不在快登流程中而忽略错误。
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                220, 220,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.qr_label.setPixmap(scaled)
            self.qr_label.setStyleSheet(
                "background: #fff; border: 2px solid #c9a040; border-radius: 10px;"
            )
            self.login_status_label.setText("状态: 请用手机QQ扫描上方二维码")
            self._append_log("[登录] QR码已显示，请扫码")
        else:
            self._append_log("[登录] QR码图片加载失败")

    # 需要过滤掉的 NapCat stdout 行（ASCII QR码 / 调试 / 群消息事件）
    _NAPCAT_LOG_SUPPRESS = [
        r"[▀-▟]{3,}",               # ASCII 艺术块字符
        r"\[debug\]",                # debug 日志
        r"二维码解码URL",             # QR URL
        r"如果控制台二维码",           # QR 扫码提示
        r"请扫描下面的二维码",         # QR 扫码提示
        r"\[message\]",              # 消息事件
        r"(收到|接收).*消息",         # 收到/接收消息
        r"receive.*message",         # 收到消息（英文）
        r"上报",                     # OneBot 事件上报
        r"接收\s*<-",               # NapCat 接收消息格式
        r"群.*消息|好友.*消息",       # 群消息/好友消息
        r"\[OneBot11\].*消息",       # OneBot11 消息处理
        r"\[PacketHandler\]",        # 底层 packet 日志
        r"\[Napi2NativeLoader\]",    # Native loader 日志
        r"\[FFmpeg\]",               # FFmpeg 日志
        r"\[Core\]\s*\[Config\]",    # 配置加载
        r"\[ServerTime\]",           # 时间同步
        r"WebUi\s*(Token|User\s*Panel)",  # WebUi 令牌和 URL
        r"\[::\].*webui",            # IPv6 WebUi
        r"数据库辅助支持",             # 数据库支持
        r"本账号数据/缓存目录",        # 缓存目录
        r"create_window|show_window",# 窗口创建/显示
        r"user event",               # 用户事件
        r"\[HTTP\]",                 # HTTP 请求日志
        r"\[WS\]",                   # WebSocket 日志
        r"POST\s+/",                 # HTTP POST 请求路径
        r"API.*调用|call.*api",      # API 调用
        r"私聊",                     # 私聊消息日志
        r"输入状态",                 # 对方正在输入状态通知
        r"\[Notice\]",               # 系统通知
        r"发送\s*->",               # Bot 自身发送消息日志
        r"里面贴的|链接.*失效|视频.*没了|贴子.*删除|主题.*已删",  # 贴吧/链接预览内容
        r"发生错误.*NTEvent",        # NapCat NT超时（消息已发出，仅确认丢失）
    ]

    def _on_napcat_log_line(self, line: str):
        """过滤 ANSI 转义码和无用信息后输出到日志"""
        import re
        clean = re.sub(r"\x1b\[[0-9;]*m", "", line)
        if not clean.strip():
            return
        for pattern in self._NAPCAT_LOG_SUPPRESS:
            if re.search(pattern, clean, re.IGNORECASE):
                return
        # 过滤不匹配标准日志格式的行（链接预览内容等）
        if not re.search(r"^\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+\[", clean):
            return
        self._append_log(f"[NapCat] {clean}")

    def _on_napcat_status(self, status: str):
        self._append_log(f"[NapCat] {status}")
        if "QQ已启动" in status:
            if self._quick_login_mode:
                self.qr_label.setText("快速登录中\n无需扫码")
                self.qr_label.setStyleSheet(
                    "border: 2px solid #c9a040; border-radius: 10px;"
                    "font-size: 16px; font-weight: bold; color: #c9a040; background: transparent;"
                )
            else:
                self.qr_label.setText("请在弹出的\nQQ窗口中\n扫码登录")
                self.qr_label.setStyleSheet(
                    "border: 2px solid #c9a040; border-radius: 10px;"
                    "font-size: 16px; font-weight: bold; color: #f0e8e0; background: transparent;"
                )
        elif "OneBot 已就绪" in status:
            self.qr_label.setText("OneBot\n已就绪")
            self.qr_label.setStyleSheet(
                "border: 2px solid #5a9a5a; border-radius: 10px;"
                "font-size: 18px; font-weight: bold; color: #5a9a5a; background: transparent;"
            )
        elif "正在启动" in status:
            self.qr_label.setText("正在启动\nNapCat...")
            self.qr_label.setStyleSheet(
                "border: 2px solid #c09040; border-radius: 10px;"
                "font-size: 14px; color: #c09040; background: transparent;"
            )
        elif "已退出" in status:
            self.qr_label.setText("NapCat\n已退出")
            self.qr_label.setStyleSheet(
                "border: 2px dashed #6a4040; border-radius: 10px;"
                "font-size: 14px; color: #7a6a5a; background: transparent;"
            )
            if not self._napcat or not self._napcat.is_running():
                self._set_login_btn_mode("scan")

    def _set_login_btn_mode(self, mode: str):
        """切换登录区域按钮: scan(绿色启动) / quick(蓝色快登) / external / online(红色退出)"""
        if mode == "online":
            self.login_btn.hide()
            self.logout_btn.show()
            self.logout_btn.setEnabled(True)
        elif mode == "quick":
            self.login_btn.setText("快速登录")
            self.login_btn.setProperty("mode", "quick")
            self.login_btn.setEnabled(True)
            self.login_btn.style().unpolish(self.login_btn)
            self.login_btn.style().polish(self.login_btn)
            self.login_btn.show()
            self.logout_btn.hide()
        else:  # scan / external
            self.login_btn.setText(
                "连接外部 OneBot" if self._onebot_mode == "external" else "启动并登录"
            )
            self.login_btn.setProperty("mode", "scan")
            self.login_btn.setEnabled(True)
            self.login_btn.style().unpolish(self.login_btn)
            self.login_btn.style().polish(self.login_btn)
            self.login_btn.show()
            self.logout_btn.hide()

    def _on_login_status_changed(self, online: bool, info: str):
        """登录状态变化"""
        if online:
            self._quick_login_mode = False
            self.login_status_label.setText("状态: 在线")
            self.status_online.setText("在线")
            self.status_qq.setText(f"QQ: {info}")
            self._set_login_btn_mode("online")
            self._append_log(f"[登录] 登录成功! {info}")
            self._auto_refresh_intersection()
            self._check_breakpoint_resume()
        else:
            self.login_status_label.setText(f"状态: {info}")
            self.status_online.setText("离线")
            self.status_qq.setText("QQ: -")
            # 保持当前按钮状态不变（可能是快登中/扫码中）

    def _on_intersection_ready(self, joined_ids: set):
        """收到 bot 实际加入的群号集合"""
        self._joined_groups = joined_ids
        self._intersection = self._csv_groups & joined_ids
        self._append_log(
            f"[群列表] CSV共{len(self._csv_groups)}个群, "
            f"bot已加入{len(joined_ids)}个群, "
            f"交集{len(self._intersection)}个群"
        )
        self.group_selection_label.setText(
            f"已选: 0 / {len(self._intersection)} 群（登录后可刷新交集）"
        )
        self._refresh_group_tree()

    # ================================================================
    # UI 控件事件
    # ================================================================
    def _connect_ui_signals(self):
        self.login_btn.clicked.connect(self._on_login_clicked)
        self.logout_btn.clicked.connect(self._on_logout_clicked)
        self.refresh_groups_btn.clicked.connect(self._auto_refresh_intersection)
        self.select_all_btn.clicked.connect(self._on_select_all)
        self.deselect_all_btn.clicked.connect(self._on_deselect_all)
        self.group_tree.itemChanged.connect(self._on_tree_item_changed)
        self.group_tree.itemPressed.connect(self._on_tree_item_pressed)
        self.group_tree.itemClicked.connect(self._on_tree_item_clicked)
        self.group_tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self.group_search.textChanged.connect(self._on_group_search)

    # ---- 登录 ----
    def _on_login_clicked(self):
        """登录按钮：
        - 外部模式 → 直接轮询配置的 OneBot 地址
        - 管理模式 → NapCat 子进程 + 弹窗选号/扫码
        """
        if self._onebot is not None:
            self._append_log("[登录] 已在线，无需重新登录", "info")
            return

        # 外部模式：直接开始轮询
        if self._onebot_mode == "external":
            self._start_external_poll()
            return

        cached = self._config_mgr.config.cached_accounts
        cached = [(q, n) for q, n in cached if q]

        # NapCat 已运行（扫码模式）→ 弹窗快登（不显示"扫码登录"选项）
        if self._napcat and self._napcat.is_running():
            if cached:
                dlg = QuickLoginDialog(cached, self, show_scan_option=False)
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    qq = dlg.selected_qq()
                    if qq:
                        self._do_quick_login_restart(qq)
            else:
                self._append_log("[登录] 暂无缓存账号，请扫码登录", "info")
            return

        # NapCat 未运行 → 弹窗选号或扫码
        if cached:
            dlg = QuickLoginDialog(cached, self, show_scan_option=True)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            if dlg.is_scan_mode():
                # 用户选了"扫码登录"
                self._pending_qq = ""
                self._quick_login_attempting = False
                self._quick_login_mode = False
            else:
                qq = dlg.selected_qq()
                if not qq:
                    return
                self._pending_qq = qq
                self._quick_login_attempting = True
                self._quick_login_mode = True
        else:
            self._pending_qq = ""
            self._quick_login_attempting = False
            self._quick_login_mode = False

        self.login_btn.setEnabled(False)
        self.login_status_label.setText("状态: 正在准备 NapCat...")
        self._append_log("[登录] 正在搜索/下载 NapCat（首次需下载约30MB）...")

        self._setup_worker = NapCatSetupWorker(self._config_mgr.state_dir())
        self._setup_worker.status.connect(self._on_setup_status)
        self._setup_worker.progress.connect(self._on_setup_progress)
        self._setup_worker.finished.connect(self._on_setup_finished)
        self._setup_worker.failed.connect(self._on_setup_failed)
        self._setup_worker.start()

    def _on_setup_status(self, msg: str):
        self.login_status_label.setText(f"状态: {msg}")
        self._append_log(f"[NapCat] {msg}")

    def _on_setup_progress(self, filename: str, done: int, total: int):
        if total > 0:
            pct = min(100, done * 100 // total)
            self.login_status_label.setText(f"状态: 下载 {filename} {pct}%")

    def _on_setup_finished(self, napcat_root: str):
        """NapCat 准备就绪，按模式启动"""
        self._config_mgr.config.napcat_path = napcat_root
        self._config_mgr.save()
        self._append_log(f"[登录] NapCat 路径: {napcat_root}")

        qq = getattr(self, "_pending_qq", "")
        self._napcat = NapCatManager(napcat_root)
        saved_qq = self._config_mgr.config.qq_exe_path
        if self._napcat.start(qq=qq, saved_qq_path=saved_qq):
            self._set_login_btn_mode("quick")
            if qq:
                self.login_status_label.setText(f"状态: 正在快速登录 {qq}...")
            else:
                self.login_status_label.setText("状态: NapCat 已启动，等待扫码...")
            self._login_retry_count = 0
            self._login_retry_max = 30
            self._login_poll_active = True
            self._start_login_poll()
        else:
            self.login_status_label.setText("状态: 启动失败")
            self.login_btn.setEnabled(True)
            self._append_log("[错误] NapCat 启动失败")

    def _start_login_poll(self, delay_ms: int = 0):
        """启动登录轮询 — 自适应间隔：前10次1s，之后2s"""
        if not getattr(self, "_login_poll_active", True):
            return
        if not self._napcat or not self._napcat.is_running():
            return

        class LoginCheckWorker(QThread):
            login_result = pyqtSignal(bool, str, str)

            def run(self_):
                try:
                    client = self._make_onebot_client()
                    info = client.get_login_info()
                    uid = str(info.get("user_id", ""))
                    nickname = info.get("nickname", "")
                    self_.login_result.emit(True, uid, nickname)
                except Exception as e:
                    self_.login_result.emit(False, "", str(e))

        self._login_checker = LoginCheckWorker()
        self._login_checker.login_result.connect(self._on_login_poll_result)
        if delay_ms > 0:
            QTimer.singleShot(delay_ms, self._login_checker.start)
        else:
            self._login_checker.start()

    def _on_login_poll_result(self, ok: bool, uid: str, nickname: str):
        if not getattr(self, "_login_poll_active", True):
            return
        if ok:
            self._login_poll_active = False
            self._quick_login_attempting = False
            self._clear_quick_login_buttons()
            self._onebot = self._make_onebot_client()
            self._config_mgr.config.last_self_id = uid
            self._config_mgr.config.last_self_nick = nickname
            self._config_mgr.save()
            self._listener_panel.set_bot_info(uid, nickname)
            self._merge_cached_accounts([(uid, nickname)])
            label = f"{nickname} ({uid})" if nickname else uid
            self._state.login_status_changed.emit(True, label)
            return

        self._login_retry_count += 1
        if self._login_retry_count < self._login_retry_max:
            if self._login_retry_count <= 5 or self._login_retry_count % 10 == 0:
                self._append_log(f"[登录] 等待中... ({self._login_retry_count}/{self._login_retry_max})")
            interval = 1000 if self._login_retry_count < 10 else 2000
            if self._onebot_mode == "external":
                QTimer.singleShot(interval, self._do_external_poll_check)
            else:
                QTimer.singleShot(interval, self._start_login_poll)
        else:
            self._append_log(f"[登录] 超时：{self._login_retry_max}次尝试后仍未连接")
            self.login_btn.setEnabled(True)

    def _make_onebot_client(self) -> OneBotHTTPClient:
        """根据当前模式创建 OneBot HTTP 客户端"""
        url = self._onebot_url if self._onebot_mode == "external" else "http://127.0.0.1:5700"
        return OneBotHTTPClient(base_url=url)

    def _start_external_poll(self):
        """外部模式：轮询配置的 OneBot 地址直到有响应"""
        self.login_btn.setEnabled(False)
        self.login_status_label.setText(f"状态: 正在连接 {self._onebot_url}...")
        self._append_log(f"[登录] 外部模式，连接 {self._onebot_url} ...")
        self._login_retry_count = 0
        self._login_retry_max = 30
        self._login_poll_active = True
        self._do_external_poll_check()

    def _do_external_poll_check(self):
        """执行一次外部轮询检查"""
        if not getattr(self, "_login_poll_active", True):
            return

        class ExternalCheckWorker(QThread):
            login_result = pyqtSignal(bool, str, str)
            def __init__(self_, url):
                super().__init__()
                self_._url = url
            def run(self_):
                try:
                    client = OneBotHTTPClient(base_url=self_._url, timeout=5.0)
                    info = client.get_login_info()
                    uid = str(info.get("user_id", ""))
                    nickname = info.get("nickname", "")
                    self_.login_result.emit(True, uid, nickname)
                except Exception as e:
                    self_.login_result.emit(False, "", str(e))

        self._login_checker = ExternalCheckWorker(self._onebot_url)
        self._login_checker.login_result.connect(self._on_login_poll_result)
        self._login_checker.start()

    def _merge_cached_accounts(self, new_accounts: list):
        """合并账号到缓存，按QQ号去重，优先保留有昵称的条目"""
        merged: dict[str, str] = {}
        # 先加载已有缓存
        for qq, nick in self._config_mgr.config.cached_accounts:
            if qq:
                merged[qq] = nick if nick else merged.get(qq, "")
        # 新数据覆盖（优先保留有昵称的）
        for qq, nick in new_accounts:
            if qq:
                if nick or qq not in merged:
                    merged[qq] = nick
        # 上次登录排最前
        last_id = self._config_mgr.config.last_self_id
        sorted_items = sorted(merged.items(), key=lambda a: (a[0] != last_id, a[0]))
        self._config_mgr.config.cached_accounts = [list(a) for a in sorted_items[:5]]
        self._config_mgr.save()

    def _on_quick_login_accounts(self, accounts: list):
        """检测到快速登录账号 — 保存到配置 + 渲染内联快登按钮"""
        if not accounts:
            return
        self._merge_cached_accounts(accounts)
        self._quick_login_accounts = accounts
        self._append_log(f"[登录] 检测到 {len(accounts)} 个缓存账号（已保存，下次启动可快速登录）")

        # 扫码模式下，在二维码下方渲染快捷登录按钮
        if not self._quick_login_attempting and self._napcat and self._napcat.is_running() and self._onebot is None:
            self._render_inline_quick_login_buttons(accounts)

    def _do_quick_login_restart(self, qq: str):
        """NapCat 已在运行（扫码模式），杀掉后用指定账号重启快登"""
        self._quick_login_attempting = True
        self._quick_login_mode = True
        self._login_poll_active = False
        self._clear_quick_login_buttons()
        self.login_status_label.setText(f"状态: 正在切换快速登录 {qq}...")
        self._append_log(f"[登录] 切换快速登录 {qq}，重启 NapCat...")

        if self._napcat:
            self._napcat.stop()
            self._napcat = None

        napcat_root = self._config_mgr.config.napcat_path
        if not napcat_root:
            self._append_log("[错误] NapCat 路径未知")
            self._quick_login_attempting = False
            self._set_login_btn_mode("scan")
            return

        self._config_mgr.config.last_self_id = qq
        self._config_mgr.save()

        self._napcat = NapCatManager(napcat_root)
        saved_qq = self._config_mgr.config.qq_exe_path
        if self._napcat.start(qq=qq, saved_qq_path=saved_qq):
            self._set_login_btn_mode("quick")
            self.login_status_label.setText(f"状态: 正在快速登录 {qq}...")
            self._login_retry_count = 0
            self._login_retry_max = 30
            self._login_poll_active = True
            self._start_login_poll()
        else:
            self._quick_login_attempting = False
            self._set_login_btn_mode("scan")
            self._append_log("[错误] 快登启动失败")

    def _on_recheck_quick_login(self):
        """手动触发快速登录（扫描模式下点按钮时调用）"""
        if self._onebot is not None:
            self._append_log("[登录] 已在线，无需重新登录", "info")
            return

        cached = self._config_mgr.config.cached_accounts
        cached = [(q, n) for q, n in cached if q]
        if not cached:
            if self._napcat and self._napcat.is_running():
                self._append_log("[登录] 暂无缓存账号，请扫码登录", "warn")
            else:
                self._append_log("[登录] NapCat未运行，请先点击启动", "warn")
            return

        # NapCat 已在扫码模式运行 → 直接 kill+重启快登
        if self._napcat and self._napcat.is_running():
            dlg = QuickLoginDialog(cached, self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                qq = dlg.selected_qq()
                if qq:
                    self._do_quick_login_restart(qq)
            return

        # NapCat 未运行 → 走完整 setup 流程
        dlg = QuickLoginDialog(cached, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        qq = dlg.selected_qq()
        if not qq:
            return
        self._pending_qq = qq
        self._quick_login_attempting = True
        self.login_btn.setEnabled(False)
        self.login_status_label.setText("状态: 正在准备 NapCat...")
        self._setup_worker = NapCatSetupWorker(self._config_mgr.state_dir())
        self._setup_worker.status.connect(self._on_setup_status)
        self._setup_worker.progress.connect(self._on_setup_progress)
        self._setup_worker.finished.connect(self._on_setup_finished)
        self._setup_worker.failed.connect(self._on_setup_failed)
        self._setup_worker.start()

    # ---- 扫码模式下内联快登按钮 ----
    def _render_inline_quick_login_buttons(self, accounts: list):
        """在二维码下方动态渲染快登按钮"""
        if not hasattr(self, '_quick_login_btn_layout'):
            self._quick_login_btn_layout = QVBoxLayout()
            self._quick_login_btn_layout.setSpacing(2)
            parent_layout = self.login_status_label.parent().layout()
            if parent_layout:
                idx = parent_layout.indexOf(self.login_status_label)
                if idx >= 0:
                    parent_layout.insertLayout(idx + 1, self._quick_login_btn_layout)
                else:
                    parent_layout.addLayout(self._quick_login_btn_layout)

        self._clear_quick_login_buttons()

        label = QLabel("快速登录:")
        label.setStyleSheet("font-size: 10px; background: transparent; padding: 2px 0;")
        self._quick_login_btn_layout.addWidget(label)

        for qq, nickname in accounts:
            if not qq:
                continue
            label = f"  {nickname} ({qq})" if nickname else f"  {qq}"
            btn = QPushButton(label)
            btn.setFixedHeight(28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, q=qq: self._do_quick_login_restart(q))
            self._quick_login_btn_layout.addWidget(btn)

    def _clear_quick_login_buttons(self):
        """清除内联快登按钮"""
        if hasattr(self, '_quick_login_btn_layout'):
            while self._quick_login_btn_layout.count():
                item = self._quick_login_btn_layout.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()
            try:
                parent_layout = self.login_status_label.parent().layout()
                if parent_layout:
                    parent_layout.removeItem(self._quick_login_btn_layout)
            except Exception:
                pass

    def _on_login_busy_detected(self, qq: str):
        """账号已在别处登录 → 重启纯扫码模式"""
        if self._quick_login_attempting:
            self._append_log(f"[登录] 账号{qq}快登失败（会话未过期），切换扫码模式...")
            self.login_status_label.setText(f"状态: {qq} 会话未过期，切换扫码中...")
        else:
            self._append_log(f"[登录] NapCat 自发快登 {qq} 失败，重启纯扫码模式...")
            self.login_status_label.setText("状态: 旧会话冲突，切换扫码中...")
        self._fallback_to_scan(qq)

    def _fallback_to_scan(self, qq: str):
        """快登失败 → 强杀并重启纯扫码模式"""
        self._quick_login_attempting = False
        self._quick_login_mode = False
        self._login_poll_active = False
        self._clear_quick_login_buttons()
        self._append_log(f"[登录] 切换纯扫码模式...")
        self.login_status_label.setText("状态: 正在切换扫码模式...")
        self._login_poll_active = False

        if self._napcat:
            self._napcat.stop()
            self._napcat = None

        napcat_root = self._config_mgr.config.napcat_path
        if napcat_root:
            self._napcat = NapCatManager(napcat_root)
            if self._napcat.start(saved_qq_path=self._config_mgr.config.qq_exe_path):  # 不传 qq = 纯扫码
                self._set_login_btn_mode("quick")
                self.login_status_label.setText("状态: 请扫码登录")
                self._login_retry_count = 0
                self._login_retry_max = 30
                self._login_poll_active = True
                self._start_login_poll()
                return
        self._set_login_btn_mode("scan")
        self.login_btn.setEnabled(True)
        self._append_log("[错误] 切换扫码模式失败")

    def _on_setup_failed(self, error: str):
        self.login_status_label.setText(f"状态: {error}")
        self.login_btn.setEnabled(True)
        self._append_log(f"[错误] {error}")

    def _on_logout_clicked(self):
        """退出登录：停一切，回到未登录状态"""
        self._login_poll_active = False
        self._quick_login_attempting = False
        self._quick_login_mode = False
        self._clear_quick_login_buttons()
        self._stop_post_listener()
        self._onebot = None
        self._joined_groups.clear()
        self._intersection.clear()
        self.qr_label.clear()
        if self._onebot_mode == "external":
            self.qr_label.setText("外部 OneBot 模式\n请在 QQ 中自行启动\nOneBot 服务端")
        else:
            self.qr_label.setText("请点击下方按钮\n启动NapCat并登录")
        self.qr_label.setStyleSheet(
            "border: 2px dashed #6a4040; border-radius: 10px;"
            "font-size: 14px; color: #7a6a5a; background: transparent;"
        )
        self.login_status_label.setText("状态: 未登录")
        self.status_online.setText("离线")
        self.status_qq.setText("QQ: -")
        self.status_last_send.setText("上次发送: -")
        self.logout_btn.setEnabled(False)
        self._csv_records.clear()
        self.group_tree.clear()
        self.group_selection_label.setText("已选: 0 / 0 群（登录后可刷新交集）")
        self._append_log("[登录] 已退出登录")

        # 停 NapCat
        if self._napcat:
            self._napcat.stop()
            self._napcat = None

        self._set_login_btn_mode("scan")

    def _check_breakpoint_resume(self):
        """检测是否有未完成的发送会话，提示用户是否继续"""
        state_mgr = SendStateManager()
        session = state_mgr.load()
        if not session:
            return

        remaining = session.total_count - session.sent_index
        if remaining <= 0:
            state_mgr.clear()
            return

        reply = QMessageBox.question(
            self, "断点续传",
            f"检测到上次未完成的发送会话：\n\n"
            f"已发送: {session.sent_index} / {session.total_count} 群\n"
            f"剩余: {remaining} 群\n"
            f"消息: 「{session.message[:60]}{'...' if len(session.message) > 60 else ''}」\n\n"
            f"是否继续发送？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )

        if reply != QMessageBox.StandardButton.Yes:
            state_mgr.clear()
            self._append_log("[发送] 已放弃上次未完成的会话")
            return

        self._append_log(f"[发送] 断点续传: 从第 {session.sent_index + 1} 个群继续...")

        # 重建 targets
        targets = []
        for gid in session.target_group_ids:
            # 从 csv_records 中找群名
            name = gid
            for r in self._csv_records:
                if r.group_id == gid:
                    name = r.group_name or gid
                    break
            targets.append((gid, name))

        if not targets:
            self._append_log("[发送] 无法重建目标列表，已清除会话")
            state_mgr.clear()
            return

        self._send_btn_enabled(False)
        self._send_worker = SendWorker(
            message=session.message,
            targets=targets,
            start_index=session.sent_index,
        )
        self._send_worker.start()

    # ---- CSV ----
    def _on_load_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择东方QQ群列表CSV", "",
            "CSV文件 (*.csv);;所有文件 (*.*)"
        )
        if not path:
            return
        from touhou_promoter.core.csv_loader import load_groups
        try:
            records = load_groups(path)
            self._csv_records = records
            self._csv_groups = {r.group_id for r in records}
            self._config_mgr.config.csv_path = path
            self._config_mgr.save()
            self._append_log(f"[CSV] 加载完成: {len(records)} 条记录, {len(self._csv_groups)} 个唯一群号")
            self._intersection = self._csv_groups & self._joined_groups
            self._refresh_group_tree()
        except Exception as e:
            self._append_log(f"[CSV] 加载失败: {e}")

    # ---- 群列表刷新 ----
    def _auto_refresh_intersection(self):
        """登录后自动获取群列表并求交集"""
        if not self._napcat or not self._napcat.is_running():
            self._append_log("[群列表] 请先登录")
            return

        # 自动重新加载CSV（用户可能外部编辑了CSV文件）
        csv_path = self._config_mgr.config.csv_path
        if csv_path and os.path.isfile(csv_path):
            try:
                from touhou_promoter.core.csv_loader import load_groups
                records = load_groups(csv_path)
                self._csv_records = records
                self._csv_groups = {r.group_id for r in records}
            except Exception:
                pass  # CSV读取失败则用旧数据
        elif not self._csv_records:
            self._append_log("[群列表] 请先通过 文件→加载CSV 加载群列表")
            return

        make_client = self._make_onebot_client

        class IntersectionWorker(QThread):
            result_ready = pyqtSignal(set)
            error_msg = pyqtSignal(str)

            def run(self):
                try:
                    client = make_client()
                    groups = client.get_group_list()
                    ids = {str(g.get("group_id", "")) for g in groups}
                    self.result_ready.emit(ids)
                except Exception as e:
                    self.error_msg.emit(str(e))
                    self.result_ready.emit(set())

        # 断开并停止前一个 worker
        if hasattr(self, "_worker") and self._worker is not None:
            try:
                self._worker.result_ready.disconnect()
                self._worker.error_msg.disconnect()
            except Exception:
                pass
            if self._worker.isRunning():
                self._worker.quit()
                self._worker.wait(1000)

        self._worker = IntersectionWorker()
        self._worker.result_ready.connect(self._on_intersection_ready)
        self._worker.error_msg.connect(lambda e: self._append_log(f"[群列表] 获取失败: {e}"))
        self._worker.start()
        self._append_log("[群列表] 正在获取bot加入的群列表...")

    def _refresh_group_tree(self):
        """用交集结果重建带复选框的群树（默认折叠，三态勾选）"""
        self.group_tree.clear()
        if not self._intersection:
            self.group_tree.addTopLevelItem(
                QTreeWidgetItem(["暂无交集群"])
            )
            self.group_selection_label.setText("已选: 0 / 0 群")
            return

        from touhou_promoter.core.csv_loader import build_tree
        filtered = [r for r in self._csv_records if r.group_id in self._intersection]
        roots = build_tree(filtered)

        # 显式 flags
        LEAF_FLAGS = (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsUserCheckable
        )
        PARENT_FLAGS = LEAF_FLAGS

        self._updating_checkboxes = True
        for root in roots:
            item = QTreeWidgetItem([root.label])
            item.setFlags(PARENT_FLAGS)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            item.setData(0, Qt.ItemDataRole.UserRole, "")
            self.group_tree.addTopLevelItem(item)
            for sub in root.children:
                sub_item = QTreeWidgetItem([sub.label])
                sub_item.setFlags(PARENT_FLAGS)
                sub_item.setCheckState(0, Qt.CheckState.Unchecked)
                sub_item.setData(0, Qt.ItemDataRole.UserRole, "")
                item.addChild(sub_item)
                for leaf in sub.children:
                    gid = leaf.group.group_id if leaf.group else ""
                    name = leaf.group.group_name if leaf.group else leaf.label
                    leaf_item = QTreeWidgetItem([name])
                    leaf_item.setFlags(LEAF_FLAGS)
                    leaf_item.setCheckState(0, Qt.CheckState.Unchecked)
                    leaf_item.setData(0, Qt.ItemDataRole.UserRole, gid)
                    sub_item.addChild(leaf_item)
        self._updating_checkboxes = False
        # 默认折叠，只显示大类
        # self.group_tree.expandAll()  ← 不展开
        self._update_selection_count()

    def _on_tree_item_changed(self, item: QTreeWidgetItem, column: int):
        """复选框变化时传播到子/父节点"""
        if getattr(self, "_updating_checkboxes", False):
            return
        if column != 0:
            return

        self._updating_checkboxes = True
        state = item.checkState(0)

        # 父节点被点成 PartiallyChecked 时强制转 Checked，只允许全选/全不选
        if item.childCount() > 0 and state == Qt.CheckState.PartiallyChecked:
            state = Qt.CheckState.Checked
            item.setCheckState(0, state)

        # 向下传播到所有子节点
        self._propagate_check_state(item, state)

        # 向上更新所有父节点的三态
        parent = item.parent()
        while parent:
            self._update_parent_check_state(parent)
            parent = parent.parent()

        self._updating_checkboxes = False
        self._update_selection_count()

    def _on_tree_item_pressed(self, item: QTreeWidgetItem, column: int):
        """记录点击前的勾选状态，用于区分点击复选框 vs 点击文本"""
        self._pre_click_state = item.checkState(0)
        self._pre_click_item = item

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        """点击叶子节点文本时也切换复选框（不只是点小方框）"""
        if getattr(self, "_updating_checkboxes", False):
            return
        # 只对叶子节点生效
        if item.childCount() > 0:
            return
        # 如果点击前后状态没变 → 用户点的是文本行 → 手动切换
        pre = getattr(self, "_pre_click_state", None)
        if pre is not None and item is getattr(self, "_pre_click_item", None) and pre == item.checkState(0):
            new_state = Qt.CheckState.Unchecked if pre == Qt.CheckState.Checked else Qt.CheckState.Checked
            item.setCheckState(0, new_state)
            # itemChanged 会自动触发 _on_tree_item_changed 完成传播
        self._pre_click_item = None
        self._pre_click_state = None

    def _on_tree_context_menu(self, pos):
        """右键菜单"""
        item = self.group_tree.itemAt(pos)
        gid = item.data(0, Qt.ItemDataRole.UserRole) if item else ""
        if not gid:
            return
        menu = QMenu(self)
        copy_action = menu.addAction(f"复制群号: {gid}")
        info_action = menu.addAction(f"ℹ️ 查看详情")

        action = menu.exec(self.group_tree.mapToGlobal(pos))
        if action == copy_action:
            QApplication.clipboard().setText(gid)
            self._append_log(f"已复制群号: {gid}")
        elif action == info_action:
            self._show_group_detail(gid, item.text(0))

    def _show_group_detail(self, gid: str, name: str):
        """通过 OneBot API 获取群详情并显示"""
        if not self._onebot:
            QMessageBox.information(
                self, "群详情",
                f"群名称: {name}\n群号: {gid}"
            )
            return
        self._append_log(f"[群详情] 正在查询群 {gid}...")
        self._detail_worker = GroupDetailWorker(self._onebot, gid, name)
        self._detail_worker.finished.connect(self._on_group_detail_ready)
        self._detail_worker.failed.connect(
            lambda e: QMessageBox.warning(self, "群详情", f"获取群信息失败: {e}")
        )
        self._detail_worker.start()

    def _on_group_detail_ready(self, gid: str, name: str, info: dict):
        """群详情 API 返回后显示"""
        member_count = info.get("member_count", "?")
        max_members = info.get("max_member_count", "?")
        group_name = info.get("group_name", name)
        group_remark = info.get("group_remark", "")
        all_shut = info.get("group_all_shut", 0)

        lines = [
            f"群名称: {group_name}",
            f"群号: {gid}",
            f"成员数: {member_count}/{max_members}",
        ]
        if group_remark:
            lines.append(f"备注: {group_remark}")
        if all_shut:
            lines.append("状态: 全员禁言中")

        QMessageBox.information(self, f"群详情 - {group_name}", "\n".join(lines))
        self._append_log(f"[群详情] {group_name}({gid}) — 成员{member_count}/{max_members}")

    def _on_group_search(self, text: str):
        """搜索过滤群列表"""
        t = text.strip().lower()
        for i in range(self.group_tree.topLevelItemCount()):
            cat_item = self.group_tree.topLevelItem(i)
            cat_visible = False
            for j in range(cat_item.childCount()):
                sub_item = cat_item.child(j)
                sub_visible = False
                for k in range(sub_item.childCount()):
                    leaf = sub_item.child(k)
                    if not t:
                        leaf.setHidden(False)
                        sub_visible = True
                        continue
                    record = leaf.data(0, Qt.ItemDataRole.UserRole)
                    label = leaf.text(0)
                    gid = leaf.text(1)
                    match = (t in label.lower() or t in gid) if record else True
                    leaf.setHidden(not match)
                    if match:
                        sub_visible = True
                sub_item.setHidden(not sub_visible)
                if sub_visible:
                    cat_visible = True
            cat_item.setHidden(not cat_visible)

    def _propagate_check_state(self, parent: QTreeWidgetItem, state):
        """递归设置所有后代叶子节点的勾选状态，父节点只做 Checked/Unchecked"""
        if state == Qt.CheckState.PartiallyChecked:
            state = Qt.CheckState.Checked
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.childCount() == 0:
                child.setCheckState(0, state)
            else:
                self._propagate_check_state(child, state)
                self._update_parent_check_state(child)

    def _update_parent_check_state(self, parent: QTreeWidgetItem):
        """根据子节点更新父节点的三态勾选"""
        checked = 0
        unchecked = 0
        for i in range(parent.childCount()):
            s = parent.child(i).checkState(0)
            if s == Qt.CheckState.Checked:
                checked += 1
            elif s == Qt.CheckState.Unchecked:
                unchecked += 1
        total = parent.childCount()
        if checked == total:
            parent.setCheckState(0, Qt.CheckState.Checked)
        elif unchecked == total:
            parent.setCheckState(0, Qt.CheckState.Unchecked)
        else:
            parent.setCheckState(0, Qt.CheckState.PartiallyChecked)

    def _update_selection_count(self):
        """统计已选中的叶子群数量（仅限交集内）"""
        count = self._count_checked_leaves(self.group_tree.invisibleRootItem())
        total = len(self._intersection)
        # 防止因树中有残留节点导致 count > total
        count = min(count, total)
        self._state.selection_changed.emit(count)
        self.group_selection_label.setText(f"已选: {count} / {total} 群")
        self.target_label.setText(f"目标群: {count}")

    def _count_checked_leaves(self, parent: QTreeWidgetItem) -> int:
        """递归统计已勾选的叶子节点数（只计入在 _intersection 中的群）"""
        total = 0
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.childCount() == 0:
                gid = child.data(0, Qt.ItemDataRole.UserRole) or ""
                if (child.checkState(0) == Qt.CheckState.Checked
                        and gid in self._intersection):
                    total += 1
            else:
                total += self._count_checked_leaves(child)
        return total

    def _on_select_all(self):
        """全选所有交集群"""
        if not self._intersection:
            return
        self._updating_checkboxes = True
        self._set_all_check_state(self.group_tree.invisibleRootItem(), Qt.CheckState.Checked)
        self._updating_checkboxes = False
        self._update_selection_count()

    def _on_deselect_all(self):
        """取消全选"""
        if not self._intersection:
            return
        self._updating_checkboxes = True
        self._set_all_check_state(self.group_tree.invisibleRootItem(), Qt.CheckState.Unchecked)
        self._updating_checkboxes = False
        self._update_selection_count()

    def _set_all_check_state(self, parent: QTreeWidgetItem, state):
        """递归设置所有叶子节点（父节点不直接勾选，只勾选交集内的叶子）"""
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.childCount() == 0:
                gid = child.data(0, Qt.ItemDataRole.UserRole) or ""
                if gid in self._intersection:
                    child.setCheckState(0, state)
            else:
                self._set_all_check_state(child, state)
                self._update_parent_check_state(child)

    # ---- 发送 ----
    def _on_send_clicked(self):
        """开始群发：收集选中群 → 确认 → 启动 SendWorker"""
        # 检查是否有内容
        html = self.message_edit.toHtml()
        if not self.message_edit.toPlainText().strip() and "<img " not in html:
            QMessageBox.warning(self, "提示", "请输入要发送的消息内容")
            return

        # 从富文本编辑器提取 CQ 码消息
        message = self._build_send_message()

        # 收集选中的叶子群
        targets = self._collect_checked_targets()
        if not targets:
            QMessageBox.warning(self, "提示", "请先在群列表中勾选要发送的群")
            return

        total = len(targets)
        # 计算预计耗时（用最新配置）
        self._refresh_config()
        cfg = self._config_mgr.config
        est_seconds = total * (cfg.send_interval + cfg.send_interval_jitter / 2)
        est_seconds += (total // cfg.batch_pause_every) * cfg.batch_pause_seconds if cfg.batch_pause_every else 0
        est_str = f"{int(est_seconds // 60)}分{int(est_seconds % 60)}秒" if est_seconds >= 60 else f"{int(est_seconds)}秒"

        # 确认对话框摘要
        img_count = html.count("<img ")
        plain = self.message_edit.toPlainText().strip()
        summary = f"{img_count}张图片" if img_count else ""
        if plain:
            summary = f"{summary} + 文本" if summary else plain[:80]
        reply = QMessageBox.question(
            self, "确认发送",
            f"即将向 {total} 个群发送消息：\n\n"
            f"「{summary}{'...' if plain and len(plain) > 80 else ''}」\n\n"
            f"预计耗时: {est_str}\n\n"
            f"确定开始发送？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._send_btn_enabled(False)
        self._append_log(f"[发送] 开始向 {total} 个群发送消息...")

        self._send_worker = SendWorker(
            message=message,
            targets=targets,
        )
        self._send_worker.start()

    def _on_recall_clicked(self):
        """撤回全部已发送消息，同时终止正在进行的发送任务"""
        # 如果正在发送，先停止
        if self._send_worker and self._send_worker.isRunning():
            self._append_log("[发送] 正在中断...")
            self._recalling = True
            self._send_worker.stop()
            self._send_worker.quit()
            self._send_worker.wait(1000)
            # 处理排队的 send_interrupted 信号，让 _on_send_interrupted 在 _recalling 保护下执行
            QApplication.processEvents()
            self._recalling = False
            # 如果 _on_send_interrupted 没拿到 ids，这里兜底
            if self._send_worker._engine and not self._last_sent_ids:
                self._last_sent_ids = dict(self._send_worker._engine._sent_message_ids)
            self._send_worker = None
            self._stop_post_listener()

        # 如果正在撤回，先停下来
        if self._recall_worker and self._recall_worker.isRunning():
            self._recall_worker.stop()
            self._recall_worker.quit()
            self._recall_worker.wait(1000)
            self._recall_worker = None

        if not self._last_sent_ids:
            QMessageBox.information(self, "提示", "没有可撤回的消息（上次发送为空或应用已重启）")
            self._send_btn_enabled(True)
            return

        total = len(self._last_sent_ids)
        nt_warning = ""
        if self._nt_timeout_groups:
            nt_warning = (
                f"\n注意: {len(self._nt_timeout_groups)}个群因NT超时无法撤回"
                f"（消息已发出但未收到确认）:\n"
                + "\n".join(f"  • {n}" for n in self._nt_timeout_groups)
                + "\n"
            )
        reply = QMessageBox.question(
            self, "确认撤回",
            f"将撤回已发送到 {total} 个群的消息。\n{nt_warning}\n确定撤回？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self._send_btn_enabled(True)
            return

        self._send_btn_enabled(False)
        self._append_log(f"[撤回] 开始撤回 {total} 条消息...")

        self._recall_worker = RecallWorker(
            sent_message_ids=dict(self._last_sent_ids),
        )
        self._recall_worker.start()

    def _collect_checked_targets(self) -> list[tuple[str, str]]:
        """从群树中收集所有勾选的叶子节点，返回 [(group_id, group_name), ...]"""
        targets = []
        self._collect_checked_recursive(self.group_tree.invisibleRootItem(), targets)
        return targets

    def _collect_checked_recursive(self, parent, targets: list):
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.childCount() == 0:
                # 叶子节点
                if child.checkState(0) == Qt.CheckState.Checked:
                    gid = child.data(0, Qt.ItemDataRole.UserRole) or ""
                    name = child.text(0) or ""
                    if gid:
                        targets.append((gid, name))
            else:
                self._collect_checked_recursive(child, targets)

    # ---- 发送信号处理 ----

    def _on_send_started(self, total: int):
        """发送开始"""
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(0)
        self._last_sent_ids.clear()
        self._nt_timeout_groups.clear()

    def _on_send_progress(self, current: int, total: int, group_name: str, status: str):
        """发送/撤回进度更新"""
        self.progress_bar.setValue(current)
        self.progress_bar.setMaximum(total)

        if status == "sending":
            self._append_log(f"> {group_name} ...")
        elif status == "ok":
            self._append_log(f"{group_name} - 成功", "success")
        elif status == "ok(NT超时)":
            self._append_log(f"{group_name} - 已发出(NT超时无法撤回)", "success")
            self._nt_timeout_groups.append(group_name)
        elif status.startswith("fail:"):
            reason = status[5:]
            self._append_log(f"{group_name} - {reason}", "error")
        elif status == "pausing":
            self._append_log(f"{group_name}", "warning")
        elif status.startswith("recall:ok"):
            self._append_log(f"群{group_name} - 已撤回", "success")
        elif status.startswith("recall:fail:"):
            reason = status[11:]
            self._append_log(f"群{group_name} - {reason}", "error")

    def _on_send_completed(self, success: int, failed: int):
        """发送/撤回完成"""
        is_recall = self._recall_worker is not None
        self._send_btn_enabled(True)
        self.progress_bar.setValue(self.progress_bar.maximum())

        if is_recall:
            # 撤回完成 → 终止监听，清空记录
            self._append_log(f"[撤回] 完成! 成功: {success}, 失败: {failed}",
                             "success" if failed == 0 else "warning")
            self._last_sent_ids.clear()
            self._stop_post_listener()
            
            if self._listener_panel:
                self._listener_panel.clear()
        else:
            self._append_log(f"完成! 成功: {success}, 失败: {failed}",
                             "success" if failed == 0 else "warning")
            if self._send_worker and hasattr(self._send_worker, "_engine") and self._send_worker._engine:
                self._last_sent_ids = dict(self._send_worker._engine._sent_message_ids)
            if self._nt_timeout_groups:
                self._append_log(
                    f"[注意] {len(self._nt_timeout_groups)}个群NT超时，消息已发出但无法撤回: "
                    + ", ".join(self._nt_timeout_groups),
                    "warning")
            self.status_last_send.setText(
                f"上次发送: {datetime.now().strftime('%H:%M')} ({success}成功/{failed}失败)"
            )
            # 启动发送后监听
            self._start_post_send_listener()

        self._send_worker = None
        self._recall_worker = None

        # 3秒后重置进度条
        QTimer.singleShot(3000, lambda: self.progress_bar.reset())

    def _on_send_interrupted(self, sent: int):
        """发送被中断"""
        if self._recalling:
            # 由 _on_recall_clicked 接管 UI 状态，这里只记录
            self._last_sent_ids = dict(self._send_worker._engine._sent_message_ids) \
                if self._send_worker and hasattr(self._send_worker, "_engine") and self._send_worker._engine \
                else {}
            self._send_worker = None
            return

        self._send_btn_enabled(True)
        self.progress_bar.setValue(0)
        self._append_log(f"已中断，已发送 {sent} 条消息（未发送的群可在断点恢复后继续）", "warning")

        if self._send_worker and hasattr(self._send_worker, "_engine") and self._send_worker._engine:
            self._last_sent_ids = dict(self._send_worker._engine._sent_message_ids)

        self.status_last_send.setText(
            f"上次发送: {datetime.now().strftime('%H:%M')} (中断, 已发{sent})"
        )
        self._send_worker = None

    def _start_post_send_listener(self):
        """发送完成后启动回复监听（如果配置了监听时长）。

        每次新的发送都会停止上次监听，重置缓存，只监听最新一次发送的回复。
        """
        duration = self._config_mgr.config.listener_expiry_seconds
        if duration <= 0 or not self._last_sent_ids:
            return

        # 停止之前可能还在运行的监听
        self._stop_post_listener()

        # 重置监听窗口（新的发送周期）
        if self._listener_panel:
            self._listener_panel.clear()

        target_gids = {gid for gid in self._last_sent_ids}
        self_id = self._config_mgr.config.last_self_id

        self._append_log(f"发送后监听已启动（{duration}秒），监控目标群中的回复...", "info")

        self._post_listener = PostSendListener(
            target_group_ids=target_gids,
            duration_seconds=duration,
            self_id=self_id,
        )
        self._post_listener.hit_detected.connect(self._on_listener_hit)
        self._post_listener.ws_error.connect(
            lambda err: self._append_log(f"监听器错误: {err}", "error")
        )
        self._post_listener.finished.connect(self._on_listener_finished)
        self._post_listener.start()
        

    def _stop_post_listener(self):
        """停止当前运行的监听器"""
        if self._post_listener and self._post_listener.isRunning():
            self._post_listener.stop_listening()
        self._post_listener = None

    def _on_listener_hit(self, group_id: str, group_name: str, user_nick: str, message: str, elapsed: int):
        """监听命中 — 写入主日志 + 注入嵌入式监听面板"""
        # 从 CSV 缓存解析群名
        if not group_name:
            for r in self._csv_records:
                if r.group_id == group_id:
                    group_name = r.group_name or group_id
                    break
            if not group_name:
                group_name = group_id
        preview = message[:80] + ('...' if len(message) > 80 else '')
        self._append_log(f"群{group_name} {user_nick}: {preview}", "join")
        if self._listener_panel:
            self._listener_panel.add_message(group_id, group_name, user_nick, message)

    def _on_listener_finished(self):
        """监听结束"""
        hits = self._post_listener.hits() if self._post_listener else []
        if hits:
            self._append_log(f"监听结束，共收到 {len(hits)} 条相关回复", "info")
        else:
            self._append_log("监听结束，未收到相关回复", "info")

    def _on_listener_reply(self, group_id: str, text: str):
        """监听面板请求回复 → 调用 API 发送"""
        try:
            client = self._make_onebot_client()
            from touhou_promoter.core.forwarding_engine import parse_message_to_segments
            segs = parse_message_to_segments(text)
            client.send_group_msg(group_id, segs, auto_escape=False)
            self._append_log(f"回复群{group_id}: {text[:40]}", "success")
        except Exception as e:
            self._append_log(f"回复失败: {e}", "error")

    def _send_btn_enabled(self, enabled: bool):
        """设置发送相关按钮状态"""
        self.send_btn.setEnabled(enabled)
        self.recall_btn.setEnabled(enabled)

    def _on_message_changed(self):
        """文本变化 -> 更新字数"""
        # Count text only (strip HTML tags for image-only messages)
        html = self.message_edit.toHtml()
        text = self.message_edit.toPlainText().strip()
        img_count = html.count("<img ")
        if text:
            self.char_count_label.setText(f"字数: {len(text.replace(chr(10),''))}")
        elif img_count:
            self.char_count_label.setText(f"图片: {img_count}张")
        else:
            self.char_count_label.setText("字数: 0")

    # ── 图片操作 ──

    def _on_insert_image(self):
        """选择图片文件，插入到光标位置"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;所有文件 (*.*)"
        )
        if not path:
            return
        self._insert_image_at_cursor(path)

    def _insert_image_at_cursor(self, path: str):
        """将图片以base64嵌入QTextEdit当前光标处"""
        import base64 as _b64
        try:
            with open(path, "rb") as f:
                data = f.read()
            b64 = _b64.b64encode(data).decode()
        except Exception:
            self._append_log(f"[错误] 无法读取图片: {path}", "error")
            return
        ext = os.path.splitext(path)[1].lower()
        mime_map = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg",
                    ".gif": "gif", ".webp": "webp", ".bmp": "bmp"}
        mime = mime_map.get(ext, "png")

        self._image_paths.append(path)
        self._b64_to_path[b64] = path

        cursor = self.message_edit.textCursor()
        cursor.insertHtml(
            f'<img src="data:image/{mime};base64,{b64}" '
            f'style="max-width:200px;border-radius:8px;margin:4px 2px" '
            f'title="{os.path.basename(path)}">'
        )
        self._append_log(f"已插入图片: {os.path.basename(path)}")

    def _clear_message(self):
        """清空消息文本和所有图片"""
        self.message_edit.clear()
        self._image_paths.clear()
        self._b64_to_path.clear()
        self.char_count_label.setText("字数: 0")

    # ── 拖拽图片到编辑器 ──

    def _on_editor_drag_enter(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def _on_editor_drop(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')):
                # Move cursor to drop position then insert
                cursor = self.message_edit.cursorForPosition(event.position().toPoint())
                self.message_edit.setTextCursor(cursor)
                self._insert_image_at_cursor(path)

    # ── 提取消息用于发送 ──

    def _build_send_message(self) -> str:
        """从富文本编辑器中提取 CQ码格式的消息字符串"""
        import re as _re

        html = self.message_edit.toHtml()
        # Only process body content (strip Qt's <html><head>... preamble)
        body_match = _re.search(r'<body[^>]*>(.*)</body>', html, _re.DOTALL)
        if body_match:
            html = body_match.group(1)
        # Walk through HTML: img tags -> [CQ:image], text -> plain text
        parts = []
        pos = 0
        img_re = _re.compile(r'<img\s+[^>]*?src="data:image/[^;]+;base64,([^"]+)"[^>]*>')
        for m in img_re.finditer(html):
            text_html = html[pos:m.start()]
            text = _re.sub(r'<[^>]+>', '', text_html)
            text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
            if text.strip():
                parts.append(text.strip())
            b64 = m.group(1)
            filepath = self._b64_to_path.get(b64, "")
            if filepath:
                parts.append(f"[CQ:image,file={filepath}]")
            pos = m.end()
        text_html = html[pos:]
        text = _re.sub(r'<[^>]+>', '', text_html)
        text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        if text.strip():
            parts.append(text.strip())
        return "".join(parts) if parts else ""

    # ---- 设置 ----
    def _on_napcat_path(self):
        path = QFileDialog.getExistingDirectory(
            self, "选择NapCat所在目录",
            self._config_mgr.config.napcat_path or os.path.expanduser("~")
        )
        if path:
            self._config_mgr.config.napcat_path = path
            self._config_mgr.save()
            self._append_log(f"[设置] NapCat路径已设为: {path}")

    def _on_send_params(self):
        dlg = SettingsDialog(self)
        if dlg.exec() == SettingsDialog.DialogCode.Accepted:
            self._refresh_config()
            self._append_log("[设置] 发送参数已更新")
            self._update_interval_label()

    def _position_editor_overlay(self):
        """将叠加标签定位到编辑区右下角"""
        if not hasattr(self, '_editor_overlay') or not self._editor_overlay:
            return
        vp = self.message_edit.viewport()
        w, h = vp.width(), vp.height()
        self._editor_overlay.setGeometry(w - 190, h - 26, 182, 24)
        self._editor_overlay.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._position_editor_overlay)

    def _resolve_asset(self, filename: str) -> str:
        """返回资源文件的绝对路径（兼容 dev 和 PyInstaller onefile）"""
        base = getattr(sys, '_MEIPASS', '')
        if base:
            p = os.path.join(base, 'touhou_promoter', 'assets', filename)
        else:
            pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            p = os.path.join(pkg_dir, 'assets', filename)
        return os.path.normpath(p)

    def _resolve_theme(self, theme_str: str) -> str:
        """将 QSS 中的 {{placeholder}} 替换为运行时资源路径"""
        asset_dir = os.path.dirname(self._resolve_asset("asanoha_bg.png"))
        sd = asset_dir.replace('\\', '/')
        return theme_str.replace("{{asanoha_light}}", f"{sd}/asanoha_bg.png") \
                        .replace("{{asanoha_dark}}", f"{sd}/asanoha_bg_dark.png")

    def _refresh_overlay_theme(self):
        """主题切换时更新叠加标签背景色"""
        if not hasattr(self, '_editor_overlay') or not self._editor_overlay:
            return
        bg = "rgba(36, 22, 20, 0.88)" if self._dark_mode else "rgba(255, 255, 255, 0.88)"
        text_c = "#b8a898" if self._dark_mode else "#6a5040"
        bold_c = "#f0e8e0" if self._dark_mode else "#2a1810"
        self._editor_overlay.setStyleSheet(
            f"QFrame#editorOverlay {{ background: {bg}; border-radius: 4px; }}"
        )
        self.interval_label.setStyleSheet(
            f"font-size: 10px; color: {text_c}; background: transparent;"
        )
        self.target_label.setStyleSheet(
            f"font-weight: bold; font-size: 11px; color: {bold_c}; background: transparent;"
        )

    def _refresh_config(self):
        """从磁盘重新加载配置（在设置对话框保存后调用）"""
        self._config_mgr._config = self._config_mgr._load()

    def _update_interval_label(self):
        c = self._config_mgr.config
        self.interval_label.setText(
            f"间隔{c.send_interval}s/"
            f"每{c.batch_pause_every}停{c.batch_pause_seconds}s"
        )
        self.interval_label.setToolTip(
            f"发送间隔 {c.send_interval}s，"
            f"每{c.batch_pause_every}条暂停{c.batch_pause_seconds}s"
        )

    def _on_toggle_theme(self):
        """切换深色/亮色主题"""
        self._dark_mode = not self._dark_mode
        if self._dark_mode:
            self.setStyleSheet(self._resolve_theme(self._THEME))
            self._theme_action.setText("切换亮色主题")
        else:
            self.setStyleSheet(self._resolve_theme(self._THEME_LIGHT))
            self._theme_action.setText("切换深色主题")
        self._config_mgr.config.dark_mode = self._dark_mode
        self._config_mgr.save()
        self._rebuild_log_view()
        self._refresh_overlay_theme()
        self._append_log(
            "[设置] 已切换为深色主题" if self._dark_mode else "[设置] 已切换为亮色主题"
        )
        # 同步监听窗口主题
        if self._listener_panel:
            self._listener_panel.set_dark_mode(self._dark_mode)

    def _on_about(self):
        QMessageBox.about(
            self, "关于",
            "东方Project一键宣发姬 v1.0\n\n"
            "基于NapCat + OneBot v11的QQ群发工具\n"
            "开发: 没灵感的鼓 & 没人管的鼓\n\n"
            "东方幻想指南网站：https://fantasyguide.cn/"
            "东方人人人网站: https://thtripeople.ren/"
            
        )

    # ================================================================
    # 工具
    # ================================================================
    COLOR_MAP_DARK = {
        "info":    "#f0e8e0",
        "success": "#5a9a5a",
        "error":   "#d04040",
        "warning": "#c09040",
        "debug":   "#7a6a5a",
        "join":    "#6090c0",
    }

    COLOR_MAP_LIGHT = {
        "info":    "#2a1810",
        "success": "#4a8040",
        "error":   "#c03030",
        "warning": "#a07030",
        "debug":   "#9a8070",
        "join":    "#5070a0",
    }

    @property
    def _color_map(self):
        return self.COLOR_MAP_LIGHT if not self._dark_mode else self.COLOR_MAP_DARK

    def _append_log(self, msg: str, level: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_entries.append((msg, level, ts))
        if len(self._log_entries) > 1000:
            self._log_entries = self._log_entries[-600:]

        color = self._color_map.get(level, self._color_map["info"])
        html = f'<span style="color:#7a6a5a">[{ts}]</span> ' \
               f'<span style="color:{color}">{msg}</span>'
        self.log_view.append(html)

        # 自动滚动到底部
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        # 手动限制行数（QTextEdit 没有 setMaximumBlockCount）
        excess = self.log_view.document().blockCount() - self._log_max_lines - 100
        if excess > 0:
            cursor = self.log_view.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.movePosition(
                cursor.MoveOperation.Down,
                cursor.MoveMode.KeepAnchor,
                excess,
            )
            cursor.removeSelectedText()

    def _rebuild_log_view(self):
        """主题切换后重建所有日志条目颜色（保留时间戳）"""
        self.log_view.clear()
        for msg, level, ts in self._log_entries[-600:]:
            color = self._color_map.get(level, self._color_map["info"])
            html = f'<span style="color:#7a6a5a">[{ts}]</span> ' \
                   f'<span style="color:{color}">{msg}</span>'
            self.log_view.append(html)
