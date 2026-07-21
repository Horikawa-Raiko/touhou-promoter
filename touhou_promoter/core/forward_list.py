"""自定义转发列表 — 用户可从交集群中自行组配转发目标

持久化到 %APPDATA%/touhou-promoter/lists.json，更新时不会被覆盖。
"""

import json
import os
from dataclasses import dataclass, field


@dataclass
class ForwardListStore:
    """多个命名列表，每个列表是 {group_id: group_name} 的扁平字典"""
    active_list: str = "全部交集群"
    lists: dict[str, dict[str, str]] = field(default_factory=dict)

    # ---- 列表 CRUD ----

    def get_active_name(self) -> str:
        if self.active_list not in self.lists:
            self.active_list = next(iter(self.lists)) if self.lists else "全部交集群"
            if self.active_list not in self.lists:
                self.lists[self.active_list] = {}
        return self.active_list

    def get_active_targets(self) -> dict[str, str]:
        name = self.get_active_name()
        return self.lists.get(name, {})

    def get_active_count(self) -> int:
        return len(self.get_active_targets())

    def create_list(self, name: str):
        if name in self.lists:
            return False
        self.lists[name] = {}
        return True

    def delete_list(self, name: str) -> bool:
        if name not in self.lists:
            return False
        if len(self.lists) <= 1:
            return False
        del self.lists[name]
        if self.active_list == name:
            self.active_list = next(iter(self.lists))
        return True

    def rename_list(self, old: str, new: str) -> bool:
        if old not in self.lists or new in self.lists:
            return False
        self.lists[new] = self.lists.pop(old)
        if self.active_list == old:
            self.active_list = new
        return True

    def switch_active(self, name: str) -> bool:
        if name not in self.lists:
            return False
        self.active_list = name
        return True

    # ---- 群维护 ----

    def add_groups(self, groups: dict[str, str]):
        """批量添加群到当前激活列表。groups = {group_id: group_name}"""
        targets = self.get_active_targets()
        targets.update(groups)

    def remove_groups(self, group_ids: set[str]):
        """从当前列表删除指定群号"""
        targets = self.get_active_targets()
        for gid in group_ids:
            targets.pop(gid, None)

    def has_group(self, group_id: str) -> bool:
        return group_id in self.get_active_targets()

    # ---- 默认列表自动填充 ----

    def ensure_default_populated(self, intersection: dict[str, str]):
        """如果"全部交集群"为空，用交集填充"""
        default = self.lists.setdefault("全部交集群", {})
        if not default and intersection:
            default.update(intersection)


class ForwardListPersistence:
    """本地 JSON 持久化，与 ConfigManager 同目录"""

    def __init__(self, appdata_dir: str = ""):
        if not appdata_dir:
            appdata_dir = os.path.join(
                os.environ.get("APPDATA", os.path.expanduser("~")), "touhou-promoter"
            )
        os.makedirs(appdata_dir, exist_ok=True)
        self._path = os.path.join(appdata_dir, "lists.json")

    def load(self) -> ForwardListStore:
        if not os.path.exists(self._path):
            store = ForwardListStore()
            store.lists["全部交集群"] = {}
            return store
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ForwardListStore(
                active_list=data.get("active_list", "全部交集群"),
                lists=data.get("lists", {"全部交集群": {}}),
            )
        except (json.JSONDecodeError, TypeError):
            store = ForwardListStore()
            store.lists["全部交集群"] = {}
            return store

    def save(self, store: ForwardListStore):
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump({
                "active_list": store.active_list,
                "lists": store.lists,
            }, f, indent=2, ensure_ascii=False)
