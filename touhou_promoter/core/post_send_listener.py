"""发送后监听器 — 发送完成后监听Bot被@和关键词回复

- 使用独立 WebSocket 连接
- 过滤纯@/无实质内容的噪音消息
- 命中消息注入 ListenerPanel 实时展示
- 支持中断/撤回时停止监听
- 短时间内多次发送只监听最后一条

"""

import json
import time
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from touhou_promoter.core.onebot_client import OneBotWSListener


def _segments_to_cq(message: list) -> str:
    """将 OneBot 消息段数组转为 CQ 码字符串"""
    parts = []
    for seg in message:
        t = seg.get("type", "")
        d = seg.get("data", {})
        if t == "text":
            parts.append(d.get("text", ""))
        elif t == "image":
            file_path = d.get("file", "")
            url = d.get("url", "")
            if file_path:
                parts.append(f"[CQ:image,file={file_path}]")
            elif url:
                parts.append(f"[CQ:image,url={url}]")
        elif t == "at":
            qq = d.get("qq", "all")
            parts.append(f"[CQ:at,qq={qq}]")
        elif t == "face":
            parts.append(f"[CQ:face,id={d.get('id', '')}]")
        elif t == "reply":
            parts.append(f"[CQ:reply,id={d.get('id', '')}]")
        else:
            parts.append(f"[CQ:{t}]")
    return "".join(parts)


def _has_meaningful_text(raw_message: str) -> bool:
    """检查消息除去 CQ 码后是否有实质文本内容（>=1个字母或数字）。

    过滤纯 @ / 纯 CQ 码的噪音消息。
    """
    import re
    import unicodedata

    stripped = re.sub(r"\[CQ:[^\]]+\]", "", raw_message)
    count = 0
    for ch in stripped:
        cat = unicodedata.category(ch)
        # L* = 各类字母（含CJK汉字/日文假名）, Nd = 十进制数字
        if cat.startswith("L") or cat == "Nd":
            count += 1
    return count >= 1


class PostSendListener(QThread):
    """发送后监听指定的时长，收集目标群内对Bot的提及和关键词回复。

    使用独立的 WebSocket 连接，不干扰主 WebSocket 生命周期。
    """

    hit_detected = pyqtSignal(str, str, str, str, int, str, str)
    """(group_id, group_name, sender_nick, raw_message, elapsed, message_id, sender_user_id)"""

    ws_error = pyqtSignal(str)
    """WebSocket 连接错误"""

    KEYWORDS = ["加群", "进群", "宣发", "推广", "东方", "车万"]

    def __init__(
        self,
        target_group_ids: set[str],
        duration_seconds: int = 1200,
        ws_url: str = "ws://127.0.0.1:5700",
        self_id: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._target_gids = set(str(g) for g in target_group_ids)
        self._duration = duration_seconds
        self._ws_url = ws_url
        self._self_id = str(self_id)
        self._hits: list[tuple[str, str, str, str, int]] = []
        self._listener: Optional[OneBotWSListener] = None
        self._start_ts = 0.0

    def run(self):
        self._start_ts = time.time()
        _error_count = 0

        def on_msg(data: dict):
            elapsed = time.time() - self._start_ts
            if elapsed > self._duration:
                if self._listener:
                    self._listener.stop()
                return

            group_id = str(data.get("group_id", ""))
            if group_id not in self._target_gids:
                return

            raw_message = data.get("raw_message", "") or data.get("message", "")
            if isinstance(raw_message, list):
                raw_message = _segments_to_cq(raw_message)

            sender = data.get("sender", {})
            sender_nick = (
                sender.get("nickname")
                or sender.get("card")
                or str(sender.get("user_id", ""))
            )
            sender_user_id = str(sender.get("user_id", ""))

            message_id = str(data.get("message_id", ""))

            at_bot = f"[CQ:at,qq={self._self_id}]" in raw_message
            is_reply = "[CQ:reply" in raw_message

            msg_lower = raw_message.lower()
            keyword_match = any(kw in msg_lower for kw in self.KEYWORDS)

            if at_bot or keyword_match or is_reply:
                if not is_reply and at_bot and not keyword_match and not _has_meaningful_text(raw_message):
                    return

                group_name = data.get("group_name", "") or ""
                if not group_name:
                    ginfo = data.get("group_info", {}) or {}
                    group_name = ginfo.get("group_name", "") or ""

                self._hits.append((group_id, group_name, sender_nick, raw_message, int(elapsed), message_id, sender_user_id))
                self.hit_detected.emit(group_id, group_name, sender_nick, raw_message, int(elapsed), message_id, sender_user_id)

        def on_ws_error(err: str):
            nonlocal _error_count
            _error_count += 1
            if _error_count <= 5:
                self.ws_error.emit(err)
            if _error_count == 5:
                self.ws_error.emit("监听器连续连接失败，已停止（请检查QQ是否在线）")
            if _error_count >= 5:
                if self._listener:
                    self._listener.stop()

        self._listener = OneBotWSListener(ws_url=self._ws_url)
        self._listener.on_group_message = on_msg
        self._listener.on_error = on_ws_error

        try:
            self._listener.start()
        except Exception as e:
            self.ws_error.emit(f"监听器启动失败: {e}")

    def stop_listening(self):
        if self._listener:
            self._listener.stop()
        self.quit()
        if not self.wait(2000):
            self.terminate()

    def hits(self) -> list:
        return list(self._hits)
