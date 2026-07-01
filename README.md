# 东方Project一键宣发姬

PyQt6 桌面应用，通过 NapCat（OneBot v11）一键向 QQ 群批量发送消息。

## 功能

- **群列表管理** — 加载本地 CSV，按分类勾选目标群，支持搜索/筛选/右键复制群号
- **一键群发** — 可配置发送间隔、间隔抖动、批量暂停，支持 CQ 码（图片、@等）
- **断点续传** — 发送中途退出自动保存进度，下次启动可继续
- **批量撤回** — 一键撤回本轮已发消息
- **发送后监听** — 发送完成后监听群内 @Bot 和关键词回复
- **QQ 登录** — 扫码登录 / 快速登录，由 NapCat 管理 QQ NT 通道
- **双连接模式** — 程序管理 NapCat 进程（Windows 推荐），或连接外部 OneBot 服务（Mac/Linux 适用）
- **深色/浅色主题** — 可切换，默认深色
- **单 exe 分发** — PyInstaller 打包，开箱即用

## 截图

> ![00431e6a5125d2e1008aa69edeb59a48.png](C:\Users\15752\Documents\Tencent%20Files\1575232594\nt_qq\nt_data\Pic\2026-06\Ori\00431e6a5125d2e1008aa69edeb59a48.png)
> 
> TODO

## 系统要求

- **操作系统**: Windows 10/11（NapCat 仅支持 Windows）
- **QQ**: 已安装 QQ NT 客户端
- **网络**: 首次启动需下载 NapCat（~30MB）

Mac/Linux 用户可使用「外部 OneBot 模式」，自行运行 [Lagrange.OneBot](https://github.com/LagrangeDev/Lagrange.Core) 等服务后连接。

## 快速开始

从 [Releases](../../releases) 下载最新 `东方Project一键宣发姬.exe`，双击运行。

首次启动时：

1. 程序自动从 GitHub 下载 NapCat 到 `%APPDATA%/touhou-promoter/napcat/`
2. 点击「启动并登录」，在弹出窗口中扫码或快速登录 QQ
3. 通过「文件 → 打开CSV」加载群列表
4. 在左侧群树勾选目标群，右侧编辑消息，点击「发送」

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
pyinstaller touhou_promoter.spec
```

输出在 `dist/东方Project一键宣发姬.exe`（~40MB）。

## 项目结构

```
main.py                          # 入口
touhou_promoter/
├── app.py                       # QApplication 启动流程
├── ui/
│   ├── main_window.py           # 主窗口（三栏布局）
│   ├── workers.py               # QThread 工作线程（发送/撤回）
│   ├── listener_panel.py        # 发送后监听面板
│   └── settings_dialog.py       # 设置对话框
├── core/
│   ├── onebot_client.py         # OneBot v11 HTTP + WebSocket 客户端
│   ├── forwarding_engine.py     # 发送引擎（批量/限速/断点）
│   ├── napcat_manager.py        # NapCat 子进程管理
│   ├── napcat_config.py         # OneBot 配置文件生成
│   ├── napcat_bootstrap.py      # NapCat 自动下载/解压
│   ├── csv_loader.py            # CSV 群列表解析
│   ├── group_model.py           # 群数据模型
│   ├── message_builder.py       # CQ 码构建
│   └── post_send_listener.py    # WebSocket 监听
└── state/
    ├── app_state.py             # 全局信号
    ├── config_manager.py        # 持久化配置
    └── send_state.py            # 发送会话持久化
```

## 致谢

- [NapCat](https://github.com/NapNeko/NapCatQQ) — QQ NT 注入框架，提供 OneBot v11 协议
- [OneBot v11](https://github.com/botuniverse/onebot-11) — 聊天机器人标准协议
- 开发时帮忙测试的各位

## License

MIT
