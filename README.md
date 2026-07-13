# 原初电台

[![License](https://img.shields.io/badge/license-MIT-red.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows-blue.svg)](#系统要求)

<img src="docs/logo.png" width="128" height="128" align="right">

东方 Project 主题的 QQ 群批量群发工具，基于 NapCat (OneBot v11) 协议。

通过本地注入 QQ NT 通道实现一键向数千个群发送消息，支持 CQ 码、断点续传、批量撤回、发送后监听回复等完整群发工作流。

## 功能

- **群列表管理** — 加载本地 CSV 按分类构建群树，支持全选/反选/搜索/右键复制群号，自动与 Bot 群列表取交集
- **一键群发** — 可配置发送间隔、随机抖动、批量暂停，支持图片/CQ 码/@ 等富文本消息
- **断点续传** — 发送中途关闭自动保存进度，下次打开可续发
- **批量撤回** — 一键撤回本轮所有已发消息
- **发送后监听** — 发送完成后自动监听群内 @Bot 及关键词回复，在 QQ 气泡面板中实时显示
- **双连接模式** — 程序管理 NapCat 进程（Windows 推荐）或连接外部 OneBot 服务（Mac/Linux 适用）
- **扫码/快速登录** — 通过 NapCat 拉起 QQ NT 通道，支持二维码扫码登录和 QQ 快捷登录
- **增量同步** — 对接云端服务器自动拉取最新群列表、提交新群
- **深色/浅色主题** — 默认深色，可切换

## 系统要求

| 项目 | 说明 |
|------|------|
| **操作系统** | Windows 10/11（NapCat 仅支持 Windows） |
| **QQ** | 已安装 QQ NT 客户端 |
| **网络** | 首次启动需下载 NapCat (~30MB)，后续离线可用 |

Mac/Linux 用户可使用「外部 OneBot 模式」，自行运行 [Lagrange.OneBot](https://github.com/LagrangeDev/Lagrange.Core) 等 OneBot 实现后连接。

## 快速开始

从 [Releases](https://github.com/Horikawa-Raiko/touhou-promoter/releases) 下载最新 `原初电台.exe`，双击运行。

**首次使用：**

1. 程序自动从 GitHub 下载 NapCat 到 `%APPDATA%/touhou-promoter/napcat/`
2. 点击「启动并登录」，弹出 QQ 窗口，扫码或快速登录
3. 通过「文件 → 打开 CSV」加载群列表
4. 左侧群树勾选目标群，右侧编辑消息，点击发送

**CSV 格式：**

```csv
群号,分类
123456789,东方同好群
987654321,车万社团
...
```

## 工作原理

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  原初电台    │────▶│   NapCat    │────▶│  QQ NT      │
│  (PyQt6)    │◀────│  (OneBot)   │◀────│  (注入)     │
└─────────────┘     └─────────────┘     └─────────────┘
   GUI + 引擎       HTTP/WS 协议        QQ 消息通道
```

程序通过 NapCat 注入 QQ NT 进程，以 OneBot v11 标准协议（HTTP API + WebSocket 事件）进行通信。消息发送、群列表获取、事件监听均走此通道，无需操作 QQ 客户端本身。

## 开发

```bash
git clone https://github.com/Horikawa-Raiko/touhou-promoter.git
cd touhou-promoter
pip install -r requirements.txt
python main.py
```

### 依赖

- Python 3.10+
- PyQt6 >= 6.5.0
- requests >= 2.28.0
- websocket-client >= 1.5.0
- qrcode >= 7.4.0
- Pillow >= 9.0.0

### 打包

```bash
pyinstaller touhou_promoter.spec --noconfirm --distpath Desktop
```

输出 `桌面/原初电台.exe`（~48MB，含 Python runtime + PyQt6）。

## 项目结构

```
main.py                          # 入口
touhou_promoter/
├── app.py                       # QApplication 启动流程
├── ui/
│   ├── main_window.py           # 主窗口（三栏布局 + 发送/撤回控制）
│   ├── workers.py               # QThread 工作线程
│   ├── listener_panel.py        # 发送后监听面板（QQ 气泡聊天视图）
│   ├── settings_dialog.py       # 设置对话框
│   └── add_group_dialog.py      # 添加群聊对话框
├── core/
│   ├── onebot_client.py         # OneBot v11 HTTP + WebSocket 客户端
│   ├── forwarding_engine.py     # 发送引擎（限速/抖动/断点续传）
│   ├── napcat_manager.py        # NapCat 子进程管理 + stdout 解析
│   ├── napcat_config.py         # OneBot 配置文件生成
│   ├── napcat_bootstrap.py      # NapCat 自动下载/解压
│   ├── csv_loader.py            # CSV 群列表解析 + 树结构构建
│   ├── group_model.py           # 群数据模型
│   ├── message_builder.py       # 消息编辑 + CQ 码构建
│   ├── post_send_listener.py    # WebSocket 回复监听
│   └── update_checker.py        # 云端增量同步 + 版本更新检查
├── state/
│   ├── app_state.py             # 全局信号总线
│   ├── config_manager.py        # 持久化配置管理
│   └── send_state.py            # 发送会话状态持久化
└── resources/
    └── prompt.json              # 一键群发提示词模板

server/
└── touhou-api.py                # 云端同步服务器（Flask API）
```

## 致谢

- [NapCat](https://github.com/NapNeko/NapCatQQ) — QQ NT 注入框架，提供 OneBot v11 协议
- [OneBot v11](https://github.com/botuniverse/onebot-11) — 聊天机器人标准协议
- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) — Python Qt 绑定
- 帮忙测试车万人 Thanks

## License

MIT
