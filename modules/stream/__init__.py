"""
流处理模块 (Stream Processing Module)

功能：
1. 流类型识别与路由
2. 媒体流处理（视频/音频）
3. Server-Sent Events (SSE) 处理
4. 分块传输处理
5. 流量控制与缓冲管理

模块结构：
- handle.py: 流处理核心引擎
- media.py: 媒体流处理（视频/音频）
- sse.py: Server-Sent Events 处理
- others.py: 其他流类型处理（WebSocket 升级准备等）

作者: SilkRoad-Next Team
版本: 3.0.0
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import time


class StreamType(Enum):
    """
    流类型枚举
    
    Attributes:
        MEDIA: 媒体流（视频/音频）
        SSE: Server-Sent Events
        CHUNKED: 分块传输
        WEBSOCKET: WebSocket（V4 准备）
        UNKNOWN: 未知类型
    """
    MEDIA = "media"
    SSE = "sse"
    CHUNKED = "chunked"
    WEBSOCKET = "websocket"
    UNKNOWN = "unknown"


@dataclass
class StreamContext:
    """
    流处理上下文
    
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


# 延迟导入，避免循环依赖
def get_stream_handler():
    """
    获取 StreamHandler 类
    
    Returns:
        StreamHandler 类
    """
    from modules.stream.handle import StreamHandler
    return StreamHandler


def get_media_handler():
    """
    获取 MediaHandler 类
    
    Returns:
        MediaHandler 类
    """
    from modules.stream.media import MediaHandler
    return MediaHandler


def get_sse_handler():
    """
    获取 SSEHandler 类
    
    Returns:
        SSEHandler 类
    """
    from modules.stream.sse import SSEHandler
    return SSEHandler


def get_others_handler():
    """
    获取 OthersHandler 类
    
    Returns:
        OthersHandler 类
    """
    from modules.stream.others import OthersHandler
    return OthersHandler


# 模块版本信息
__version__ = "3.0.0"
__author__ = "SilkRoad-Next Team"

# 公开 API
__all__ = [
    # 枚举和数据类
    'StreamType',
    'StreamContext',
    # 处理器获取函数
    'get_stream_handler',
    'get_media_handler',
    'get_sse_handler',
    'get_others_handler',
]
