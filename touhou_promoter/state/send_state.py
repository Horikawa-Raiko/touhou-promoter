"""发送会话持久化 — 断点续传支持

发送过程中每完成一个群就保存进度到 JSON。
应用重启后检测到未完成的会话，提示用户是否继续。
"""

import json
import os
from dataclasses import dataclass, field, asdict


@dataclass
class SendSession:
    """一次群发会话的完整状态"""
    session_id: str = ""                       # 会话ID（时间戳）
    message: str = ""                          # 发送的消息内容
    target_group_ids: list[str] = field(default_factory=list)  # 目标群号列表
    sent_index: int = 0                        # 已发送到的索引（下一个要发的）
    total_count: int = 0                       # 总目标数
    success_count: int = 0                     # 成功数
    failed_count: int = 0                      # 失败数
    # group_id -> {"message_id": ..., "group_name": ..., "status": "ok"|"fail", "error": ...}
    results: dict[str, dict] = field(default_factory=dict)
    finished: bool = False                     # 是否已完成


class SendStateManager:
    """发送状态持久化管理"""

    DIR: str = os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")), "touhou-promoter"
    )

    def __init__(self):
        os.makedirs(self.DIR, exist_ok=True)
        self._path = os.path.join(self.DIR, "send_state.json")

    def save(self, session: SendSession):
        """保存当前发送会话状态"""
        data = asdict(session)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load(self) -> SendSession | None:
        """加载上次未完成的会话，已完成则返回 None"""
        if not os.path.exists(self._path):
            return None
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, TypeError):
            return None

        session = SendSession(
            session_id=data.get("session_id", ""),
            message=data.get("message", ""),
            target_group_ids=data.get("target_group_ids", []),
            sent_index=data.get("sent_index", 0),
            total_count=data.get("total_count", 0),
            success_count=data.get("success_count", 0),
            failed_count=data.get("failed_count", 0),
            results=data.get("results", {}),
            finished=data.get("finished", False),
        )

        # 已完成的不返回，让调用方清理
        if session.finished or session.sent_index >= session.total_count:
            self.clear()
            return None

        return session

    def clear(self):
        """删除持久化的会话状态"""
        try:
            os.remove(self._path)
        except FileNotFoundError:
            pass

    def has_unfinished(self) -> bool:
        """是否存在未完成的会话"""
        s = self.load()
        return s is not None
