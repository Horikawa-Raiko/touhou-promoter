"""NapCat OneBot v11 配置自动生成

NapCat 启动前需要正确的配置文件。本模块负责：
- 首次启动时自动生成 onebot11_<qq>.json
- 非首次启动复用已有配置（仅更新端口等关键字段）
"""

import json
import os
from typing import Optional


def set_auto_login_account(napcat_root: str, qq: str):
    """在 webui.json 中设置/清除 autoLoginAccount。

    qq 非空时写入，为空时删除该 key 以确保 NapCat 进入扫码模式。
    """
    config_dir = find_napcat_config_dir(napcat_root)
    webui_path = os.path.join(config_dir, "webui.json")
    config = {}
    if os.path.isfile(webui_path):
        try:
            with open(webui_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    if qq:
        config["autoLoginAccount"] = qq
    else:
        config.pop("autoLoginAccount", None)
    os.makedirs(os.path.dirname(webui_path), exist_ok=True)
    with open(webui_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


ONEBOX_CONFIG_TEMPLATE = {
    "network": {
        "httpServers": [
            {
                "name": "touhou-promoter-http",
                "enable": True,
                "port": 5700,
                "host": "127.0.0.1",
                "enableCors": True,
                "enableWebsocket": True,
                "enableHeart": True,
                "heartInterval": 30000,
                "postUrls": [],
                "secret": "",
                "rateLimit": {"enabled": False, "count": 10, "duration": 1000},
                "postMessageFormat": "array",
                "reportSelfMessage": False,
                "accessToken": "",
                "timeout": 30000,
            }
        ],
        "wsServers": [
            {
                "name": "touhou-promoter-ws",
                "enable": True,
                "port": 5701,
                "host": "127.0.0.1",
                "enableHeart": True,
                "heartInterval": 30000,
                "accessToken": "",
            }
        ],
        "wsReverseServers": [],
    },
    "musicSignUrl": "",
    "heartInterval": 30000,
    "enableLocalFile2Url": True,
    "parseMultMsg": True,
    "reportSelfMessage": False,
    "token": "",
}


def find_napcat_config_dir(napcat_root: str) -> Optional[str]:
    """在 napcat 根目录下查找 config 目录。
    NapCat 的 OneBot 配置在 napcat/config/ 下。
    """
    candidates = [
        os.path.join(napcat_root, "napcat", "config"),
        os.path.join(napcat_root, "config"),
        os.path.join(napcat_root, "QQ", "exe", "config"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    # 未找到则默认使用 napcat/config
    default = os.path.join(napcat_root, "napcat", "config")
    os.makedirs(default, exist_ok=True)
    return default


def list_existing_onebot_configs(napcat_root: str) -> list[str]:
    """列出 napcat 目录下已有的 onebot11_*.json 配置"""
    config_dir = find_napcat_config_dir(napcat_root)
    if not config_dir or not os.path.isdir(config_dir):
        return []
    result = []
    for fn in os.listdir(config_dir):
        if fn.startswith("onebot11_") and fn.endswith(".json"):
            result.append(os.path.join(config_dir, fn))
    return sorted(result)


def generate_onebot_config(
    napcat_root: str,
    qq: str = "",
    http_port: int = 5700,
    ws_port: int = 5701,
    reuse_existing: bool = True,
) -> str:
    """生成/更新所有 OneBot v11 配置文件，确保 HTTP/WS 服务器配置存在。

    NapCat 会为每个账号创建 onebot11_<qq>.json，但这些文件默认
    服务器数组为空。此函数强制所有 onebot11_*.json 都包含正确配置。
    """
    config_dir = find_napcat_config_dir(napcat_root)
    config = dict(ONEBOX_CONFIG_TEMPLATE)
    config["network"]["httpServers"][0]["port"] = http_port
    config["network"]["wsServers"][0]["port"] = ws_port

    # 更新已有的所有 onebot11_*.json 文件
    existing = list_existing_onebot_configs(napcat_root)
    if existing:
        for path in existing:
            _ensure_onebot_servers(path, http_port, ws_port)
        return existing[0]

    # 没有已有配置则新建
    filename = f"onebot11_{qq}.json" if qq else "onebot11_default.json"
    config_path = os.path.join(config_dir, filename)
    _write_config(config_path, config)
    return config_path


def _ensure_onebot_servers(config_path: str, http_port: int, ws_port: int):
    """确保 OneBot 配置文件中有正确的 HTTP/WS 服务器配置。

    NapCat 为每个账号自动生成的 onebot11_<qq>.json 默认
    httpServers/wsServers 为空数组，需要强制写入。
    """
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        config = {}

    network = config.setdefault("network", {})

    # HTTP 服务器
    http_servers = network.get("httpServers")
    if not isinstance(http_servers, list) or len(http_servers) == 0:
        network["httpServers"] = [{
            "name": "touhou-promoter-http",
            "enable": True,
            "port": http_port,
            "host": "127.0.0.1",
            "enableCors": True,
            "enableWebsocket": True,
            "enableHeart": True,
            "heartInterval": 30000,
            "postUrls": [],
            "secret": "",
            "rateLimit": {"enabled": False, "count": 10, "duration": 1000},
            "postMessageFormat": "array",
            "reportSelfMessage": False,
            "accessToken": "",
            "timeout": 30000,
        }]
    else:
        for srv in http_servers:
            srv["port"] = http_port
            srv["host"] = srv.get("host", "127.0.0.1")
            srv["enable"] = True

    # WebSocket 服务器（NapCat 可能读 websocketServers 或 wsServers，两个都写）
    for ws_key in ("websocketServers", "wsServers"):
        ws_servers = network.get(ws_key)
        if not isinstance(ws_servers, list) or len(ws_servers) == 0:
            network[ws_key] = [{
                "name": "touhou-promoter-ws",
                "enable": True,
                "port": ws_port,
                "host": "127.0.0.1",
                "enableHeart": True,
                "heartInterval": 30000,
                "accessToken": "",
            }]
        else:
            for srv in ws_servers:
                srv["port"] = ws_port
                srv["host"] = srv.get("host", "127.0.0.1")
                srv["enable"] = True

    network.setdefault("enableLocalFile2Url", True)
    network.setdefault("parseMultMsg", True)

    _write_config(config_path, config)


def _write_config(config_path: str, config: dict):
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def find_napcat_executable(napcat_root: str) -> Optional[str]:
    """在 napcat 目录下查找可启动文件。

    NapCat 通过 bat 脚本启动（注入 QQ 客户端），不是独立的 exe。
    返回 launcher-user.bat 路径。
    """
    candidates = [
        os.path.join(napcat_root, "napcat", "launcher-user.bat"),
        os.path.join(napcat_root, "napcat", "launcher.bat"),
        os.path.join(napcat_root, "napcat", "launcher-win10-user.bat"),
        os.path.join(napcat_root, "napcat", "launcher-win10.bat"),
        os.path.join(napcat_root, "napcat.bat"),
        # 旧版可能的路径
        os.path.join(napcat_root, "napcat.exe"),
        os.path.join(napcat_root, "NapCat.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None
