"""群发引擎 — 逐群发送 / 限速 / 批量暂停 / 断点续传 / 撤回

从服务器插件移植核心发送循环，改为同步 + QThread 模式。

架构:
    ForwardingEngine  → 纯逻辑（无 Qt 依赖）
    SendWorker(QThread) → workers.py 中包装
"""

import os
import re
import time
import random
from typing import Callable, Optional

from touhou_promoter.core.onebot_client import OneBotHTTPClient, OneBotAPIError
from touhou_promoter.core.onebot_adapter import is_likely_offline_error

# 匹配 CQ 码: [CQ:type,key=value,...]
_CQ_RE = re.compile(r"\[CQ:(\w+),([^\]]+)\]")


def _parse_params(params_str: str) -> dict[str, str]:
    """解析 CQ 码参数串 key=value,... 为字典"""
    result = {}
    for part in params_str.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            result[k.strip()] = v.strip()
    return result


def parse_message_to_segments(message: str) -> list[dict]:
    """将包含 CQ 码的文本拆分并转换为 OneBot 消息段数组。

    例如 "你好[CQ:image,file=C:/pic.jpg]世界" →
    [{"type":"text","data":{"text":"你好"}},
     {"type":"image","data":{"file":"file:///C:/pic.jpg"}},
     {"type":"text","data":{"text":"世界"}}]
    """
    segments = []
    pos = 0
    for m in _CQ_RE.finditer(message):
        # CQ 码之前的纯文本
        if m.start() > pos:
            text = message[pos:m.start()]
            if text:
                segments.append({"type": "text", "data": {"text": text}})

        cq_type = m.group(1)
        params = _parse_params(m.group(2))

        if cq_type == "image":
            file_path = params.get("file", "")
            # file:// 协议是 NapCat 识别本地文件的标准方式
            if file_path and not file_path.startswith("http"):
                # 确保路径分隔符统一
                file_path = file_path.replace("\\", "/")
                if not file_path.startswith("file:///"):
                    file_path = "file:///" + file_path
            segments.append({"type": "image", "data": {"file": file_path}})
        elif cq_type == "at":
            qq = params.get("qq", "all")
            segments.append({"type": "at", "data": {"qq": qq}})
        elif cq_type == "face":
            fid = params.get("id", "")
            segments.append({"type": "face", "data": {"id": fid}})
        elif cq_type == "reply":
            mid = params.get("id", "")
            segments.append({"type": "reply", "data": {"id": mid}})
        else:
            # 不支持的类型保留原 CQ 码文本
            segments.append({"type": "text", "data": {"text": m.group(0)}})

        pos = m.end()

    # 尾部剩余文本
    if pos < len(message):
        segments.append({"type": "text", "data": {"text": message[pos:]}})

    return segments if segments else [{"type": "text", "data": {"text": message}}]


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
            # 纯文本字符串 → 解析 CQ 码后拆分为消息段数组
            msg = message
            if isinstance(msg, str):
                msg = parse_message_to_segments(msg)

            try:
                result = self._client.send_group_msg(group_id, msg, auto_escape=False)
                msg_id = str(result.get("message_id", ""))
                self._sent_message_ids[group_id] = msg_id
                success += 1
                if self.on_progress:
                    self.on_progress(i + 1, total, group_name, "ok")
            except OneBotAPIError as e:
                reason = str(e)
                # NapCat NT kernel 超时：消息实际已发出，仅确认回调丢失
                # 重试会导致重复消息，直接计为成功
                if "Timeout" in reason and "NTEvent" in reason:
                    success += 1
                    if self.on_progress:
                        self.on_progress(i + 1, total, group_name, "ok(NT超时)")
                else:
                    failed += 1
                    if self.on_progress:
                        self.on_progress(i + 1, total, group_name, f"fail:API错误: {e}")
            except Exception as e:
                failed += 1
                reason = str(e)
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
