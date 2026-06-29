"""NapCat 子进程生命周期管理

负责:
- 启动/停止 NapCat.exe 子进程
- 监控 stdout 检测 QR 码 URL 和登录状态
- 通过信号通知 GUI 各阶段状态变化
"""

import os
import re
import subprocess
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from touhou_promoter.core.napcat_config import (
    generate_onebot_config,
    find_napcat_executable,
    set_auto_login_account,
)
from touhou_promoter.state.app_state import AppState


def _ensure_load_napcat_js(napcat_dir: str):
    """生成 loadNapCat.js — NapCat 启动所需的 bootstrap 文件"""
    napcat_mjs = os.path.join(napcat_dir, "napcat.mjs")
    if os.path.isfile(napcat_mjs):
        load_js = os.path.join(napcat_dir, "loadNapCat.js")
        mjs_path = napcat_mjs.replace("\\", "/")
        content = f'(async () => {{await import("file:///{mjs_path}")}})()\n'
        try:
            with open(load_js, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            pass


# --- stdout 模式匹配 ---
# 只匹配 OneBot 协议适配器完成初始化的消息，避免把 WebUi 的 URL 误判为 API 就绪
ONEBOT_READY_PATTERN = re.compile(
    r"OneBot11.*(?:初始化完成|适配器.*完成|已加载)|"
    r"\[OneBot11\].*network.*配置加载",
    re.IGNORECASE,
)
LOGIN_SUCCESS_PATTERN = re.compile(
    r"(登录成功|login\s*success|上线|online\s*success)",
    re.IGNORECASE,
)
LOGIN_FAIL_PATTERN = re.compile(
    r"(登录失败|login\s*fail|扫码超时|二维码.*过期|验证失败|账号.*冻结)",
    re.IGNORECASE,
)
LOGIN_BUSY_PATTERN = re.compile(
    r"(已登录|无法重复登录|already\s*login|already\s*online)",
    re.IGNORECASE,
)
QQ_WINDOW_PATTERN = re.compile(
    r"(QQ.*启动|launch.*qq|注入|inject|hook.*ok|boot.*success|启动.*成功)",
    re.IGNORECASE,
)
QR_IMAGE_PATTERN = re.compile(
    r"二维码已保存[到至]?\s*[:：]?\s*(.+)",
    re.IGNORECASE,
)
# 匹配 "可用于快速登录" 之后的账号行，如 "1. 3234089021 射命丸 约沂"
QUICK_LOGIN_HEADER_PATTERN = re.compile(
    r"快速登录|quick\s*login| cached ",
    re.IGNORECASE,
)
QUICK_LOGIN_ACCOUNT_PATTERN = re.compile(
    r"^\s*(\d+)\.\s*(\d{5,15})\s+(.+)",
    re.MULTILINE,
)


class NapCatMonitorThread(QThread):
    """在独立线程中读取 NapCat 子进程 stdout，通过信号通知 GUI"""

    line_received = pyqtSignal(str)          # 原始 stdout 行
    qr_image_ready = pyqtSignal(str)         # QR 码图片路径
    qq_launched = pyqtSignal()               # QQ 已启动（用户可以扫码了）
    login_success = pyqtSignal(str)          # 登录成功 (self_id)
    login_failed = pyqtSignal(str)           # 登录失败原因
    login_busy = pyqtSignal(str)            # 账号已在别处登录 (qq_number)
    quick_login_accounts = pyqtSignal(list)  # [(qq, nickname), ...]
    onebot_ready = pyqtSignal(int, int)      # (http_port, ws_port)
    process_exited = pyqtSignal(int)         # 进程退出码

    def __init__(self, process: subprocess.Popen, parent=None):
        super().__init__(parent)
        self._process = process
        self._stop_flag = False
        self._qq_launched = False
        self._quick_login_detected = False
        self._account_buffer = ""
        self._collecting_accounts = False

    def run(self):
        try:
            for line in iter(self._process.stdout.readline, ""):
                if self._stop_flag:
                    break
                if not line:
                    continue
                line_str = line.strip()
                if not line_str:
                    continue

                self.line_received.emit(line_str)
                self._scan_line(line_str)
        except Exception:
            pass
        finally:
            rc = self._process.poll()
            self.process_exited.emit(rc if rc is not None else -1)

    def _scan_line(self, line: str):
        """扫描 stdout 行中的关键事件"""
        # QQ 启动 / Hook 注入成功
        if not self._qq_launched and QQ_WINDOW_PATTERN.search(line):
            self._qq_launched = True
            self.qq_launched.emit()

        # QR 码图片路径
        m = QR_IMAGE_PATTERN.search(line)
        if m:
            path = m.group(1).strip()
            if os.path.isfile(path):
                self.qr_image_ready.emit(path)

        # 账号已登录,无法重复登录
        m = LOGIN_BUSY_PATTERN.search(line)
        if m:
            # 尝试提取 QQ 号
            qq_match = re.search(r"(\d{5,15})", line)
            busy_qq = qq_match.group(1) if qq_match else ""
            self.login_busy.emit(busy_qq)
            return

        # 登录成功
        if LOGIN_SUCCESS_PATTERN.search(line):
            self.login_success.emit(line)
            return

        # 登录失败
        m = LOGIN_FAIL_PATTERN.search(line)
        if m:
            self.login_failed.emit(line)
            return

        # OneBot 适配器初始化完成
        if ONEBOT_READY_PATTERN.search(line):
            self.onebot_ready.emit(5700, 5701)

        # 快速登录账号列表检测
        self._detect_quick_login_accounts(line)

    def _detect_quick_login_accounts(self, line: str):
        """检测 NapCat 输出的快速登录账号列表"""
        if self._quick_login_detected:
            return

        if QUICK_LOGIN_HEADER_PATTERN.search(line):
            self._collecting_accounts = True
            self._account_buffer = ""
            return

        if self._collecting_accounts:
            # 账号行格式: "1. 3234089021 射命丸 约沂"
            m = re.match(r"^\s*(\d+)\.\s*(\d{5,15})\s+(.+)", line)
            if m:
                qq = m.group(2)
                nickname = m.group(3).strip()
                self._account_buffer += f"{qq}|{nickname}\n"
                return
            # 空行或非账号行 → 收集结束
            if self._account_buffer:
                accounts = []
                for aline in self._account_buffer.strip().split("\n"):
                    parts = aline.split("|", 1)
                    if len(parts) == 2:
                        accounts.append((parts[0], parts[1]))
                if accounts:
                    self._quick_login_detected = True
                    self.quick_login_accounts.emit(accounts)
            self._collecting_accounts = False

    def stop(self):
        self._stop_flag = True


class NapCatManager:
    """NapCat 进程管理器。

    使用方式:
        mgr = NapCatManager(napcat_root)
        mgr.start()          # 启动 NapCat
        mgr.start(qq="1575232594")  # 快速登录
        mgr.stop()           # 停止
        mgr.is_running()     # 是否运行中
    """

    HTTP_PORT = 5700
    WS_PORT = 5701

    def __init__(self, napcat_root: str):
        self._napcat_root = napcat_root
        self._process: Optional[subprocess.Popen] = None
        self._monitor: Optional[NapCatMonitorThread] = None
        self._state = AppState.instance()
        self._intentional_stop = False

        # 连接 monitor 信号到全局 state 信号
        self._monitor_connected = False

    @property
    def napcat_root(self) -> str:
        return self._napcat_root

    def start(self, qq: str = "") -> bool:
        """启动 NapCat 子进程。返回 True 表示进程已启动。

        Args:
            qq: 若不为空，传递给 NapCatWinBootMain.exe 实现免扫码快登
        """
        if self.is_running():
            return True

        # 杀掉上次残留的 QQ.exe，避免 "已登录无法重复登录"
        if os.name == "nt":
            try:
                subprocess.run(
                    'taskkill /F /IM QQ.exe',
                    shell=True, capture_output=True, timeout=5,
                )
            except Exception:
                pass

        launcher = find_napcat_executable(self._napcat_root)
        if not launcher:
            self._state.napcat_status.emit(f"错误: 在 {self._napcat_root} 中找不到 NapCat 启动脚本")
            return False

        # 确保 loadNapCat.js 存在（新版 NapCat v5+ 引导入口）
        napcat_dir = os.path.dirname(launcher)
        _ensure_load_napcat_js(napcat_dir)

        # webui.json autoLoginAccount — 快登时设QQ号，扫码时清空
        set_auto_login_account(self._napcat_root, qq)

        # 生成/更新 OneBot 配置
        generate_onebot_config(
            self._napcat_root,
            qq=qq,
            http_port=self.HTTP_PORT,
            ws_port=self.WS_PORT,
            reuse_existing=True,
        )

        mode = f"自动登录 (QQ:{qq})" if qq else "扫码登录"
        self._state.napcat_status.emit(f"正在启动 NapCat ({mode})...")

        # 只通过 webui.json 的 autoLoginAccount 传递账号信息，
        # 不在命令行上传 qq（等价于 -q 强制快登）。
        # -q 模式下遇到「当前账号已登录」NapCat 会直接退出进程，
        # 而仅靠 autoLoginAccount 时 NapCat 快登失败会降级回二维码模式继续运行。
        cmd = f'"{launcher}"'

        try:
            self._process = subprocess.Popen(
                cmd,
                cwd=napcat_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception as e:
            self._state.napcat_status.emit(f"启动失败: {e}")
            return False

        # 启动 stdout 监控线程
        self._monitor = NapCatMonitorThread(self._process)
        self._connect_monitor()
        self._monitor.start()

        self._state.napcat_status.emit(f"NapCat 已启动 ({mode})")
        return True

    def stop(self):
        """停止 NapCat 并清理整个进程树"""
        self._intentional_stop = True
        if self._monitor:
            self._monitor.stop()
        if self._process:
            try:
                if os.name == "nt":
                    pid = self._process.pid
                    try:
                        subprocess.run(
                            f'taskkill /T /PID {pid}',
                            shell=True, capture_output=True, timeout=5,
                        )
                    except Exception:
                        pass
                    try:
                        self._process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        import threading
                        def force_kill():
                            try:
                                subprocess.run(
                                    f'taskkill /F /T /PID {pid}',
                                    shell=True, capture_output=True, timeout=5,
                                )
                            except Exception:
                                pass
                        def kill_exes():
                            for exe in ("NapCatWinBootMain.exe", "QQ.exe"):
                                try:
                                    subprocess.run(
                                        f"taskkill /F /IM {exe}",
                                        shell=True, capture_output=True, timeout=5,
                                    )
                                except Exception:
                                    pass
                        t1 = threading.Thread(target=force_kill)
                        t2 = threading.Thread(target=kill_exes)
                        t1.start(); t2.start()
                        t1.join(timeout=8); t2.join(timeout=8)
                    # 额外确保 QQ.exe 被杀掉（NapCat 注入的 QQ 可能不在进程树内）
                    try:
                        subprocess.run(
                            'taskkill /F /IM QQ.exe',
                            shell=True, capture_output=True, timeout=5,
                        )
                    except Exception:
                        pass
                else:
                    self._process.terminate()
                    try:
                        self._process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self._process.kill()
                        self._process.wait(timeout=3)
            except Exception:
                pass
            self._process = None
        self._monitor = None
        self._monitor_connected = False
        self._state.napcat_status.emit("NapCat 已停止")

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _connect_monitor(self):
        """连接监控线程信号到全局 state（仅连接一次）"""
        if self._monitor_connected or not self._monitor:
            return
        self._monitor.line_received.connect(self._state.napcat_log_line.emit)
        self._monitor.qr_image_ready.connect(self._state.qr_code_ready.emit)
        self._monitor.qq_launched.connect(self._on_qq_launched)
        self._monitor.login_success.connect(self._on_login_success)
        self._monitor.login_failed.connect(self._on_login_failed)
        self._monitor.login_busy.connect(self._on_login_busy)
        self._monitor.quick_login_accounts.connect(self._on_quick_login_accounts)
        self._monitor.onebot_ready.connect(self._on_onebot_ready)
        self._monitor.process_exited.connect(self._on_process_exited)
        self._monitor_connected = True

    def _on_qq_launched(self):
        self._state.napcat_status.emit("QQ已启动，请在QQ窗口中扫码登录")

    def _on_login_success(self, line: str):
        self._state.napcat_status.emit("登录成功")
        # 不 emit login_status_changed(True) —
        # main_window 的轮询通过 get_login_info() 获取准确的昵称和QQ号

    def _on_login_failed(self, reason: str):
        clean = re.sub(r"\x1b\[[0-9;]*m", "", reason).strip()
        # 截断为简短摘要，避免 stdout 垃圾污染状态栏
        short = clean[:60] + "..." if len(clean) > 60 else clean
        self._state.login_status_changed.emit(False, short)
        self._state.napcat_status.emit(f"登录失败: {short}")

    def _on_login_busy(self, qq: str):
        """账号已在别处登录"""
        msg = f"账号{qq}已在别处登录，无法重复登录" if qq else "当前账号已在别处登录"
        self._state.napcat_status.emit(msg)
        self._state.login_busy_detected.emit(qq)

    def _on_quick_login_accounts(self, accounts: list):
        """检测到快速登录账号列表"""
        self._state.quick_login_accounts.emit(accounts)
        names = ", ".join(f"{qq}" for qq, _ in accounts)
        self._state.napcat_status.emit(f"检测到可用账号: {names}")

    def _on_onebot_ready(self, http_port: int, ws_port: int):
        # 适配器初始化完成后，HTTP 服务器还需要一点时间才真正开始监听
        self._state.napcat_status.emit(
            "OneBot 适配器已初始化，等待 HTTP 服务就绪..."
        )
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(2000, lambda: self._emit_onebot_ready(http_port, ws_port))

    def _emit_onebot_ready(self, http_port: int, ws_port: int):
        self._state.napcat_status.emit(f"OneBot 已就绪 (HTTP:{http_port} WS:{ws_port})")
        self._state.onebot_ready.emit(http_port, ws_port)

    def _on_process_exited(self, rc: int):
        self._process = None
        self._monitor_connected = False
        if self._intentional_stop:
            self._intentional_stop = False
            self._state.napcat_status.emit(f"NapCat 已停止 (code={rc})")
        elif rc is not None and rc > 0:
            # 明确的正数退出码表示进程崩溃
            self._state.napcat_status.emit(f"NapCat 异常退出 (code={rc})")
            self._state.login_status_changed.emit(False, f"NapCat 异常退出 (code={rc})")
        else:
            # rc=0（正常退出）或 rc=None→-1（bat 后台化导致 cmd 先退出，node 可能仍在运行）
            # 不 emit login_status_changed，让 OneBot HTTP 轮询来判断真实状态
            self._state.napcat_status.emit("NapCat 启动器已退出，等待 OneBot 就绪...")
