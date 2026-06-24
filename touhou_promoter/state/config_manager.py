"""持久化配置 — %APPDATA%/touhou-promoter/config.json"""
import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class AppConfig:
    """可持久化的应用配置"""
    napcat_path: str = ""                    # NapCat可执行文件路径
    csv_path: str = ""                       # CSV文件路径
    send_interval: float = 0.9               # 每条消息间隔（秒）
    send_interval_jitter: float = 0.1        # 间隔抖动（秒）
    batch_pause_every: int = 10              # 每N条暂停一次
    batch_pause_seconds: int = 5             # 暂停秒数
    recall_interval: float = 0.6             # 撤回间隔（秒）
    listener_expiry_seconds: int = 1200      # 发送后监听过期时间（秒），默认20分钟
    last_self_id: str = ""                   # 上次登录的QQ号
    last_self_nick: str = ""                 # 上次登录的QQ昵称
    cached_accounts: list = field(default_factory=list)  # [(qq, nickname), ...] 缓存的快登账号
    last_token_path: str = ""                # 上次NapCat token路径（复用登录）
    dark_mode: bool = True                   # 深色/浅色主题（默认深色）
    # LLM配置
    local_model_path: str = ""               # 本地GGUF模型路径
    local_n_ctx: int = 2048                  # 本地模型上下文窗口
    local_n_threads: int = 4                 # 本地模型推理线程数
    cloud_endpoint: str = ""                 # 云端API端点
    cloud_api_key: str = ""                  # 云端API密钥
    cloud_model: str = ""                    # 云端模型名
    cloud_max_tokens: int = 256              # 云端最大token数


class ConfigManager:
    """读写 %APPDATA%/touhou-promoter/config.json"""

    DIR: str = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "touhou-promoter")

    def __init__(self):
        os.makedirs(self.DIR, exist_ok=True)
        self._path = os.path.join(self.DIR, "config.json")
        self._config: AppConfig = self._load()

    @property
    def config(self) -> AppConfig:
        return self._config

    def save(self):
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(asdict(self._config), f, indent=2, ensure_ascii=False)

    def _load(self) -> AppConfig:
        if not os.path.exists(self._path):
            return AppConfig()
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return AppConfig(**{k: v for k, v in data.items() if k in AppConfig.__dataclass_fields__})
        except (json.JSONDecodeError, TypeError):
            return AppConfig()

    def state_dir(self) -> str:
        """发送状态持久化目录"""
        return self.DIR
