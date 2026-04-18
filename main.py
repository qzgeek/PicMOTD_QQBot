import asyncio
import json
import time
import random
import aiohttp
import base64
import io
import math
from typing import Dict, Any, Optional, List
from datetime import datetime
from collections import defaultdict

from motd import MinecraftPinger, ServerInfo
from onebot_bridge import OneBot服务端, OneBot接口, 消息段
from status_card import MCServerStatusCardRenderer

# ------------------- 配置加载 -------------------
def load_config(config_path: str = "config.json") -> Dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)

config = load_config()

# ------------------- 频率限制器 -------------------
class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window = window_seconds
        self.records = defaultdict(list)

    def is_allowed(self, group_id: int) -> bool:
        now = time.time()
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
    delay_cfg = config.get("message_delay", {})
    if delay_cfg.get("enabled", False):
        min_sec = delay_cfg.get("min_seconds", 0.5)
        max_sec = delay_cfg.get("max_seconds", 2.0)
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)

async def send_group_message(api: OneBot接口, group_id: int, content, is_hint: bool = False):
    if is_hint and not config.get("send_hint_messages", True):
        return
    await random_delay()
    await api.发送群消息(group_id, content)

# ------------------- 系统资源获取 -------------------
async def fetch_cpu_usage(url: str) -> Optional[float]:
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
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    return float(text.strip())
    except Exception:
        pass
    return None

# ------------------- 玩家列表处理 -------------------
def filter_and_format_players(
    players_sample: List[Dict[str, str]],
    player_list_config: Dict[str, Any]
) -> List[str]:
    """
    过滤假人、随机选取、格式化成多行文本
    返回每行字符串列表
    """
    if not player_list_config.get("enabled", False) or not players_sample:
        return []

    # 过滤排除项
    exclude_names = set(player_list_config.get("exclude_names", []))
    exclude_uuids = set(player_list_config.get("exclude_uuids", []))

    filtered = []
    for p in players_sample:
        name = p.get("name", "")
        uuid = p.get("id", "")
        # 按名称排除（支持子串匹配）
        if any(ex in name for ex in exclude_names):
            continue
        # 按UUID排除（精确匹配）
        if uuid in exclude_uuids:
            continue
        filtered.append(name)

    if not filtered:
        return []

    # 随机打乱
    random.shuffle(filtered)

    # 限制最大显示数量
    max_players = player_list_config.get("max_players", 24)
    if len(filtered) > max_players:
        filtered = filtered[:max_players]

    # 按最大行数折行
    max_lines = player_list_config.get("max_lines", 3)
    # 估算每行最大字符数（假设等宽字体，中文约2字符宽，这里粗略按1.2倍英文字符算）
    # 卡片宽度约1500，减去左侧留白，文本起始x=80+190+45=315，可用宽度约1100px
    # 36px字体，英文字符平均宽约18px，中文字符约36px，粗略估计每行最多约50个中文字符或100个英文字符
    # 为简化，我们用一个固定最大字符数，或者动态计算（这里用固定60个字符作为折行依据）
    max_chars_per_line = 60

    lines = []
    current_line = ""
    for name in filtered:
        # 添加玩家名，后面加逗号和空格
        segment = name + ", "
        # 如果当前行加上新名字会超长，则换行
        if len(current_line) + len(segment) > max_chars_per_line:
            if current_line:
                lines.append(current_line.rstrip(", "))
                current_line = ""
            # 若名字本身超长，直接作为独立行（极少见）
            if len(segment) > max_chars_per_line:
                lines.append(segment.rstrip(", "))
                continue
        current_line += segment

    if current_line:
        lines.append(current_line.rstrip(", "))

    # 限制最大行数
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        # 如果最后一行被截断，末尾加"..."
        if lines:
            lines[-1] = lines[-1] + "..."

    # 在每行前加 "在线玩家：" 作为第一行的前缀，后续行对齐缩进
    if lines:
        lines[0] = "在线玩家：" + lines[0]
        indent = "          "  # 10个空格，与"在线玩家："视觉对齐（可根据字体调整）
        for i in range(1, len(lines)):
            lines[i] = indent + lines[i]

    return lines

# ------------------- 渲染卡片 -------------------
def build_status_card(
    server_info: ServerInfo,
    server_config: Dict[str, Any],
    cpu_usage: Optional[float],
    mem_usage: Optional[float],
    status_ok: bool,
    error_msg: str = "",
    player_lines: List[str] = None
) -> io.BytesIO:
    if player_lines is None:
        player_lines = []

    renderer = MCServerStatusCardRenderer(
        canvas_size=tuple(config.get("card", {}).get("canvas_size", (1920, 600))),
        font_path=config.get("card", {}).get("font_path", "./LXGWWenKaiMono-Medium.ttf"),
        theme=config.get("card", {}).get("theme"),
        threshold=config.get("card", {}).get("threshold")
    )

    from PIL import Image, ImageDraw
    if server_info.icon and server_info.online:
        icon_img = server_info.icon
    else:
        icon_img = Image.new("RGB", (190, 190), "#2C3E50")
        draw = ImageDraw.Draw(icon_img)
        draw.ellipse((10, 10, 180, 180), fill="#5D6D7E")

    bg_path = config.get("card", {}).get("background_path", "")
    if bg_path and __import__("os").path.exists(bg_path):
        bg_img = Image.open(bg_path)
    else:
        bg_img = Image.new("RGB", (renderer.canvas_w, renderer.canvas_h), "#1A252F")

    motd_text = server_info.motd if server_info.motd else "暂无 MOTD"

    bottom_lines = [
        f"查询时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}" if status_ok else f"异常：{error_msg}",
        "Write by 黔中极客"
    ]

    online_players = server_info.online_players if server_info.online else 0
    max_players = server_info.max_players if server_info.online else 0
    cpu_val = cpu_usage if cpu_usage is not None else -1.0
    mem_val = mem_usage if mem_usage is not None else -1.0

    if server_info.resolved_host != server_info.host or server_info.resolved_port != server_info.port:
        display_address = server_info.host
    else:
        display_address = f"{server_info.host}:{server_info.port}"

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
        background=bg_img,
        player_lines=player_lines
    )

    img_bytes = io.BytesIO()
    card_img.save(img_bytes, format="PNG")
    img_bytes.seek(0)
    return img_bytes

# ------------------- 命令处理 -------------------
async def handle_group_command(api: OneBot接口, group_id: int, user_id: int, message: str):
    cmd_trigger = config.get("command_trigger", "/状态")
    if message.strip() != cmd_trigger:
        return

    allowed_groups = config.get("allowed_groups", [])
    if allowed_groups and group_id not in allowed_groups:
        return

    if not rate_limiter.is_allowed(group_id):
        await send_group_message(api, group_id, "请求过于频繁，请稍后再试～", is_hint=True)
        return

    server_cfg = config["minecraft_server"]
    host = server_cfg["host"]
    port = server_cfg.get("port", 25565)

    await send_group_message(api, group_id, "正在查询服务器状态，请稍候...", is_hint=True)

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

    cpu_task = fetch_cpu_usage(config["system_stats"]["cpu_url"])
    mem_task = fetch_mem_usage(config["system_stats"]["mem_url"])
    cpu_usage, mem_usage = await asyncio.gather(cpu_task, mem_task)

    status_ok = server_info.online and cpu_usage is not None and mem_usage is not None
    error_msg = ""
    if not server_info.online:
        error_msg = f"MOTD获取失败：{server_info.error}"
    elif cpu_usage is None:
        error_msg = "CPU占用获取失败"
    elif mem_usage is None:
        error_msg = "内存占用获取失败"

    # 处理玩家列表
    player_list_config = config.get("player_list", {})
    player_lines = []
    if server_info.online and player_list_config.get("enabled", False):
        player_lines = filter_and_format_players(server_info.players_sample, player_list_config)

    try:
        img_bytes = build_status_card(
            server_info=server_info,
            server_config=server_cfg,
            cpu_usage=cpu_usage,
            mem_usage=mem_usage,
            status_ok=status_ok,
            error_msg=error_msg,
            player_lines=player_lines
        )
    except Exception as e:
        await send_group_message(api, group_id, f"渲染卡片时出错：{e}", is_hint=True)
        return

    base64_img = base64.b64encode(img_bytes.read()).decode("utf-8")
    img_message = 消息段.图片(f"base64://{base64_img}")
    await send_group_message(api, group_id, [img_message], is_hint=False)

# ------------------- 主函数 -------------------
async def main():
    ws_config = config["onebot"]
    server = OneBot服务端(
        主机=ws_config["host"],
        端口=ws_config["port"],
        访问令牌=ws_config.get("access_token")
    )

    @server.注册事件处理器
    async def on_message(event: dict):
        if event.get("post_type") != "message":
            return
        if event.get("message_type") != "group":
            return

        group_id = event["group_id"]
        user_id = event["user_id"]
        raw_message = event["raw_message"]

        if not server._连接池:
            return
        client_id = next(iter(server._连接池.keys()))
        api = OneBot接口(server, client_id)

        await handle_group_command(api, group_id, user_id, raw_message)

    print(f"OneBot 服务端启动在 ws://{ws_config['host']}:{ws_config['port']}")
    await server.启动服务()

if __name__ == "__main__":
    asyncio.run(main())