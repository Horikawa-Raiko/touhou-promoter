"""全局状态 — PyQt6信号驱动的事件总线"""
from PyQt6.QtCore import QObject, pyqtSignal


class AppState(QObject):
    """应用级状态，各面板通过信号解耦通信"""

    # --- QQ登录 ---
    login_status_changed = pyqtSignal(bool, str)        # (在线, self_id/错误信息)
    qr_code_ready = pyqtSignal(str)                      # QR码图片路径
    qr_code_expired = pyqtSignal()

    # --- 群列表 ---
    groups_loaded = pyqtSignal(list)                     # List[TreeNode] — CSV加载完成
    group_intersection_ready = pyqtSignal(set)           # Set[str] — bot实际加入的群号集合
    selection_changed = pyqtSignal(int)                  # 已选群数量

    # --- 发送 ---
    send_started = pyqtSignal(int)                       # 目标群总数
    send_progress = pyqtSignal(int, int, str, str)       # (当前序号, 总数, 群名, 状态)
    send_completed = pyqtSignal(int, int)                # (成功数, 失败数)
    send_interrupted = pyqtSignal(int)                   # 中断时已发数量
    send_error = pyqtSignal(str)                         # 全局错误

    # --- 监听 ---
    listener_event = pyqtSignal(str, str, str)           # (群名, 发送者, 消息内容)

    # --- NapCat ---
    napcat_status = pyqtSignal(str)                      # 进程状态文本
    napcat_log_line = pyqtSignal(str)                    # stdout单行
    onebot_ready = pyqtSignal(int, int)                  # (http_port, ws_port)
    quick_login_accounts = pyqtSignal(list)              # [(qq, nickname), ...]
    login_busy_detected = pyqtSignal(str)               # qq_number — 账号在别处登录
    kicked_offline = pyqtSignal()                        # 账号被踢下线

    # 单例
    _instance: "AppState | None" = None

    @classmethod
    def instance(cls) -> "AppState":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
