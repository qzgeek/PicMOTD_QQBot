import asyncio
import json
import websockets
from typing import Callable, Dict, Any, Optional, List, Union
import base64
from urllib.parse import parse_qs

# -------------------- 连接封装 --------------------
class 客户端连接:
    def __init__(self, websocket):
        self.websocket = websocket
        self.待处理请求: Dict[str, asyncio.Future] = {}

# -------------------- 服务端核心 --------------------
class OneBot服务端:
    def __init__(self, 主机: str = "0.0.0.0", 端口: int = 8080, 访问令牌: Optional[str] = None):
        self.主机 = 主机
        self.端口 = 端口
        self.访问令牌 = 访问令牌
        self._服务实例 = None
        self._连接池: Dict[str, 客户端连接] = {}
        self._事件处理器列表: List[Callable] = []
        self._api超时 = 10

    def 注册事件处理器(self, 处理器: Callable):
        """注册事件处理器（支持异步函数）
        用法:
            @server.注册事件处理器
            async def 处理函数(事件: dict):
                print(事件)
        """
        self._事件处理器列表.append(处理器)
        return 处理器

    async def _处理客户端连接(self, websocket):
        # Token 鉴权
        if not await self._验证令牌(websocket):
            return

        客户端标识 = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        self._连接池[客户端标识] = 客户端连接(websocket)
        print(f"[OneBot] 客户端 {客户端标识} 已连接")

        try:
            async for 消息文本 in websocket:
                try:
                    数据 = json.loads(消息文本)
                except json.JSONDecodeError:
                    print(f"[OneBot] 无效 JSON: {消息文本}")
                    continue

                # API 响应处理
                if "echo" in 数据 and "status" in 数据:
                    连接 = self._连接池.get(客户端标识)
                    if 连接 and 数据["echo"] in 连接.待处理请求:
                        连接.待处理请求.pop(数据["echo"]).set_result(数据)
                    continue

                # 事件上报
                if "post_type" in 数据:
                    for 处理器 in self._事件处理器列表:
                        asyncio.create_task(处理器(数据))

                # 心跳
                elif 数据.get("meta_event_type") == "heartbeat":
                    await websocket.send(json.dumps({
                        "status": "ok", "retcode": 0, "echo": 数据.get("echo")
                    }))
        except websockets.exceptions.ConnectionClosedError:
            print(f"[OneBot] 客户端 {客户端标识} 连接断开")
        finally:
            连接 = self._连接池.pop(客户端标识, None)
            if 连接:
                for 未来对象 in 连接.待处理请求.values():
                    未来对象.set_exception(ConnectionError("连接已断开"))

    async def _验证令牌(self, websocket) -> bool:
        if self.访问令牌 is None:
            return True

        # 1. 从 Header 获取
        headers = websocket.request.headers
        令牌 = headers.get("Authorization", "").replace("Bearer ", "")
        if 令牌 == self.访问令牌:
            return True

        # 2. 从 URL 参数获取
        if hasattr(websocket.request, "path") and "?" in websocket.request.path:
            查询字符串 = websocket.request.path.split("?", 1)[1]
            参数 = parse_qs(查询字符串)
            令牌 = 参数.get("access_token", [None])[0]
            if 令牌 == self.访问令牌:
                return True

        print(f"[OneBot] Token 验证失败，期望: {self.访问令牌}, 收到: {令牌}")
        await websocket.close(1008, "Token验证失败")
        return False

    async def 启动服务(self):
        self._服务实例 = await websockets.serve(self._处理客户端连接, self.主机, self.端口)
        print(f"[OneBot] 服务端启动于 ws://{self.主机}:{self.端口}")
        await self._服务实例.wait_closed()

    async def 调用API(self, 客户端标识: str, 动作: str, 参数: dict = None, 超时: int = 10) -> dict:
        """主动调用 API，返回响应数据"""
        if 客户端标识 not in self._连接池:
            raise ValueError(f"客户端 {客户端标识} 未连接")
        连接 = self._连接池[客户端标识]
        回显标识 = str(asyncio.get_event_loop().time())
        未来对象 = asyncio.get_event_loop().create_future()
        连接.待处理请求[回显标识] = 未来对象

        try:
            await 连接.websocket.send(json.dumps({
                "action": 动作,
                "params": 参数 or {},
                "echo": 回显标识
            }))
            return await asyncio.wait_for(未来对象, 超时)
        except asyncio.TimeoutError:
            连接.待处理请求.pop(回显标识, None)
            raise TimeoutError(f"API '{动作}' 超时")
        except Exception:
            连接.待处理请求.pop(回显标识, None)
            raise

# -------------------- 消息段构造器 --------------------
class 消息段:
    """构造各类 OneBot 消息段，文件类参数支持 base64"""

    @staticmethod
    def _base64编码(数据: Union[str, bytes]) -> str:
        """若传入本地文件路径，读取并转为 base64；若为 URL 或已 base64 字符串则直接返回"""
        if isinstance(数据, str):
            # 如果是 URL 或已含协议头，不进行文件读取
            if 数据.startswith(('http://', 'https://', 'base64://', 'file://')):
                return 数据
            # 尝试作为本地文件路径读取
            try:
                with open(数据, 'rb') as f:
                    return f"base64://{base64.b64encode(f.read()).decode('utf-8')}"
            except (OSError, FileNotFoundError):
                # 不是有效文件路径，返回原字符串（可能是 base64 但缺少前缀）
                return 数据
        return 数据

    @staticmethod
    def 文本(文本内容: str) -> dict:
        """纯文本"""
        return {"type": "text", "data": {"text": 文本内容}}

    @staticmethod
    def 艾特(qq号: Union[int, str]) -> dict:
        """@某人"""
        return {"type": "at", "data": {"qq": str(qq号)}}

    @staticmethod
    def 回复(消息id: int) -> dict:
        """回复消息"""
        return {"type": "reply", "data": {"id": str(消息id)}}

    @staticmethod
    def 图片(文件: str, 链接: str = "", 缓存: bool = True) -> dict:
        """图片：支持本地路径、URL、base64"""
        文件 = 消息段._base64编码(文件)
        return {"type": "image", "data": {"file": 文件, "url": 链接, "cache": 缓存}}

    @staticmethod
    def 文件(文件: str, 文件名: str = "", 链接: str = "") -> dict:
        """文件：支持本地路径、URL、base64（适用于群文件 / 私聊文件）"""
        文件 = 消息段._base64编码(文件)
        数据 = {"file": 文件}
        if 文件名:
            数据["name"] = 文件名
        if 链接:
            数据["url"] = 链接
        return {"type": "file", "data": 数据}

    @staticmethod
    def 视频(文件: str, 文件名: str = "", 链接: str = "") -> dict:
        """视频：支持本地路径、URL、base64"""
        文件 = 消息段._base64编码(文件)
        数据 = {"file": 文件}
        if 文件名:
            数据["name"] = 文件名
        if 链接:
            数据["url"] = 链接
        return {"type": "video", "data": 数据}

    @staticmethod
    def 语音(文件: str, 文件名: str = "", 链接: str = "") -> dict:
        """语音：支持本地路径、URL、base64"""
        文件 = 消息段._base64编码(文件)
        数据 = {"file": 文件}
        if 文件名:
            数据["name"] = 文件名
        if 链接:
            数据["url"] = 链接
        return {"type": "record", "data": 数据}

    @staticmethod
    def 表情(表情id: int) -> dict:
        """QQ 表情"""
        return {"type": "face", "data": {"id": str(表情id)}}

    @staticmethod
    def 骰子(结果: Optional[int] = None) -> dict:
        """骰子（群聊/私聊），若指定 result 则为预设点数"""
        数据 = {}
        if 结果 is not None:
            数据["result"] = 结果
        return {"type": "dice", "data": 数据}

    @staticmethod
    def 猜拳(结果: Optional[int] = None) -> dict:
        """猜拳（群聊/私聊），若指定 result 则为预设结果（0:石头,1:剪刀,2:布）"""
        数据 = {}
        if 结果 is not None:
            数据["result"] = 结果
        return {"type": "rps", "data": 数据}

    @staticmethod
    def JSON卡片(json字符串: str) -> dict:
        """JSON 卡片消息"""
        return {"type": "json", "data": {"data": json字符串}}

    @staticmethod
    def 音乐卡片(平台类型: str, 音乐id: str) -> dict:
        """音乐卡片（type_ 可选 qq/163/xm）"""
        return {"type": "music", "data": {"type": 平台类型, "id": 音乐id}}

    @staticmethod
    def 合并转发节点(用户id: int, 昵称: str, 内容: Union[str, List[dict]]) -> dict:
        """合并转发节点"""
        if isinstance(内容, str):
            内容 = [消息段.文本(内容)]
        return {
            "type": "node",
            "data": {
                "user_id": 用户id,
                "nickname": 昵称,
                "content": 内容
            }
        }

# -------------------- API 快捷封装 --------------------
class OneBot接口:
    def __init__(self, 服务端: "OneBot服务端", 客户端标识: str):
        self._服务端 = 服务端
        self._客户端标识 = 客户端标识

    async def _调用(self, 动作: str, 参数: dict, 超时: int = 10) -> dict:
        """底层 API 调用"""
        return await self._服务端.调用API(self._客户端标识, 动作, 参数, 超时)

    # ==================== 消息发送 ====================
    async def 发送群消息(self, 群号: int, 消息: Union[str, List[dict]], 不转义: bool = False) -> dict:
        """发送群消息，message 可为字符串或消息段列表"""
        if isinstance(消息, str):
            消息 = [消息段.文本(消息)]
        return await self._调用("send_group_msg", {"group_id": 群号, "message": 消息, "auto_escape": 不转义})

    async def 发送私聊消息(self, 用户id: int, 消息: Union[str, List[dict]], 不转义: bool = False) -> dict:
        """发送私聊消息"""
        if isinstance(消息, str):
            消息 = [消息段.文本(消息)]
        return await self._调用("send_private_msg", {"user_id": 用户id, "message": 消息, "auto_escape": 不转义})

    async def 发送群合并转发(self, 群号: int, 节点列表: List[dict]) -> dict:
        """发送群合并转发消息"""
        return await self._调用("send_group_forward_msg", {"group_id": 群号, "messages": 节点列表})

    async def 发送私聊合并转发(self, 用户id: int, 节点列表: List[dict]) -> dict:
        """发送私聊合并转发消息"""
        return await self._调用("send_private_forward_msg", {"user_id": 用户id, "messages": 节点列表})

    async def 转发消息到群(self, 群号: int, 消息id: int) -> dict:
        """将单条消息转发到群"""
        return await self._调用("forward_group_single_msg", {"group_id": 群号, "message_id": 消息id})

    async def 转发消息到私聊(self, 用户id: int, 消息id: int) -> dict:
        """将单条消息转发到私聊"""
        return await self._调用("forward_friend_single_msg", {"user_id": 用户id, "message_id": 消息id})

    # ==================== 消息获取 ====================
    async def 获取消息详情(self, 消息id: int) -> dict:
        """获取消息详情"""
        return await self._调用("get_msg", {"message_id": 消息id})

    async def 获取合并转发内容(self, 消息id: int) -> dict:
        """获取合并转发消息内容"""
        return await self._调用("get_forward_msg", {"message_id": 消息id})

    async def 获取群历史消息(self, 群号: int, 起始序号: Optional[int] = None, 数量: int = 20, 倒序: bool = False) -> dict:
        """获取群历史消息"""
        参数 = {"group_id": 群号, "count": 数量, "reverseOrder": 倒序}
        if 起始序号:
            参数["message_seq"] = 起始序号
        return await self._调用("get_group_msg_history", 参数)

    async def 获取好友历史消息(self, 用户id: int, 起始序号: Optional[int] = None, 数量: int = 20, 倒序: bool = False) -> dict:
        """获取好友历史消息"""
        参数 = {"user_id": 用户id, "count": 数量, "reverseOrder": 倒序}
        if 起始序号:
            参数["message_seq"] = 起始序号
        return await self._调用("get_friend_msg_history", 参数)

    # ==================== 消息操作 ====================
    async def 撤回消息(self, 消息id: int) -> dict:
        """撤回消息"""
        return await self._调用("delete_msg", {"message_id": 消息id})

    async def 贴表情(self, 消息id: int, 表情id: int, 设置: bool = True) -> dict:
        """贴表情（表情表态）"""
        return await self._调用("set_msg_emoji_like", {"message_id": 消息id, "emoji_id": 表情id, "set": 设置})

    async def 获取贴表情详情(self, 消息id: int) -> dict:
        """获取贴表情详情"""
        return await self._调用("get_emoji_like_list", {"message_id": 消息id})

    # ==================== 戳一戳 ====================
    async def 群聊戳一戳(self, 群号: int, 用户id: int) -> dict:
        """发送群聊戳一戳"""
        return await self._调用("group_poke", {"group_id": 群号, "user_id": 用户id})

    async def 私聊戳一戳(self, 用户id: int, 目标id: Optional[int] = None) -> dict:
        """发送私聊戳一戳"""
        参数 = {"user_id": 用户id}
        if 目标id:
            参数["target_id"] = 目标id
        return await self._调用("friend_poke", 参数)

    async def 发送戳一戳(self, 用户id: int, 群号: Optional[int] = None) -> dict:
        """通用戳一戳（group_id 不填则为私聊）"""
        参数 = {"user_id": 用户id}
        if 群号:
            参数["group_id"] = 群号
        return await self._调用("send_poke", 参数)

    # ==================== 群聊管理 ====================
    async def 获取群列表(self, 不使用缓存: bool = False) -> dict:
        """获取群列表"""
        return await self._调用("get_group_list", {"no_cache": 不使用缓存})

    async def 获取群信息(self, 群号: int) -> dict:
        """获取群信息"""
        return await self._调用("get_group_info", {"group_id": 群号})

    async def 获取群详细信息(self, 群号: int) -> dict:
        """获取群详细信息（成员数、最大成员数等）"""
        return await self._调用("get_group_detail_info", {"group_id": 群号})

    async def 获取群成员列表(self, 群号: int, 不使用缓存: bool = False) -> dict:
        """获取群成员列表"""
        return await self._调用("get_group_member_list", {"group_id": 群号, "no_cache": 不使用缓存})

    async def 获取群成员信息(self, 群号: int, 用户id: int, 不使用缓存: bool = False) -> dict:
        """获取群成员信息"""
        return await self._调用("get_group_member_info", {"group_id": 群号, "user_id": 用户id, "no_cache": 不使用缓存})

    async def 设置群名称(self, 群号: int, 新群名: str) -> dict:
        """设置群名"""
        return await self._调用("set_group_name", {"group_id": 群号, "group_name": 新群名})

    async def 设置群名片(self, 群号: int, 用户id: int, 名片: str = "") -> dict:
        """设置群成员名片（card 为空则取消）"""
        return await self._调用("set_group_card", {"group_id": 群号, "user_id": 用户id, "card": 名片})

    async def 设置群管理员(self, 群号: int, 用户id: int, 设为管理: bool = True) -> dict:
        """设置/取消群管理员"""
        return await self._调用("set_group_admin", {"group_id": 群号, "user_id": 用户id, "enable": 设为管理})

    async def 踢出群成员(self, 群号: int, 用户id: int, 拒绝再次申请: bool = False) -> dict:
        """踢出群成员"""
        return await self._调用("set_group_kick", {"group_id": 群号, "user_id": 用户id, "reject_add_request": 拒绝再次申请})

    async def 批量踢出群成员(self, 群号: int, 用户id列表: List[int], 拒绝再次申请: bool = False) -> dict:
        """批量踢出群成员"""
        return await self._调用("set_group_kick_members", {"group_id": 群号, "user_id": 用户id列表, "reject_add_request": 拒绝再次申请})

    async def 群禁言(self, 群号: int, 用户id: int, 时长秒: int = 1800) -> dict:
        """群禁言（duration 单位秒，0 为解除）"""
        return await self._调用("set_group_ban", {"group_id": 群号, "user_id": 用户id, "duration": 时长秒})

    async def 全体禁言(self, 群号: int, 开启: bool = True) -> dict:
        """全体禁言"""
        return await self._调用("set_group_whole_ban", {"group_id": 群号, "enable": 开启})

    async def 退出群聊(self, 群号: int) -> dict:
        """退出群聊"""
        return await self._调用("set_group_leave", {"group_id": 群号})

    async def 设置群待办(self, 群号: int, 消息id: int) -> dict:
        """设置群待办"""
        return await self._调用("set_group_todo", {"group_id": 群号, "message_id": 消息id})

    # ==================== 群公告 ====================
    async def _获取群公告(self, 群号: int) -> dict:
        """获取群公告"""
        return await self._调用("_get_group_notice", {"group_id": 群号})

    async def _发送群公告(self, 群号: int, 内容: str, 图片: Optional[str] = None) -> dict:
        """发送群公告"""
        参数 = {"group_id": 群号, "content": 内容}
        if 图片:
            参数["image"] = 图片
        return await self._调用("_send_group_notice", 参数)

    # ==================== 加群请求处理 ====================
    async def 处理加群请求(self, 请求标识: str, 同意: bool = True, 拒绝理由: str = "") -> dict:
        """处理加群请求"""
        return await self._调用("set_group_add_request", {"flag": 请求标识, "approve": 同意, "reason": 拒绝理由})

    # ==================== 账号相关 ====================
    async def 获取登录号信息(self) -> dict:
        """获取登录号信息"""
        return await self._调用("get_login_info", {})

    async def 获取陌生人信息(self, 用户id: int) -> dict:
        """获取陌生人/账号信息"""
        return await self._调用("get_stranger_info", {"user_id": 用户id})

    async def 获取好友列表(self, 不使用缓存: bool = False) -> dict:
        """获取好友列表"""
        return await self._调用("get_friend_list", {"no_cache": 不使用缓存})

    async def 点赞(self, 用户id: int, 次数: int = 1) -> dict:
        """点赞"""
        return await self._调用("send_like", {"user_id": 用户id, "times": 次数})

    async def 设置好友备注(self, 用户id: int, 备注: str) -> dict:
        """设置好友备注"""
        return await self._调用("set_friend_remark", {"user_id": 用户id, "remark": 备注})

    async def 删除好友(self, 用户id: int, 临时屏蔽: bool = False, 双向删除: bool = False) -> dict:
        """删除好友"""
        return await self._调用("delete_friend", {"user_id": 用户id, "temp_block": 临时屏蔽, "temp_both_del": 双向删除})

    async def 处理好友请求(self, 请求标识: str, 同意: bool = True, 备注: str = "") -> dict:
        """处理好友请求"""
        return await self._调用("set_friend_add_request", {"flag": 请求标识, "approve": 同意, "remark": 备注})

    async def 设置在线状态(self, 状态: int = 10, 扩展状态: int = 0, 电量状态: int = 0) -> dict:
        """设置在线状态（status: 10=在线, 30=离开, 40=隐身, 50=忙碌, 60=Q我吧, 70=请勿打扰）"""
        return await self._调用("set_online_status", {"status": 状态, "ext_status": 扩展状态, "battery_status": 电量状态})

    async def 设置个性签名(self, 签名: str) -> dict:
        """设置个性签名"""
        return await self._调用("set_self_longnick", {"longNick": 签名})

    async def 标记消息已读(self, 群号: Optional[int] = None, 用户id: Optional[int] = None) -> dict:
        """设置消息已读（group_id 与 user_id 二选一）"""
        参数 = {}
        if 群号:
            参数["group_id"] = 群号
        if 用户id:
            参数["user_id"] = 用户id
        return await self._调用("mark_msg_as_read", 参数)

    async def 标记所有消息已读(self) -> dict:
        """设置所有消息已读"""
        return await self._调用("mark_all_as_read", {})


async def main():
    服务端 = OneBot服务端(主机="0.0.0.0", 端口=10100, 访问令牌="saj*4ihv3921c54e23b8f84883e3a78d721cfd8b")

    @服务端.注册事件处理器
    async def 处理所有事件(事件: dict):
        # 确保有客户端连接后再创建 API 实例（也可以缓存到字典中）
        if not 服务端._连接池:
            return
        客户端标识 = next(iter(服务端._连接池.keys()))
        api = OneBot接口(服务端, 客户端标识)

        # ---------- 消息事件 ----------
        if 事件.get("post_type") == "message":
            消息类型 = 事件.get("message_type")
            原始消息 = 事件.get("raw_message", "")

            # 群聊消息
            if 消息类型 == "group":
                群号 = 事件["group_id"]
                发送者 = 事件["user_id"]

                if 原始消息 == "猫猫，活着吗":
                    await api.发送群消息(群号, "包的")

                elif "猫猫，来张图片" in 原始消息:
                    await api.发送群消息(群号, [
                        消息段.艾特(发送者),
                        消息段.文本(" 这是你要的图片"),
                        消息段.图片("https://api.furry.ist/furry-img/")
                    ])

                elif "猫猫，戳我" in 原始消息:
                    await api.群聊戳一戳(群号, 发送者)

                elif 原始消息 == "猫猫，看看你的好友列表":
                    好友列表 = await api.获取好友列表()
                    # 将好友列表发送到群内（注意好友列表可能很长，可酌情截断）
                    await api.发送群消息(群号, f"当前好友数量：{len(好友列表.get('data', []))}")

            # 私聊消息
            elif 消息类型 == "private":
                用户id = 事件["user_id"]

                if 原始消息 == "猫猫，活着吗":
                    await api.发送私聊消息(用户id, "包的")

                elif "猫猫，来张图片" in 原始消息:
                    await api.发送私聊消息(用户id, [
                        消息段.文本("这是你要的图片"),
                        消息段.图片("https://api.furry.ist/furry-img/")
                    ])

                elif "猫猫，戳我" in 原始消息:
                    await api.私聊戳一戳(用户id)

                elif 原始消息 == "猫猫，看看你的好友列表":
                    好友列表 = await api.获取好友列表()
                    await api.发送私聊消息(用户id, f"当前好友数量：{len(好友列表.get('data', []))}")

    await 服务端.启动服务()

if __name__ == "__main__":
    asyncio.run(main())