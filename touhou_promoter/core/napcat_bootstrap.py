"""NapCat 一键引导 — 自动搜索/下载/配置 NapCat

实现"点按钮即出二维码"：
1. 检查 %APPDATA%/touhou-promoter/napcat/ 是否已有 NapCat
2. 搜索常见安装位置
3. 都没有则自动从 GitHub 下载（多源竞速获取API，下载顺序回退）
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

# GitHub 下载加速源 — API 查询用竞速，文件下载用顺序回退
# 直连放最后兜底，前面的镜像按可用性排列
_GITHUB_MIRRORS = [
    "https://gh-proxy.com/",
    "https://ghproxy.net/",
    "",                            # 直连
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
    """获取最新 NapCat 下载链接（API 竞速：多镜像+直连谁快用谁）。

    返回 [(文件名, URL), ...]
    """
    # 构建 API URL 列表
    api_urls = []
    for proxy in _GITHUB_MIRRORS:
        if proxy:
            api_urls.append(proxy.rstrip("/") + "/" + NAPCAT_RELEASE_API)
        else:
            api_urls.append(NAPCAT_RELEASE_API)

    data = None
    with ThreadPoolExecutor(max_workers=len(api_urls)) as pool:
        futures = {pool.submit(_fetch_api_json, u, 8): u for u in api_urls}
        for f in as_completed(futures):
            result = f.result()
            if result is not None:
                data = result
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


def _build_mirror_urls(github_url: str) -> list[str]:
    """为一个 GitHub 直链生成 [镜像URL, ..., 直链URL] 列表"""
    urls = []
    for proxy in _GITHUB_MIRRORS:
        urls.append((proxy.rstrip("/") + "/" + github_url) if proxy else github_url)
    return urls


def download_with_progress(url: str, dest: str, progress_cb=None) -> bool:
    """下载文件（顺序回退：镜像 → 直连）。

    每个候选 URL 写入独立临时文件，成功后 rename 到 dest，
    避免多源同时写同一文件导致损坏。
    """
    candidates = _build_mirror_urls(url)
    last_error = None

    for i, download_url in enumerate(candidates):
        try:
            # 每个候选写独立临时文件
            tmp_fd, tmp_path = tempfile.mkstemp(prefix="napcat_dl_", suffix=".zip")
            os.close(tmp_fd)
            try:
                resp = requests.get(download_url, stream=True, timeout=120)
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                done = 0
                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                        done += len(chunk)
                        if progress_cb:
                            progress_cb(done, total)
                # 完整写入后 rename
                if os.path.exists(dest):
                    os.remove(dest)
                os.rename(tmp_path, dest)
                return True
            except Exception:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as e:
            last_error = e
            continue

    if last_error:
        try:
            # 给调用者一个可读的提示
            if hasattr(last_error, "response") and last_error.response is not None:
                pass  # HTTPError 自带状态码信息
        except Exception:
            pass
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
            # 损坏文件清理掉，下次重试可以重新下载
            try:
                os.remove(dest)
            except OSError:
                pass
            if status_cb:
                status_cb(f"{filename} 文件损坏，请重试")
            return False

    # 清理临时文件
    try:
        import shutil
        shutil.rmtree(tmpdir)
    except Exception:
        pass

    if status_cb:
        status_cb("NapCat 下载解压完成")

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
        else:
            if status_cb:
                status_cb("NapCat 已下载但未找到可执行文件，目录结构可能已变更")
            return None

    return None
