from PIL import Image, ImageDraw, ImageFont
import os
import warnings
from typing import Union, Tuple, List

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
    "cpu_warning": 50,  # CPU占用超50%变黄
    "cpu_danger": 80,   # CPU占用超80%变红
    "mem_warning": 50,  # 内存占用超50%变黄
    "mem_danger": 80    # 内存占用超80%变红
}

# 卡片主题配色（全区域风格统一，适配大字体）
DEFAULT_THEME = {
    "main_bg_mask": "#0F2540CC",        # 主区域背景遮罩
    "bottom_bar_bg": "#051225E0",       # 底部声明栏背景（低不透明度，弱化存在感）
    "text_main": "#D0E0FF",             # 主文本色
    "text_sub": "#B0C4DE",              # 副文本色
    "text_bottom": "#607090",           # 底部声明文本色（淡化，和主文本强区分）
    "success": "#55FF55",               # 正常状态绿色
    "warning": "#FFFF55",               # 警告状态黄色
    "danger": "#FF5555",                # 危险状态红色
}

class MCServerStatusCardRenderer:
    """
    我的世界服务器状态卡渲染器
    【重要】所有图片资源必须由主程序传入PIL.Image对象，本模块不读取任何本地图片文件
    全局仅需实例化1次，多次调用render()复用实例，极致渲染效率
    """

    def __init__(
            self,
            canvas_size: Tuple[int, int] = (1920, 600),
            font_path: str = "./LXGWWenKaiMono-Medium.ttf",
            theme: dict = None,
            threshold: dict = None
    ):
        """
        初始化渲染器
        :param canvas_size: 生成图片的宽高
        :param font_path: 自定义字体路径（推荐带粗体的中文字体，如LXGW WenKai Bold）
        :param theme: 自定义配色字典，覆盖默认配色
        :param threshold: 自定义阈值字典，覆盖默认阈值
        """
        self.canvas_w, self.canvas_h = canvas_size
        self.theme = theme if theme else DEFAULT_THEME
        self.threshold = threshold if threshold else THRESHOLD

        # 固定布局配置（适配垂直居中+宽松阅读）
        self.ICON_SIZE = (190, 190)          # 服务器图标尺寸
        self.ICON_RADIUS = 24                 # 图标圆角，保持圆润风格
        self.LINE_GAP = 52                    # 宽松行间距，适配大字体无拥挤
        self.BOTTOM_BAR_HEIGHT = 75           # 底部声明栏高度
        self.TEXT_LINE_COUNT = 7              # 固定文本行数，用于计算总高度

        # 字体预加载（全量调大+加粗优先，核心提升阅读体验）
        self.fonts = self._init_fonts(font_path)

    def _init_fonts(self, custom_font_path: str) -> dict:
        """初始化字体，自动适配多系统中文字体，全量调大字号提升可读性"""
        # 优先使用用户自定义字体
        if custom_font_path and os.path.exists(custom_font_path):
            font_file = custom_font_path
        else:
            # 多系统中文字体兜底（Linux服务器优先适配，按优先级排序）
            font_candidates = [
                # Linux 服务器环境优先
                "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                # Windows
                "C:/Windows/Fonts/msyhbd.ttc",
                "C:/Windows/Fonts/msyh.ttc",
                "C:/Windows/Fonts/simhei.ttf",
                # macOS
                "/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/STHeitiMedium.ttc",
            ]
            font_file = None
            for candidate in font_candidates:
                if os.path.exists(candidate):
                    font_file = candidate
                    break
            if not font_file:
                warnings.warn("未找到支持中文的系统字体，中文可能显示乱码，建议手动指定font_path", UserWarning)
                return self._get_default_fonts()

        # 全量调大字号，核心内容优先加粗，大幅提升阅读舒适度
        try:
            return {
                "title": ImageFont.truetype(font_file, 48),       # 服务器名称
                "normal": ImageFont.truetype(font_file, 36),      # IP/版本/人数/CPU/内存（统一字体）
                "motd": ImageFont.truetype(font_file, 40),        # MOTD彩色文本
                "bottom": ImageFont.truetype(font_file, 24),      # 底部声明（远小于主字体）
            }
        except Exception as e:
            warnings.warn(f"字体加载失败，使用默认字体：{str(e)}", UserWarning)
            return self._get_default_fonts()

    def _get_default_fonts(self) -> dict:
        """兜底默认字体（不支持中文）"""
        default_font = ImageFont.load_default()
        return {k: default_font for k in ["title", "normal", "motd", "bottom"]}

    def _parse_mc_color_code(self, text: str) -> List[Tuple[str, str]]:
        """解析MC的§颜色代码，返回(文本片段, 颜色代码)的列表"""
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
        """
        【仅处理主程序传入的Image对象，不读取任何本地文件】
        校验图片格式，统一转为RGBA。
        对于服务器图标，强制用NEAREST插值放大到target_size，保证像素点清晰无模糊。
        """
        if not isinstance(img, Image.Image):
            raise TypeError("图片必须传入PIL.Image.Image对象，本模块不读取本地文件路径，请主程序提前打开图片")
        img = img.convert("RGBA")
        if target_size:
            # 使用最近邻插值强制放大，保留像素风格（64x64 -> 190x190，每个像素点清晰可见）
            img = img.resize(target_size, Image.NEAREST)
        return img

    def _add_rounded_mask(self, img: Image.Image, radius: int) -> Image.Image:
        """给图片添加圆角蒙版，保持圆润风格统一"""
        w, h = img.size
        mask = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((0, 0, w, h), radius=radius, fill=255)
        img.putalpha(mask)
        return img

    def _draw_colored_text(self, draw: ImageDraw.Draw, x: int, y: int, text: str, font: ImageFont.FreeTypeFont) -> int:
        """绘制带MC彩色代码的文本，返回绘制完成后的总宽度，使用la锚点保证垂直对齐"""
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
        """根据阈值获取指标对应的颜色，适配MC风格预警"""
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
        """根据延迟值返回对应颜色：≤60绿，60~500黄，>500红"""
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
    ) -> Image.Image:
        """
        核心渲染方法，传入服务器参数生成状态卡
        【重要】server_icon 和 background 必须传入 PIL.Image.Image 对象，本模块不读取本地文件
        """
        # -------------------------- 1. 参数校验与预处理 --------------------------
        cpu_usage = max(0, min(100, float(cpu_usage)))
        mem_usage = max(0, min(100, float(mem_usage)))
        online_players = max(0, int(online_players))
        max_players = max(1, int(max_players))
        server_ping = max(0, int(server_ping))

        # 校验并处理图片（仅处理主程序传入的Image对象，不读取任何文件）
        bg_img = self._validate_and_process_image(background)
        # 图标强制放大到ICON_SIZE，并用最近邻保留像素感
        icon_img = self._validate_and_process_image(server_icon, self.ICON_SIZE)
        icon_img = self._add_rounded_mask(icon_img, self.ICON_RADIUS)

        # -------------------------- 2. 画布与背景初始化 --------------------------
        # 背景图等比缩放+居中裁剪，铺满画布无变形
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

        # 添加主区域背景遮罩
        main_mask = Image.new("RGBA", (self.canvas_w, self.canvas_h - self.BOTTOM_BAR_HEIGHT), self.theme["main_bg_mask"])
        canvas = Image.alpha_composite(bg_img.convert("RGBA"), Image.new("RGBA", (self.canvas_w, self.canvas_h), (0,0,0,0)))
        canvas.paste(main_mask, (0, 0), mask=main_mask)
        draw = ImageDraw.Draw(canvas)

        # -------------------------- 3. 核心修复：图标与文本垂直居中对齐 --------------------------
        # 左侧服务器图标：垂直居中于主内容区域
        icon_x = 80
        main_content_height = self.canvas_h - self.BOTTOM_BAR_HEIGHT
        icon_y = (main_content_height - self.ICON_SIZE[1]) // 2
        icon_center_y = icon_y + self.ICON_SIZE[1] / 2  # 图标的垂直中心坐标
        canvas.paste(icon_img, (icon_x, icon_y), mask=icon_img)

        # 计算文本块总高度，让文本块的垂直中心和图标中心完全对齐
        total_text_height = self.TEXT_LINE_COUNT * self.LINE_GAP
        text_start_y = icon_center_y - total_text_height / 2  # 文本块起始y坐标，完美居中
        text_x = icon_x + self.ICON_SIZE[0] + 45
        current_line_y = text_start_y
        font_normal = self.fonts["normal"]
        text_main = self.theme["text_main"]
        text_sub = self.theme["text_sub"]

        # -------------------------- 4. 逐行绘制文本（全部使用la锚点，垂直对齐精准） --------------------------
        # 第一行：服务器名称
        draw.text((text_x, current_line_y), server_name, font=self.fonts["title"], fill=text_main, anchor="la")
        current_line_y += self.LINE_GAP

        # 第二行：IP地址 + 延迟（延迟数值按规则变色）
        # 先绘制前缀部分 "IP：{server_address} - 延迟 "
        prefix = f"IP：{server_address} - 延迟 "
        draw.text((text_x, current_line_y), prefix, font=font_normal, fill=text_sub, anchor="la")
        # 计算前缀宽度，以便后续绘制延迟数值
        prefix_width = font_normal.getbbox(prefix, anchor="la")[2] - font_normal.getbbox(prefix, anchor="la")[0]
        current_x = text_x + prefix_width

        # 延迟数值及其单位
        ping_text = f"{server_ping}ms"
        ping_color = self._get_ping_color(server_ping)
        draw.text((current_x, current_line_y), ping_text, font=font_normal, fill=ping_color, anchor="la")
        current_line_y += self.LINE_GAP

        # 第三行：版本号
        version_text = f"版本: {server_version}"
        draw.text((text_x, current_line_y), version_text, font=font_normal, fill=text_sub, anchor="la")
        current_line_y += self.LINE_GAP

        # 第四行：MOTD（支持MC彩色代码）
        self._draw_colored_text(draw, text_x, current_line_y, server_motd, self.fonts["motd"])
        current_line_y += self.LINE_GAP

        # 第五行：服务器介绍
        draw.text((text_x, current_line_y), server_intro, font=font_normal, fill=text_main, anchor="la")
        current_line_y += self.LINE_GAP

        # 第六行：在线人数
        player_text = f"在线人数: {online_players}/{max_players}"
        draw.text((text_x, current_line_y), player_text, font=font_normal, fill=text_sub, anchor="la")
        current_line_y += self.LINE_GAP

        # 第七行：CPU和内存占用（和在线人数完全同风格，纯文字左对齐，带阈值变色）
        cpu_color = self._get_metric_color(cpu_usage, "cpu")
        mem_color = self._get_metric_color(mem_usage, "mem")
        current_x = text_x

        # 分段绘制，实现标题灰色、数值带预警色的效果
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

        # -------------------------- 5. 底部区域：缩窄淡化的声明栏 --------------------------
        # 绘制底部栏背景
        draw.rounded_rectangle(
            (0, self.canvas_h - self.BOTTOM_BAR_HEIGHT, self.canvas_w, self.canvas_h),
            radius=0,
            fill=self.theme["bottom_bar_bg"]
        )
        # 绘制底部声明文本（居中对齐，小字体+淡色）
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

        # 返回最终渲染完成的图片
        return canvas.convert("RGBA")