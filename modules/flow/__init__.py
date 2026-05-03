"""
流量处理模块 (Flow Processing Module)

功能：
1. 流量类型识别与路由
2. 正常 HTTP 流量处理
3. 流式流量处理（媒体流、SSE、分块传输）
4. WebSocket 流量处理
5. 流量控制与缓冲管理

模块结构：
- router.py: 流量路由器，根据流量类型路由至对应处理器
- normal.py: 正常 HTTP 流量处理器
- handle.py: 流处理核心引擎
- media.py: 媒体流处理（视频/音频）
- sse.py: Server-Sent Events 处理
- others.py: 其他流类型处理
- websocket.py: WebSocket 协议支持

作者: SilkRoad-Next Team
版本: 1.0.0
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import time


class FlowType(Enum):
    """
    流量类型枚举

    Attributes:
        NORMAL: 正常 HTTP 流量
        STREAM: 流式流量（媒体流、SSE、分块传输等）
        WEBSOCKET: WebSocket 流量
    """
    NORMAL = "normal"
    STREAM = "stream"
    WEBSOCKET = "websocket"


class StreamType(Enum):
    """
    流类型枚举（兼容旧代码）

    Attributes:
        MEDIA: 媒体流（视频/音频）
        SSE: Server-Sent Events
        CHUNKED: 分块传输
        WEBSOCKET: WebSocket
        UNKNOWN: 未知类型
    """
    MEDIA = "media"
    SSE = "sse"
    CHUNKED = "chunked"
    WEBSOCKET = "websocket"
    UNKNOWN = "unknown"


@dataclass
class FlowContext:
    """
    流量处理上下文

    Attributes:
        flow_id: 流量唯一标识符
        flow_type: 流量类型
        target_url: 目标 URL
        method: HTTP 方法
        content_type: 内容类型
        content_length: 内容长度（可选）
        start_time: 处理开始时间
        bytes_transferred: 已传输字节数
        is_active: 流量是否活跃
        metadata: 元数据字典
    """
    flow_id: str
    flow_type: FlowType
    target_url: str
    method: str
    content_type: str
    content_length: Optional[int]
    start_time: float
    bytes_transferred: int = 0
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamContext:
    """
    流处理上下文（兼容旧代码）

    Attributes:
        stream_id: 流唯一标识符
        stream_type: 流类型
        target_url: 目标 URL
        content_type: 内容类型
        content_length: 内容长度（可选）
        start_time: 流开始时间
        bytes_transferred: 已传输字节数
        is_active: 流是否活跃
        metadata: 元数据字典
    """
    stream_id: str
    stream_type: StreamType
    target_url: str
    content_type: str
    content_length: Optional[int]
    start_time: float
    bytes_transferred: int = 0
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


def get_flow_router():
    from modules.flow.router import FlowRouter
    return FlowRouter


def get_normal_handler():
    from modules.flow.normal import NormalHandler
    return NormalHandler


def get_stream_handler():
    from modules.flow.handle import StreamHandler
    return StreamHandler


def get_media_handler():
    from modules.flow.media import MediaHandler
    return MediaHandler


def get_sse_handler():
    from modules.flow.sse import SSEHandler
    return SSEHandler


def get_others_handler():
    from modules.flow.others import OthersHandler
    return OthersHandler


def get_websocket_handler():
    from modules.flow.websocket import WebSocketHandler
    return WebSocketHandler


__version__ = "1.0.0"
__author__ = "SilkRoad-Next Team"

__all__ = [
    'FlowType',
    'FlowContext',
    'StreamType',
    'StreamContext',
    'get_flow_router',
    'get_normal_handler',
    'get_stream_handler',
    'get_media_handler',
    'get_sse_handler',
    'get_others_handler',
    'get_websocket_handler',
]
