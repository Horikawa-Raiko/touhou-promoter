"""设置对话框 — 发送参数 + OneBot 连接模式"""
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QDoubleSpinBox, QSpinBox, QLineEdit,
    QDialogButtonBox, QGroupBox, QComboBox, QLabel,
)
from PyQt6.QtCore import Qt

from touhou_promoter.state.config_manager import ConfigManager


class SettingsDialog(QDialog):
    """应用设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(480)
        self.setModal(True)
        self._config_mgr = ConfigManager()
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # -- OneBot 连接 --
        conn_group = QGroupBox("OneBot 连接")
        conn_form = QFormLayout(conn_group)

        self._onebot_mode = QComboBox()
        self._onebot_mode.addItem("程序管理 NapCat 进程 (Windows 推荐)", "managed")
        self._onebot_mode.addItem("连接外部 OneBot 服务 (Mac/Linux — 暂未支持)", "external")
        self._onebot_mode.currentIndexChanged.connect(self._on_mode_changed)
        conn_form.addRow("连接模式:", self._onebot_mode)

        self._onebot_url = QLineEdit()
        self._onebot_url.setPlaceholderText("http://127.0.0.1:5700")
        self._onebot_url.setToolTip("外部 OneBot v11 HTTP API 地址，仅「外部模式」下生效")
        conn_form.addRow("API 地址:", self._onebot_url)

        layout.addWidget(conn_group)

        # -- 云同步 --
        cloud_group = QGroupBox("云端同步")
        cloud_form = QFormLayout(cloud_group)

        self._update_server = QLineEdit()
        self._update_server.setPlaceholderText("https://thpromoter.dismused-beat.cloud")
        self._update_server.setToolTip("更新服务器地址，用于自动同步群列表和提交新群")
        cloud_form.addRow("服务器:", self._update_server)

        layout.addWidget(cloud_group)

        # -- 发送参数 --
        send_group = QGroupBox("发送参数")
        form = QFormLayout(send_group)

        self._send_interval = QDoubleSpinBox()
        self._send_interval.setRange(0.1, 60.0)
        self._send_interval.setSingleStep(0.1)
        self._send_interval.setDecimals(1)
        self._send_interval.setSuffix(" 秒")
        self._send_interval.setToolTip("每条消息发送的间隔时间")
        form.addRow("发送间隔:", self._send_interval)

        self._send_jitter = QDoubleSpinBox()
        self._send_jitter.setRange(0.0, 10.0)
        self._send_jitter.setSingleStep(0.05)
        self._send_jitter.setDecimals(2)
        self._send_jitter.setSuffix(" 秒")
        self._send_jitter.setToolTip("在间隔上随机增加的抖动范围（防风控）")
        form.addRow("间隔抖动:", self._send_jitter)

        self._batch_every = QSpinBox()
        self._batch_every.setRange(0, 200)
        self._batch_every.setSuffix(" 个群")
        self._batch_every.setSpecialValueText("不暂停")
        self._batch_every.setToolTip("每发送N个群后暂停一次，0=不暂停")
        form.addRow("批量暂停间隔:", self._batch_every)

        self._batch_seconds = QSpinBox()
        self._batch_seconds.setRange(0, 600)
        self._batch_seconds.setSuffix(" 秒")
        self._batch_seconds.setToolTip("批量暂停时的等待秒数")
        form.addRow("批量暂停时长:", self._batch_seconds)

        self._recall_interval = QDoubleSpinBox()
        self._recall_interval.setRange(0.1, 30.0)
        self._recall_interval.setSingleStep(0.1)
        self._recall_interval.setDecimals(1)
        self._recall_interval.setSuffix(" 秒")
        self._recall_interval.setToolTip("批量撤回时每条消息的间隔")
        form.addRow("撤回间隔:", self._recall_interval)

        self._listener_expiry = QSpinBox()
        self._listener_expiry.setRange(0, 7200)
        self._listener_expiry.setSingleStep(60)
        self._listener_expiry.setSuffix(" 秒")
        self._listener_expiry.setSpecialValueText("禁用监听")
        self._listener_expiry.setToolTip("发送后继续监听回复的时长，0=禁用")
        form.addRow("发送后监听:", self._listener_expiry)

        layout.addWidget(send_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_mode_changed(self):
        external = self._onebot_mode.currentData() == "external"
        self._onebot_url.setEnabled(external)

    # ── 加载/保存 ──

    def _load(self):
        c = self._config_mgr.config
        mode = getattr(c, "onebot_mode", "managed")
        idx = self._onebot_mode.findData(mode)
        if idx >= 0:
            self._onebot_mode.setCurrentIndex(idx)
        self._onebot_url.setText(getattr(c, "onebot_http_url", "http://127.0.0.1:5700"))
        self._onebot_url.setEnabled(mode == "external")

        self._update_server.setText(getattr(c, "update_server", "https://thpromoter.dismused-beat.cloud"))

        self._send_interval.setValue(c.send_interval)
        self._send_jitter.setValue(c.send_interval_jitter)
        self._batch_every.setValue(c.batch_pause_every)
        self._batch_seconds.setValue(c.batch_pause_seconds)
        self._recall_interval.setValue(c.recall_interval)
        self._listener_expiry.setValue(c.listener_expiry_seconds)

    def _save_and_accept(self):
        c = self._config_mgr.config
        c.onebot_mode = self._onebot_mode.currentData()
        c.onebot_http_url = self._onebot_url.text().strip() or "http://127.0.0.1:5700"
        c.update_server = self._update_server.text().strip() or "https://thpromoter.dismused-beat.cloud"
        c.send_interval = self._send_interval.value()
        c.send_interval_jitter = self._send_jitter.value()
        c.batch_pause_every = self._batch_every.value()
        c.batch_pause_seconds = self._batch_seconds.value()
        c.recall_interval = self._recall_interval.value()
        c.listener_expiry_seconds = self._listener_expiry.value()

        self._config_mgr.save()
        self.accept()
