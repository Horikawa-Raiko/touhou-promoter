"""启动流程编排"""
import sys
from PyQt6.QtWidgets import QApplication
from touhou_promoter.ui.main_window import MainWindow
from touhou_promoter.version import APP_VERSION


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("原初电台")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("touhou-promoter")

    window = MainWindow()
    window.show()

    return app.exec()
