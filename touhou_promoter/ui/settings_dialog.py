"""设置对话框 — 发送参数 + LLM配置"""
from PyQt6.QtWidgets import (
    QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QDoubleSpinBox, QSpinBox, QLineEdit, QPushButton,
    QDialogButtonBox, QGroupBox, QLabel, QFileDialog,
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

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_send_tab(), "📤 发送参数")
        self._tabs.addTab(self._build_llm_tab(), "🤖 LLM配置")
        layout.addWidget(self._tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── 发送参数 ──

    def _build_send_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        form = QFormLayout()

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

        layout.addLayout(form)
        layout.addStretch()
        return w

    # ── LLM配置 ──

    def _build_llm_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        local_group = QGroupBox("本地模型 (llama-cpp-python)")
        local_form = QFormLayout(local_group)

        self._local_model_path = QLineEdit()
        self._local_model_path.setPlaceholderText("留空则使用默认模型路径 (自动下载)")
        self._local_model_path.setToolTip(
            "GGUF格式的模型文件路径，推荐 Qwen2.5-0.5B-Instruct Q4_K_M (~400MB)"
        )
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_model)
        path_row = QHBoxLayout()
        path_row.addWidget(self._local_model_path)
        path_row.addWidget(browse_btn)
        local_form.addRow("模型路径:", path_row)

        self._local_n_ctx = QSpinBox()
        self._local_n_ctx.setRange(256, 8192)
        self._local_n_ctx.setValue(2048)
        self._local_n_ctx.setToolTip("上下文窗口大小（越大越吃内存）")
        local_form.addRow("上下文长度:", self._local_n_ctx)

        self._local_n_threads = QSpinBox()
        self._local_n_threads.setRange(1, 32)
        self._local_n_threads.setValue(4)
        self._local_n_threads.setToolTip("推理线程数（建议设为CPU核心数的一半）")
        local_form.addRow("推理线程:", self._local_n_threads)

        layout.addWidget(local_group)

        cloud_group = QGroupBox("云端API (OpenAI兼容)")
        cloud_form = QFormLayout(cloud_group)

        self._cloud_endpoint = QLineEdit()
        self._cloud_endpoint.setPlaceholderText(
            "https://api.openai.com/v1/chat/completions"
        )
        self._cloud_endpoint.setToolTip(
            "OpenAI兼容的API端点，支持 deepseek/通义千问/硅基流动等"
        )
        cloud_form.addRow("API端点:", self._cloud_endpoint)

        self._cloud_api_key = QLineEdit()
        self._cloud_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._cloud_api_key.setPlaceholderText("sk-...")
        cloud_form.addRow("API Key:", self._cloud_api_key)

        self._cloud_model = QLineEdit()
        self._cloud_model.setPlaceholderText("deepseek-chat / qwen-turbo / gpt-4o-mini")
        self._cloud_model.setToolTip("模型名称，按各家API文档填写")
        cloud_form.addRow("模型名:", self._cloud_model)

        self._cloud_max_tokens = QSpinBox()
        self._cloud_max_tokens.setRange(16, 4096)
        self._cloud_max_tokens.setValue(256)
        self._cloud_max_tokens.setToolTip("单次回答的最大token数（加群答案一般很短）")
        cloud_form.addRow("最大Token:", self._cloud_max_tokens)

        layout.addWidget(cloud_group)
        layout.addStretch()
        return w

    # ── 加载/保存 ──

    def _load(self):
        c = self._config_mgr.config
        self._send_interval.setValue(c.send_interval)
        self._send_jitter.setValue(c.send_interval_jitter)
        self._batch_every.setValue(c.batch_pause_every)
        self._batch_seconds.setValue(c.batch_pause_seconds)
        self._recall_interval.setValue(c.recall_interval)
        self._listener_expiry.setValue(c.listener_expiry_seconds)

        self._local_model_path.setText(getattr(c, "local_model_path", ""))
        self._local_n_ctx.setValue(getattr(c, "local_n_ctx", 2048))
        self._local_n_threads.setValue(getattr(c, "local_n_threads", 4))

        self._cloud_endpoint.setText(getattr(c, "cloud_endpoint", ""))
        self._cloud_api_key.setText(getattr(c, "cloud_api_key", ""))
        self._cloud_model.setText(getattr(c, "cloud_model", ""))
        self._cloud_max_tokens.setValue(getattr(c, "cloud_max_tokens", 256))

    def _save_and_accept(self):
        c = self._config_mgr.config
        c.send_interval = self._send_interval.value()
        c.send_interval_jitter = self._send_jitter.value()
        c.batch_pause_every = self._batch_every.value()
        c.batch_pause_seconds = self._batch_seconds.value()
        c.recall_interval = self._recall_interval.value()
        c.listener_expiry_seconds = self._listener_expiry.value()

        # 扩展配置字段（config_manager 的 AppConfig 会在 _load 时忽略未知字段，
        # 但我们需要把这些字段加到 AppConfig 里）
        # 这里用 setattr 兼容，后续需要在 AppConfig 里加字段
        c.local_model_path = self._local_model_path.text().strip()
        c.local_n_ctx = self._local_n_ctx.value()
        c.local_n_threads = self._local_n_threads.value()
        c.cloud_endpoint = self._cloud_endpoint.text().strip()
        c.cloud_api_key = self._cloud_api_key.text().strip()
        c.cloud_model = self._cloud_model.text().strip()
        c.cloud_max_tokens = self._cloud_max_tokens.value()

        self._config_mgr.save()
        self.accept()

    def _browse_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择GGUF模型文件", "",
            "GGUF模型 (*.gguf);;所有文件 (*.*)"
        )
        if path:
            self._local_model_path.setText(path)
