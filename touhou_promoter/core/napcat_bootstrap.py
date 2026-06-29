"""NapCat 一键引导 — 自动搜索/下载/配置 NapCat

实现"点按钮即出二维码"：
1. 检查 %APPDATA%/touhou-promoter/napcat/ 是否已有 NapCat
2. 搜索常见安装位置
3. 都没有则自动从 GitHub 下载（支持 ghproxy 镜像加速）
4. 下载完成后自动解压并配置
"""

import os
import zipfile
import tempfile
from typing import Optional
from urllib.parse import urlparse

import requests

from touhou_promoter.core.napcat_config import find_napcat_executable

NAPCAT_RELEASE_API = "https://api.github.com/repos/NapNeko/NapCatQQ/releases/latest"
GHPROXY_PREFIX = "https://ghproxy.com/"
DEFAULT_NUM_WORKERS = 4


# ---------- 搜索 ----------

_SEARCH_DIRS = [
    os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "NapCat"),
    os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "NapCat"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "NapCat"),
    os.path.join(os.path.expanduser("~"), "NapCat"),
    os.path.join(os.path.expanduser("~"), "Downloads", "NapCat"),
    "D:\\NapCat",
    "E:\\NapCat",
]


def find_napcat_on_system() -> Optional[str]:
    """在系统常见位置搜索 NapCat 可执行文件"""
    for d in _SEARCH_DIRS:
        if os.path.isdir(d):
            exe = find_napcat_executable(d)
            if exe:
                return d
    return None


# ---------- 下载 ----------

def _get_download_urls() -> list[tuple[str, str]]:
    """获取最新 NapCat 下载链接。返回 [(文件名, URL), ...]"""
    try:
        resp = requests.get(NAPCAT_RELEASE_API, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return _fallback_urls()

    assets = []
    for a in data.get("assets", []):
        name = a.get("name", "")
        url = a.get("browser_download_url", "")
        if not name or not url:
            continue
        # 只下载 Framework + Windows Shell
        if "Framework" in name or ("Shell" in name and "Windows" in name):
            assets.append((name, url))

    return assets if assets else _fallback_urls()


def _fallback_urls() -> list[tuple[str, str]]:
    """硬编码回退 URL（v4.18.6）"""
    base = "https://github.com/NapNeko/NapCatQQ/releases/download/v4.18.6"
    return [
        ("NapCat.Framework.zip", f"{base}/NapCat.Framework.zip"),
        ("NapCat.Shell.Windows.OneKey.zip", f"{base}/NapCat.Shell.Windows.OneKey.zip"),
    ]


def download_with_progress(url: str, dest: str, progress_cb=None) -> bool:
    """下载文件，可选进度回调 progress_cb(bytes_done, total_bytes)"""
    for attempt in range(3):
        download_url = url
        # 第一次尝试直连，后续尝试走镜像
        if attempt > 0:
            download_url = GHPROXY_PREFIX + url
        try:
            resp = requests.get(download_url, stream=True, timeout=30)
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            done = 0
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    done += len(chunk)
                    if progress_cb:
                        progress_cb(done, total)
            return True
        except Exception:
            if attempt == 2:
                return False
            continue
    return False


# ---------- 安装 ----------

def install_napcat(target_dir: str, progress_cb=None, status_cb=None) -> bool:
    """下载并解压 NapCat 到 target_dir。

    Args:
        target_dir: 安装目标目录 (如 %APPDATA%/touhou-promoter/napcat)
        progress_cb: 进度回调 (filename, bytes_done, total_bytes)
        status_cb: 状态回调 (message)

    Returns:
        是否成功
    """
    os.makedirs(target_dir, exist_ok=True)

    if status_cb:
        status_cb("正在获取最新 NapCat 下载地址...")

    urls = _get_download_urls()
    if not urls:
        if status_cb:
            status_cb("无法获取 NapCat 下载地址")
        return False

    tmpdir = tempfile.mkdtemp(prefix="napcat_dl_")

    for filename, url in urls:
        if status_cb:
            status_cb(f"正在下载 {filename} ...")

        dest = os.path.join(tmpdir, filename)
        ok = download_with_progress(url, dest,
            lambda done, total: progress_cb and progress_cb(filename, done, total))
        if not ok:
            if status_cb:
                status_cb(f"下载 {filename} 失败，请检查网络连接")
            return False

        if status_cb:
            status_cb(f"正在解压 {filename} ...")

        try:
            with zipfile.ZipFile(dest, "r") as zf:
                zf.extractall(target_dir)
        except zipfile.BadZipFile:
            if status_cb:
                status_cb(f"{filename} 文件损坏，正在重试...")
            return False

    # 清理临时文件
    try:
        import shutil
        shutil.rmtree(tmpdir)
    except Exception:
        pass

    if status_cb:
        status_cb("NapCat 安装完成")

    return True


# ---------- 统一入口 ----------

def ensure_napcat_ready(
    config_dir: str,
    status_cb=None,
    progress_cb=None,
) -> Optional[str]:
    """确保 NapCat 可用，返回 napcat 根目录路径。

    优先级:
    1. config 中已保存的路径
    2. 系统搜索
    3. %APPDATA%/touhou-promoter/napcat/ 已有安装
    4. 自动下载安装

    Returns:
        napcat_root 路径，失败返回 None
    """
    # 1. 检查 app data 下的缓存安装
    cached = os.path.join(config_dir, "napcat")
    if os.path.isdir(cached):
        exe = find_napcat_executable(cached)
        if exe:
            if status_cb:
                status_cb("找到已安装的 NapCat")
            return cached

    # 2. 搜索系统
    found = find_napcat_on_system()
    if found:
        if status_cb:
            status_cb(f"在系统中找到 NapCat: {found}")
        return found

    # 3. 自动安装
    if status_cb:
        status_cb("未找到 NapCat，正在自动下载安装（约30MB）...")

    ok = install_napcat(cached, progress_cb=progress_cb, status_cb=status_cb)
    if ok:
        exe = find_napcat_executable(cached)
        if exe:
            return cached

    return None
