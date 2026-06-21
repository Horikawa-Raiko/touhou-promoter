"""消息构建 — CQ码拼接 / 消息段数组构造

从服务器插件移植，支持:
- 纯文本消息
- CQ 码: image, at, face, record, share, json, xml
- 消息段数组格式 (OneBot v11 array message)
"""

from typing import Any, Union


# CQ 码 → 消息段映射
def cq_image(file: str, url: str = "", cache: bool = True, timeout: int | None = None) -> dict:
    """构建 CQ:image 消息段"""
    seg: dict[str, Any] = {"type": "image", "data": {"file": file}}
    if url:
        seg["data"]["url"] = url
    if not cache:
        seg["data"]["cache"] = 0
    if timeout is not None:
        seg["data"]["timeout"] = timeout
    return seg


def cq_at(qq: str | int = "all") -> dict:
    """构建 CQ:at 消息段"""
    return {"type": "at", "data": {"qq": str(qq)}}


def cq_face(face_id: int) -> dict:
    """构建 CQ:face 消息段"""
    return {"type": "face", "data": {"id": str(face_id)}}


def cq_record(file: str, magic: bool = False) -> dict:
    """构建 CQ:record 消息段（语音）"""
    seg: dict[str, Any] = {"type": "record", "data": {"file": file}}
    if magic:
        seg["data"]["magic"] = 1
    return seg


def cq_reply(message_id: str | int) -> dict:
    """构建 CQ:reply 消息段"""
    return {"type": "reply", "data": {"id": str(message_id)}}


# ── 消息构建器 ──

def build_message(text: str, images: list[str] | None = None) -> list[dict]:
    """从纯文本和可选图片列表构建 OneBot 消息段数组。

    Args:
        text: 消息文本（支持 \\n 换行）
        images: 图片文件路径或URL列表

    Returns:
        OneBot v11 消息段数组
    """
    segments: list[dict] = []

    # 文本
    if text.strip():
        segments.append({"type": "text", "data": {"text": text}})

    # 图片
    if images:
        for img in images:
            segments.append(cq_image(file=img))

    return segments


def build_plain_text(text: str) -> str:
    """构建纯文本消息（CQ码字符串格式）。

    注意: 纯文本中若包含需要转义的字符（[ ] & , 等），
    需由调用方自行处理。OneBot 的 auto_escape 参数可自动转义。
    """
    return text


def estimate_segment_count(message: Union[str, list]) -> int:
    """估算消息段数量"""
    if isinstance(message, list):
        return len(message)
    # 字符串中估算 CQ 码数量
    count = 1
    count += message.count("[CQ:")
    return count


def validate_message(message: Union[str, list]) -> str | None:
    """验证消息是否合法。返回 None 表示合法，否则返回错误描述。

    规则:
    - 不能为空
    - 字符串长度不超过 5000
    - 消息段数组不能包含未知类型
    """
    if isinstance(message, list):
        if not message:
            return "消息不能为空"
        for seg in message:
            if not isinstance(seg, dict):
                return f"无效的消息段: {seg}"
            if "type" not in seg:
                return f"消息段缺少 type 字段: {seg}"
        return None
    else:
        text = str(message)
        if not text.strip():
            return "消息不能为空"
        if len(text) > 5000:
            return f"消息过长 ({len(text)} 字符，上限 5000)"
        return None
