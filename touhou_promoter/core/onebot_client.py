"""OneBot v11 HTTP + WebSocket 客户端

同步 API 调用（设计在 QThread 中运行），以及 WebSocket 事件监听。
"""

import json
import time
from typing import Any, Callable, Optional

import requests
from websocket import WebSocketApp, WebSocket


class OneBotAPIError(Exception):
    """OneBot API 返回错误"""

    def __init__(self, message: str, retcode: Any = None, raw: Any = None):
        super().__init__(message)
        self.retcode = retcode
        self.raw = raw


class OneBotHTTPClient:
    """OneBot v11 HTTP API 客户端（同步）"""

    def __init__(self, base_url: str = "http://127.0.0.1:5700", timeout: float = 15.0):
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()

    # ---- 基础请求 ----

    def _call(self, action: str, params: dict | None = None) -> Any:
        url = f"{self._base}/{action}"
        payload = params or {}
        try:
            resp = self._session.post(url, json=payload, timeout=self._timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise OneBotAPIError(f"HTTP请求失败: {e}")

        data = resp.json()
        return self._parse_response(data, action)

    def _parse_response(self, data: Any, action: str) -> Any:
        if isinstance(data, dict):
            status = str(data.get("status", "")).lower()
            if status and status not in ("ok", "async"):
                raise OneBotAPIError(
                    f"{action} 返回失败状态: {data.get('wording', status)}",
                    retcode=data.get("retcode"),
                    raw=data,
                )
            retcode = data.get("retcode")
            if isinstance(retcode, int) and retcode != 0:
                raise OneBotAPIError(
                    f"{action} retcode={retcode}: {data.get('wording', '')}",
                    retcode=retcode,
                    raw=data,
                )
            if "data" in data:
                return data["data"]
        return data

    # ---- 账号 ----

    def get_login_info(self) -> dict:
        """获取登录号信息。返回 {'user_id': ..., 'nickname': ...}"""
        return self._call("get_login_info")

    def get_self_id(self) -> str:
        """获取当前登录 QQ 号（纯数字字符串）"""
        info = self.get_login_info()
        return str(info.get("user_id", ""))

    # ---- 群操作 ----

    def get_group_list(self) -> list[dict]:
        """获取机器人加入的群列表"""
        return self._call("get_group_list")

    def get_group_info(self, group_id: str | int, no_cache: bool = False) -> dict:
        """获取群信息"""
        return self._call("get_group_info", {
            "group_id": int(group_id) if str(group_id).isdigit() else group_id,
            "no_cache": no_cache,
        })

    def get_group_member_info(
        self, group_id: str | int, user_id: str | int, no_cache: bool = False
    ) -> dict:
        """获取群成员信息"""
        return self._call("get_group_member_info", {
            "group_id": int(group_id) if str(group_id).isdigit() else group_id,
            "user_id": int(user_id) if str(user_id).isdigit() else user_id,
            "no_cache": no_cache,
        })

    def send_group_msg(
        self, group_id: str | int, message: str | list, auto_escape: bool = False
    ) -> dict:
        """发送群消息。message 可以是 CQ 码字符串或消息段数组。"""
        return self._call("send_group_msg", {
            "group_id": int(group_id) if str(group_id).isdigit() else group_id,
            "message": message,
            "auto_escape": auto_escape,
        })

    def delete_msg(self, message_id: str | int) -> dict:
        """撤回消息"""
        return self._call("delete_msg", {"message_id": int(message_id)})

    def get_msg(self, message_id: str | int) -> dict:
        """获取消息"""
        return self._call("get_msg", {"message_id": int(message_id)})

    # ---- 好友操作 ----

    def send_private_msg(
        self, user_id: str | int, message: str | list, auto_escape: bool = False
    ) -> dict:
        """发送私聊消息"""
        return self._call("send_private_msg", {
            "user_id": int(user_id) if str(user_id).isdigit() else user_id,
            "message": message,
            "auto_escape": auto_escape,
        })


class OneBotWSListener:
    """OneBot v11 WebSocket 事件监听器（在 QThread 中运行）"""

    def __init__(self, ws_url: str = "ws://127.0.0.1:5701"):
        self._url = ws_url
        self._ws: Optional[WebSocketApp] = None
        self._running = False

        # 回调
        self.on_message: Optional[Callable[[dict], None]] = None
        self.on_lifecycle: Optional[Callable[[str, dict], None]] = None
        self.on_group_message: Optional[Callable[[dict], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

    def start(self):
        """启动 WebSocket 连接（阻塞，应在 QThread 中运行）"""
        self._running = True
        self._ws = WebSocketApp(
            self._url,
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
            on_open=self._on_ws_open,
        )
        # 带自动重连
        while self._running:
            try:
                self._ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception:
                if self._running:
                    time.sleep(3)
            if not self._running:
                break

    def stop(self):
        """停止 WebSocket 连接"""
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def _on_ws_open(self, ws: WebSocket):
        pass

    def _on_ws_message(self, ws: WebSocket, message: str):
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return

        if self.on_message:
            self.on_message(data)

        post_type = data.get("post_type", "")
        if post_type == "meta_event":
            meta_type = data.get("meta_event_type", "")
            if meta_type == "lifecycle":
                if self.on_lifecycle:
                    self.on_lifecycle(data.get("sub_type", ""), data)
            elif meta_type == "heartbeat":
                pass  # 忽略心跳
        elif post_type == "message":
            msg_type = data.get("message_type", "")
            if msg_type == "group" and self.on_group_message:
                self.on_group_message(data)

    def _on_ws_error(self, ws: WebSocket, error):
        if self.on_error:
            self.on_error(str(error))

    def _on_ws_close(self, ws: WebSocket, close_status_code, close_msg):
        pass  # 断线由 start() 的循环自动重连
