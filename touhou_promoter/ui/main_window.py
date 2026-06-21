"""主窗口 — QSplitter左右布局，集成登录/群列表/消息编辑/发送控制/日志"""
import os
from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QSplitter, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTreeWidget, QTreeWidgetItem, QTextEdit, QPushButton,
    QProgressBar, QPlainTextEdit, QStatusBar, QMessageBox, QGroupBox,
    QFileDialog, QScrollArea,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap

from touhou_promoter.state.app_state import AppState
from touhou_promoter.state.config_manager import ConfigManager
from touhou_promoter.state.send_state import SendStateManager
from touhou_promoter.core.napcat_manager import NapCatManager
from touhou_promoter.core.napcat_bootstrap import ensure_napcat_ready
from touhou_promoter.core.onebot_client import OneBotHTTPClient
from touhou_promoter.core.onebot_adapter import build_intersection
from touhou_promoter.ui.workers import SendWorker, RecallWorker


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


class MainWindow(QMainWindow):
    """东方Project一键宣发姬 主窗口"""

    # ── 明亮主题 ──────────────────────────────────────────────────
    _THEME_LIGHT = """
    /* === 全局 === */
    QMainWindow {
        background: #ffffff;
    }
    QWidget {
        background: #ffffff;
        color: #24292f;
        font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif;
        font-size: 13px;
    }

    /* === 分组框 === */
    QGroupBox {
        background: #f6f8fa;
        border: 1px solid #d0d7de;
        border-radius: 10px;
        margin-top: 14px;
        padding: 20px 14px 14px 14px;
        font-weight: bold;
        font-size: 13px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 16px;
        padding: 0 10px;
        color: #24292f;
        background: #f6f8fa;
        border-radius: 4px;
    }

    /* === 按钮 — 通用 === */
    QPushButton {
        border: 1px solid #d0d7de;
        border-radius: 6px;
        padding: 7px 14px;
        background: #f6f8fa;
        color: #24292f;
        font-size: 12px;
        min-height: 20px;
    }
    QPushButton:hover {
        background: #eaeef2;
        border-color: #afb8c1;
    }
    QPushButton:pressed {
        background: #d0d7de;
        border-color: #8c959f;
    }
    QPushButton:disabled {
        color: #8c959f;
        background: #f6f8fa;
        border-color: #d0d7de;
    }

    /* === 主操作按钮 — 红色强调 === */
    QPushButton#loginBtn, QPushButton#sendBtn {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #e63946, stop:1 #c1121f);
        border-color: #c1121f;
        color: #fff;
        font-weight: bold;
    }
    QPushButton#loginBtn:hover, QPushButton#sendBtn:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #f25c67, stop:1 #e63946);
    }

    /* === 绿色按钮 === */
    QPushButton#logoutBtn {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #2b9348, stop:1 #1b6b2a);
        border-color: #2b9348;
        color: #fff;
        font-weight: bold;
    }
    QPushButton#logoutBtn:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #3cb054, stop:1 #2b9348);
    }

    /* === 危险按钮 === */
    QPushButton#stopBtn, QPushButton#recallBtn {
        background: #f6f8fa;
        border-color: #e63946;
        color: #e63946;
    }
    QPushButton#stopBtn:hover, QPushButton#recallBtn:hover {
        background: #ffeef0;
        border-color: #c1121f;
    }

    /* === 快捷登录按钮 === */
    QPushButton[cssClass="quickLogin"] {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #e3ecff, stop:1 #d0dcff);
        border: 1px solid #5b7fc0;
        border-radius: 8px;
        color: #2d4a7a;
        font-weight: bold;
        font-size: 13px;
        text-align: left;
        padding: 10px 14px;
    }
    QPushButton[cssClass="quickLogin"]:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #d0dcff, stop:1 #b8c8f0);
        border-color: #3b5998;
    }

    /* === 输入框 === */
    QTextEdit, QPlainTextEdit {
        border: 1px solid #d0d7de;
        border-radius: 6px;
        background: #ffffff;
        color: #24292f;
        padding: 10px;
        selection-background: #b6d4fe;
    }
    QTextEdit:focus, QPlainTextEdit:focus {
        border-color: #0969da;
    }

    /* === 树形控件 === */
    QTreeWidget {
        border: 1px solid #d0d7de;
        border-radius: 6px;
        background: #ffffff;
        alternate-background-color: #f6f8fa;
        outline: none;
        padding: 4px;
    }
    QTreeWidget::item {
        padding: 3px 6px;
        border-radius: 3px;
    }
    QTreeWidget::item:selected {
        background: #0969da;
        color: #fff;
    }
    QTreeWidget::item:hover:!selected {
        background: #eaeef2;
    }
    QHeaderView::section {
        background: #f6f8fa;
        border: none;
        border-bottom: 1px solid #d0d7de;
        padding: 6px 10px;
        font-weight: bold;
        color: #656d76;
        font-size: 11px;
        text-transform: uppercase;
    }

    /* === 进度条 === */
    QProgressBar {
        border: none;
        border-radius: 4px;
        background: #eaeef2;
        height: 6px;
        text-align: center;
        font-size: 10px;
        color: #656d76;
    }
    QProgressBar::chunk {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #e63946, stop:1 #f0883e);
        border-radius: 4px;
    }

    /* === 分割条 === */
    QSplitter::handle {
        background: #d0d7de;
        width: 2px;
    }

    /* === 状态栏 === */
    QStatusBar {
        background: #f6f8fa;
        border-top: 1px solid #d0d7de;
        color: #656d76;
        padding: 2px 8px;
        font-size: 12px;
    }

    /* === 滚动条 === */
    QScrollBar:vertical {
        background: transparent;
        width: 8px;
        margin: 2px;
    }
    QScrollBar::handle:vertical {
        background: #c0c8d0;
        border-radius: 4px;
        min-height: 30px;
    }
    QScrollBar::handle:vertical:hover {
        background: #8c959f;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
    }
    QScrollBar:horizontal {
        background: transparent;
        height: 8px;
        margin: 2px;
    }
    QScrollBar::handle:horizontal {
        background: #c0c8d0;
        border-radius: 4px;
        min-width: 30px;
    }
    QScrollBar::handle:horizontal:hover {
        background: #8c959f;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0;
    }

    /* === 标签 === */
    QLabel {
        background: transparent;
        color: #656d76;
        border: none;
    }

    /* === 菜单栏 === */
    QMenuBar {
        background: #f6f8fa;
        border-bottom: 1px solid #d0d7de;
        padding: 2px;
        color: #24292f;
    }
    QMenuBar::item {
        padding: 4px 12px;
        border-radius: 4px;
    }
    QMenuBar::item:selected {
        background: #eaeef2;
    }
    QMenu {
        background: #ffffff;
        border: 1px solid #d0d7de;
        border-radius: 6px;
        padding: 4px;
    }
    QMenu::item {
        padding: 6px 28px 6px 16px;
        border-radius: 4px;
    }
    QMenu::item:selected {
        background: #0969da;
        color: #ffffff;
    }
    QMenu::separator {
        height: 1px;
        background: #d0d7de;
        margin: 4px 8px;
    }

    /* === 提示框 === */
    QToolTip {
        background: #ffffff;
        border: 1px solid #d0d7de;
        border-radius: 4px;
        padding: 4px 8px;
        color: #24292f;
    }
    """.strip()
    _THEME = """
    /* === 全局 === */
    QMainWindow {
        background: #0d1117;
    }
    QWidget {
        background: #0d1117;
        color: #c9d1d9;
        font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif;
        font-size: 13px;
    }

    /* === 分组框 — 玻璃卡片风格 === */
    QGroupBox {
        background: #161b22;
        border: 1px solid #21262d;
        border-radius: 10px;
        margin-top: 14px;
        padding: 20px 14px 14px 14px;
        font-weight: bold;
        font-size: 13px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 16px;
        padding: 0 10px;
        color: #e6edf3;
        background: #161b22;
        border-radius: 4px;
    }

    /* === 按钮 — 通用 === */
    QPushButton {
        border: 1px solid #30363d;
        border-radius: 6px;
        padding: 7px 14px;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #21262d, stop:1 #1a1e25);
        color: #c9d1d9;
        font-size: 12px;
        min-height: 20px;
    }
    QPushButton:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #30363d, stop:1 #252a33);
        border-color: #8b949e;
    }
    QPushButton:pressed {
        background: #0d1117;
        border-color: #6e7681;
    }
    QPushButton:disabled {
        color: #484f58;
        background: #161b22;
        border-color: #21262d;
    }

    /* === 主操作按钮 — 强调色 === */
    QPushButton#loginBtn, QPushButton#sendBtn {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #da3633, stop:1 #b62324);
        border-color: #f85149;
        color: #fff;
        font-weight: bold;
    }
    QPushButton#loginBtn:hover, QPushButton#sendBtn:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #f85149, stop:1 #da3633);
    }
    QPushButton#loginBtn:pressed, QPushButton#sendBtn:pressed {
        background: #b62324;
    }

    /* === 登录成功按钮 — 绿色 === */
    QPushButton#logoutBtn {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #238636, stop:1 #1a6b2a);
        border-color: #3fb950;
        color: #fff;
        font-weight: bold;
    }
    QPushButton#logoutBtn:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #3fb950, stop:1 #238636);
    }

    /* === 危险按钮 — 中断/撤回 === */
    QPushButton#stopBtn, QPushButton#recallBtn {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #21262d, stop:1 #1a1e25);
        border-color: #f85149;
        color: #f85149;
    }
    QPushButton#stopBtn:hover, QPushButton#recallBtn:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #3d1f1f, stop:1 #2d1515);
        border-color: #ff7b72;
    }

    /* === 快捷登录按钮 === */
    QPushButton[cssClass="quickLogin"] {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #1c2541, stop:1 #16213e);
        border: 1px solid #3b5998;
        border-radius: 8px;
        color: #a8c0f0;
        font-weight: bold;
        font-size: 13px;
        text-align: left;
        padding: 10px 14px;
    }
    QPushButton[cssClass="quickLogin"]:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #2a3d6e, stop:1 #1c2e54);
        border-color: #5b7fc0;
        color: #c8d8ff;
    }

    /* === 输入框 === */
    QTextEdit, QPlainTextEdit {
        border: 1px solid #21262d;
        border-radius: 6px;
        background: #0d1117;
        color: #c9d1d9;
        padding: 10px;
        selection-background: #264f78;
    }
    QTextEdit:focus, QPlainTextEdit:focus {
        border-color: #58a6ff;
    }

    /* === 树形控件 === */
    QTreeWidget {
        border: 1px solid #21262d;
        border-radius: 6px;
        background: #0d1117;
        alternate-background-color: #161b22;
        outline: none;
        padding: 4px;
    }
    QTreeWidget::item {
        padding: 3px 6px;
        border-radius: 3px;
    }
    QTreeWidget::item:selected {
        background: #1f6feb;
        color: #fff;
    }
    QTreeWidget::item:hover:!selected {
        background: #1a2535;
    }
    QHeaderView::section {
        background: #161b22;
        border: none;
        border-bottom: 1px solid #21262d;
        padding: 6px 10px;
        font-weight: bold;
        color: #8b949e;
        font-size: 11px;
        text-transform: uppercase;
    }

    /* === 进度条 === */
    QProgressBar {
        border: none;
        border-radius: 4px;
        background: #21262d;
        height: 6px;
        text-align: center;
        font-size: 10px;
        color: #8b949e;
    }
    QProgressBar::chunk {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #da3633, stop:1 #f0883e);
        border-radius: 4px;
    }

    /* === 分割条 === */
    QSplitter::handle {
        background: #21262d;
        width: 2px;
    }

    /* === 状态栏 === */
    QStatusBar {
        background: #161b22;
        border-top: 1px solid #21262d;
        color: #8b949e;
        padding: 2px 8px;
        font-size: 12px;
    }

    /* === 滚动条 === */
    QScrollBar:vertical {
        background: transparent;
        width: 8px;
        margin: 2px;
    }
    QScrollBar::handle:vertical {
        background: #30363d;
        border-radius: 4px;
        min-height: 30px;
    }
    QScrollBar::handle:vertical:hover {
        background: #484f58;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
    }
    QScrollBar:horizontal {
        background: transparent;
        height: 8px;
        margin: 2px;
    }
    QScrollBar::handle:horizontal {
        background: #30363d;
        border-radius: 4px;
        min-width: 30px;
    }
    QScrollBar::handle:horizontal:hover {
        background: #484f58;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0;
    }

    /* === 标签 === */
    QLabel {
        background: transparent;
        color: #8b949e;
        border: none;
    }

    /* === 菜单栏 === */
    QMenuBar {
        background: #161b22;
        border-bottom: 1px solid #21262d;
        padding: 2px;
        color: #c9d1d9;
    }
    QMenuBar::item {
        padding: 4px 12px;
        border-radius: 4px;
    }
    QMenuBar::item:selected {
        background: #21262d;
    }
    QMenu {
        background: #161b22;
        border: 1px solid #30363d;
        border-radius: 6px;
        padding: 4px;
    }
    QMenu::item {
        padding: 6px 28px 6px 16px;
        border-radius: 4px;
    }
    QMenu::item:selected {
        background: #1f6feb;
    }
    QMenu::separator {
        height: 1px;
        background: #21262d;
        margin: 4px 8px;
    }

    /* === 提示框 === */
    QToolTip {
        background: #21262d;
        border: 1px solid #30363d;
        border-radius: 4px;
        padding: 4px 8px;
        color: #e6edf3;
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
        self._dark_mode = True  # 默认深色，与 _THEME 一致

        self.setWindowTitle("东方Project一键宣发姬")
        self.resize(1100, 720)
        self.setStyleSheet(self._THEME)

        self._build_menu()
        self._build_ui()
        self._build_statusbar()
        self._connect_state_signals()
        self._connect_ui_signals()

        self._append_log("[系统] 🔮 东方Project一键宣发姬 已就绪")

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
        self._theme_action = settings_menu.addAction("☀ 切换亮色主题", self._on_toggle_theme)

        help_menu = mb.addMenu("帮助(&H)")
        help_menu.addAction("关于...", self._on_about)

    # ================================================================
    # 主布局
    # ================================================================
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        splitter = QSplitter(Qt.Orientation.Horizontal, central)

        # === 左侧面板 ===
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(8)

        # -- 登录区 --
        login_group = QGroupBox("🔐 QQ登录")
        login_layout = QVBoxLayout(login_group)
        login_layout.setSpacing(8)

        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setMinimumSize(200, 200)
        self.qr_label.setStyleSheet(
            "border: 2px dashed #8c959f; border-radius: 12px;"
            "font-size: 14px; background: transparent;"
        )
        self.qr_label.setText("🔮\n请点击下方按钮\n启动NapCat并扫码")

        self.login_status_label = QLabel("状态: 未登录")
        self.login_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.login_status_label.setStyleSheet("font-size: 12px; background: transparent;")

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.login_btn = QPushButton("🚀 启动NapCat并扫码")
        self.login_btn.setObjectName("loginBtn")
        self.logout_btn = QPushButton("断开连接")
        self.logout_btn.setObjectName("logoutBtn")
        self.logout_btn.setEnabled(False)
        btn_row.addWidget(self.login_btn)
        btn_row.addWidget(self.logout_btn)

        # 快速登录账号按钮
        self.quick_login_group = QGroupBox("⚡ 快速登录（免扫码）")
        self.quick_login_group.setVisible(False)
        self.quick_login_layout = QVBoxLayout(self.quick_login_group)
        self.quick_login_layout.setSpacing(6)
        self.quick_login_label = QLabel("检测到以下已缓存账号，点击即可登录：")
        self.quick_login_label.setWordWrap(True)
        self.quick_login_label.setStyleSheet("font-size: 12px; background: transparent;")
        self.quick_login_layout.addWidget(self.quick_login_label)
        self.quick_login_btns_layout = QVBoxLayout()
        self.quick_login_btns_layout.setSpacing(4)
        self.quick_login_layout.addLayout(self.quick_login_btns_layout)

        login_layout.addWidget(self.qr_label)
        login_layout.addWidget(self.login_status_label)
        login_layout.addLayout(btn_row)
        login_layout.addWidget(self.quick_login_group)
        left_layout.addWidget(login_group)

        # -- 群列表区 --
        group_group = QGroupBox("📋 群列表")
        group_layout = QVBoxLayout(group_group)
        group_layout.setSpacing(6)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.select_all_btn = QPushButton("全选")
        self.deselect_all_btn = QPushButton("取消全选")
        self.refresh_groups_btn = QPushButton("🔄 刷新交集")
        toolbar.addWidget(self.select_all_btn)
        toolbar.addWidget(self.deselect_all_btn)
        toolbar.addWidget(self.refresh_groups_btn)
        self.group_tree = QTreeWidget()
        self.group_tree.setHeaderLabels(["分类 / 群名称", "群号"])
        self.group_tree.setColumnWidth(0, 240)
        self.group_tree.setAlternatingRowColors(True)
        self.group_selection_label = QLabel("已选: 0 / 0 群（登录后可刷新交集）")
        self.group_selection_label.setStyleSheet("font-size: 12px; background: transparent;")
        group_layout.addLayout(toolbar)
        group_layout.addWidget(self.group_tree)
        group_layout.addWidget(self.group_selection_label)
        left_layout.addWidget(group_group)

        splitter.addWidget(left)

        # === 右侧面板 ===
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        # -- 消息编辑区 --
        msg_group = QGroupBox("✏️ 消息编辑")
        msg_layout = QVBoxLayout(msg_group)
        msg_layout.setSpacing(6)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.insert_image_btn = QPushButton("🖼️ 插入图片")
        self.preview_btn = QPushButton("预览")
        self.clear_msg_btn = QPushButton("清空")
        self.char_count_label = QLabel("字数: 0")
        self.char_count_label.setStyleSheet("font-size: 12px; background: transparent;")
        toolbar.addWidget(self.insert_image_btn)
        toolbar.addWidget(self.preview_btn)
        toolbar.addWidget(self.clear_msg_btn)
        toolbar.addStretch()
        toolbar.addWidget(self.char_count_label)
        self.message_edit = QTextEdit()
        self.message_edit.setPlaceholderText("在此输入要群发的消息内容...")
        self.message_edit.setMaximumHeight(180)
        msg_layout.addLayout(toolbar)
        msg_layout.addWidget(self.message_edit)
        right_layout.addWidget(msg_group)

        # -- 发送控制区 --
        send_group = QGroupBox("📤 发送控制")
        send_layout = QVBoxLayout(send_group)
        send_layout.setSpacing(6)
        info_row = QHBoxLayout()
        self.target_label = QLabel("目标群: 0")
        self.target_label.setStyleSheet("font-weight: bold; font-size: 13px; background: transparent;")
        self.interval_label = QLabel(
            f"间隔 {self._config_mgr.config.send_interval}s "
            f"| 每{self._config_mgr.config.batch_pause_every}个停"
            f"{self._config_mgr.config.batch_pause_seconds}s"
        )
        self.interval_label.setStyleSheet("font-size: 12px; background: transparent;")
        info_row.addWidget(self.target_label)
        info_row.addStretch()
        info_row.addWidget(self.interval_label)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.recall_btn = QPushButton("◀ 撤回上次")
        self.recall_btn.setObjectName("recallBtn")
        self.send_btn = QPushButton("▶ 开始发送")
        self.send_btn.setObjectName("sendBtn")
        self.stop_btn = QPushButton("■ 中断")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setEnabled(False)
        btn_row.addWidget(self.recall_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.send_btn)
        btn_row.addWidget(self.stop_btn)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        send_layout.addLayout(info_row)
        send_layout.addLayout(btn_row)
        send_layout.addWidget(self.progress_bar)
        right_layout.addWidget(send_group)

        # -- 日志区 --
        log_group = QGroupBox("📜 发送日志")
        log_layout = QVBoxLayout(log_group)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.log_view.setMaximumWidth(600)
        log_layout.addWidget(self.log_view)
        right_layout.addWidget(log_group)

        splitter.addWidget(right)
        splitter.setSizes([340, 740])

        main_layout = QHBoxLayout(central)
        main_layout.addWidget(splitter)

    # ================================================================
    # 状态栏
    # ================================================================
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
        st.send_started.connect(self._on_send_started)
        st.send_progress.connect(self._on_send_progress)
        st.send_completed.connect(self._on_send_completed)
        st.send_interrupted.connect(self._on_send_interrupted)

    def _on_qr_image_ready(self, path: str):
        """NapCat 生成了 QR 码图片，直接显示在界面上"""
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                220, 220,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.qr_label.setPixmap(scaled)
            self.qr_label.setStyleSheet(
                "background: #fff; border: 2px solid #3fb950; border-radius: 12px;"
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
        self._append_log(f"[NapCat] {clean}")

    def _on_napcat_status(self, status: str):
        self._append_log(f"[NapCat] {status}")
        if "QQ已启动" in status:
            self.qr_label.setText("请在弹出的\nQQ窗口中\n扫码登录")
            self.qr_label.setStyleSheet(
                "border: 2px solid #3fb950; border-radius: 12px;"
                "font-size: 16px; font-weight: bold; background: transparent;"
            )
        elif "OneBot 已就绪" in status:
            self.qr_label.setText("✅ OneBot\n已就绪")
            self.qr_label.setStyleSheet(
                "border: 2px solid #3fb950; border-radius: 12px;"
                "font-size: 18px; font-weight: bold; background: transparent;"
            )
        elif "正在启动" in status:
            self.qr_label.setText("正在启动\nNapCat...")
            self.qr_label.setStyleSheet(
                "border: 2px solid #d2991d; border-radius: 12px;"
                "font-size: 14px; background: transparent;"
            )
        elif "已退出" in status:
            self.qr_label.setText("NapCat\n已退出")
            self.qr_label.setStyleSheet(
                "border: 2px dashed #8c959f; border-radius: 12px;"
                "font-size: 14px; background: transparent;"
            )

    def _on_login_status_changed(self, online: bool, info: str):
        """登录状态变化"""
        if online:
            self.login_status_label.setText("状态: ✅ 在线")
            self.status_online.setText("\U0001f7e2 在线")
            self.status_qq.setText(f"QQ: {info}")
            self.login_btn.setEnabled(False)
            self.logout_btn.setEnabled(True)
            self.quick_login_group.setVisible(False)
            self._append_log(f"[登录] 登录成功! {info}")
            # 登录成功后自动获取群列表并求交集
            self._auto_refresh_intersection()
            # 检测是否有未完成的发送会话（断点续传）
            self._check_breakpoint_resume()
        else:
            self.login_status_label.setText(f"状态: ❌ {info}")
            self.status_online.setText("⚪ 离线")
            self.status_qq.setText("QQ: -")
            self.login_btn.setEnabled(True)
            self.logout_btn.setEnabled(False)
            self._append_log(f"[登录] 登录失败: {info}")

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
        self.send_btn.clicked.connect(self._on_send_clicked)
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        self.recall_btn.clicked.connect(self._on_recall_clicked)
        self.message_edit.textChanged.connect(self._on_message_changed)
        self.refresh_groups_btn.clicked.connect(self._auto_refresh_intersection)
        self.select_all_btn.clicked.connect(self._on_select_all)
        self.deselect_all_btn.clicked.connect(self._on_deselect_all)
        self.group_tree.itemChanged.connect(self._on_tree_item_changed)
        self.group_tree.itemPressed.connect(self._on_tree_item_pressed)
        self.group_tree.itemClicked.connect(self._on_tree_item_clicked)
        self.clear_msg_btn.clicked.connect(lambda: self.message_edit.clear())
        self.preview_btn.clicked.connect(self._on_preview)

    # ---- 登录 ----
    def _on_login_clicked(self):
        """一键登录：自动查找/下载NapCat → 启动 → 等扫码"""
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
        """NapCat 准备就绪，启动（扫码模式，检测到缓存账号后显示快登按钮）"""
        self._config_mgr.config.napcat_path = napcat_root
        self._config_mgr.save()
        self._append_log(f"[登录] NapCat 路径: {napcat_root}")

        self._napcat = NapCatManager(napcat_root)
        if self._napcat.start():  # 扫码模式，让 NapCat 输出缓存账号
            self.login_status_label.setText("状态: NapCat 已启动，等待扫码...")
            self._login_retry_count = 0
            self._login_retry_max = 60
            self._login_poll_active = True
            self._start_login_poll()
        else:
            self.login_status_label.setText("状态: 启动失败")
            self.login_btn.setEnabled(True)
            self._append_log("[错误] NapCat 启动失败")

    def _start_login_poll(self):
        """启动登录轮询：每 2 秒调一次 get_login_info，直到成功"""
        if not getattr(self, "_login_poll_active", True):
            return
        if not self._napcat or not self._napcat.is_running():
            return

        class LoginCheckWorker(QThread):
            login_result = pyqtSignal(bool, str)

            def run(self_):
                try:
                    client = OneBotHTTPClient(timeout=5.0)
                    info = client.get_login_info()
                    uid = str(info.get("user_id", ""))
                    nickname = info.get("nickname", "")
                    label = f"{nickname} ({uid})" if nickname else uid
                    self_.login_result.emit(True, label)
                except Exception as e:
                    self_.login_result.emit(False, str(e))

        self._login_checker = LoginCheckWorker()
        self._login_checker.login_result.connect(self._on_login_poll_result)
        self._login_checker.start()

    def _on_login_poll_result(self, ok: bool, info: str):
        if not getattr(self, "_login_poll_active", True):
            return
        if ok:
            self._login_poll_active = False
            self._state.login_status_changed.emit(True, info)
            return

        self._login_retry_count += 1
        if self._login_retry_count < self._login_retry_max:
            if self._login_retry_count <= 5 or self._login_retry_count % 10 == 0:
                self._append_log(f"[登录] 等待中... ({self._login_retry_count}/{self._login_retry_max})")
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(2000, self._start_login_poll)
        else:
            self._append_log(f"[登录] 超时：{self._login_retry_max}次尝试后仍未连接")
            self.login_btn.setEnabled(True)

    def _on_quick_login_accounts(self, accounts: list):
        """检测到快速登录账号，显示账号选择按钮"""
        # 清空旧按钮
        while self.quick_login_btns_layout.count():
            child = self.quick_login_btns_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        for qq, nickname in accounts:
            btn = QPushButton(f"⚡ {nickname} ({qq})")
            btn.setProperty("qq", qq)
            btn.setProperty("cssClass", "quickLogin")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(self._on_quick_login_btn_clicked)
            self.quick_login_btns_layout.addWidget(btn)

        self.quick_login_group.setVisible(True)
        self._append_log(f"[登录] 检测到 {len(accounts)} 个缓存账号，可免扫码快速登录")

    def _on_quick_login_btn_clicked(self):
        """快速登录按钮点击 — 通过 sender().property('qq') 获取QQ号"""
        btn = self.sender()
        if btn:
            qq = btn.property("qq")
            if qq:
                self._do_quick_login(qq)

    def _do_quick_login(self, qq: str):
        """执行快速登录：停止当前NapCat，用 -q 参数重启"""
        self._append_log(f"[登录] 使用账号 {qq} 快速登录...")
        self.quick_login_group.setVisible(False)
        self.login_status_label.setText(f"状态: 正在以 {qq} 快速登录...")
        # 停掉旧的轮询链
        self._login_poll_active = False

        # 停止当前 NapCat
        if self._napcat:
            self._napcat.stop()

        # 等进程完全退出后再重启（给 taskkill 足够清理时间）
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(3000, lambda: self._restart_with_quick_login(qq))

    def _restart_with_quick_login(self, qq: str):
        """用 -q 参数重启 NapCat"""
        napcat_root = self._config_mgr.config.napcat_path
        if not napcat_root:
            self._append_log("[错误] NapCat 路径未配置")
            self.login_btn.setEnabled(True)
            return

        self._config_mgr.config.last_self_id = qq
        self._config_mgr.save()

        self._napcat = NapCatManager(napcat_root)
        if self._napcat.start(qq=qq):
            self.login_status_label.setText(f"状态: 正在快速登录 {qq}...")
            self._login_retry_count = 0
            self._login_retry_max = 60
            self._login_poll_active = True
            self._start_login_poll()
        else:
            self.login_status_label.setText("状态: 快登启动失败")
            self.login_btn.setEnabled(True)

    def _on_login_busy_detected(self, qq: str):
        """账号已在别处登录 — 停止轮询并恢复按钮"""
        msg = f"账号 {qq} 已在别处登录，请尝试其他账号或退出其他设备上的QQ" if qq else \
              "当前账号已在别处登录，无法重复登录"
        self._append_log(f"[登录] ⚠ {msg}")
        self.login_status_label.setText(f"状态: 账号{qq}已在别处登录" if qq else "状态: 当前账号已在别处登录")
        self._login_poll_active = False
        self.login_btn.setEnabled(True)
        # 快登失败：重新显示按钮让用户选其他账号
        if self.quick_login_btns_layout.count() > 0:
            self.quick_login_group.setVisible(True)

    def _on_setup_failed(self, error: str):
        self.login_status_label.setText(f"状态: {error}")
        self.login_btn.setEnabled(True)
        self._append_log(f"[错误] {error}")

    def _on_logout_clicked(self):
        self._login_poll_active = False
        if self._napcat:
            self._napcat.stop()
            self._napcat = None
        self._onebot = None
        self._joined_groups.clear()
        self._intersection.clear()
        self.qr_label.clear()
        self.qr_label.setText("🔮\n请点击下方按钮\n启动NapCat并扫码")
        self.qr_label.setStyleSheet(
            "border: 2px dashed #8c959f; border-radius: 12px;"
            "font-size: 14px; background: transparent;"
        )
        self.login_status_label.setText("状态: 未登录")
        self.status_online.setText("⚪ 离线")
        self.status_qq.setText("QQ: -")
        self.status_last_send.setText("上次发送: -")
        self.login_btn.setEnabled(True)
        self.logout_btn.setEnabled(False)
        self.quick_login_group.setVisible(False)
        self._csv_records.clear()
        self.group_tree.clear()
        self.group_selection_label.setText("已选: 0 / 0 群（登录后可刷新交集）")
        self._append_log("[登录] 已断开连接")

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

        class IntersectionWorker(QThread):
            result_ready = pyqtSignal(set)
            error_msg = pyqtSignal(str)

            def run(self):
                try:
                    client = OneBotHTTPClient()
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
                QTreeWidgetItem(["暂无交集群", "请先登录并加载CSV"])
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
        PARENT_FLAGS = LEAF_FLAGS | Qt.ItemFlag.ItemIsAutoTristate

        self._updating_checkboxes = True
        for root in roots:
            item = QTreeWidgetItem([root.label, ""])
            item.setFlags(PARENT_FLAGS)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            item.setData(0, Qt.ItemDataRole.UserRole, "")
            self.group_tree.addTopLevelItem(item)
            for sub in root.children:
                sub_item = QTreeWidgetItem([sub.label, ""])
                sub_item.setFlags(PARENT_FLAGS)
                sub_item.setCheckState(0, Qt.CheckState.Unchecked)
                sub_item.setData(0, Qt.ItemDataRole.UserRole, "")
                item.addChild(sub_item)
                for leaf in sub.children:
                    gid = leaf.group.group_id if leaf.group else ""
                    name = leaf.group.group_name if leaf.group else leaf.label
                    leaf_item = QTreeWidgetItem([name, gid])
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

    def _propagate_check_state(self, parent: QTreeWidgetItem, state):
        """递归设置所有子节点的勾选状态"""
        for i in range(parent.childCount()):
            child = parent.child(i)
            child.setCheckState(0, state)
            if child.childCount() > 0:
                self._propagate_check_state(child, state)

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
        """统计已选中的叶子群数量"""
        count = self._count_checked_leaves(self.group_tree.invisibleRootItem())
        total = len(self._intersection)
        self._state.selection_changed.emit(count)
        self.group_selection_label.setText(f"已选: {count} / {total} 群")
        self.target_label.setText(f"目标群: {count}")

    def _count_checked_leaves(self, parent: QTreeWidgetItem) -> int:
        """递归统计已勾选的叶子节点数"""
        total = 0
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.childCount() == 0:
                # 叶子节点
                if child.checkState(0) == Qt.CheckState.Checked:
                    total += 1
            else:
                total += self._count_checked_leaves(child)
        return total

    def _on_select_all(self):
        """全选所有群"""
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
        """递归设置所有节点（含父节点）的勾选状态"""
        for i in range(parent.childCount()):
            child = parent.child(i)
            child.setCheckState(0, state)
            if child.childCount() > 0:
                self._set_all_check_state(child, state)

    # ---- 发送 ----
    def _on_send_clicked(self):
        """开始群发：收集选中群 → 确认 → 启动 SendWorker"""
        text = self.message_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请输入要发送的消息内容")
            return

        # 收集选中的叶子群
        targets = self._collect_checked_targets()
        if not targets:
            QMessageBox.warning(self, "提示", "请先在群列表中勾选要发送的群")
            return

        total = len(targets)
        # 计算预计耗时
        cfg = self._config_mgr.config
        est_seconds = total * (cfg.send_interval + cfg.send_interval_jitter / 2)
        est_seconds += (total // cfg.batch_pause_every) * cfg.batch_pause_seconds if cfg.batch_pause_every else 0
        est_str = f"{int(est_seconds // 60)}分{int(est_seconds % 60)}秒" if est_seconds >= 60 else f"{int(est_seconds)}秒"

        reply = QMessageBox.question(
            self, "确认发送",
            f"即将向 {total} 个群发送消息：\n\n"
            f"「{text[:80]}{'...' if len(text) > 80 else ''}」\n\n"
            f"预计耗时: {est_str}\n\n"
            f"确定开始发送？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # 构建消息
        from touhou_promoter.core.message_builder import build_message
        message = text  # 纯文本直接用字符串

        self._send_btn_enabled(False)
        self._append_log(f"[发送] 开始向 {total} 个群发送消息...")

        self._send_worker = SendWorker(
            message=message,
            targets=targets,
        )
        self._send_worker.start()

    def _on_stop_clicked(self):
        """中断发送"""
        if self._send_worker and self._send_worker.isRunning():
            reply = QMessageBox.question(
                self, "确认中断",
                "确定要中断当前发送吗？\n已发送的消息不会被撤回，未发送的群可以下次继续。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._send_worker.stop()
            self._append_log("[发送] 正在中断...")
        elif self._recall_worker and self._recall_worker.isRunning():
            self._recall_worker.stop()
            self._append_log("[撤回] 正在中断...")

    def _on_recall_clicked(self):
        """撤回上次发送的消息"""
        if not self._last_sent_ids:
            QMessageBox.information(self, "提示", "没有可撤回的消息（上次发送为空或应用已重启）")
            return

        total = len(self._last_sent_ids)
        reply = QMessageBox.question(
            self, "确认撤回",
            f"将撤回上次发送到 {total} 个群的消息。\n\n确定撤回？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
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

    def _on_send_progress(self, current: int, total: int, group_name: str, status: str):
        """发送/撤回进度更新"""
        self.progress_bar.setValue(current)
        self.progress_bar.setMaximum(total)

        if status == "sending":
            self._append_log(f"[发送] → {group_name} ...")
        elif status == "ok":
            self._append_log(f"[发送] ✓ {group_name} — 成功")
        elif status.startswith("fail:"):
            reason = status[5:]
            self._append_log(f"[发送] ✗ {group_name} — {reason}")
        elif status == "pausing":
            self._append_log(f"[发送] ⏸ {group_name}")
        elif status.startswith("recall:ok"):
            self._append_log(f"[撤回] ✓ 群{group_name} — 已撤回")
        elif status.startswith("recall:fail:"):
            reason = status[11:]
            self._append_log(f"[撤回] ✗ 群{group_name} — {reason}")

    def _on_send_completed(self, success: int, failed: int):
        """发送/撤回完成"""
        self._send_btn_enabled(True)
        self.progress_bar.setValue(self.progress_bar.maximum())
        self._append_log(f"[发送] 完成! 成功: {success}, 失败: {failed}")

        if self._send_worker and hasattr(self._send_worker, "_engine") and self._send_worker._engine:
            self._last_sent_ids = dict(self._send_worker._engine._sent_message_ids)

        self.status_last_send.setText(
            f"上次发送: {datetime.now().strftime('%H:%M')} ({success}成功/{failed}失败)"
        )
        self._send_worker = None
        self._recall_worker = None

    def _on_send_interrupted(self, sent: int):
        """发送被中断"""
        self._send_btn_enabled(True)
        self.progress_bar.setValue(0)
        self._append_log(f"[发送] 已中断，已发送 {sent} 条消息（未发送的群可在断点恢复后继续）")

        if self._send_worker and hasattr(self._send_worker, "_engine") and self._send_worker._engine:
            self._last_sent_ids = dict(self._send_worker._engine._sent_message_ids)

        self.status_last_send.setText(
            f"上次发送: {datetime.now().strftime('%H:%M')} (中断, 已发{sent})"
        )
        self._send_worker = None

    def _send_btn_enabled(self, enabled: bool):
        """设置发送相关按钮状态"""
        self.send_btn.setEnabled(enabled)
        self.stop_btn.setEnabled(not enabled)
        self.recall_btn.setEnabled(enabled)

    def _on_message_changed(self):
        text = self.message_edit.toPlainText()
        self.char_count_label.setText(f"字数: {len(text)}")

    def _on_preview(self):
        """预览消息内容"""
        text = self.message_edit.toPlainText()
        if not text.strip():
            QMessageBox.information(self, "预览", "消息内容为空")
            return
        target = self.target_label.text()
        QMessageBox.information(
            self, "消息预览",
            f"目标: {target}\n"
            f"字数: {len(text)}\n\n"
            f"{text[:500]}{'...' if len(text) > 500 else ''}"
        )

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
        self._append_log("[设置] 发送参数设置将在后续版本完善")

    def _on_toggle_theme(self):
        """切换深色/亮色主题"""
        self._dark_mode = not self._dark_mode
        if self._dark_mode:
            self.setStyleSheet(self._THEME)
            self._theme_action.setText("☀ 切换亮色主题")
            self._append_log("[设置] 已切换为深色主题")
        else:
            self.setStyleSheet(self._THEME_LIGHT)
            self._theme_action.setText("🌙 切换深色主题")
            self._append_log("[设置] 已切换为亮色主题")

    def _on_about(self):
        QMessageBox.about(
            self, "关于",
            "东方Project一键宣发姬 v1.0\n\n"
            "基于NapCat + OneBot v11的QQ群发工具\n"
            "开发: 没灵感的鼓 & AI助手\n\n"
            "东方人人人网站: https://thtripeople.ren/"
        )

    # ================================================================
    # 工具
    # ================================================================
    def _append_log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"[{ts}] {msg}")
