"""群发引擎 — 逐群发送 / 限速 / 批量暂停 / 断点续传 / 撤回

从服务器插件移植核心发送循环，改为同步 + QThread 模式。

架构:
    ForwardingEngine  → 纯逻辑（无 Qt 依赖）
    SendWorker(QThread) → workers.py 中包装
"""

import time
import random
from typing import Callable, Optional

from touhou_promoter.core.onebot_client import OneBotHTTPClient, OneBotAPIError
from touhou_promoter.core.onebot_adapter import is_likely_offline_error


class ForwardingEngine:
    """群发引擎 — 纯逻辑，通过回调与 UI 通信"""

    def __init__(
        self,
        client: OneBotHTTPClient,
        interval: float = 0.9,
        jitter: float = 0.1,
        batch_pause_every: int = 10,
        batch_pause_seconds: int = 5,
    ):
        self._client = client
        self._interval = interval
        self._jitter = jitter
        self._batch_pause_every = batch_pause_every
        self._batch_pause_seconds = batch_pause_seconds

        # 运行时状态
        self._stop_flag = False
        self._sent_message_ids: dict[str, str] = {}  # group_id → message_id

    # ── 回调 ──

    on_progress: Optional[Callable[[int, int, str, str], None]] = None
    """进度回调: (current_index, total, group_name, status)

    status: 'sending' | 'ok' | 'fail:原因' | 'skip' | 'pausing'
    """

    on_finished: Optional[Callable[[int, int, dict[str, str]], None]] = None
    """完成回调: (success_count, failed_count, sent_message_ids)"""

    on_pause: Optional[Callable[[int, int], None]] = None
    """批量暂停回调: (paused_count, pause_seconds)"""

    on_stopped: Optional[Callable[[int, int, dict[str, str]], None]] = None
    """中断回调: (sent_count, total, sent_message_ids)"""

    # ── 属性 ──

    @property
    def sent_count(self) -> int:
        return len(self._sent_message_ids)

    # ── 发送 ──

    def send(
        self,
        message: str | list,
        targets: list[tuple[str, str]],  # [(group_id, group_name), ...]
        start_index: int = 0,
    ) -> bool:
        """逐群发送消息。

        Args:
            message: OneBot 消息（字符串或消息段数组）
            targets: 目标群列表 [(group_id, group_name), ...]
            start_index: 断点续传起始索引

        Returns:
            True 表示全部成功或部分成功，False 表示被中断
        """
        self._stop_flag = False
        self._sent_message_ids.clear()
        total = len(targets)
        success = 0
        failed = 0

        for i in range(start_index, total):
            if self._stop_flag:
                if self.on_stopped:
                    self.on_stopped(success, total, dict(self._sent_message_ids))
                return False

            group_id, group_name = targets[i]

            # 发送前回调
            if self.on_progress:
                self.on_progress(i + 1, total, group_name, "sending")

            # 调用 API 发送
            try:
                result = self._client.send_group_msg(group_id, message, auto_escape=False)
                msg_id = str(result.get("message_id", ""))
                self._sent_message_ids[group_id] = msg_id
                success += 1
                if self.on_progress:
                    self.on_progress(i + 1, total, group_name, "ok")
            except OneBotAPIError as e:
                failed += 1
                reason = f"API错误: {e}"
                if self.on_progress:
                    self.on_progress(i + 1, total, group_name, f"fail:{reason}")
            except Exception as e:
                failed += 1
                reason = str(e)
                # 判断是否掉线
                if is_likely_offline_error(reason):
                    if self.on_progress:
                        self.on_progress(i + 1, total, group_name, "fail:掉线")
                    if self.on_stopped:
                        self.on_stopped(success, total, dict(self._sent_message_ids))
                    return False
                if self.on_progress:
                    self.on_progress(i + 1, total, group_name, f"fail:{reason}")

            # 间隔 + 抖动
            if i < total - 1 and not self._stop_flag:
                delay = self._interval + random.uniform(0, self._jitter)
                time.sleep(delay)

            # 批量暂停
            batch_num = i - start_index + 1
            if (
                self._batch_pause_every > 0
                and batch_num % self._batch_pause_every == 0
                and i < total - 1
                and not self._stop_flag
            ):
                remaining = total - i - 1
                if self.on_progress:
                    self.on_progress(
                        i + 1, total,
                        f"--- 已发{batch_num}条, 暂停{self._batch_pause_seconds}秒, 剩余{remaining}群 ---",
                        "pausing",
                    )
                if self.on_pause:
                    self.on_pause(batch_num, self._batch_pause_seconds)
                time.sleep(self._batch_pause_seconds)

        # 完成
        if self.on_finished:
            self.on_finished(success, failed, dict(self._sent_message_ids))
        return True

    def stop(self):
        """请求中断发送"""
        self._stop_flag = True

    # ── 撤回 ──

    def recall(
        self,
        sent_message_ids: dict[str, str],  # group_id → message_id
        interval: float = 0.6,
        progress_cb: Optional[Callable[[int, int, str, str], None]] = None,
    ) -> tuple[int, int]:
        """批量撤回已发送的消息。

        Args:
            sent_message_ids: 群号 → 消息ID 映射
            interval: 撤回间隔（秒）
            progress_cb: 进度回调 (current, total, group_id, status)

        Returns:
            (成功数, 失败数)
        """
        self._stop_flag = False
        items = list(sent_message_ids.items())
        total = len(items)
        success = 0
        failed = 0

        for i, (group_id, msg_id) in enumerate(items):
            if self._stop_flag:
                break

            try:
                self._client.delete_msg(msg_id)
                success += 1
                if progress_cb:
                    progress_cb(i + 1, total, group_id, "ok")
            except Exception as e:
                failed += 1
                if progress_cb:
                    progress_cb(i + 1, total, group_id, f"fail:{e}")

            if i < total - 1 and not self._stop_flag:
                time.sleep(interval)

        return success, failed
