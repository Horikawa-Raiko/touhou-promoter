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


def _find_qq_exe(saved_path: str = "") -> tuple:
    """查找 QQ.exe 路径，返回 (路径或None, [调试行列表])。

    搜索策略（逐级降级）：
    0. 用户手动指定的路径（config.json qq_exe_path）
    1. 精确注册表键 (HKLM + HKCU, "QQ" + "QQNT")
    2. 遍历 Uninstall 子键，匹配 DisplayName 含 "QQ" 的项
    3. 搜索常见安装目录（含通配符匹配版本号子目录）
    """
    import winreg
    debug_lines = []

    def _check_exe(path: str) -> bool:
        if os.path.isfile(path):
            debug_lines.append(f"  [搜索] QQ.exe 存在: {path}")
            return True
        return False

    # --- 策略0: 用户手动指定的路径 ---
    if saved_path:
        debug_lines.append(f"  [配置] 检查手动指定的路径: {saved_path}")
        if _check_exe(saved_path):
            return saved_path, debug_lines
        else:
            debug_lines.append(f"  [配置] 路径已失效，回退到自动搜索")

    # --- 策略1: 精确注册表键 ---
    for hive, hive_name in (
        (winreg.HKEY_LOCAL_MACHINE, "HKLM"),
        (winreg.HKEY_CURRENT_USER, "HKCU"),
    ):
        for subkey in (
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQ",
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\QQ",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQNT",
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\QQNT",
        ):
            debug_lines.append(f"  [注册表] 尝试: {hive_name}\\{subkey}")
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    for val_name in ("UninstallString", "DisplayIcon", "InstallLocation"):
                        try:
                            val, _ = winreg.QueryValueEx(key, val_name)
                            debug_lines.append(f"  [注册表] {val_name}={val}")
                            qq_dir = val if val_name == "InstallLocation" else os.path.dirname(val)
                            qq_exe = os.path.join(qq_dir, "QQ.exe")
                            if _check_exe(qq_exe):
                                return qq_exe, debug_lines
                        except OSError:
                            continue
            except OSError:
                debug_lines.append(f"  [注册表] 键不存在")
                continue

    # --- 策略2: 枚举 Uninstall 子键 ---
    debug_lines.append("  [注册表] 枚举 Uninstall 子键搜索 QQ...")
    for hive, hive_name in (
        (winreg.HKEY_LOCAL_MACHINE, "HKLM"),
        (winreg.HKEY_CURRENT_USER, "HKCU"),
    ):
        for uninstall_base in (
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        ):
            try:
                with winreg.OpenKey(hive, uninstall_base) as base:
                    i = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(base, i)
                            i += 1
                        except OSError:
                            break
                        # 不预过滤子键名 — MSI安装的键名是GUID不包含QQ
                        try:
                            with winreg.OpenKey(base, subkey_name) as sk:
                                try:
                                    dn, _ = winreg.QueryValueEx(sk, "DisplayName")
                                except OSError:
                                    continue
                                if "QQ" not in dn and "qq" not in dn.lower() and "腾讯QQ" not in dn:
                                    continue
                                debug_lines.append(f"  [注册表] 匹配: {hive_name}\\...\\{subkey_name} -> {dn}")
                                for val_name in ("UninstallString", "DisplayIcon", "InstallLocation"):
                                    try:
                                        val, _ = winreg.QueryValueEx(sk, val_name)
                                        debug_lines.append(f"  [注册表] {val_name}={val}")
                                        qq_dir = val if val_name == "InstallLocation" else os.path.dirname(val)
                                        qq_exe = os.path.join(qq_dir, "QQ.exe")
                                        if _check_exe(qq_exe):
                                            return qq_exe, debug_lines
                                    except OSError:
                                        continue
                        except OSError:
                            continue

    # --- 策略3: 扫描常见安装目录 ---
    debug_lines.append("  [搜索] 扫描常见安装目录...")

    # 先收集所有候选根目录
    search_roots = set()

    # 每个驱动器的 Program Files (C: D: E: F: G:)
    for drive in ("C:", "D:", "E:", "F:", "G:"):
        search_roots.update([
            rf"{drive}\Program Files\Tencent",
            rf"{drive}\Program Files (x86)\Tencent",
        ])

    # %LOCALAPPDATA% / %APPDATA% / %USERPROFILE%
    search_roots.update([
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tencent"),
        os.path.expandvars(r"%LOCALAPPDATA%\Tencent"),
        os.path.expandvars(r"%APPDATA%\Tencent"),
        os.path.expanduser(r"~\Tencent"),
        os.path.expanduser(r"~\Desktop\Tencent"),
        os.path.expanduser(r"~\Downloads\Tencent"),
    ])

    # 遍历每个根目录，试 QQNT/QQ/TIM 子目录 + 版本号子目录
    for root in sorted(search_roots):
        if not os.path.isdir(root):
            continue
        for sub in ("QQNT", "QQ", "TIM"):
            candidate = os.path.join(root, sub)
            # 先试直接的 QQ.exe
            debug_lines.append(f"  [搜索] 尝试: {candidate}")
            qq_exe = os.path.join(candidate, "QQ.exe")
            if _check_exe(qq_exe):
                return qq_exe, debug_lines
            # QQNT 可能有版本号子目录，如 QQNT\9.9.12\QQ.exe
            if sub == "QQNT":
                try:
                    for item in sorted(os.listdir(candidate), reverse=True):
                        ver_dir = os.path.join(candidate, item)
                        if not os.path.isdir(ver_dir):
                            continue
                        qq_exe = os.path.join(ver_dir, "QQ.exe")
                        if _check_exe(qq_exe):
                            return qq_exe, debug_lines
                except OSError:
                    continue
            # TIM 的 QQ.exe 可能在 Bin 子目录下
            if sub == "TIM":
                bin_exe = os.path.join(candidate, "Bin", "QQ.exe")
                if _check_exe(bin_exe):
                    return qq_exe, debug_lines

    debug_lines.append("  [搜索] 所有策略均未找到 QQ.exe")
    return None, debug_lines


def _launch_napcat_direct(launcher_exe: str, napcat_dir: str, log_cb=None, saved_qq_path: str = "") -> subprocess.Popen:
    """直接启动 NapCatWinBootMain.exe（shell=False，stdout 不会断）。

    复刻 launcher-user.bat 的逻辑：设环境变量、找 QQ.exe、启动。
    """
    def _log(msg):
        if log_cb:
            log_cb(msg)

    _log(f"[调试] 启动器: {launcher_exe}")
    _log(f"[调试] NapCat 目录: {napcat_dir}")

    qq_exe, qq_debug = _find_qq_exe(saved_path=saved_qq_path)
    for line in qq_debug:
        _log(line)

    if not qq_exe:
        raise FileNotFoundError(
            "未找到 QQ.exe，请确认 QQ 已安装（注册表无安装记录）"
        )

    hook_dll = os.path.join(napcat_dir, "NapCatWinBootHook.dll")
    _log(f"[调试] Hook DLL: {hook_dll} (存在={os.path.isfile(hook_dll)})")
    if not os.path.isfile(hook_dll):
        raise FileNotFoundError(f"未找到 Hook DLL: {hook_dll}")

    env = os.environ.copy()
    env["NAPCAT_PATCH_PACKAGE"] = os.path.join(napcat_dir, "qqnt.json")
    env["NAPCAT_LOAD_PATH"] = os.path.join(napcat_dir, "loadNapCat.js")
    env["NAPCAT_INJECT_PATH"] = hook_dll
    env["NAPCAT_LAUNCHER_PATH"] = launcher_exe
    env["NAPCAT_MAIN_PATH"] = os.path.join(napcat_dir, "napcat.mjs")

    _log(f"[调试] NAPCAT_PATCH_PACKAGE={env['NAPCAT_PATCH_PACKAGE']}")
    _log(f"[调试] NAPCAT_LOAD_PATH={env['NAPCAT_LOAD_PATH']}")
    _log(f"[调试] 命令行: {launcher_exe} \"{qq_exe}\" \"{hook_dll}\"")

    return subprocess.Popen(
        [launcher_exe, qq_exe, hook_dll],
        cwd=napcat_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


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

    def __init__(self, process: subprocess.Popen, parent=None, napcat_dir: str = ""):
        super().__init__(parent)
        self._process = process
        self._stop_flag = False
        self._qq_launched = False
        self._quick_login_detected = False
        self._account_buffer = ""
        self._collecting_accounts = False
        self._napcat_dir = napcat_dir
        self._lines_received = 0

    def run(self):
        self.line_received.emit(f"[调试-监控] stdout 监控线程启动 (PID={self._process.pid})")
        try:
            for line in iter(self._process.stdout.readline, ""):
                if self._stop_flag:
                    self.line_received.emit("[调试-监控] 收到停止信号")
                    break
                if not line:
                    self.line_received.emit("[调试-监控] stdout EOF (管道关闭)")
                    break
                self._lines_received += 1
                line_str = line.strip()
                if not line_str:
                    continue

                if self._lines_received <= 3:
                    # 首批输出行做诊断用
                    self.line_received.emit(f"[调试-监控] 首批输出#{self._lines_received}: {line_str[:120]}")
                self.line_received.emit(line_str)
                self._scan_line(line_str)
        except Exception as e:
            self.line_received.emit(f"[调试-监控] stdout 读取异常: {e}")
            import traceback
            self.line_received.emit(f"[调试-监控] 堆栈: {traceback.format_exc()}")
        finally:
            rc = self._process.poll()
            self.line_received.emit(
                f"[调试-监控] 监控线程结束, 共收到 {self._lines_received} 行, "
                f"进程poll={rc} (None=还在跑)"
            )
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

    def start(self, qq: str = "", saved_qq_path: str = "") -> bool:
        """启动 NapCat 子进程。返回 True 表示进程已启动。

        Args:
            qq: 若不为空，传递给 NapCatWinBootMain.exe 实现免扫码快登
            saved_qq_path: 手动指定的 QQ.exe 路径（来自 config.json qq_exe_path）
        """
        def _log(msg):
            self._state.napcat_status.emit(msg)

        if self.is_running():
            return True

        # 杀掉上次残留的 QQ.exe，避免 "已登录无法重复登录"
        _log("[调试] 步骤1: 清理残留 QQ.exe")
        if os.name == "nt":
            try:
                r = subprocess.run(
                    'taskkill /F /IM QQ.exe',
                    shell=True, capture_output=True, timeout=5,
                )
                _log(f"[调试] taskkill QQ.exe: returncode={r.returncode}")
            except Exception as e:
                _log(f"[调试] taskkill QQ.exe 异常: {e}")

        _log(f"[调试] 步骤2: 查找启动器 (napcat_root={self._napcat_root})")
        launcher = find_napcat_executable(self._napcat_root)
        if not launcher:
            _log(f"错误: 在 {self._napcat_root} 中找不到 NapCat 启动脚本")

            # 额外诊断：列出目录内容
            for sub in ("napcat", ""):
                d = os.path.join(self._napcat_root, sub)
                if os.path.isdir(d):
                    try:
                        items = os.listdir(d)[:20]
                        _log(f"[调试] {d} 内容: {items}")
                    except Exception:
                        pass

            return False

        is_bat = launcher.lower().endswith(".bat")
        _log(f"[调试] 启动器: {launcher} (类型={'bat' if is_bat else 'exe'})")

        # webui.json autoLoginAccount — 快登时设QQ号，扫码时清空
        _log(f"[调试] 步骤3: 设置 autoLoginAccount={qq or '(清空-扫码模式)'}")
        set_auto_login_account(self._napcat_root, qq)

        # 生成/更新 OneBot 配置
        _log(f"[调试] 步骤4: 生成 OneBot 配置 (HTTP:{self.HTTP_PORT}, WS:{self.WS_PORT})")
        try:
            cfg_path = generate_onebot_config(
                self._napcat_root,
                qq=qq,
                http_port=self.HTTP_PORT,
                ws_port=self.WS_PORT,
                reuse_existing=True,
            )
            _log(f"[调试] OneBot 配置路径: {cfg_path}")
        except Exception as e:
            _log(f"[调试] OneBot 配置生成异常: {e}")

        mode = f"自动登录 (QQ:{qq})" if qq else "扫码登录"
        _log(f"正在启动 NapCat ({mode})...")

        napcat_dir = os.path.dirname(launcher)
        _log(f"[调试] 步骤5: NapCat 工作目录={napcat_dir}")

        # 检查关键文件
        for fn in ("napcat.mjs", "NapCatWinBootHook.dll", "qqnt.json"):
            fp = os.path.join(napcat_dir, fn)
            _log(f"[调试]   关键文件 {fn}: {'存在' if os.path.isfile(fp) else '缺失!'}")

        # 确保 loadNapCat.js 存在（v5+ 引导入口）
        _ensure_load_napcat_js(napcat_dir)
        ljs = os.path.join(napcat_dir, "loadNapCat.js")
        _log(f"[调试]   loadNapCat.js: {'存在' if os.path.isfile(ljs) else '缺失!'}")

        _log(f"[调试] 步骤6: 启动子进程 (is_bat={is_bat})")

        try:
            if is_bat:
                _log(f"[调试] 用 shell=True 启动 bat: {launcher}")
                self._process = subprocess.Popen(
                    f'"{launcher}"',
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
            else:
                # 直接启动 exe — stdout 不断，可正确跟踪进程
                self._process = _launch_napcat_direct(launcher, napcat_dir, log_cb=_log, saved_qq_path=saved_qq_path)
            _log(f"[调试] 子进程已启动, PID={self._process.pid}")
        except FileNotFoundError as e:
            _log(f"[调试] FileNotFoundError: {e}")
            _log(f"启动失败: {e}")
            return False
        except Exception as e:
            _log(f"[调试] 启动异常 ({type(e).__name__}): {e}")
            _log(f"启动失败: {e}")
            return False

        # 启动 stdout 监控线程
        _log("[调试] 步骤7: 启动 stdout 监控线程")
        self._monitor = NapCatMonitorThread(self._process, napcat_dir=napcat_dir)
        self._connect_monitor()
        self._monitor.start()

        _log(f"NapCat 已启动 ({mode}) [PID={self._process.pid}]")
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
        self._state.napcat_status.emit(
            f"[调试] 进程退出事件: rc={rc}, intentional_stop={self._intentional_stop}, "
            f"process_is_None={self._process is None}"
        )
        self._process = None
        self._monitor_connected = False
        if self._intentional_stop:
            self._intentional_stop = False
            self._state.napcat_status.emit(f"NapCat 已停止 (code={rc})")
        elif rc is not None and rc > 0:
            # 明确的正数退出码 = 真崩溃
            self._state.napcat_status.emit(f"NapCat 异常退出 (code={rc}) — 常见原因: QQ未安装/版本不兼容/被杀毒拦截")
            self._state.login_status_changed.emit(False, f"NapCat 异常退出 (code={rc})")
        else:
            # rc=0（正常退出）或 rc=None→-1（bat后台化cmd先死，node可能还在跑）
            # 不 emit login_status_changed，让 HTTP 轮询判断真实状态
            self._state.napcat_status.emit("NapCat 启动器已退出，等待 OneBot 就绪...")
