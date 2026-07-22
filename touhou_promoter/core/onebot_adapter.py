"""OneBot 适配器 — 从服务器插件移植的工具函数（同步化）

包含:
- 响应解析 (_unwrap_onebot_response, _is_onebot_ok_response)
- 掉线检测 (_is_likely_offline_error)
- 群可达性探测 (_probe_group_access)
- 机器人成员探测 (_probe_bot_member)
"""

from typing import Optional

from touhou_promoter.core.onebot_client import OneBotHTTPClient, OneBotAPIError


def unwrap_onebot_response(data):
    """剥离 OneBot 响应的 data 包装层"""
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], (dict, list)):
        return data["data"]
    return data


def is_onebot_ok_response(data) -> bool:
    """判断 OneBot API 响应是否为成功"""
    if data is None:
        return False
    if not isinstance(data, dict):
        return True
    status = str(data.get("status", "")).lower()
    if status and status not in ("ok", "async"):
        return False
    retcode = data.get("retcode")
    if isinstance(retcode, int) and retcode != 0:
        return False
    if isinstance(retcode, str) and retcode.isdigit() and int(retcode) != 0:
        return False
    if data.get("wording") and status == "failed":
        return False
    return True


def is_likely_offline_error(err_text: str) -> bool:
    """判断错误文本是否指示掉线"""
    text = str(err_text or "").lower()
    if not text:
        return False
    keys = [
        "offline", "not online",
        "connection refused", "connection reset", "connection closed",
        "reset by peer", "broken pipe",
        "unreachable", "network is unreachable",
        "disconnect", "not logged",
        "session is closed",
        "[winerror 10061]",  # Windows: 由于目标计算机积极拒绝，无法连接
        "websocket closed",
        "no connection could be made",
    ]
    return any(k in text for k in keys)


def probe_group_access(
    client: OneBotHTTPClient,
    group_id: str,
    self_id: str = "",
) -> tuple[bool, Optional[str], Optional[str]]:
    """探测群可达性 + 机器人是否在群内。

    Returns:
        (can_access, group_name_or_None, error_reason_or_None)
    """
    # Step 1: get_group_info
    group_id_num = int(group_id) if group_id.isdigit() else group_id
    payloads = [
        {"group_id": group_id_num, "no_cache": False},
        {"group_id": group_id_num},
        {"group_id": group_id},
    ]

    info_ok = False
    group_name = None
    last_error = None

    for payload in payloads:
        try:
            result = client._call("get_group_info", payload)
            if is_onebot_ok_response(result):
                info_ok = True
                data = unwrap_onebot_response(result)
                if isinstance(data, dict):
                    group_name = data.get("group_name") or data.get("name")
                break
        except OneBotAPIError as e:
            last_error = str(e)
            continue
        except Exception as e:
            last_error = str(e)
            break

    if not info_ok:
        return False, None, last_error or "get_group_info 返回失败"

    # Step 2: get_group_member_info 确认机器人在群内
    if not self_id:
        try:
            self_id = client.get_self_id()
        except Exception:
            return False, group_name, "无法获取 self_id"

    member_ok, member_reason = _probe_bot_member(client, group_id, self_id)
    if member_ok:
        return True, group_name, None

    return False, group_name, member_reason or "无法确认机器人在该群内"


def _probe_bot_member(
    client: OneBotHTTPClient, group_id: str, self_id: str
) -> tuple[Optional[bool], Optional[str]]:
    """探测机器人自身是否在群内"""
    user_id_num = int(self_id) if self_id.isdigit() else self_id
    group_id_num = int(group_id) if group_id.isdigit() else group_id

    payloads = [
        {"group_id": group_id_num, "user_id": user_id_num, "no_cache": False},
        {"group_id": group_id_num, "user_id": user_id_num},
        {"group_id": group_id, "user_id": self_id, "no_cache": False},
        {"group_id": group_id, "user_id": self_id},
    ]

    for payload in payloads:
        try:
            result = client._call("get_group_member_info", payload)
            if not is_onebot_ok_response(result):
                continue
            info = unwrap_onebot_response(result)
            if isinstance(info, dict):
                uid = str(info.get("user_id") or "")
                if uid and uid == str(self_id):
                    return True, None
        except Exception:
            continue

    return None, "未匹配到机器人成员信息"


def build_intersection(
    client: OneBotHTTPClient, csv_group_ids: set[str]
) -> tuple[set[str], dict[str, str]]:
    """取 CSV 群号和 bot 实际加入群的交集。

    Returns:
        (intersected_group_ids, group_id_to_name)
    """
    try:
        joined = client.get_group_list()
    except Exception:
        return set(), {}

    joined_ids: set[str] = set()
    id_to_name: dict[str, str] = {}
    for g in joined:
        gid = str(g.get("group_id", ""))
        if gid:
            joined_ids.add(gid)
            id_to_name[gid] = g.get("group_name", "") or f"群{gid}"

    intersection = csv_group_ids & joined_ids
    result_names = {gid: id_to_name.get(gid, f"群{gid}") for gid in intersection}
    return intersection, result_names
