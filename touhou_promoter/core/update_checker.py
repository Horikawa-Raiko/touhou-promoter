"""增量同步 — 后台拉取 /api/changes?since=N 和 /version.json，调用方负责合并到本地CSV"""
import json
from urllib.request import urlopen, Request
from urllib.error import URLError
from PyQt6.QtCore import QThread, pyqtSignal

from touhou_promoter.version import APP_VERSION


DEFAULT_SERVER = "https://thpromoter.dismused-beat.cloud"


def _parse_version(v: str) -> tuple:
    """语义版本号 → 可比较的 tuple"""
    try:
        return tuple(map(int, v.split(".")))
    except (ValueError, AttributeError):
        return (0, 0, 0)


class UpdateChecker(QThread):
    """后台获取增量变更列表 + 检查应用版本更新，调用方负责合并到本地CSV"""
    finished = pyqtSignal(dict)  # {"changes": [...], "latest_seq": int, "app_update": dict|None, "error": str|None}

    def __init__(self, server_url: str, local_seq: int):
        super().__init__()
        self._server = server_url.rstrip("/")
        self._local_seq = local_seq

    def run(self):
        result = {"changes": [], "latest_seq": self._local_seq, "app_update": None, "error": None}

        # ── CSV 增量同步 ──
        try:
            req = Request(
                f"{self._server}/api/changes?since={self._local_seq}",
                headers={"User-Agent": f"TouhouPromoter/{APP_VERSION}"},
            )
            with urlopen(req, timeout=15) as resp:
                vdata = json.loads(resp.read().decode("utf-8"))

            remote_ver = vdata.get("app_version", "")
            if _parse_version(remote_ver) > _parse_version(APP_VERSION):
                result["app_update"] = {
                    "version": remote_ver,
                    "download_url": vdata.get("download_url", ""),
                    "sha256": vdata.get("sha256", ""),
                }
        except Exception:
            pass  # 版本检查失败不影响 CSV 同步

        self.finished.emit(result)
