# 🎮 Minecraft 服务器状态卡片查询 QQ_Bot

基于 OneBot 协议的 QQ 机器人，用于实时查询 Minecraft Java 版服务器状态，并生成包含 MOTD、玩家数量、延迟、系统负载等信息的高颜值状态卡片。

[![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![OneBot](https://img.shields.io/badge/OneBot-11-black?logo=data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAHAAAABwCAMAAADxPgR5AAAAXVBMVEUAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD///+3lT7cAAAAHXRSTlMAgMBAwECAwMCAgICBgoKCgICAwMDAwMDAwMDAwMCA/3gAAAD+SURBVHgB7dXBDoAgDIXhoxAEVPD+X9tqqWmTXrL5aPpLWRLX/4HpTczmzOcLZ2eWrXWtLaZUNsuybdu2bdu2bdu2bdu2bdu2j+P6/f55TfXbc84559zX/KfUPeccJfnpuecN/Q+BN0hImO4JEiZMmDBhwoQJEyZMmDBhwoQJEyZMmDBhwoQJEyZMmDBhwoQJEyZMmDBhwoQJEyZMmDBhwoQJEyZMmDBhwoQJEyZMmDBhwoQJEyZMmDBhwoQJEyZMmDBhwoQJEyZMmDBhwoQJEyZMmDBhwoQJEyZMmDBhwoQJEyZMmDBhwoQJEyZMmDBhwoQJEyZMmDBhwoQJEyZMmDBhwoQJEyZMnF7eAE1eE7J2kHfrAAAAAElFTkSuQmCC)](https://github.com/botuniverse/onebot-11)

## ✨ 特性

-   **🔌 标准 OneBot 协议**：理论上支持所有实现了 OneBot v11 标准的机器人框架（推荐使用 [NapCat](https://github.com/NapNeko/NapCatQQ)）。
-   **🖼️ 精美状态卡片**：使用 PIL (Pillow) 动态渲染服务器信息卡片，支持自定义主题、背景和字体。
-   **📊 系统状态监控**：可选的 C++ 微服务，用于获取机器人所在服务器的 CPU 和内存使用情况（你也可以自己修改以实现其他获取方式），并显示在卡片上。
-   **⏱️ 实时 Ping 值**：通过 TCP 握手和协议查询，准确测量与 Minecraft 服务器的延迟。
-   **🎨 完整 MOTD 解析**：支持 Minecraft 经典 `§` 颜色代码解析，还原游戏内彩色字体效果。
-   **⚙️ 灵活配置**：支持自定义命令触发词、速率限制、延迟发送和访问权限。
-   **🛡️ 速率限制**：内置基于滑动窗口的请求限流器，防止滥用。

## 📸 预览

机器人接收到命令后，会返回类似下方的卡片图片（示例）：

- 这里应该放一张图片

## 📁 项目结构

```

.
├── README.md
├── LICENSE
├── config.json            # 配置文件
├── main.py                # 主程序
├── motd.py                # Minecraft 服务器 Ping 库（支持SRV、IPv6等）
├── onebot_bridge.py       # 易用的 OneBot 接口封装，本项目只用到其中少量接口
├── status_card.py         # 卡片渲染引擎
├── requirements.txt       # Python 依赖列表
├── LXGWWenKaiMono-Medium.ttf      # 卡片的默认字体 
└── webApi
        ├── main.cpp       # (可选) C++ 系统监控微服务源码
        ├── httplib.h        # (可选) C++ 微服务依赖
        ├── build.sh       # (可选) C++ 微服务编译脚本
        └── sys_monitor    # (可选) C++ 系统监控微服务编译成品（基于Linux-x86-64）

```

## 🚀 快速开始

### 0. 环境要求

-   Python 3.8+
-   一个支持 OneBot v11 的机器人客户端（如 NapCat）

### 1. 配置机器人客户端

务必开启以下配置

- 反向 WebSocket 连接（WebSocket客户端）
- 数组（Array）格式上报消息
- 上报自身消息（report_self）


### 2. 安装 Python 依赖

1. 获取 requirements.txt
2. 执行下方命令安装

```bash
pip install -r requirements.txt
```

### 3. (可选) 启动系统监控服务

如果您希望在卡片上显示 CPU 和内存占用，需要启动一个提供数据的 HTTP 服务。项目提供了一个 C++ 实现。

这个 API 默认会开放在端口 **35008** 上，请确保该端口空闲，或**修改源码**并自行编译

若您知晓上述情况，可以直接运行已经编译好的 `sys_monitor`（基于Linux-x86-64）

若您因故需手动编译，可参考下方：

Linux / macOS:

```bash
# 编译
g++ -std=c++11 -pthread -o sys_monitor main.cpp

# 运行 (默认监听 0.0.0.0:35008)
./sys_monitor
```

Windows: 可以使用 Visual Studio 或 MinGW 编译 main.cpp，或自行实现返回 CPU/内存百分比的简单 HTTP 接口。

接口返回示例（/cpu、/mem，均返回百分比数值部分）：

```text
43.5
```

注意：如果您不需要显示系统状态，可以将 config.json 中的 cpu_url 和 mem_url 指向一个始终返回固定数值（如 0.0）的地址，或者在代码中修改逻辑。不过，为了卡片显示完整，建议配置好此项。

### 4. 配置 config.json

这是最关键的一步，请根据您的实际情况修改 config.json 文件。

```json
{
    "onebot": {
        "host": "0.0.0.0",           // 监听地址，一般保持 0.0.0.0
        "port": 10100,               // WebSocket 服务端口，需与 OneBot 客户端一致
        "access_token": "your_token" // 若 OneBot 客户端设置了 access_token，请填写
    },
    "allowed_groups": [1145141919810], // 允许使用机器人的群号列表，留空 [] 表示所有群
    "command_trigger": "服务器还活着吗", // 触发查询的指令 (不带斜杠，需要斜杠的可自行添加。支持中文)
    "rate_limit": {
        "max_per_window": 3,          // 时间窗口内最大请求次数
        "window_seconds": 60          // 时间窗口长度 (秒)
    },
    "timeout": 3.0,                   // MOTD 获取超时 (秒)
    "minecraft_server": {
        "host": "mc.example.com",     // Minecraft 服务器地址
        "port": 25565,                // Minecraft 服务器端口
        "display_name": "示例 服务器", // 卡片上显示的服务器名称
        "description": "> 这是一段平平无奇的介绍~~"
    },
    "system_stats": {
        "cpu_url": "http://127.0.0.1:35008/cpu", // 获取 CPU 用量的 API
        "mem_url": "http://127.0.0.1:35008/mem"  // 获取内存用量的 API
    },
    "card": {
        "canvas_size": [1500, 600],     // 卡片尺寸 (宽, 高)
        "font_path": "./LXGWWenKaiMono-Medium.ttf", // 字体路径 (强烈建议指定)
        "background_path": "./background.png", // 自定义背景图片路径
        "theme": { ... },              // 主题颜色配置
        "threshold": { ... }           // CPU/内存告警阈值
    },
    "message_delay": {
        "enabled": true,               // 是否启用发送前随机延迟
        "min_seconds": 0.5,
        "max_seconds": 5.0
    },
    "send_hint_messages": false        // 是否发送 "正在查询..." 等提示语
}
```



### 5. 运行机器人

```bash
python main.py
```

启动后，您会看到控制台输出类似：

```
[OneBot] 服务端启动于 ws://0.0.0.0:10100
[OneBot] 客户端 127.0.0.1:54321 已连接
```

此时，在您配置的 QQ 群内发送 `服务器还活着吗`，机器人便会开始查询并返回服务器状态卡片。

## 🛠️ 自定义与扩展

### 更改字体

1. 下载您喜欢的中文 TrueType 字体（.ttf 文件）。
2. 将其放置在项目目录下，并修改 config.json 中的 card.font_path 路径。

### 更换背景图片

1. 准备一张尺寸与 canvas_size 比例相近的图片（推荐 16:9）。
2. 修改 config.json 中的 card.background_path 路径。

### 修改卡片主题颜色

在 config.json 的 card.theme 对象中，您可以自定义所有颜色。颜色值支持常见的 CSS 颜色格式（如 #RRGGBB 或 #RRGGBBAA）。

### 添加更多命令

您可以在 main.py 的 handle_group_command 函数中添加更多触发词和相应的处理逻辑。

## ❓ 常见问题

### Q: 机器人连接成功后，发送命令没有反应？

· 检查 config.json 中的 allowed_groups 是否包含当前群号。
· 检查发送的消息是否与 command_trigger 完全匹配。
· 确认 OneBot 客户端已正常登录 QQ 并接收消息。

### Q: 卡片中的中文显示为方块或乱码？

· 这是由于缺少中文字体。请务必在 config.json 的 card.font_path 中指定一个支持中文的 .ttf 字体文件路径。项目推荐使用 LXGW WenKai 或 Noto Sans CJK。

### Q: CPU/内存信息显示为 -1.0% 或异常？

· 这表示机器人无法从 cpu_url / mem_url 获取到正确的数据。
· 请检查 C++ 监控服务是否正在运行，端口是否被占用，以及防火墙设置。
· 您可以在浏览器中直接访问 http://127.0.0.1:35008/cpu 来测试接口是否正常，亦或者在命令行中执行：`curl http://127.0.0.1:35008/cpu`

### Q: 如何对接其他 OneBot 实现（如 LLOneBot）？

· 在 LLOneBot 的设置中，开启“反向 WebSocket 服务”，将端口设置为 config.json 中 onebot.port 的值（例如 10100），并确保 access_token 匹配以及符合快速开始中的配置要求即可。

### Q：为什么很多时候服务器图标不显示

· 服务器的图标通过Motd获取，很多时候网络波动或其他一些原因都可能导致服务器图标获取失败，再次尝试即可。

## 📄 许可证

本项目仅供学习交流使用，请勿用于非法用途。代码中引用的 Minecraft 协议部分遵循其原始许可。

## 🙏 致谢

· OneBot - 统一的聊天机器人应用接口标准
· Pillow - Python 图像处理库
· NapCat - 优秀的 OneBot 实现
· 霞鹜文楷 - 优秀的开源中文字体
![霞鹜文楷](https://raw.githubusercontent.com/lxgw/LxgwWenKai/main/documentation/wenkai-1.png)
