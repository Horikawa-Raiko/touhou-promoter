"""添加群聊对话框 — 根据大类动态切换表单字段 + 实时重复提示"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QLabel, QMessageBox,
    QGroupBox, QWidget, QStackedWidget, QListWidget, QListWidgetItem,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont


CATEGORIES = [
    "活动官方群",
    "学校东方群",
    "地区性东方群",
    "功能性公开群",
    "组织实体官方群",
    "网络区域社群",
]

# 学校东方群专用（省份 + 海外）
SCHOOL_REGIONS = [
    "北京市", "天津市", "上海市", "重庆市",
    "河北省", "山西省", "辽宁省", "吉林省", "黑龙江省",
    "江苏省", "浙江省", "安徽省", "福建省", "江西省", "山东省",
    "河南省", "湖北省", "湖南省", "广东省", "海南省",
    "四川省", "贵州省", "云南省", "陕西省", "甘肃省", "青海省",
    "内蒙古自治区", "广西壮族自治区", "西藏自治区", "宁夏回族自治区", "新疆维吾尔自治区",
    "台湾省", "香港特别行政区", "澳门特别行政区",
    "海外",
]

# 地区性东方群专用（省份 + 海外 + 全球）
REGIONAL_REGIONS = [
    "北京市", "天津市", "上海市", "重庆市",
    "河北省", "山西省", "辽宁省", "吉林省", "黑龙江省",
    "江苏省", "浙江省", "安徽省", "福建省", "江西省", "山东省",
    "河南省", "湖北省", "湖南省", "广东省", "海南省",
    "四川省", "贵州省", "云南省", "陕西省", "甘肃省", "青海省",
    "内蒙古自治区", "广西壮族自治区", "西藏自治区", "宁夏回族自治区", "新疆维吾尔自治区",
    "台湾省", "香港特别行政区", "澳门特别行政区",
    "海外", "全球",
]

# 功能性公开群 → 专题讨论 的子类
TOPIC_SUBCATEGORIES = [
    "Cosplay", "东方CP交流", "东方MMD交流", "东方TRPG交流",
    "东方stg交流", "东方文学交流", "东方格斗作交流", "东方绘画交流",
    "东方角色交流", "东方设定交流", "东方音乐交流", "游戏模组",
    "新闻整合宣发", "其他",
]

# 活动官方群 → 活动范围
EVENT_SCOPES = ["全国性活动", "地区性活动", "网络性活动"]


class AddGroupDialog(QDialog):
    """添加群聊对话框 — 大类决定显示哪些字段"""

    def __init__(self, parent=None, server_url: str = "", existing_groups: dict[str, str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("添加群聊")
        self.setMinimumWidth(500)
        self.setModal(True)
        self._server = server_url.rstrip("/") if server_url else ""
        self._existing = existing_groups or {}  # gid -> group_name
        self._result_entry = None
        self._build_ui()
        self._on_category_changed(0)

    # ── UI 构建 ──

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 大类选择（始终可见）
        top = QHBoxLayout()
        top.addWidget(QLabel("大类:"))
        self._category_combo = QComboBox()
        self._category_combo.addItems(CATEGORIES)
        self._category_combo.currentIndexChanged.connect(self._on_category_changed)
        top.addWidget(self._category_combo, 1)
        layout.addLayout(top)

        # 群号 + 群名称（始终可见）
        base_group = QGroupBox("基本信息")
        base_form = QFormLayout(base_group)

        self._gid = QLineEdit()
        self._gid.setPlaceholderText("必填，纯数字")
        self._gid.textChanged.connect(self._on_gid_changed)
        base_form.addRow("群号 *:", self._gid)

        # 重复提示列表（显示在群号下方，默认隐藏）
        self._dup_list = QListWidget()
        self._dup_list.setMaximumHeight(120)
        self._dup_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._dup_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._dup_list.setStyleSheet(
            "QListWidget { border: 1px solid #C04040; border-radius: 4px; "
            "background: #3A2020; color: #F0C0C0; font-size: 12px; }"
            "QListWidget::item { padding: 2px 6px; }"
        )
        self._dup_list.hide()
        base_form.addRow(self._dup_list)

        self._name = QLineEdit()
        self._name.setPlaceholderText("必填")
        base_form.addRow("群名称 *:", self._name)

        layout.addWidget(base_group)

        # 动态表单区（QStackedWidget，每个大类一个页面）
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_event_page())      # index 0: 活动官方群
        self._stack.addWidget(self._build_school_page())      # index 1: 学校东方群
        self._stack.addWidget(self._build_regional_page())    # index 2: 地区性东方群
        self._stack.addWidget(self._build_functional_page())  # index 3: 功能性公开群
        self._stack.addWidget(self._build_org_page())         # index 4: 组织实体官方群
        self._stack.addWidget(self._build_network_page())     # index 5: 网络区域社群
        layout.addWidget(self._stack)

        # 初始化各页面的动态显隐状态
        self._on_event_scope_changed(EVENT_SCOPES[0])
        self._on_func_category_changed("专题讨论")

        # 说明（始终可见）
        note_group = QGroupBox("备注")
        note_layout = QHBoxLayout(note_group)
        self._note = QLineEdit()
        self._note.setPlaceholderText("备注信息（可选）")
        note_layout.addWidget(self._note)
        layout.addWidget(note_group)

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

        # 覆盖默认蓝色选中条 + 添加悬浮高亮
        self.setStyleSheet("""
            QComboBox QAbstractItemView {
                selection-background-color: #C04040;
                selection-color: #ffffff;
                outline: none;
            }
            QComboBox QAbstractItemView::item:hover {
                background: #F0D8D8;
                color: #000000;
            }
        """)

    # ── 各分类的动态表单页 ──

    def _build_event_page(self):
        """活动官方群: 活动范围 + 活动名 + 地点(地区性时)"""
        page = QGroupBox("活动信息")
        form = QFormLayout(page)

        self._event_scope = QComboBox()
        self._event_scope.addItems(EVENT_SCOPES)
        self._event_scope.currentTextChanged.connect(self._on_event_scope_changed)
        form.addRow("活动范围:", self._event_scope)

        self._event_name = QLineEdit()
        self._event_name.setPlaceholderText("如：幻奏盛宴、东方LiveParty")
        form.addRow("活动名:", self._event_name)

        self._event_location = QLineEdit()
        self._event_location.setPlaceholderText("如：上海市、广州市")
        form.addRow("地点:", self._event_location)

        self._event_location_label = form.itemAt(form.count() - 2)
        self._event_location_field = form.itemAt(form.count() - 1)

        return page

    def _build_school_page(self):
        """学校东方群: 省份 + 学校"""
        page = QGroupBox("学校信息")
        form = QFormLayout(page)

        self._school_province = QComboBox()
        self._school_province.addItems(SCHOOL_REGIONS)
        form.addRow("省份/地区:", self._school_province)

        self._school_name = QLineEdit()
        self._school_name.setPlaceholderText("如：北京大学")
        form.addRow("学校:", self._school_name)

        return page

    def _build_regional_page(self):
        """地区性东方群: 省份 + 地点 + (海外时: 国家输入)"""
        page = QGroupBox("地区信息")
        form = QFormLayout(page)

        # 行1: 省份/地区（始终为下拉）
        self._regional_province = QComboBox()
        self._regional_province.addItems(REGIONAL_REGIONS)
        self._regional_province.currentTextChanged.connect(self._on_regional_province_changed)
        form.addRow("省份/地区:", self._regional_province)

        # 行2: 地点
        self._regional_location = QLineEdit()
        self._regional_location.setPlaceholderText("如：广州市、深圳市")
        form.addRow("地点:", self._regional_location)

        self._regional_location_label = form.itemAt(form.count() - 2)
        self._regional_location_field = form.itemAt(form.count() - 1)

        # 行3: 海外分类下拉 / 国家文本输入（QStackedWidget 切换）
        self._overseas_stack = QStackedWidget()

        self._overseas_category = QComboBox()
        self._overseas_category.addItems(["东亚", "东南亚", "大洋洲", "欧洲"])
        self._overseas_stack.addWidget(self._overseas_category)

        self._overseas_country = QLineEdit()
        self._overseas_country.setPlaceholderText("如：日本、韩国、英国")
        self._overseas_stack.addWidget(self._overseas_country)

        self._overseas_label = QLabel("海外分类:")
        form.addRow(self._overseas_label, self._overseas_stack)

        # 默认隐藏（用 helper 确保完全折叠）
        self._set_row_visible(self._overseas_label, self._overseas_stack, False)

        return page

    def _build_functional_page(self):
        """功能性公开群: 分类 + 专题类型(专题讨论时)"""
        page = QGroupBox("功能分类")
        form = QFormLayout(page)

        self._func_category = QComboBox()
        self._func_category.addItems(["专题讨论", "线下活动", "综合性东方群"])
        self._func_category.currentTextChanged.connect(self._on_func_category_changed)
        form.addRow("分类:", self._func_category)

        self._func_topic = QComboBox()
        self._func_topic.addItems(TOPIC_SUBCATEGORIES)
        form.addRow("专题类型:", self._func_topic)

        self._func_topic_label = form.itemAt(form.count() - 2)
        self._func_topic_field = form.itemAt(form.count() - 1)

        return page

    def _build_org_page(self):
        """组织实体官方群: 仅类型"""
        page = QGroupBox("组织信息")
        form = QFormLayout(page)

        self._org_type = QComboBox()
        self._org_type.addItems(["社团官方群", "组织官方群"])
        form.addRow("类型:", self._org_type)

        return page

    def _build_network_page(self):
        """网络区域社群: 仅类型"""
        page = QGroupBox("社群信息")
        form = QFormLayout(page)

        self._net_type = QComboBox()
        self._net_type.addItems(["网站用户", "论坛附属", "贴吧附属", "非官方粉丝群"])
        form.addRow("类型:", self._net_type)

        return page

    # ── 动态显隐 ──

    @staticmethod
    def _set_row_visible(label, field, visible):
        """显隐表单行并强制布局折叠——只 hide 会有间距残留"""
        for w in (label, field):
            w.setVisible(visible)
            w.setMaximumHeight(16777215 if visible else 0)

    def _on_category_changed(self, index):
        self._stack.setCurrentIndex(index)

    def _on_event_scope_changed(self, scope):
        """地区性活动才显示地点"""
        visible = scope == "地区性活动"
        self._set_row_visible(
            self._event_location_label.widget(),
            self._event_location_field.widget(),
            visible,
        )
        if not visible:
            self._event_location.clear()

    def _on_regional_province_changed(self, province):
        """选「海外」→ 显示国家文本输入；选「全球」→ 隐藏地点；其他→ 正常省份 + 地点"""
        is_overseas = province == "海外"
        is_global = province == "全球"

        # 地点：仅普通省份时显示
        show_location = not is_overseas and not is_global
        self._set_row_visible(
            self._regional_location_label.widget(),
            self._regional_location_field.widget(),
            show_location,
        )
        if is_global:
            self._regional_location.setText("全球")
        else:
            self._regional_location.clear()
            if show_location:
                self._regional_location.setPlaceholderText("如：广州市、深圳市")

        # 海外/全球的特殊行
        if is_overseas:
            self._overseas_label.setText("国家:")
            self._overseas_stack.setCurrentIndex(1)  # country QLineEdit
        self._set_row_visible(self._overseas_label, self._overseas_stack, is_overseas)

    def _on_func_category_changed(self, category):
        """专题讨论时显示专题类型"""
        visible = category == "专题讨论"
        self._set_row_visible(
            self._func_topic_label.widget(),
            self._func_topic_field.widget(),
            visible,
        )
        if not visible:
            self._func_topic.setCurrentIndex(0)

    # ── 重复群号实时提示 ──

    def _on_gid_changed(self, text: str):
        """输入群号时实时显示前缀匹配的已有群"""
        text = text.strip()
        if len(text) < 3 or not self._existing:
            self._dup_list.hide()
            return

        matches = [
            (gid, name) for gid, name in self._existing.items()
            if gid.startswith(text)
        ]
        if not matches:
            self._dup_list.hide()
            return

        self._dup_list.clear()
        for gid, name in sorted(matches, key=lambda x: x[0]):
            item = QListWidgetItem(f"{gid} — {name}")
            if gid == text:
                item.setForeground(QColor("#FF6060"))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self._dup_list.addItem(item)

        self._dup_list.setVisible(True)
        # 限制列表高度：最多显示6条
        row_h = self._dup_list.sizeHintForRow(0)
        self._dup_list.setMaximumHeight(min(len(matches), 6) * (row_h + 4) + 4)

    # ── 验证 ──

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

    # ── 组装 CSV 行 ──

    def _build_entry(self):
        gid = (self._gid.text() or "").strip()
        name = (self._name.text() or "").strip()
        note = (self._note.text() or "").strip()
        cat = self._category_combo.currentText()

        if cat == "活动官方群":
            return {
                "群号": gid, "群名称": name, "大类": cat,
                "地区/小类": self._event_scope.currentText(),
                "子类": "",
                "地点": (self._event_location.text() or "").strip(),
                "学校": "",
                "活动名": (self._event_name.text() or "").strip(),
                "说明": note,
            }
        elif cat == "学校东方群":
            province = (self._school_province.currentText() or "").strip()
            return {
                "群号": gid, "群名称": name, "大类": cat,
                "地区/小类": province,
                "子类": "",
                "地点": province,
                "学校": (self._school_name.text() or "").strip(),
                "活动名": "",
                "说明": note,
            }
        elif cat == "地区性东方群":
            region = (self._regional_province.currentText() or "").strip()
            if region == "海外":
                location = (self._overseas_country.text() or "").strip()
            elif region == "全球":
                location = "全球"
            else:
                location = (self._regional_location.text() or "").strip()
            return {
                "群号": gid, "群名称": name, "大类": cat,
                "地区/小类": region,
                "子类": "",
                "地点": location,
                "学校": "",
                "活动名": "",
                "说明": note,
            }
        elif cat == "功能性公开群":
            topic = (self._func_topic.currentText() or "").strip() if self._func_category.currentText() == "专题讨论" else ""
            return {
                "群号": gid, "群名称": name, "大类": cat,
                "地区/小类": self._func_category.currentText(),
                "子类": topic,
                "地点": "",
                "学校": "",
                "活动名": "",
                "说明": note,
            }
        elif cat == "组织实体官方群":
            return {
                "群号": gid, "群名称": name, "大类": cat,
                "地区/小类": self._org_type.currentText(),
                "子类": "",
                "地点": "",
                "学校": "",
                "活动名": "",
                "说明": note,
            }
        else:  # 网络区域社群
            return {
                "群号": gid, "群名称": name, "大类": cat,
                "地区/小类": self._net_type.currentText(),
                "子类": "",
                "地点": "",
                "学校": "",
                "活动名": "",
                "说明": note,
            }

    # ── 提交 ──

    def _add_local_only(self):
        if not self._validate():
            return
        self._result_entry = self._build_entry()
        self._result_entry["_submit"] = "local"
        self.accept()

    def _add_and_submit(self):
        if not self._validate():
            return
        self._result_entry = self._build_entry()
        self._result_entry["_submit"] = "cloud"
        self.accept()

    def result(self) -> dict | None:
        return self._result_entry
