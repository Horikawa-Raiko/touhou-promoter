"""NapCat 子进程生命周期管理

负责:
- 启动/停止 NapCat.exe 子进程
- 监控 stdout 检测 QR 码 URL 和登录状态
- 通过信号通知 GUI 各阶段状态变化

NapCat 版本兼容性：
- v4.18.9+: napimain.exe <QQ.exe> <napiloader.dll> <nativeLoader.cjs>，显式传参不依赖注册表
- v4.18.6-: 旧版 NapCatWinBootMain，ensure_napcat_ready 会自动升级
"""

import datetime
import os
import re
import subprocess
import threading
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from touhou_promoter.core.napcat_config import (
    ensure_bypass_config,
    generate_onebot_config,
    find_napcat_executable,
    set_auto_login_account,
)
from touhou_promoter.state.app_state import AppState


def _ensure_load_napcat_js(napcat_root: str):
    """生成 loadNapCat.js — NapCat 启动所需的 bootstrap 文件。
    检查根目录和 bootmain/ 两个位置。
    """
    for subdir in ("", "bootmain"):
        base = os.path.join(napcat_root, subdir) if subdir else napcat_root
        napcat_mjs = os.path.join(base, "napcat.mjs")
        if os.path.isfile(napcat_mjs):
            load_js = os.path.join(base, "loadNapCat.js")
            mjs_path = napcat_mjs.replace("\\", "/")
            content = f'(async () => {{await import("file:///{mjs_path}")}})()\n'
            try:
                with open(load_js, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception:
                pass
            return


def _get_qqnt_version(qq_exe: str) -> Optional[str]:
    """读取 QQ.exe 的 FileVersion，返回 "w.x.y.z" 字符串。"""
    import ctypes
    import struct

    try:
        ver_size = ctypes.windll.version.GetFileVersionInfoSizeW(qq_exe, None)
        if not ver_size:
            return None
        buf = ctypes.create_string_buffer(ver_size)
        if not ctypes.windll.version.GetFileVersionInfoW(qq_exe, 0, ver_size, buf):
            return None
        ptr = ctypes.c_void_p()
        ulen = ctypes.c_uint()
        if not ctypes.windll.version.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(ulen)):
            return None
        fixed = struct.unpack_from("8H", ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ushort * 8)).contents)
        return f"{fixed[2]}.{fixed[3]}.{fixed[4]}.{fixed[8]}"
    except Exception:
        return None


def _find_qq_exe_simple() -> Optional[str]:
    """查找 QQ.exe 路径，轻量版。先查注册表 QQNT，再文件系统。"""
    import winreg

    # 注册表：QQNT 自己的 Install 键
    for hive, subkey in (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Tencent\QQNT"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Tencent\QQNT"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Tencent\QQNT"),
    ):
        try:
            with winreg.OpenKey(hive, subkey) as k:
                install, _ = winreg.QueryValueEx(k, "Install")
                qq = os.path.join(install, "QQ.exe")
                if os.path.isfile(qq):
                    return qq
        except OSError:
            pass

    # 文件系统回退
    candidates = [
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Tencent", "QQNT", "QQ.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Tencent", "QQNT", "QQ.exe"),
        "D:/QQ/QQ.exe",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def _pick_launcher(napcat_root: str) -> Optional[str]:
    """选择最佳启动器。

    napimain.exe 优先 — 显式传QQ路径不依赖注册表。
    NapCatWinBootMain.exe 仅作为 fallback（当 napimain 不存在时）。
    两个都不支持命令行快登，QQ 自身缓存登录状态。
    """
    napimain = os.path.join(napcat_root, "napimain.exe")
    winboot = os.path.join(napcat_root, "bootmain", "NapCatWinBootMain.exe")

    if os.path.isfile(napimain):
        return napimain

    if os.path.isfile(winboot):
        return winboot

    return find_napcat_executable(napcat_root)


def _launch_napcat_direct(launcher_exe: str, napcat_root: str, log_cb=None, qq: str = "") -> subprocess.Popen:
    """启动 NapCat — 优先 napimain.exe（显式传QQ路径），回退 NapCatWinBootMain。

    napimain.exe CLI: napimain.exe <QQ.exe绝对路径> <注入DLL绝对路径> <主脚本绝对路径(正斜杠)>
    NapCatWinBootMain.exe CLI (fallback): NapCatWinBootMain.exe [qq]
    """
    import datetime

    def _log(msg):
        if log_cb:
            log_cb(msg)

    qq_exe = _find_qq_exe_simple()
    if not qq_exe:
        raise FileNotFoundError("未找到 QQ.exe — 请确认已安装 QQNT")

    ver = _get_qqnt_version(qq_exe)
    if ver:
        _log(f"QQNT 版本: {ver} ({qq_exe})")

    launcher_name = os.path.basename(launcher_exe).lower()
    env = os.environ.copy()

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    logs_dir = os.path.join(napcat_root, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    stderr_log = os.path.join(logs_dir, f"napcat_stderr_{ts}.log")
    stderr_fp = open(stderr_log, "w", encoding="utf-8", errors="replace")
    _log(f"调试日志: {stderr_log}")

    def _pipe_stderr():
        try:
            for data in iter(process.stderr.readline, ""):
                if data:
                    stderr_fp.write(data)
                    stderr_fp.flush()
        except Exception:
            pass
        finally:
            stderr_fp.close()

    if launcher_name == "napimain.exe":
        # v4.18.9+: 显式传参，不依赖注册表
        inject_dll = os.path.join(napcat_root, "napiloader.dll")
        main_js = os.path.join(napcat_root, "nativeLoader.cjs")
        if not os.path.isfile(inject_dll) or not os.path.isfile(main_js):
            raise FileNotFoundError(
                f"NapCat 安装不完整 — 缺少 napiloader.dll 或 nativeLoader.cjs 在 {napcat_root}"
            )

        # 脚本路径必须用正斜杠
        main_js_fwd = main_js.replace("\\", "/")
        cmd = [launcher_exe, qq_exe, inject_dll, main_js_fwd]
        cwd = napcat_root
        _log(f"启动: napimain.exe (显式QQ路径)")

        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,  # napimain.exe 初始化后等待按键退出，不关 stdin 使其保持存活
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    else:
        # Fallback: NapCatWinBootMain.exe v4.18.9 CLI: NapCatWinBootMain.exe [qq]
        # 设 cwd 到 QQ.exe 所在目录确保回退能找到
        cwd = os.path.dirname(qq_exe)
        cmd = [launcher_exe]
        if qq:
            cmd.append(qq)
        _log(f"启动命令: {' '.join(cmd)} (cwd={cwd})")

        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    threading.Thread(target=_pipe_stderr, daemon=True).start()
    return process


# --- stdout 模式匹配 ---
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
    r"(登录失败|login\s*fail|扫码超时|二维码.*过期|验证失败)",
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
QUICK_LOGIN_HEADER_PATTERN = re.compile(
    r"快速登录|quick\s*login| cached ",
    re.IGNORECASE,
)
QUICK_LOGIN_ACCOUNT_PATTERN = re.compile(
    r"^\s*(\d+)\.\s*(\d{5,15})\s+(.+)",
    re.MULTILINE,
)
KICKED_OFFLINE_PATTERN = re.compile(
    r"(KickedOffLine|下线通知|kicked\s*offline|账号.*已失效|登录.*失效|kick.*off)",
    re.IGNORECASE,
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
    kicked_offline = pyqtSignal()            # 账号被踢下线
    process_exited = pyqtSignal(int)         # 进程退出码

    def __init__(self, process: subprocess.Popen, parent=None, napcat_dir: str = ""):
        super().__init__(parent)
        self._process = process
        self._stop_flag = False
        self._qq_launched = False
        self._quick_login_detected = False
        self._account_buffer = ""
        self._collecting_accounts = False
        self._napcat_dir = napcat_dir

    def run(self):
        try:
            for line in iter(self._process.stdout.readline, ""):
                if self._stop_flag:
                    break
                if not line:
                    break
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
        if not self._qq_launched and QQ_WINDOW_PATTERN.search(line):
            self._qq_launched = True
            self.qq_launched.emit()

        m = QR_IMAGE_PATTERN.search(line)
        if m:
            path = m.group(1).strip()
            if os.path.isfile(path):
                self.qr_image_ready.emit(path)

        m = LOGIN_BUSY_PATTERN.search(line)
        if m:
            qq_match = re.search(r"(\d{5,15})", line)
            busy_qq = qq_match.group(1) if qq_match else ""
            self.login_busy.emit(busy_qq)
            return

        if LOGIN_SUCCESS_PATTERN.search(line):
            self.login_success.emit(line)
            return

        m = LOGIN_FAIL_PATTERN.search(line)
        if m:
            self.login_failed.emit(line)
            return

        if KICKED_OFFLINE_PATTERN.search(line):
            self.kicked_offline.emit()

        if ONEBOT_READY_PATTERN.search(line):
            self.onebot_ready.emit(5700, 5701)

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
            m = re.match(r"^\s*(\d+)\.\s*(\d{5,15})\s+(.+)", line)
            if m:
                qq = m.group(2)
                nickname = m.group(3).strip()
                self._account_buffer += f"{qq}|{nickname}\n"
                return
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
        self._launcher_exited_ok = False  # napimain 正常退出但 QQ 仍在运行

        self._monitor_connected = False

    @property
    def napcat_root(self) -> str:
        return self._napcat_root

    def start(self, qq: str = "") -> bool:
        """启动 NapCat 子进程。返回 True 表示进程已启动。

        Args:
            qq: 若不为空，传递给 NapCatWinBootMain.exe 实现免扫码快登
        """
        def _log(msg):
            self._state.napcat_status.emit(msg)

        if self.is_running():
            return True

        self._launcher_exited_ok = False
        self._intentional_stop = False
        if os.name == "nt":
            try:
                subprocess.run(
                    'taskkill /F /IM QQ.exe',
                    shell=True, capture_output=True, timeout=5,
                )
            except Exception:
                pass

        launcher = _pick_launcher(self._napcat_root)
        if not launcher:
            _log(f"错误: 在 {self._napcat_root} 中找不到 NapCat 启动脚本")
            return False

        is_bat = launcher.lower().endswith(".bat")

        # webui.json autoLoginAccount
        set_auto_login_account(self._napcat_root, qq)

        # 生成/更新 OneBot 配置
        try:
            generate_onebot_config(
                self._napcat_root,
                qq=qq,
                http_port=self.HTTP_PORT,
                ws_port=self.WS_PORT,
                reuse_existing=True,
            )
            ensure_bypass_config(self._napcat_root)
        except Exception:
            pass

        mode = f"自动登录 (QQ:{qq})" if qq else "扫码登录"
        _log(f"正在启动 NapCat ({mode})...")

        _ensure_load_napcat_js(self._napcat_root)

        exe_dir = os.path.dirname(launcher)
        try:
            if is_bat:
                bat_cmd = f'"{launcher}"'
                if qq:
                    bat_cmd += f" {qq}"
                self._process = subprocess.Popen(
                    bat_cmd,
                    cwd=exe_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    shell=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            else:
                self._process = _launch_napcat_direct(launcher, self._napcat_root, log_cb=_log, qq=qq)
        except FileNotFoundError as e:
            _log(f"启动失败: {e}")
            return False
        except Exception as e:
            _log(f"启动失败: {e}")
            return False

        self._monitor = NapCatMonitorThread(self._process, napcat_dir=self._napcat_root)
        self._connect_monitor()
        self._monitor.start()

        _log(f"NapCat 已启动 ({mode}) [PID={self._process.pid}]")
        return True

    def stop(self, kill_qq: bool = True):
        """停止 NapCat 并清理进程树。

        Args:
            kill_qq: 是否同时结束 QQ.exe。关闭软件时传 False 保留 QQ。
        """
        self._intentional_stop = True
        self._launcher_exited_ok = False
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
                            targets = ["napimain.exe", "NapCatWinBootMain.exe"]
                            if kill_qq:
                                targets.append("QQ.exe")
                            for exe in targets:
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
                    if kill_qq:
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
        """launcher 存活，或 napimain 正常退出后 QQ 仍在运行。

        不依赖 _on_process_exited 信号（有竞态），直接 poll 判断。"""
        if self._process is not None:
            rc = self._process.poll()
            if rc is None:
                return True
            # launcher 正常退出（napimain 注完就退），QQ 还在跑
            if rc == 0 and not self._intentional_stop:
                self._launcher_exited_ok = True
        return self._launcher_exited_ok

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
        self._monitor.kicked_offline.connect(self._on_kicked_offline)
        self._monitor.process_exited.connect(self._on_process_exited)
        self._monitor_connected = True

    def _on_qq_launched(self):
        self._state.napcat_status.emit("QQ已启动，请在QQ窗口中扫码登录")

    def _on_login_success(self, line: str):
        self._state.napcat_status.emit("登录成功")

    def _on_login_failed(self, reason: str):
        clean = re.sub(r"\x1b\[[0-9;]*m", "", reason).strip()
        # 不直接展示原始行——可能包含 QQ 界面泄露的任意文字
        self._state.login_status_changed.emit(False, "登录失败")
        self._state.napcat_status.emit("登录失败，请重试扫码")

    def _on_login_busy(self, qq: str):
        """账号已在别处登录"""
        msg = f"账号{qq}已在别处登录，无法重复登录" if qq else "当前账号已在别处登录"
        self._state.napcat_status.emit(msg)
        self._state.login_busy_detected.emit(qq)

    def _on_kicked_offline(self):
        """账号被踢下线"""
        self._state.napcat_status.emit("账号被踢下线，登录已失效")
        self._state.login_status_changed.emit(False, "被踢下线")
        self._state.kicked_offline.emit()

    def _on_quick_login_accounts(self, accounts: list):
        """检测到快速登录账号列表"""
        self._state.quick_login_accounts.emit(accounts)
        names = ", ".join(f"{qq}" for qq, _ in accounts)
        self._state.napcat_status.emit(f"检测到可用账号: {names}")

    def _on_onebot_ready(self, http_port: int, ws_port: int):
        self._state.napcat_status.emit(
            "OneBot 适配器已初始化，等待 HTTP 服务就绪..."
        )
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(2000, lambda: self._emit_onebot_ready(http_port, ws_port))

    def _emit_onebot_ready(self, http_port: int, ws_port: int):
        self._state.napcat_status.emit(f"OneBot 已就绪 (HTTP:{http_port} WS:{ws_port})")
        self._state.onebot_ready.emit(http_port, ws_port)

    def _on_process_exited(self, rc: int):
        was_connected = self._monitor_connected  # 在清零前记住：OneBot 之前是否已就绪
        self._process = None
        self._monitor_connected = False
        if self._intentional_stop:
            self._intentional_stop = False
            self._launcher_exited_ok = False
            self._state.napcat_status.emit(f"NapCat 已停止 (code={rc})")
        elif rc is not None and rc > 0:
            self._launcher_exited_ok = False
            self._state.napcat_status.emit(f"NapCat 异常退出 (code={rc}) — 常见原因: QQ未安装/版本不兼容/被杀毒拦截")
            self._state.login_status_changed.emit(False, f"NapCat 异常退出 (code={rc})")
        elif was_connected:
            # OneBot 之前已就绪，现在进程退出 → QQ 被关掉了 → 立即离线
            self._launcher_exited_ok = False
            self._state.napcat_status.emit("QQ 已退出，连接丢失")
            self._state.login_status_changed.emit(False, "QQ已退出")
        else:
            self._launcher_exited_ok = True  # napimain 注入后正常退出，QQ 仍在运行，等 OneBot 就绪
            self._state.napcat_status.emit("NapCat 启动器已退出，等待 OneBot 就绪...")
            # 15 秒后 OneBot 仍未就绪 → QQ 可能启动失败
            from PyQt6.QtCore import QTimer
            this = self

            def _check_qq_gone():
                if this._monitor_connected or this._process is not None:
                    return
                this._launcher_exited_ok = False
                this._state.napcat_status.emit("QQ 启动失败，连接丢失")
                this._state.login_status_changed.emit(False, "QQ启动失败")

            QTimer.singleShot(15000, _check_qq_gone)
