"""自定检查更新 + CSV同步 — 后台拉取 version.json，有更新自动下载"""
import os, json, csv
from urllib.request import urlopen, Request
from urllib.error import URLError
from PyQt6.QtCore import QThread, pyqtSignal


DEFAULT_SERVER = "http://152.136.232.146"
VERSION_PATH = "/version.json"
CSV_PATH = "/csv"


class UpdateChecker(QThread):
    """后台检查 CSV 是否有新版本，有则下载并替换本地文件"""
    finished = pyqtSignal(dict)  # {"csv_updated": bool, "app_update": bool, "error": str|None}

    def __init__(self, server_url: str, local_csv_path: str, local_csv_version: int):
        super().__init__()
        self._server = server_url.rstrip("/")
        self._csv_path = local_csv_path
        self._local_ver = local_csv_version

    def run(self):
        result = {"csv_updated": False, "app_update": False, "error": None, "csv_rows": 0}
        try:
            req = Request(
                f"{self._server}{VERSION_PATH}",
                headers={"User-Agent": "TouhouPromoter/1.0"},
            )
            with urlopen(req, timeout=10) as resp:
                info = json.loads(resp.read().decode("utf-8"))

            server_csv_ver = info.get("csv_version", 0)
            server_app_ver = info.get("app_version", "")

            if server_app_ver and server_app_ver != "1.0":
                result["app_update"] = True

            if server_csv_ver > self._local_ver:
                # 下载新CSV
                csv_req = Request(
                    f"{self._server}{CSV_PATH}",
                    headers={"User-Agent": "TouhouPromoter/1.0"},
                )
                with urlopen(csv_req, timeout=60) as csv_resp:
                    content = csv_resp.read().decode("utf-8-sig")

                # 写入本地
                if self._csv_path and os.path.isdir(os.path.dirname(self._csv_path)):
                    with open(self._csv_path, "w", encoding="utf-8-sig", newline="") as f:
                        f.write(content)
                    result["csv_updated"] = True
                    result["csv_rows"] = content.count("\n")

        except URLError as e:
            result["error"] = f"无法连接到更新服务器: {e.reason}"
        except Exception as e:
            result["error"] = f"更新检查失败: {e}"

        self.finished.emit(result)
