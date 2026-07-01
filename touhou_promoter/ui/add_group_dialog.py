"""添加群聊对话框 — 可视化表单，支持本地保存 + 云端提交"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QLabel, QMessageBox,
    QGroupBox,
)
from PyQt6.QtCore import Qt
import json
from urllib.request import urlopen, Request
from urllib.error import URLError


CATEGORIES = [
    "活动官方群",
    "学校东方群",
    "地区性东方群",
    "功能性公开群",
    "组织实体官方群",
    "网络区域社群",
]

SUBMIT_SECRET = "raiko-touhou-2026"


class AddGroupDialog(QDialog):
    """添加群聊对话框"""

    def __init__(self, parent=None, server_url: str = ""):
        super().__init__(parent)
        self.setWindowTitle("添加群聊")
        self.setMinimumWidth(480)
        self.setModal(True)
        self._server = server_url.rstrip("/") if server_url else ""
        self._result_entry = None  # dict, 成功添加后设置
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        form_group = QGroupBox("群聊信息")
        form = QFormLayout(form_group)

        self._gid = QLineEdit()
        self._gid.setPlaceholderText("必填，纯数字")
        form.addRow("群号 *:", self._gid)

        self._name = QLineEdit()
        self._name.setPlaceholderText("必填")
        form.addRow("群名称 *:", self._name)

        self._category = QComboBox()
        self._category.addItems(CATEGORIES)
        form.addRow("大类:", self._category)

        self._region = QLineEdit()
        self._region.setPlaceholderText("如：广东省、北京市")
        form.addRow("地区/小类:", self._region)

        self._location = QLineEdit()
        self._location.setPlaceholderText("如：广州市")
        form.addRow("地点:", self._location)

        self._school = QLineEdit()
        self._school.setPlaceholderText("如：北京理工大学")
        form.addRow("学校:", self._school)

        self._event = QLineEdit()
        self._event.setPlaceholderText("如：沙包大会十九回")
        form.addRow("活动名:", self._event)

        self._note = QLineEdit()
        self._note.setPlaceholderText("备注信息")
        form.addRow("说明:", self._note)

        layout.addWidget(form_group)

        # 按钮
        btn_layout = QHBoxLayout()

        self._local_btn = QPushButton("添加到本地")
        self._local_btn.clicked.connect(self._add_local_only)
        btn_layout.addWidget(self._local_btn)

        self._cloud_btn = QPushButton("添加到本地并提交云端")
        self._cloud_btn.clicked.connect(self._add_and_submit)
        self._cloud_btn.setStyleSheet(
            "QPushButton { background: #C04040; color: #fff; border: none; "
            "border-radius: 4px; padding: 6px 16px; font-weight: bold; }"
            "QPushButton:hover { background: #D46060; }"
        )
        btn_layout.addWidget(self._cloud_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        if not self._server:
            self._cloud_btn.setEnabled(False)
            self._cloud_btn.setToolTip("未配置更新服务器")

    def _validate(self):
        gid = (self._gid.text() or "").strip()
        name = (self._name.text() or "").strip()
        if not gid:
            QMessageBox.warning(self, "提示", "群号不能为空")
            return False
        if not gid.isdigit():
            QMessageBox.warning(self, "提示", "群号必须是纯数字")
            return False
        if not name:
            QMessageBox.warning(self, "提示", "群名称不能为空")
            return False
        return True

    def _build_entry(self):
        return {
            "群号": (self._gid.text() or "").strip(),
            "群名称": (self._name.text() or "").strip(),
            "大类": self._category.currentText(),
            "地区/小类": (self._region.text() or "").strip(),
            "子类": "",
            "地点": (self._location.text() or "").strip(),
            "学校": (self._school.text() or "").strip(),
            "活动名": (self._event.text() or "").strip(),
            "说明": (self._note.text() or "").strip(),
        }

    def _add_local_only(self):
        if not self._validate():
            return
        self._result_entry = self._build_entry()
        self._result_entry["_submit"] = "local"
        self.accept()

    def _add_and_submit(self):
        if not self._validate():
            return
        entry = self._build_entry()
        # 先设本地结果
        self._result_entry = entry
        self._result_entry["_submit"] = "cloud"

        if self._server:
            try:
                payload = json.dumps({
                    "secret": SUBMIT_SECRET,
                    "entry": entry,
                }, ensure_ascii=False).encode("utf-8")
                req = Request(
                    f"{self._server}/api/submit",
                    data=payload,
                    headers={
                        "Content-Type": "application/json; charset=utf-8",
                        "User-Agent": "TouhouPromoter/1.0",
                    },
                )
                with urlopen(req, timeout=15) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                if resp_data.get("ok"):
                    self._result_entry["_submit_success"] = True
                else:
                    self._result_entry["_submit_success"] = False
                    self._result_entry["_submit_error"] = resp_data.get("error", "未知错误")
            except URLError as e:
                self._result_entry["_submit_success"] = False
                self._result_entry["_submit_error"] = f"网络错误: {e.reason}"
            except Exception as e:
                self._result_entry["_submit_success"] = False
                self._result_entry["_submit_error"] = str(e)

        self.accept()

    def result(self) -> dict | None:
        return self._result_entry
