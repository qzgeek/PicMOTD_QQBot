import asyncio
import json
import time
import random
import aiohttp
import base64
import io
from typing import Dict, Any, Optional
from datetime import datetime
from collections import defaultdict

# 导入项目中的模块（确保文件名正确）
from motd import MinecraftPinger, ServerInfo
from onebot_bridge import OneBot服务端, OneBot接口, 消息段
from status_card import MCServerStatusCardRenderer

# ------------------- 配置加载 -------------------
def load_config(config_path: str = "config.json") -> Dict[str, Any]:
    """加载配置文件"""
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)

config = load_config()

# ------------------- 频率限制器 -------------------
class RateLimiter:
    """基于群聊的请求频率限制"""
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window = window_seconds
        self.records = defaultdict(list)

    def is_allowed(self, group_id: int) -> bool:
        now = time.time()
        # 清理过期记录
        self.records[group_id] = [
            ts for ts in self.records[group_id]
            if now - ts < self.window
        ]
        if len(self.records[group_id]) < self.max_requests:
            self.records[group_id].append(now)
            return True
        return False

rate_limiter = RateLimiter(
    max_requests=config.get("rate_limit", {}).get("max_per_window", 3),
    window_seconds=config.get("rate_limit", {}).get("window_seconds", 60)
)

# ------------------- 随机延迟 -------------------
async def random_delay():
    """根据配置在发送消息前随机延迟一段时间，防止行为模式被识别"""
    delay_cfg = config.get("message_delay", {})
    if delay_cfg.get("enabled", False):
        min_sec = delay_cfg.get("min_seconds", 0.5)
        max_sec = delay_cfg.get("max_seconds", 2.0)
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)

# ------------------- 带延迟的消息发送封装 -------------------
async def send_group_message(api: OneBot接口, group_id: int, content, is_hint: bool = False):
    """
    发送群消息，自动处理随机延迟和提示文本开关。
    - content: 消息内容，字符串或消息段列表
    - is_hint: 是否为提示类消息（如"请求过于频繁"），受 send_hint_messages 开关控制
    """
    # 如果是提示消息且配置关闭提示，则直接返回不发送
    if is_hint and not config.get("send_hint_messages", True):
        return

    await random_delay()
    await api.发送群消息(group_id, content)

# ------------------- 系统资源获取 -------------------
async def fetch_cpu_usage(url: str) -> Optional[float]:
    """获取 CPU 占用百分比（直接返回数值）"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    return float(text.strip())
    except Exception:
        pass
    return None

async def fetch_mem_usage(url: str) -> Optional[float]:
    """获取内存占用百分比"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    return float(text.strip())
    except Exception:
        pass
    return None

# ------------------- 渲染卡片 -------------------
def build_status_card(
    server_info: ServerInfo,
    server_config: Dict[str, Any],
    cpu_usage: Optional[float],
    mem_usage: Optional[float],
    status_ok: bool,
    error_msg: str = ""
) -> io.BytesIO:
    """根据服务器信息渲染状态卡片，返回图片的 BytesIO 对象"""
    # 初始化渲染器
    renderer = MCServerStatusCardRenderer(
        canvas_size=tuple(config.get("card", {}).get("canvas_size", (1920, 600))),
        font_path=config.get("card", {}).get("font_path", "./LXGWWenKaiMono-Medium.ttf"),
        theme=config.get("card", {}).get("theme"),
        threshold=config.get("card", {}).get("threshold")
    )

    # 处理服务器图标（若无则生成一个默认纯色图标）
    from PIL import Image, ImageDraw
    if server_info.icon and server_info.online:
        icon_img = server_info.icon
    else:
        icon_img = Image.new("RGB", (190, 190), "#2C3E50")
        draw = ImageDraw.Draw(icon_img)
        draw.ellipse((10, 10, 180, 180), fill="#5D6D7E")

    # 处理背景图片
    bg_path = config.get("card", {}).get("background_path", "")
    if bg_path and __import__("os").path.exists(bg_path):
        bg_img = Image.open(bg_path)
    else:
        bg_img = Image.new("RGB", (renderer.canvas_w, renderer.canvas_h), "#1A252F")

    # 处理 MOTD 文本
    motd_text = server_info.motd if server_info.motd else "暂无 MOTD"

    # 底部声明信息
    bottom_lines = [
        f"查询时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}" if status_ok else f"异常：{error_msg}",
        "Write by 黔中极客"
    ]

    # 在线人数
    online_players = server_info.online_players if server_info.online else 0
    max_players = server_info.max_players if server_info.online else 0

    # CPU/内存值处理（异常时显示 -1.0，卡片会以红色显示）
    cpu_val = cpu_usage if cpu_usage is not None else -1.0
    mem_val = mem_usage if mem_usage is not None else -1.0

    # 确定显示的服务器地址：若经过 SRV 解析则仅显示域名，否则显示 host:port
    if server_info.resolved_host != server_info.host or server_info.resolved_port != server_info.port:
        # 经过了 SRV 解析，显示原始域名（不带端口）
        display_address = server_info.host
    else:
        # 未经过 SRV 解析，显示 host:port
        display_address = f"{server_info.host}:{server_info.port}"

    # 调用渲染器生成图片
    card_img = renderer.render(
        server_name=server_config.get("display_name", "Minecraft服务器") if status_ok else "连接失败",
        server_icon=icon_img,
        server_address=display_address,
        server_ping=int(server_info.latency) if server_info.online else 0,
        server_version=server_info.version if server_info.online else "离线",
        server_motd=motd_text,
        server_intro=server_config.get("description", "欢迎来到服务器"),
        online_players=online_players,
        max_players=max_players,
        bottom_declaration=bottom_lines,
        cpu_usage=cpu_val,
        mem_usage=mem_val,
        background=bg_img
    )

    # 转为 BytesIO 供发送
    img_bytes = io.BytesIO()
    card_img.save(img_bytes, format="PNG")
    img_bytes.seek(0)
    return img_bytes

async def handle_group_command(api: OneBot接口, group_id: int, user_id: int, message: str):
    """处理群聊命令"""
    cmd_trigger = config.get("command_trigger", "/状态")
    if message.strip() != cmd_trigger:
        return

    # 检查是否允许的群
    allowed_groups = config.get("allowed_groups", [])
    if allowed_groups and group_id not in allowed_groups:
        return

    # 频率限制
    if not rate_limiter.is_allowed(group_id):
        await send_group_message(api, group_id, "请求过于频繁，请稍后再试～", is_hint=True)
        return

    # 获取服务器配置
    server_cfg = config["minecraft_server"]
    host = server_cfg["host"]
    port = server_cfg.get("port", 25565)

    # 可选：发送“正在查询”提示（受提示开关控制）
    await send_group_message(api, group_id, "正在查询服务器状态，请稍候...", is_hint=True)

    # 异步获取 MOTD
    timeout_val = config.get("timeout", 3.0)
    pinger = MinecraftPinger(
        host=host,
        port=port,
        connect_timeout=timeout_val,
        read_timeout=timeout_val,
        debug=False
    )
    loop = asyncio.get_event_loop()
    server_info = await loop.run_in_executor(None, pinger.ping)

    # 并发获取系统资源
    cpu_task = fetch_cpu_usage(config["system_stats"]["cpu_url"])
    mem_task = fetch_mem_usage(config["system_stats"]["mem_url"])
    cpu_usage, mem_usage = await asyncio.gather(cpu_task, mem_task)

    # 判断整体状态
    status_ok = server_info.online and cpu_usage is not None and mem_usage is not None
    error_msg = ""
    if not server_info.online:
        error_msg = f"MOTD获取失败：{server_info.error}"
    elif cpu_usage is None:
        error_msg = "CPU占用获取失败"
    elif mem_usage is None:
        error_msg = "内存占用获取失败"

    # 渲染卡片
    try:
        img_bytes = build_status_card(
            server_info=server_info,
            server_config=server_cfg,
            cpu_usage=cpu_usage,
            mem_usage=mem_usage,
            status_ok=status_ok,
            error_msg=error_msg
        )
    except Exception as e:
        await send_group_message(api, group_id, f"渲染卡片时出错：{e}", is_hint=True)
        return

    # 发送图片（base64 格式）
    base64_img = base64.b64encode(img_bytes.read()).decode("utf-8")
    img_message = 消息段.图片(f"base64://{base64_img}")
    # 图片消息通常不算提示，直接发送（不受 hint 开关影响）
    await send_group_message(api, group_id, [img_message], is_hint=False)

# ------------------- 主函数 -------------------
async def main():
    # 创建 OneBot 服务端实例
    ws_config = config["onebot"]
    server = OneBot服务端(
        主机=ws_config["host"],
        端口=ws_config["port"],
        访问令牌=ws_config.get("access_token")
    )

    # 注册消息事件处理器
    @server.注册事件处理器
    async def on_message(event: dict):
        # 只处理群聊消息事件
        if event.get("post_type") != "message":
            return
        if event.get("message_type") != "group":
            return

        group_id = event["group_id"]
        user_id = event["user_id"]
        raw_message = event["raw_message"]

        # 从连接池中获取第一个客户端标识（适用于单客户端连接场景）
        if not server._连接池:
            return
        client_id = next(iter(server._连接池.keys()))
        api = OneBot接口(server, client_id)

        await handle_group_command(api, group_id, user_id, raw_message)

    print(f"OneBot 服务端启动在 ws://{ws_config['host']}:{ws_config['port']}")
    await server.启动服务()

if __name__ == "__main__":
    asyncio.run(main())