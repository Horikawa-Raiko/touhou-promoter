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


def _find_qq_exe(saved_path: str = "") -> Optional[str]:
    """查找 QQNT 的 QQ.exe 路径，找不到返回 None。

    搜索策略（逐级降级）：
    0. 用户手动指定的路径
    1. 精确注册表键 (HKLM+HKCU, QQ+QQNT, Uninstall + App Paths)
    2. 遍历 Uninstall 子键，匹配 DisplayName
    3. 扫描常见安装目录
    4. 递归搜索 Tencent 目录
    5. 全盘搜索 QQNT 目录（兜底）

    NapCat 只能注入 QQNT（Electron 架构），旧版 Win32 QQ 不兼容，找到也跳过。
    """
    import ctypes
    import winreg

    def _is_qqnt(exe_path: str) -> bool:
        if "QQNT" in exe_path or "qqnt" in exe_path.lower():
            return True
        exe_dir = os.path.dirname(exe_path)
        for marker in ("misc.bin", "QQNT.dll", "wrapper.node"):
            if os.path.isfile(os.path.join(exe_dir, marker)):
                return True
        # 兜底：通过版本号判断（QQNT build >= 40000，旧版 Win32 QQ build 只有几百）
        ver = _get_qqnt_version(exe_path)
        if ver and ver["build"] >= 40000:
            return True
        return False

    def _check_exe(path: str) -> bool:
        return os.path.isfile(path)

    def _accept_exe(path: str) -> Optional[str]:
        if _is_qqnt(path):
            return path
        return None

    def _regval_to_qq_dir(val: str, val_name: str) -> str:
        if val_name == "InstallLocation":
            return val
        clean = val.split(",")[0].strip().strip('"')
        return os.path.dirname(clean)

    def _find_in_dir(qq_dir: str) -> Optional[str]:
        """在 qq_dir 及其下一级子目录中查找 QQNT 的 QQ.exe"""
        if not os.path.isdir(qq_dir):
            return None
        qq_exe = os.path.join(qq_dir, "QQ.exe")
        if _check_exe(qq_exe):
            result = _accept_exe(qq_exe)
            if result:
                return result
        # QQNT 版本号子目录 (如 QQNT/9.9.18/QQ.exe)
        if "QQNT" in qq_dir or "qqnt" in qq_dir.lower():
            try:
                for item in sorted(os.listdir(qq_dir), reverse=True):
                    sub = os.path.join(qq_dir, item)
                    if os.path.isdir(sub):
                        qq_exe = os.path.join(sub, "QQ.exe")
                        if _check_exe(qq_exe):
                            result = _accept_exe(qq_exe)
                            if result:
                                return result
            except OSError:
                pass
        return None

    def _try_key_values(key, source_label: str) -> Optional[str]:
        for val_name in ("InstallLocation", "DisplayIcon", "UninstallString"):
            try:
                val, _ = winreg.QueryValueEx(key, val_name)
                if not val:
                    continue
                qq_dir = _regval_to_qq_dir(val, val_name)
                result = _find_in_dir(qq_dir)
                if result:
                    return result
            except OSError:
                pass
        return None

    # --- 策略0: 手动路径 ---
    if saved_path:
        if os.path.isdir(saved_path):
            result = _find_in_dir(saved_path)
        elif _check_exe(saved_path):
            result = _accept_exe(saved_path)
        else:
            result = None
        if result:
            return result

    # --- 策略1: 精确注册表键 (Uninstall + App Paths) ---
    for hive, hive_name in (
        (winreg.HKEY_LOCAL_MACHINE, "HKLM"),
        (winreg.HKEY_CURRENT_USER, "HKCU"),
    ):
        for subkey in (
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQ",
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\QQ",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQNT",
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\QQNT",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\QQ.exe",
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\QQ.exe",
        ):
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    if "App Paths" in subkey:
                        try:
                            val, _ = winreg.QueryValueEx(key, "")
                            if _check_exe(val):
                                result = _accept_exe(val)
                                if result:
                                    return result
                        except OSError:
                            pass
                    result = _try_key_values(key, f"{hive_name}\\{subkey}")
                    if result:
                        return result
            except OSError:
                continue

    # --- 策略2: 枚举 Uninstall 子键 ---
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
                        try:
                            with winreg.OpenKey(base, subkey_name) as sk:
                                try:
                                    dn, _ = winreg.QueryValueEx(sk, "DisplayName")
                                except OSError:
                                    continue
                                if "QQ" not in dn and "qq" not in dn.lower() and "腾讯QQ" not in dn:
                                    continue
                                result = _try_key_values(sk, f"{hive_name}\\...\\{subkey_name}")
                                if result:
                                    return result
                        except OSError:
                            pass
            except OSError:
                pass

    # --- 策略3: 扫描常见安装目录 ---
    search_roots: set[str] = set()

    for drive in ("C:", "D:", "E:", "F:", "G:"):
        search_roots.update([
            rf"{drive}\Program Files\Tencent",
            rf"{drive}\Program Files (x86)\Tencent",
        ])

    search_roots.update([
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tencent"),
        os.path.expandvars(r"%LOCALAPPDATA%\Tencent"),
        os.path.expandvars(r"%APPDATA%\Tencent"),
        os.path.expanduser(r"~\Tencent"),
        os.path.expanduser(r"~\Desktop\Tencent"),
        os.path.expanduser(r"~\Downloads\Tencent"),
    ])

    for root in sorted(search_roots):
        if not os.path.isdir(root):
            continue
        for sub in ("QQNT", "QQ", "TIM"):
            candidate = os.path.join(root, sub)
            if _check_exe(os.path.join(candidate, "QQ.exe")):
                result = _accept_exe(os.path.join(candidate, "QQ.exe"))
                if result:
                    return result
            for subdir in ("Bin", "bin", "app", "App"):
                sub_exe = os.path.join(candidate, subdir, "QQ.exe")
                if _check_exe(sub_exe):
                    result = _accept_exe(sub_exe)
                    if result:
                        return result
            if sub == "QQNT":
                try:
                    for item in sorted(os.listdir(candidate), reverse=True):
                        if os.path.isdir(os.path.join(candidate, item)):
                            qq_exe = os.path.join(candidate, item, "QQ.exe")
                            if _check_exe(qq_exe):
                                result = _accept_exe(qq_exe)
                                if result:
                                    return result
                except OSError:
                    continue

    # --- 策略4: 递归搜索 Tencent 目录（深度限制）---
    for drive in ("C:", "D:", "E:"):
        for prog in ("Program Files", "Program Files (x86)"):
            tencent_root = os.path.join(f"{drive}\\", prog, "Tencent")
            if not os.path.isdir(tencent_root):
                continue
            try:
                for dirpath, dirnames, filenames in os.walk(tencent_root):
                    depth = dirpath[len(tencent_root):].count(os.sep)
                    if depth > 4:
                        dirnames.clear()
                        continue
                    if "QQ.exe" in filenames:
                        qq_exe = os.path.join(dirpath, "QQ.exe")
                        result = _accept_exe(qq_exe)
                        if result:
                            return result
            except OSError:
                continue

    # --- 策略5: 全盘搜索 QQNT 目录（兜底）---
    drives = []
    try:
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in range(26):
            if mask & (1 << letter):
                drives.append(f"{chr(65+letter)}:\\")
    except Exception:
        drives = ["C:\\", "D:\\", "E:\\"]

    SKIP_DIRS = {
        "Windows", "WinNT", "System Volume Information", "$Recycle.Bin",
        "Recovery", "Boot", "node_modules", ".git", "__pycache__",
    }

    for drive in drives:
        try:
            for dirpath, dirnames, filenames in os.walk(drive, topdown=True):
                # 剪枝：跳过系统/开发目录
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
                # 深度安全阀：超过 8 层停止该分支
                depth = dirpath[len(drive):].count(os.sep)
                if depth > 6:
                    dirnames.clear()
                    continue
                if "QQ.exe" in filenames:
                    qq_exe = os.path.join(dirpath, "QQ.exe")
                    result = _accept_exe(qq_exe)
                    if result:
                        return result
        except OSError:
            continue

    return None


# QQNT 版本兼容范围 (来自 NapCat 官方)
_QQNT_MIN_BUILD = 40768       # 最低可用版本
_QQNT_RECOMMENDED = 44343     # 推荐版本 (9.9.26.44343)
_QQNT_MAX_KNOWN = 45000       # 超过此版本发出警告


def _get_qqnt_version(qq_exe: str) -> Optional[dict]:
    """读取 QQ.exe 的 FileVersion，返回 {display, build} 或 None。

    使用 Windows GetFileVersionInfo API。
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    version_dll = ctypes.windll.version

    ver_size = version_dll.GetFileVersionInfoSizeW(qq_exe, None)
    if ver_size == 0:
        return None

    buf = ctypes.create_string_buffer(ver_size)
    if not version_dll.GetFileVersionInfoW(qq_exe, 0, ver_size, buf):
        return None

    # 获取固定版本信息
    ptr = ctypes.c_void_p()
    ptr_len = wintypes.UINT(0)
    if not version_dll.VerQueryValueW(buf, r"\\", ctypes.byref(ptr), ctypes.byref(ptr_len)):
        return None

    class VS_FIXEDFILEINFO(ctypes.Structure):
        _fields_ = [
            ("dwSignature", wintypes.DWORD),
            ("dwStrucVersion", wintypes.DWORD),
            ("dwFileVersionMS", wintypes.DWORD),
            ("dwFileVersionLS", wintypes.DWORD),
            ("dwProductVersionMS", wintypes.DWORD),
            ("dwProductVersionLS", wintypes.DWORD),
            ("dwFileFlagsMask", wintypes.DWORD),
            ("dwFileFlags", wintypes.DWORD),
            ("dwFileOS", wintypes.DWORD),
            ("dwFileType", wintypes.DWORD),
            ("dwFileSubtype", wintypes.DWORD),
            ("dwFileDateMS", wintypes.DWORD),
            ("dwFileDateLS", wintypes.DWORD),
        ]

    info = ctypes.cast(ptr, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
    ms = info.dwFileVersionMS
    ls = info.dwFileVersionLS
    major = (ms >> 16) & 0xFFFF
    minor = ms & 0xFFFF
    patch = (ls >> 16) & 0xFFFF
    build = ls & 0xFFFF

    return {
        "display": f"{major}.{minor}.{patch}.{build}",
        "build": build,
    }


def _launch_napcat_direct(launcher_exe: str, napcat_dir: str, log_cb=None, saved_qq_path: str = "") -> subprocess.Popen:
    """直接启动 NapCatWinBootMain.exe（shell=False，stdout 不会断）。

    复刻 launcher-user.bat 的逻辑：设环境变量、找 QQ.exe、启动。
    """
    def _log(msg):
        if log_cb:
            log_cb(msg)

    qq_exe = _find_qq_exe(saved_path=saved_qq_path)

    if not qq_exe:
        raise FileNotFoundError(
            "未找到 QQNT。NapCat 需要 QQNT（Electron 版 QQ），旧版 Win32 QQ 不支持。\n"
            "如已安装 QQNT 但仍报此错，请在设置中手动指定 QQ.exe 路径。"
        )

    # --- QQNT 版本兼容性检查 ---
    qqnt_ver = _get_qqnt_version(qq_exe)
    if qqnt_ver:
        _log(f"QQNT 版本: {qqnt_ver['display']}")
        build = qqnt_ver["build"]
        if build < _QQNT_MIN_BUILD:
            _log(f"⚠ QQNT 版本过旧 (build {build} < {_QQNT_MIN_BUILD})，NapCat 推荐 {_QQNT_RECOMMENDED}+，部分功能可能异常")
        if build > _QQNT_MAX_KNOWN:
            _log(f"⚠ QQNT 版本 (build {build}) 可能不受支持，如崩溃请降级到 QQNT 9.9.26.44343")
    else:
        _log("无法读取 QQNT 版本号（将继续启动）")

    hook_dll = os.path.join(napcat_dir, "NapCatWinBootHook.dll")
    if not os.path.isfile(hook_dll):
        raise FileNotFoundError(f"未找到 Hook DLL: {hook_dll}")

    env = os.environ.copy()
    env["NAPCAT_PATCH_PACKAGE"] = os.path.join(napcat_dir, "qqnt.json")
    env["NAPCAT_LOAD_PATH"] = os.path.join(napcat_dir, "loadNapCat.js")
    env["NAPCAT_INJECT_PATH"] = hook_dll
    env["NAPCAT_LAUNCHER_PATH"] = launcher_exe
    env["NAPCAT_MAIN_PATH"] = os.path.join(napcat_dir, "napcat.mjs")

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
            _log(f"错误: 在 {self._napcat_root} 中找不到 NapCat 启动脚本")
            return False

        is_bat = launcher.lower().endswith(".bat")

        # webui.json autoLoginAccount — 快登时设QQ号，扫码时清空
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
        except Exception:
            pass

        mode = f"自动登录 (QQ:{qq})" if qq else "扫码登录"
        _log(f"正在启动 NapCat ({mode})...")

        napcat_dir = os.path.dirname(launcher)
        _ensure_load_napcat_js(napcat_dir)

        try:
            if is_bat:
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
                self._process = _launch_napcat_direct(launcher, napcat_dir, log_cb=_log, saved_qq_path=saved_qq_path)
        except FileNotFoundError as e:
            _log(f"启动失败: {e}")
            return False
        except Exception as e:
            _log(f"启动失败: {e}")
            return False

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

    def _on_login_failed(self, reason: str):
        clean = re.sub(r"\x1b\[[0-9;]*m", "", reason).strip()
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
            self._state.napcat_status.emit(f"NapCat 异常退出 (code={rc}) — 常见原因: QQ未安装/版本不兼容/被杀毒拦截")
            self._state.login_status_changed.emit(False, f"NapCat 异常退出 (code={rc})")
        else:
            self._state.napcat_status.emit("NapCat 启动器已退出，等待 OneBot 就绪...")
