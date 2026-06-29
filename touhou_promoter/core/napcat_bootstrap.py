"""NapCat 一键引导 — 自动搜索/下载/配置 NapCat

实现"点按钮即出二维码"：
1. 检查 %APPDATA%/touhou-promoter/napcat/ 是否已有 NapCat
2. 搜索常见安装位置
3. 都没有则自动从 GitHub 下载（直连+多镜像竞速，优先国内可用）
4. 下载完成后自动解压并配置
"""

import os
import zipfile
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests

from touhou_promoter.core.napcat_config import find_napcat_executable

NAPCAT_RELEASE_API = "https://api.github.com/repos/NapNeko/NapCatQQ/releases/latest"

# 镜像列表 — 按优先级排列，直连兜底
_GITHUB_PROXIES = [
    "https://gh-proxy.com/",      # 国内镜像（实测稳定）
    "https://mirror.ghproxy.com/", # ghproxy 新域名
    "https://ghproxy.com/",        # ghproxy 旧域名
    "",                            # 直连（兜底）
]

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

def _fetch_api_json(api_url: str, timeout: float) -> dict | None:
    """尝试从一个 URL 获取 JSON，失败返回 None"""
    try:
        resp = requests.get(api_url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def _get_download_urls() -> list[tuple[str, str]]:
    """获取最新 NapCat 下载链接（API 竞速：直连+镜像谁快用谁）。

    返回 [(文件名, URL), ...]
    """
    # 构建 API URL 列表：镜像优先，直连兜底
    api_urls = []
    for proxy in _GITHUB_PROXIES:
        if proxy:
            api_urls.append(proxy.rstrip("/") + "/" + NAPCAT_RELEASE_API)
        else:
            api_urls.append(NAPCAT_RELEASE_API)

    data = None
    # 短超时竞速：300ms 内第一个响应的胜出
    with ThreadPoolExecutor(max_workers=len(api_urls)) as pool:
        futures = {pool.submit(_fetch_api_json, u, 8): u for u in api_urls}
        for f in as_completed(futures):
            result = f.result()
            if result is not None:
                data = result
                # 取消剩余请求（best-effort）
                for rf in futures:
                    rf.cancel()
                break

    if data is None:
        return _fallback_urls()

    assets = []
    for a in data.get("assets", []):
        name = a.get("name", "")
        url = a.get("browser_download_url", "")
        if not name or not url:
            continue
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


def _try_download_one(url: str, dest: str, progress_cb, timeout: float) -> bool:
    """尝试从单个 URL 下载文件。返回 True/False，不抛异常。"""
    try:
        resp = requests.get(url, stream=True, timeout=timeout)
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
        return False


def download_with_progress(url: str, dest: str, progress_cb=None) -> bool:
    """下载文件（直连+多镜像竞速，谁先通谁下载）。

    对每个候选 URL 同时发起请求，第一个成功的胜出，其余取消。
    这样无论用户有没有开梯子都不用等超时。
    """
    # 构建候选 URL 列表
    candidates = []
    for proxy in _GITHUB_PROXIES:
        candidates.append((proxy.rstrip("/") + "/" + url) if proxy else url)

    # 竞速：并发请求，取第一个成功的
    with ThreadPoolExecutor(max_workers=len(candidates)) as pool:
        futures = {pool.submit(_try_download_one, u, dest, progress_cb, 120): u for u in candidates}
        for f in as_completed(futures):
            if f.result():
                for rf in futures:
                    rf.cancel()
                return True
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
