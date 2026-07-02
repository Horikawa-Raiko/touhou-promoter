"""增量同步 — 后台拉取 /api/changes?since=N，调用方负责合并到本地CSV"""
import json
from urllib.request import urlopen, Request
from urllib.error import URLError
from PyQt6.QtCore import QThread, pyqtSignal


DEFAULT_SERVER = "http://152.136.232.146"


class UpdateChecker(QThread):
    """后台获取增量变更列表，调用方负责合并到本地CSV"""
    finished = pyqtSignal(dict)  # {"changes": [...], "latest_seq": int, "error": str|None}

    def __init__(self, server_url: str, local_seq: int):
        super().__init__()
        self._server = server_url.rstrip("/")
        self._local_seq = local_seq

    def run(self):
        result = {"changes": [], "latest_seq": self._local_seq, "error": None}
        try:
            req = Request(
                f"{self._server}/api/changes?since={self._local_seq}",
                headers={"User-Agent": "TouhouPromoter/1.0"},
            )
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            result["latest_seq"] = data.get("latest_seq", self._local_seq)
            result["changes"] = data.get("changes", [])

        except URLError as e:
            result["error"] = f"无法连接到更新服务器: {e.reason}"
        except Exception as e:
            result["error"] = f"更新检查失败: {e}"

        self.finished.emit(result)
