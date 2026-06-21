"""工作线程 — QThread 封装群发和撤回操作

将 ForwardingEngine 的同步调用包装到 QThread 中，
通过 pyqtSignal 与 UI 主线程通信。
"""

from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from touhou_promoter.core.onebot_client import OneBotHTTPClient
from touhou_promoter.core.forwarding_engine import ForwardingEngine
from touhou_promoter.state.app_state import AppState
from touhou_promoter.state.config_manager import ConfigManager
from touhou_promoter.state.send_state import SendSession, SendStateManager


class SendWorker(QThread):
    """群发工作线程"""

    # 直接连接到 AppState 信号（跨线程安全）
    # 复用 app_state.send_started / send_progress / send_completed / send_interrupted

    def __init__(
        self,
        message: str | list,
        targets: list[tuple[str, str]],  # [(group_id, group_name), ...]
        start_index: int = 0,
        client: OneBotHTTPClient | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._message = message
        self._targets = targets
        self._start_index = start_index
        self._client = client or OneBotHTTPClient()
        self._config = ConfigManager().config

        self._engine: Optional[ForwardingEngine] = None
        self._state = AppState.instance()
        self._state_mgr = SendStateManager()

    def run(self):
        self._engine = ForwardingEngine(
            client=self._client,
            interval=self._config.send_interval,
            jitter=self._config.send_interval_jitter,
            batch_pause_every=self._config.batch_pause_every,
            batch_pause_seconds=self._config.batch_pause_seconds,
        )

        # 绑定引擎回调 → AppState 信号
        self._engine.on_progress = self._on_progress
        self._engine.on_finished = self._on_finished
        self._engine.on_pause = self._on_pause
        self._engine.on_stopped = self._on_stopped

        self._state.send_started.emit(len(self._targets))

        # 创建/更新会话状态
        session = SendSession(
            session_id=str(int(__import__("time").time())),
            message=self._message if isinstance(self._message, str) else str(self._message),
            target_group_ids=[gid for gid, _ in self._targets],
            total_count=len(self._targets),
        )
        self._state_mgr.save(session)

        self._engine.send(self._message, self._targets, self._start_index)

    def stop(self):
        """请求中断发送"""
        if self._engine:
            self._engine.stop()

    # ── 回调 ──

    def _on_progress(self, current: int, total: int, group_name: str, status: str):
        # 持久化每个成功的发送
        if status == "ok" and self._engine:
            state_mgr = SendStateManager()
            session = state_mgr.load()
            if session is None:
                session = SendSession(
                    session_id=str(int(__import__("time").time())),
                    message=self._message if isinstance(self._message, str) else str(self._message),
                    target_group_ids=[gid for gid, _ in self._targets],
                    total_count=total,
                )
            # 更新进度
            session.sent_index = current
            session.success_count = self._engine._sent_message_ids.__len__() if hasattr(self._engine, "_sent_message_ids") else current
            session.results[group_name] = {"status": "ok", "message_id": self._engine._sent_message_ids.get(group_name, "")}
            state_mgr.save(session)

        self._state.send_progress.emit(current, total, group_name, status)

    def _on_pause(self, paused_count: int, pause_seconds: int):
        self._state.send_progress.emit(
            paused_count, len(self._targets),
            f"批量暂停 {pause_seconds}秒...", "pausing"
        )

    def _on_finished(self, success: int, failed: int, sent_ids: dict[str, str]):
        # 清除持久化状态
        SendStateManager().clear()
        self._state.send_completed.emit(success, failed)

    def _on_stopped(self, sent: int, total: int, sent_ids: dict[str, str]):
        # 保存断点状态
        state_mgr = SendStateManager()
        session = state_mgr.load()
        if session:
            session.sent_index = self._start_index + sent
            session.success_count = sent
            state_mgr.save(session)
        self._state.send_interrupted.emit(sent)


class RecallWorker(QThread):
    """批量撤回工作线程"""

    def __init__(
        self,
        sent_message_ids: dict[str, str],  # group_id → message_id
        client: OneBotHTTPClient | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._sent_ids = sent_message_ids
        self._client = client or OneBotHTTPClient()
        self._config = ConfigManager().config
        self._engine: Optional[ForwardingEngine] = None
        self._state = AppState.instance()

    def run(self):
        self._engine = ForwardingEngine(
            client=self._client,
            interval=self._config.recall_interval,
        )

        total = len(self._sent_ids)
        self._state.send_started.emit(total)

        def progress_cb(current: int, total: int, group_id: str, status: str):
            self._state.send_progress.emit(current, total, f"群{group_id}", f"recall:{status}")

        success, failed = self._engine.recall(
            self._sent_ids,
            interval=self._config.recall_interval,
            progress_cb=progress_cb,
        )
        self._state.send_completed.emit(success, failed)

    def stop(self):
        if self._engine:
            self._engine.stop()
