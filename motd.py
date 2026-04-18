"""
Minecraft Java 版服务器 MOTD 查询模块（支持图标返回为 PIL Image 对象）
支持 SRV 解析、多协议版本、调试输出
"""

import socket
import struct
import json
import time
import base64
import io
from typing import Optional, Tuple, Dict, Any, List
from dataclasses import dataclass

# 尝试导入 PIL，如果失败则标记为不可用
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = None  # type: ignore


@dataclass
class ServerInfo:
    online: bool
    host: str
    port: int
    resolved_host: str
    resolved_port: int
    version: str = ""
    protocol: int = 0
    motd: str = ""          # 带 § 格式代码的 MOTD 文本
    motd_raw: str = ""      # 原始 description 的 JSON 字符串（如果是 JSON 格式）
    icon: Optional[Any] = None      # PIL Image 对象，如果可用
    icon_raw: str = ""              # 原始 favicon Base64 字符串（调试用）
    max_players: int = 0
    online_players: int = 0
    latency: float = 0.0
    error: str = ""
    debug_info: str = ""

    def __str__(self) -> str:
        if not self.online:
            return f"Server {self.host}:{self.port} is offline. {self.error}"
        return (
            f"Server: {self.host}:{self.port}\n"
            f"Resolved: {self.resolved_host}:{self.resolved_port}\n"
            f"Version: {self.version} (protocol {self.protocol})\n"
            f"Players: {self.online_players}/{self.max_players}\n"
            f"MOTD: {self.motd}\n"
            f"Latency: {self.latency:.1f}ms"
        )


class MCQueryError(Exception):
    pass


class MinecraftPinger:
    DEFAULT_PORT = 25565
    CONNECT_TIMEOUT = 3.0
    READ_TIMEOUT = 3.0
    SRV_TIMEOUT = 2.0

    # 常用协议版本号（从新到旧）
    PROTOCOL_VERSIONS = [
        -1, 766, 765, 763, 762, 761, 760, 759, 758, 757, 756,
        755, 754, 578, 498, 340, 47
    ]

    # 格式代码映射表（用于 JSON 转传统格式）
    COLOR_MAP = {
        "black": "0", "dark_blue": "1", "dark_green": "2", "dark_aqua": "3",
        "dark_red": "4", "dark_purple": "5", "gold": "6", "gray": "7",
        "dark_gray": "8", "blue": "9", "green": "a", "aqua": "b",
        "red": "c", "light_purple": "d", "yellow": "e", "white": "f"
    }
    FORMAT_MAP = {
        "bold": "l", "italic": "o", "underlined": "n", "strikethrough": "m",
        "obfuscated": "k"
    }

    def __init__(self, host: str, port: Optional[int] = None,
                 connect_timeout: float = CONNECT_TIMEOUT,
                 read_timeout: float = READ_TIMEOUT,
                 debug: bool = False):
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.debug = debug
        self.host, self.port = self._parse_host_port(host, port)
        self._resolved_host = self.host
        self._resolved_port = self.port
        self._srv_resolved = False

    @staticmethod
    def _parse_host_port(host: str, port: Optional[int] = None) -> Tuple[str, int]:
        if port is not None:
            return host, port
        if ":" in host:
            if host.startswith("["):
                parts = host.rsplit(":", 1)
                if len(parts) == 2:
                    addr = parts[0].strip("[]")
                    try:
                        return addr, int(parts[1])
                    except ValueError:
                        pass
            else:
                parts = host.rsplit(":", 1)
                if len(parts) == 2:
                    try:
                        return parts[0], int(parts[1])
                    except ValueError:
                        pass
        return host, MinecraftPinger.DEFAULT_PORT

    def _resolve_srv(self) -> Tuple[str, int]:
        try:
            import dns.resolver
        except ImportError:
            return self.host, self.port

        srv_domain = f"_minecraft._tcp.{self.host}"
        try:
            resolver = dns.resolver.Resolver()
            resolver.lifetime = self.SRV_TIMEOUT
            answers = resolver.resolve(srv_domain, "SRV")
            if answers:
                answer = answers[0]
                resolved_host = str(answer.target).rstrip(".")
                resolved_port = int(answer.port)
                return resolved_host, resolved_port
        except Exception:
            pass
        return self.host, self.port

    @staticmethod
    def _pack_varint(value: int) -> bytes:
        """将整数编码为 VarInt（兼容负数）"""
        value = value & 0xFFFFFFFF
        result = bytearray()
        for _ in range(5):
            temp = value & 0x7F
            value >>= 7
            if value != 0:
                temp |= 0x80
            result.append(temp)
            if value == 0:
                break
        return bytes(result)

    @staticmethod
    def _unpack_varint(data: bytes, offset: int = 0) -> Tuple[int, int]:
        """解码 VarInt，返回 (有符号 32 位整数, 消耗字节数)"""
        value = 0
        shift = 0
        consumed = 0
        for i in range(offset, min(offset + 5, len(data))):
            b = data[i]
            value |= (b & 0x7F) << shift
            consumed += 1
            if (b & 0x80) == 0:
                break
            shift += 7
        if value & (1 << 31):
            value -= 1 << 32
        return value, consumed

    def _build_handshake_packet(self, protocol_version: int) -> bytes:
        packet_id = b"\x00"
        proto_ver = self._pack_varint(protocol_version)
        host_bytes = self.host.encode("utf-8")
        host_len = self._pack_varint(len(host_bytes))
        port_bytes = struct.pack(">H", self.port)
        next_state = self._pack_varint(1)  # Status

        data = packet_id + proto_ver + host_len + host_bytes + port_bytes + next_state
        length = self._pack_varint(len(data))
        return length + data

    def _build_status_request_packet(self) -> bytes:
        data = b"\x00"
        length = self._pack_varint(len(data))
        return length + data

    def _build_ping_request_packet(self) -> bytes:
        data = b"\x01" + struct.pack(">Q", int(time.time() * 1000))
        length = self._pack_varint(len(data))
        return length + data

    def _read_packet(self, sock: socket.socket) -> bytes:
        sock.settimeout(self.read_timeout)
        length_data = bytearray()
        for _ in range(5):
            try:
                b = sock.recv(1)
            except socket.timeout:
                raise MCQueryError("Read timeout while reading packet length")
            if not b:
                raise MCQueryError("Connection closed while reading packet length")
            length_data.append(b[0])
            if (b[0] & 0x80) == 0:
                break
        if not length_data:
            raise MCQueryError("Failed to read packet length")
        packet_length, _ = self._unpack_varint(bytes(length_data))
        data = bytearray()
        remaining = packet_length
        while remaining > 0:
            try:
                chunk = sock.recv(min(remaining, 4096))
            except socket.timeout:
                raise MCQueryError("Read timeout while reading packet data")
            if not chunk:
                raise MCQueryError("Connection closed while reading packet data")
            data.extend(chunk)
            remaining -= len(chunk)
        return bytes(data)

    def _parse_status_response(self, data: bytes) -> Dict[str, Any]:
        offset = 1  # skip packet ID (0x00)
        json_len, consumed = self._unpack_varint(data, offset)
        offset += consumed
        json_data = data[offset:offset + json_len].decode("utf-8")
        return json.loads(json_data)

    def _json_to_legacy(self, obj: Any) -> str:
        """将 Minecraft JSON 聊天组件转换为带有 § 格式代码的字符串"""
        if isinstance(obj, str):
            return obj
        if isinstance(obj, list):
            return "".join(self._json_to_legacy(item) for item in obj)
        if not isinstance(obj, dict):
            return str(obj)

        result = []
        color_code = ""
        format_codes = ""

        def apply_style(style_dict):
            nonlocal color_code, format_codes
            codes = []
            if "color" in style_dict and style_dict["color"] in self.COLOR_MAP:
                color_code = f"§{self.COLOR_MAP[style_dict['color']]}"
                codes.append(color_code)
            for fmt, code in self.FORMAT_MAP.items():
                if style_dict.get(fmt, False):
                    format_codes += f"§{code}"
            return color_code + format_codes

        style_prefix = apply_style(obj)

        if "text" in obj:
            result.append(style_prefix + obj["text"])
        if "translate" in obj:
            result.append(style_prefix + f"[{obj['translate']}]")
        if "extra" in obj and isinstance(obj["extra"], list):
            for extra in obj["extra"]:
                result.append(self._json_to_legacy(extra))

        return "".join(result)

    def _extract_motd(self, description: Any) -> Tuple[str, str]:
        """
        从 description 字段提取 MOTD
        返回 (带格式代码的文本, 原始 JSON 字符串)
        """
        raw_json = ""
        if isinstance(description, str):
            return description, description
        elif isinstance(description, dict):
            raw_json = json.dumps(description, ensure_ascii=False)
            motd = self._json_to_legacy(description)
            return motd, raw_json
        else:
            raw_json = str(description)
            return raw_json, raw_json

    def _parse_favicon(self, favicon_data: Optional[str]) -> Tuple[Optional[Any], str]:
        """
        解析 favicon 字段，返回 (PIL Image 对象或 None, 原始 base64 字符串)
        """
        if not favicon_data or not isinstance(favicon_data, str):
            return None, ""
        
        raw = favicon_data
        # 检查是否为 data URI 格式
        if favicon_data.startswith("data:image/png;base64,"):
            base64_part = favicon_data.replace("data:image/png;base64,", "")
            try:
                if PIL_AVAILABLE:
                    img_data = base64.b64decode(base64_part)
                    img = Image.open(io.BytesIO(img_data))
                    return img, raw
                else:
                    # PIL 不可用，返回 None
                    return None, raw
            except Exception:
                # 解码或图片加载失败
                return None, raw
        return None, raw

    def _try_protocol(self, sock: socket.socket, protocol: int) -> Tuple[bool, Dict[str, Any], str]:
        """尝试单个协议版本"""
        try:
            handshake = self._build_handshake_packet(protocol)
            sock.sendall(handshake)
            time.sleep(0.05)  # 给服务器一点处理时间
            sock.sendall(self._build_status_request_packet())
            response = self._read_packet(sock)
            if response[0] != 0x00:
                return False, {}, f"Unexpected packet ID: 0x{response[0]:02X}"
            data = self._parse_status_response(response)
            return True, data, ""
        except Exception as e:
            return False, {}, str(e)

    def ping(self) -> ServerInfo:
        start_time = time.time()
        if not self._srv_resolved:
            self._resolved_host, self._resolved_port = self._resolve_srv()
            self._srv_resolved = True

        sock = None
        debug_msgs = []

        try:
            sock = socket.create_connection(
                (self._resolved_host, self._resolved_port),
                timeout=self.connect_timeout
            )
            debug_msgs.append(f"Connected to {self._resolved_host}:{self._resolved_port}")

            success = False
            data = {}
            last_error = ""
            used_protocol = None

            for proto in self.PROTOCOL_VERSIONS:
                if self.debug:
                    debug_msgs.append(f"Trying protocol {proto}...")
                success, data, err = self._try_protocol(sock, proto)
                if success:
                    used_protocol = proto
                    break
                last_error = err
                if "closed" in err.lower() or "broken pipe" in err.lower():
                    debug_msgs.append("Connection closed by server.")
                    break

            if not success:
                return ServerInfo(
                    online=False,
                    host=self.host,
                    port=self.port,
                    resolved_host=self._resolved_host,
                    resolved_port=self._resolved_port,
                    error=f"All protocol attempts failed. Last error: {last_error}",
                    debug_info="\n".join(debug_msgs) if self.debug else ""
                )

            # 获取延迟
            sock.sendall(self._build_ping_request_packet())
            pong = self._read_packet(sock)
            latency = (time.time() - start_time) * 1000

            motd_text, motd_raw = self._extract_motd(data.get("description", ""))
            version = data.get("version", {}).get("name", "Unknown")
            protocol = data.get("version", {}).get("protocol", 0)
            players = data.get("players", {})
            max_players = players.get("max", 0)
            online_players = players.get("online", 0)

            # 解析图标
            favicon = data.get("favicon")
            icon, icon_raw = self._parse_favicon(favicon)

            if self.debug:
                debug_msgs.append(f"Success with protocol {used_protocol}")

            return ServerInfo(
                online=True,
                host=self.host,
                port=self.port,
                resolved_host=self._resolved_host,
                resolved_port=self._resolved_port,
                version=version,
                protocol=protocol,
                motd=motd_text,
                motd_raw=motd_raw,
                icon=icon,
                icon_raw=icon_raw,
                max_players=max_players,
                online_players=online_players,
                latency=latency,
                debug_info="\n".join(debug_msgs) if self.debug else ""
            )

        except socket.timeout:
            return ServerInfo(
                online=False,
                host=self.host,
                port=self.port,
                resolved_host=self._resolved_host,
                resolved_port=self._resolved_port,
                error="Connection timeout",
                debug_info="\n".join(debug_msgs) if self.debug else ""
            )
        except ConnectionRefusedError:
            return ServerInfo(
                online=False,
                host=self.host,
                port=self.port,
                resolved_host=self._resolved_host,
                resolved_port=self._resolved_port,
                error="Connection refused",
                debug_info="\n".join(debug_msgs) if self.debug else ""
            )
        except socket.gaierror as e:
            return ServerInfo(
                online=False,
                host=self.host,
                port=self.port,
                resolved_host=self._resolved_host,
                resolved_port=self._resolved_port,
                error=f"DNS failed: {e}",
                debug_info="\n".join(debug_msgs) if self.debug else ""
            )
        except Exception as e:
            return ServerInfo(
                online=False,
                host=self.host,
                port=self.port,
                resolved_host=self._resolved_host,
                resolved_port=self._resolved_port,
                error=str(e),
                debug_info="\n".join(debug_msgs) if self.debug else ""
            )
        finally:
            if sock:
                sock.close()


def get_motd(host: str, port: Optional[int] = None,
             connect_timeout: float = 3.0,
             read_timeout: float = 3.0,
             debug: bool = False) -> ServerInfo:
    """
    获取 Minecraft 服务器 MOTD 信息（含图标）
    """
    pinger = MinecraftPinger(host, port, connect_timeout, read_timeout, debug=debug)
    return pinger.ping()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        server = sys.argv[1]
    else:
        server = input("Enter server address: ").strip()
    print(f"Querying {server}...")
    info = get_motd(server, debug=True)
    if info.debug_info:
        print("\n=== Debug Info ===")
        print(info.debug_info)
        print("==================\n")
    if info.online:
        print(info)
        if info.icon:
            print("\nServer icon is available as a PIL Image object.")
            print(f"Icon size: {info.icon.size}")
            # 可选：保存图片到文件
            # info.icon.save("server_icon.png")
        else:
            print("\nNo server icon or PIL not installed.")
    else:
        print(f"Error: {info.error}")