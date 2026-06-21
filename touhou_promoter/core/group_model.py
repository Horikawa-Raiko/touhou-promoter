"""群数据模型"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GroupRecord:
    """CSV中的单条群记录"""
    category: str           # 大类
    region: str             # 地区/小类
    subcategory: str        # 子类
    location: str           # 地点
    school: str             # 学校
    event_name: str         # 活动名
    group_id: str           # 群号
    group_name: str         # 群名称
    note: str               # 说明

    def display_label(self) -> str:
        """树节点显示文本"""
        name = self.group_name or self.event_name or self.school or f"群{self.group_id}"
        if self.location and self.location not in name:
            name = f"[{self.location}] {name}"
        return f"{name} ({self.group_id})"


@dataclass
class TreeNode:
    """群列表树节点（3级: 大类 > 小类 > 具体群）"""
    label: str
    group: Optional[GroupRecord] = None
    children: list["TreeNode"] = field(default_factory=list)
    checked: bool = False
    # Qt.ItemIsTristate 由 QTreeWidgetItem 原生支持，此处仅存储数据

    @property
    def is_leaf(self) -> bool:
        return self.group is not None

    @property
    def is_category(self) -> bool:
        return self.group is None and len(self.children) > 0

    def group_count(self) -> int:
        """递归统计叶子节点（群）数量"""
        if self.is_leaf:
            return 1
        return sum(c.group_count() for c in self.children)
