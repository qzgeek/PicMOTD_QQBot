from PIL import Image, ImageDraw, ImageFont
import os
import warnings
from typing import Union, Tuple, List, Optional

# MC原生颜色代码映射（100%匹配游戏内颜色）
MC_COLORS = {
    "0": "#000000", "1": "#0000AA", "2": "#00AA00", "3": "#00AAAA",
    "4": "#AA0000", "5": "#AA00AA", "6": "#FFAA00", "7": "#AAAAAA",
    "8": "#555555", "9": "#5555FF", "a": "#55FF55", "b": "#55FFFF",
    "c": "#FF5555", "d": "#FF55FF", "e": "#FFFF55", "f": "#FFFFFF",
    "r": "#FFFFFF"
}

# 阈值配置（数值变色规则，和MC风格统一）
THRESHOLD = {
    "cpu_warning": 50,
    "cpu_danger": 80,
    "mem_warning": 50,
    "mem_danger": 80
}

# 卡片主题配色
DEFAULT_THEME = {
    "main_bg_mask": "#0F2540CC",
    "bottom_bar_bg": "#051225E0",
    "text_main": "#D0E0FF",
    "text_sub": "#B0C4DE",
    "text_bottom": "#607090",
    "success": "#55FF55",
    "warning": "#FFFF55",
    "danger": "#FF5555",
}

class MCServerStatusCardRenderer:
    """
    我的世界服务器状态卡渲染器
    【重要】所有图片资源必须由主程序传入PIL.Image对象，本模块不读取任何本地图片文件
    """

    def __init__(
            self,
            canvas_size: Tuple[int, int] = (1920, 600),
            font_path: str = "./LXGWWenKaiMono-Medium.ttf",
            theme: dict = None,
            threshold: dict = None
    ):
        self.canvas_w, self.canvas_h = canvas_size
        self.theme = theme if theme else DEFAULT_THEME
        self.threshold = threshold if threshold else THRESHOLD

        # 固定布局配置
        self.ICON_SIZE = (190, 190)
        self.ICON_RADIUS = 24
        self.LINE_GAP = 52                     # 行间距
        self.BOTTOM_BAR_HEIGHT = 75
        self.BASE_TEXT_LINES = 7               # 基础固定文本行数（不含玩家行）

        # 字体预加载
        self.fonts = self._init_fonts(font_path)

    def _init_fonts(self, custom_font_path: str) -> dict:
        if custom_font_path and os.path.exists(custom_font_path):
            font_file = custom_font_path
        else:
            font_candidates = [
                "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "C:/Windows/Fonts/msyhbd.ttc",
                "C:/Windows/Fonts/msyh.ttc",
                "C:/Windows/Fonts/simhei.ttf",
                "/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/STHeitiMedium.ttc",
            ]
            font_file = None
            for candidate in font_candidates:
                if os.path.exists(candidate):
                    font_file = candidate
                    break
            if not font_file:
                warnings.warn("未找到支持中文的系统字体，中文可能显示乱码", UserWarning)
                return self._get_default_fonts()

        try:
            return {
                "title": ImageFont.truetype(font_file, 48),
                "normal": ImageFont.truetype(font_file, 36),
                "motd": ImageFont.truetype(font_file, 40),
                "bottom": ImageFont.truetype(font_file, 24),
            }
        except Exception as e:
            warnings.warn(f"字体加载失败，使用默认字体：{str(e)}", UserWarning)
            return self._get_default_fonts()

    def _get_default_fonts(self) -> dict:
        default_font = ImageFont.load_default()
        return {k: default_font for k in ["title", "normal", "motd", "bottom"]}

    def _parse_mc_color_code(self, text: str) -> List[Tuple[str, str]]:
        if not text:
            return [("", MC_COLORS["f"])]
        segments = []
        current_text = ""
        current_color = MC_COLORS["f"]
        i = 0
        text_len = len(text)
        while i < text_len:
            if text[i] == "§" and i + 1 < text_len:
                if current_text:
                    segments.append((current_text, current_color))
                    current_text = ""
                color_code = text[i+1].lower()
                current_color = MC_COLORS.get(color_code, MC_COLORS["f"])
                i += 2
            else:
                current_text += text[i]
                i += 1
        if current_text:
            segments.append((current_text, current_color))
        return segments

    def _validate_and_process_image(self, img: Image.Image, target_size: Tuple[int, int] = None) -> Image.Image:
        if not isinstance(img, Image.Image):
            raise TypeError("图片必须传入PIL.Image.Image对象")
        img = img.convert("RGBA")
        if target_size:
            img = img.resize(target_size, Image.NEAREST)
        return img

    def _add_rounded_mask(self, img: Image.Image, radius: int) -> Image.Image:
        w, h = img.size
        mask = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((0, 0, w, h), radius=radius, fill=255)
        img.putalpha(mask)
        return img

    def _draw_colored_text(self, draw: ImageDraw.Draw, x: int, y: int, text: str, font: ImageFont.FreeTypeFont) -> int:
        segments = self._parse_mc_color_code(text)
        current_x = x
        for seg_text, seg_color in segments:
            if not seg_text:
                continue
            draw.text((current_x, y), seg_text, font=font, fill=seg_color, anchor="la")
            bbox = font.getbbox(seg_text, anchor="la")
            current_x += (bbox[2] - bbox[0]) if bbox else 0
        return current_x - x

    def _get_metric_color(self, value: float, metric_type: str) -> str:
        t = self.threshold
        if metric_type == "cpu":
            if value >= t["cpu_danger"]:
                return self.theme["danger"]
            elif value >= t["cpu_warning"]:
                return self.theme["warning"]
            else:
                return self.theme["success"]
        elif metric_type == "mem":
            if value >= t["mem_danger"]:
                return self.theme["danger"]
            elif value >= t["mem_warning"]:
                return self.theme["warning"]
            else:
                return self.theme["success"]
        return self.theme["success"]

    def _get_ping_color(self, ping: int) -> str:
        if ping <= 60:
            return self.theme["success"]
        elif ping <= 500:
            return self.theme["warning"]
        else:
            return self.theme["danger"]

    def render(
            self,
            server_name: str,
            server_icon: Image.Image,
            server_address: str,
            server_ping: int,
            server_version: str,
            server_motd: str,
            server_intro: str,
            online_players: int,
            max_players: int,
            bottom_declaration: List[str],
            cpu_usage: float,
            mem_usage: float,
            background: Image.Image,
            player_lines: Optional[List[str]] = None,   # 新增：玩家列表的多行文本
    ) -> Image.Image:
        """
        核心渲染方法
        :param player_lines: 玩家名称列表，每项为一行文本（已格式化好）
        """
        # 参数校验
        cpu_usage = max(0, min(100, float(cpu_usage)))
        mem_usage = max(0, min(100, float(mem_usage)))
        online_players = max(0, int(online_players))
        max_players = max(1, int(max_players))
        server_ping = max(0, int(server_ping))
        if player_lines is None:
            player_lines = []

        # 处理图片
        bg_img = self._validate_and_process_image(background)
        icon_img = self._validate_and_process_image(server_icon, self.ICON_SIZE)
        icon_img = self._add_rounded_mask(icon_img, self.ICON_RADIUS)

        # 背景裁剪与遮罩
        bg_ratio = bg_img.width / bg_img.height
        canvas_ratio = self.canvas_w / self.canvas_h
        if bg_ratio > canvas_ratio:
            new_h = self.canvas_h
            new_w = int(new_h * bg_ratio)
        else:
            new_w = self.canvas_w
            new_h = int(new_w / bg_ratio)
        bg_img = bg_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = (new_w - self.canvas_w) // 2
        top = (new_h - self.canvas_h) // 2
        bg_img = bg_img.crop((left, top, left + self.canvas_w, top + self.canvas_h))

        main_mask = Image.new("RGBA", (self.canvas_w, self.canvas_h - self.BOTTOM_BAR_HEIGHT), self.theme["main_bg_mask"])
        canvas = Image.alpha_composite(bg_img.convert("RGBA"), Image.new("RGBA", (self.canvas_w, self.canvas_h), (0,0,0,0)))
        canvas.paste(main_mask, (0, 0), mask=main_mask)
        draw = ImageDraw.Draw(canvas)

        # 计算总行数，动态调整垂直布局
        total_text_lines = self.BASE_TEXT_LINES + len(player_lines)
        total_text_height = total_text_lines * self.LINE_GAP

        # 图标垂直居中
        icon_x = 80
        main_content_height = self.canvas_h - self.BOTTOM_BAR_HEIGHT
        icon_y = (main_content_height - self.ICON_SIZE[1]) // 2
        icon_center_y = icon_y + self.ICON_SIZE[1] / 2
        canvas.paste(icon_img, (icon_x, icon_y), mask=icon_img)

        text_start_y = icon_center_y - total_text_height / 2
        text_x = icon_x + self.ICON_SIZE[0] + 45
        current_line_y = text_start_y
        font_normal = self.fonts["normal"]
        text_main = self.theme["text_main"]
        text_sub = self.theme["text_sub"]

        # 第1行：服务器名称
        draw.text((text_x, current_line_y), server_name, font=self.fonts["title"], fill=text_main, anchor="la")
        current_line_y += self.LINE_GAP

        # 第2行：IP + 延迟
        prefix = f"IP：{server_address} - 延迟 "
        draw.text((text_x, current_line_y), prefix, font=font_normal, fill=text_sub, anchor="la")
        prefix_width = font_normal.getbbox(prefix, anchor="la")[2] - font_normal.getbbox(prefix, anchor="la")[0]
        current_x = text_x + prefix_width
        ping_text = f"{server_ping}ms"
        ping_color = self._get_ping_color(server_ping)
        draw.text((current_x, current_line_y), ping_text, font=font_normal, fill=ping_color, anchor="la")
        current_line_y += self.LINE_GAP

        # 第3行：版本号
        version_text = f"版本: {server_version}"
        draw.text((text_x, current_line_y), version_text, font=font_normal, fill=text_sub, anchor="la")
        current_line_y += self.LINE_GAP

        # 第4行：MOTD
        self._draw_colored_text(draw, text_x, current_line_y, server_motd, self.fonts["motd"])
        current_line_y += self.LINE_GAP

        # 第5行：服务器介绍
        draw.text((text_x, current_line_y), server_intro, font=font_normal, fill=text_main, anchor="la")
        current_line_y += self.LINE_GAP

        # 第6行：在线人数
        player_text = f"在线人数: {online_players}/{max_players}"
        draw.text((text_x, current_line_y), player_text, font=font_normal, fill=text_sub, anchor="la")
        current_line_y += self.LINE_GAP

        # 第7行：CPU和内存
        cpu_color = self._get_metric_color(cpu_usage, "cpu")
        mem_color = self._get_metric_color(mem_usage, "mem")
        current_x = text_x
        draw.text((current_x, current_line_y), "CPU：", font=font_normal, fill=text_sub, anchor="la")
        current_x += font_normal.getbbox("CPU：", anchor="la")[2] - font_normal.getbbox("CPU：", anchor="la")[0]
        cpu_value = f"{cpu_usage:.1f}%"
        draw.text((current_x, current_line_y), cpu_value, font=font_normal, fill=cpu_color, anchor="la")
        current_x += font_normal.getbbox(cpu_value, anchor="la")[2] - font_normal.getbbox(cpu_value, anchor="la")[0]
        draw.text((current_x, current_line_y), "  -  ", font=font_normal, fill=text_sub, anchor="la")
        current_x += font_normal.getbbox("  -  ", anchor="la")[2] - font_normal.getbbox("  -  ", anchor="la")[0]
        draw.text((current_x, current_line_y), "内存：", font=font_normal, fill=text_sub, anchor="la")
        current_x += font_normal.getbbox("内存：", anchor="la")[2] - font_normal.getbbox("内存：", anchor="la")[0]
        mem_value = f"{mem_usage:.1f}%"
        draw.text((current_x, current_line_y), mem_value, font=font_normal, fill=mem_color, anchor="la")
        current_line_y += self.LINE_GAP

        # 第8行起：玩家列表（如果有）
        for line in player_lines:
            draw.text((text_x, current_line_y), line, font=font_normal, fill=text_sub, anchor="la")
            current_line_y += self.LINE_GAP

        # 底部声明栏
        draw.rounded_rectangle(
            (0, self.canvas_h - self.BOTTOM_BAR_HEIGHT, self.canvas_w, self.canvas_h),
            radius=0,
            fill=self.theme["bottom_bar_bg"]
        )
        bottom_text_y = self.canvas_h - self.BOTTOM_BAR_HEIGHT + 12
        bottom_line_gap = 28
        for i, line in enumerate(bottom_declaration):
            bbox = self.fonts["bottom"].getbbox(line, anchor="la")
            line_w = bbox[2] - bbox[0]
            line_x = (self.canvas_w - line_w) // 2
            draw.text(
                (line_x, bottom_text_y + i * bottom_line_gap),
                line,
                font=self.fonts["bottom"],
                fill=self.theme["text_bottom"],
                anchor="la"
            )

        return canvas.convert("RGBA")