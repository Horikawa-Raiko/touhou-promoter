"""启动流程编排"""
import os
import sys
import traceback
from datetime import datetime
from PyQt6.QtWidgets import QApplication, QMessageBox
from touhou_promoter.ui.main_window import MainWindow
from touhou_promoter.version import APP_VERSION


def _crash_log_path() -> str:
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    return os.path.join(appdata, "touhou-promoter", "crash.log")


def _install_excepthook():
    """将未捕获异常写入 crash.log，避免 PyInstaller windowed 模式静默崩溃"""
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    log_dir = os.path.join(appdata, "touhou-promoter")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "crash.log")

    def _hook(exc_type, exc_value, exc_tb):
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n=== Crash {ts} ===\n{tb_text}\n")

        QMessageBox.critical(
            None, "程序崩溃",
            f"原初电台遇到了未处理的错误，即将退出。\n\n"
            f"{exc_type.__name__}: {exc_value}\n\n"
            f"详细信息已写入:\n{log_path}",
        )
        sys.exit(1)

    sys.excepthook = _hook


def main() -> int:
    _install_excepthook()

    app = QApplication(sys.argv)
    app.setApplicationName("原初电台")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("touhou-promoter")

    window = MainWindow()
    window.show()

    return app.exec()
