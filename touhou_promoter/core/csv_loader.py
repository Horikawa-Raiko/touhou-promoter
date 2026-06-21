"""CSV解析 — 从东方QQ群列表.csv加载并构建树形结构"""
import csv
import os
from typing import List
from touhou_promoter.core.group_model import GroupRecord, TreeNode


def load_groups(csv_path: str) -> List[GroupRecord]:
    """解析CSV，返回所有GroupRecord。跳过空行和无效行。"""
    records: List[GroupRecord] = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            group_id = (row.get("群号") or "").strip()
            if not group_id:
                continue
            records.append(GroupRecord(
                category=(row.get("大类") or "").strip(),
                region=(row.get("地区/小类") or "").strip(),
                subcategory=(row.get("子类") or "").strip(),
                location=(row.get("地点") or "").strip(),
                school=(row.get("学校") or "").strip(),
                event_name=(row.get("活动名") or "").strip(),
                group_id=group_id,
                group_name=(row.get("群名称") or "").strip(),
                note=(row.get("说明") or "").strip(),
            ))
    return records


def build_tree(records: List[GroupRecord]) -> List[TreeNode]:
    """
    构建3级树: 大类 > 小类(分类键) > 具体群。
    小类键的优先级: region > school > event_name > 子类 > "其他"
    """
    # 按大类分组
    cats: dict[str, dict[str, list[GroupRecord]]] = {}
    for r in records:
        cat = r.category or "未分类"
        sub_key = _sub_key(r)
        cats.setdefault(cat, {}).setdefault(sub_key, []).append(r)

    roots: List[TreeNode] = []
    for cat_name in _category_order(cats.keys()):
        sub_map = cats[cat_name]
        cat_node = TreeNode(label=f"{cat_name} ({sum(len(v) for v in sub_map.values())})")
        for sub_name in sorted(sub_map):
            groups = sub_map[sub_name]
            sub_node = TreeNode(label=f"{sub_name} ({len(groups)})")
            for g in sorted(groups, key=lambda g: g.display_label()):
                sub_node.children.append(TreeNode(label=g.display_label(), group=g))
            cat_node.children.append(sub_node)
        roots.append(cat_node)

    return roots


def _sub_key(r: GroupRecord) -> str:
    """确定二级分类键"""
    if r.event_name:
        return r.event_name
    if r.school:
        return r.school
    if r.region:
        return r.region
    if r.subcategory:
        return r.subcategory
    return "其他"


def _category_order(cat_names: set[str]) -> List[str]:
    """按原始CSV的大类出现顺序排序（尽力保持语义分组）"""
    preferred = ["功能性公开群", "地区性东方群", "学校东方群", "活动官方群", "组织实体官方群", "网络区域社群"]
    result = [c for c in preferred if c in cat_names]
    result.extend(sorted(cat_names - set(preferred)))
    return result
