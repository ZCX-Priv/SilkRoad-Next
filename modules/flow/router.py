"""
流量路由器

功能：
1. 流量类型识别与路由
2. 将请求分发至对应的处理器模块
3. 处理器降级与回退策略
4. 统计信息聚合

作者: SilkRoad-Next Team
版本: 1.0.0
"""

import asyncio
import aiohttp
from typing import Optional, Dict, Any, TYPE_CHECKING
from loguru import logger as loguru_logger

from modules.flow import FlowType

if TYPE_CHECKING:
    from modules.logging import Logger


class FlowRouter:
    """
    流量路由器

    根据请求头和 URL 识别流量类型，将请求路由至对应的处理器模块。
    支持三种流量类型：NORMAL、STREAM、WEBSOCKET。

    Attributes:
        config: 配置管理器
        logger: 日志记录器
        normal_handler: 正常 HTTP 流量处理器
        stream_handler: 流式流量处理器
        websocket_handler: WebSocket 流量处理器
        _session: aiohttp.ClientSession 对象
    """

    STREAM_CONTENT_TYPES = [
        'video/',
        'audio/',
        'text/event-stream',
        'application/octet-stream',
        'multipart/x-mixed-replace',
        'application/x-mpegurl',
        'application/vnd.apple.mpegurl',
    ]

    STREAM_EXTENSIONS = [
        '.mp4', '.mp3', '.avi', '.mov', '.flv',
        '.m3u8', '.ts', '.webm', '.ogg', '.mkv',
        '.wav', '.aac', '.flac', '.m4a', '.m4v',
    ]

    def __init__(self, config, logger: Optional['Logger'] = None):
        """
        初始化流量路由器

        Args:
            config: 配置管理器，需支持 get 方法获取配置项
            logger: 日志记录器，如果为 None 则使用默认 logger
        """
        self.config = config
        self.logger = logger or loguru_logger

        self.normal_handler = None
        self.stream_handler = None
        self.websocket_handler = None
        self._session = None

        self.logger.info("FlowRouter 初始化完成")

    def identify_flow_type(self, headers: Dict[str, str], url: str) -> FlowType:
        """
        识别流量类型

        根据请求头和 URL 判断流量类型，优先级如下：
        1. WebSocket 升级请求
        2. 流式请求
        3. 普通 HTTP 请求

        同时检查配置开关：如果 websocket.enabled 为 False，不识别为 WEBSOCKET；
        如果 stream.enabled 为 False，不识别为 STREAM。

        Args:
            headers: 请求头字典
            url: 请求 URL

        Returns:
            流量类型枚举值
        """
        # 检查 WebSocket 升级
        if self.config.get('websocket.enabled', False):
            upgrade = headers.get('Upgrade', '').lower()
            connection = headers.get('Connection', '').lower()
            has_key = 'Sec-WebSocket-Key' in headers

            if upgrade == 'websocket' and 'upgrade' in connection and has_key:
                self.logger.debug(f"识别为 WebSocket 流量: {url}")
                return FlowType.WEBSOCKET

        # 检查流式请求
        if self.config.get('stream.enabled', False):
            content_type = headers.get('Content-Type', '').lower()

            for stream_type in self.STREAM_CONTENT_TYPES:
                if stream_type in content_type:
                    self.logger.debug(f"识别为流式流量 (Content-Type): {content_type}")
                    return FlowType.STREAM

            if 'Range' in headers:
                self.logger.debug(f"识别为流式流量 (Range): {headers['Range']}")
                return FlowType.STREAM

            url_lower = url.lower()
            if any(url_lower.endswith(ext) for ext in self.STREAM_EXTENSIONS):
                self.logger.debug(f"识别为流式流量 (URL 后缀): {url}")
                return FlowType.STREAM

        return FlowType.NORMAL

    async def route(self, writer, method, target_url, headers, body,
                    session_id=None, reader=None) -> None:
        """
        路由请求至对应的处理器

        根据流量类型将请求分发至对应的处理器模块。
        如果对应处理器不可用，执行降级策略：
        - STREAM 降级到 normal_handler
        - WEBSOCKET 和 NORMAL 记录警告日志

        Args:
            writer: 客户端写入器
            method: HTTP 方法
            target_url: 目标 URL
            headers: 请求头字典
            body: 请求体
            session_id: 会话 ID（可选）
            reader: 客户端读取器（WebSocket 需要）
        """
        flow_type = self.identify_flow_type(headers, target_url)

        self.logger.info(
            f"路由请求: {method} {target_url} | "
            f"流量类型={flow_type.value}"
        )

        if flow_type == FlowType.WEBSOCKET:
            if self.websocket_handler:
                await self.websocket_handler.handle_upgrade(
                    reader, writer, headers, target_url
                )
            else:
                self.logger.warning(
                    f"WebSocket 处理器不可用，无法处理: {target_url}"
                )

        elif flow_type == FlowType.STREAM:
            if self.stream_handler:
                await self._handle_stream(
                    writer, method, target_url, headers, body
                )
            elif self.normal_handler:
                self.logger.info(
                    f"流处理器不可用，降级到普通处理器: {target_url}"
                )
                await self.normal_handler.handle(
                    writer, method, target_url, headers, body, session_id
                )
            else:
                self.logger.warning(
                    f"流处理器和普通处理器均不可用: {target_url}"
                )

        else:
            if self.normal_handler:
                await self.normal_handler.handle(
                    writer, method, target_url, headers, body, session_id
                )
            else:
                self.logger.warning(
                    f"普通处理器不可用，无法处理: {target_url}"
                )

    async def _handle_stream(self, writer, method, target_url, headers, body):
        """
        处理流式请求

        使用 session 向目标服务器发送请求，然后将响应交给
        stream_handler 处理流式传输。

        Args:
            writer: 客户端写入器
            method: HTTP 方法
            target_url: 目标 URL
            headers: 请求头字典
            body: 请求体
        """
        if not self._session:
            self.logger.error("Session 未设置，无法处理流式请求")
            if self.normal_handler:
                self.logger.info("降级到普通处理器")
                await self.normal_handler.handle(
                    writer, method, target_url, headers, body
                )
            return

        try:
            self.logger.info(f"开始处理流式请求: {method} {target_url}")

            async with self._session.request(
                method,
                target_url,
                headers=headers,
                data=body,
                allow_redirects=False,
                ssl=False
            ) as response:
                if self.stream_handler:
                    await self.stream_handler.handle_stream(
                        writer, response, target_url, headers
                    )
                else:
                    self.logger.warning("流处理器未设置，无法处理流式响应")

        except asyncio.TimeoutError:
            self.logger.error(f"流请求超时: {target_url}")

        except aiohttp.ClientError as e:
            self.logger.error(f"目标服务器错误 [{target_url}]: {e}")

        except ConnectionResetError:
            self.logger.warning(f"连接被重置: {target_url}")

        except Exception as e:
            self.logger.opt(exception=True).error(
                f"流请求处理失败 [{target_url}]: {e}"
            )

    def set_normal_handler(self, handler) -> None:
        """
        设置正常 HTTP 流量处理器

        Args:
            handler: NormalHandler 实例
        """
        self.normal_handler = handler
        self.logger.debug("正常流量处理器已设置")

    def set_stream_handler(self, handler) -> None:
        """
        设置流式流量处理器

        Args:
            handler: StreamHandler 实例
        """
        self.stream_handler = handler
        self.logger.debug("流式流量处理器已设置")

    def set_websocket_handler(self, handler) -> None:
        """
        设置 WebSocket 流量处理器

        Args:
            handler: WebSocketHandler 实例
        """
        self.websocket_handler = handler
        self.logger.debug("WebSocket 流量处理器已设置")

    def set_session(self, session) -> None:
        """
        设置 HTTP 客户端会话

        Args:
            session: aiohttp.ClientSession 实例
        """
        self._session = session
        self.logger.debug("HTTP 客户端会话已设置")

    def get_stats(self) -> dict:
        """
        获取聚合统计信息

        从所有已注册的处理器中收集统计信息，聚合后返回。

        Returns:
            包含各处理器统计信息的字典
        """
        stats = {
            'handlers': {
                'normal': self.normal_handler is not None,
                'stream': self.stream_handler is not None,
                'websocket': self.websocket_handler is not None,
            },
            'session': self._session is not None,
        }

        if self.normal_handler:
            try:
                stats['normal'] = self.normal_handler.get_stats()
            except Exception as e:
                self.logger.warning(f"获取普通处理器统计信息失败: {e}")

        if self.stream_handler:
            try:
                stats['stream'] = self.stream_handler.get_stats()
            except Exception as e:
                self.logger.warning(f"获取流处理器统计信息失败: {e}")

        if self.websocket_handler:
            try:
                stats['websocket'] = self.websocket_handler.get_stats()
            except Exception as e:
                self.logger.warning(f"获取 WebSocket 处理器统计信息失败: {e}")

        return stats

    def reset_stream_stats(self) -> Dict[str, bool]:
        """
        重置流处理器统计信息

        Returns:
            包含各处理器重置状态的字典
        """
        results = {
            'stream': False,
            'media': False,
            'sse': False,
            'others': False,
        }

        try:
            if self.stream_handler:
                self.stream_handler.stats = {
                    'total_streams': 0,
                    'active_streams': 0,
                    'media_streams': 0,
                    'sse_streams': 0,
                    'bytes_transferred': 0,
                    'errors': 0,
                }
                results['stream'] = True
                self.logger.info("StreamHandler 统计信息已重置")
        except Exception as e:
            self.logger.error(f"重置 StreamHandler 统计信息失败: {e}")

        try:
            if hasattr(self.stream_handler, 'media_handler') and self.stream_handler.media_handler:
                self.stream_handler.media_handler.reset_stats()
                results['media'] = True
                self.logger.info("MediaHandler 统计信息已重置")
        except Exception as e:
            self.logger.error(f"重置 MediaHandler 统计信息失败: {e}")

        try:
            if hasattr(self.stream_handler, 'sse_handler') and self.stream_handler.sse_handler:
                self.stream_handler.sse_handler.reset_stats()
                results['sse'] = True
                self.logger.info("SSEHandler 统计信息已重置")
        except Exception as e:
            self.logger.error(f"重置 SSEHandler 统计信息失败: {e}")

        try:
            if hasattr(self.stream_handler, 'others_handler') and self.stream_handler.others_handler:
                self.stream_handler.others_handler.reset_stats()
                results['others'] = True
                self.logger.info("OthersHandler 统计信息已重置")
        except Exception as e:
            self.logger.error(f"重置 OthersHandler 统计信息失败: {e}")

        return results

    def set_stream_rate_limit(self, enabled: bool,
                              max_rate=None) -> Dict[str, Any]:
        """
        动态设置流处理器的流量整形参数

        Args:
            enabled: 是否启用流量整形
            max_rate: 最大传输速率（字节/秒），如果为 None 则保持当前值

        Returns:
            包含设置结果和当前配置的字典
        """
        result = {
            'success': False,
            'enabled': enabled,
            'max_rate': max_rate,
            'previous_config': {},
            'current_config': {},
        }

        try:
            others_handler = None
            if hasattr(self.stream_handler, 'others_handler'):
                others_handler = self.stream_handler.others_handler

            if others_handler:
                result['previous_config'] = {
                    'enabled': others_handler.enable_rate_limit,
                    'max_rate': others_handler.max_rate,
                }

                others_handler.set_rate_limit(enabled, max_rate)

                result['current_config'] = {
                    'enabled': others_handler.enable_rate_limit,
                    'max_rate': others_handler.max_rate,
                }
                result['success'] = True

                self.logger.info(
                    f"流量整形设置已更新: enabled={enabled}, "
                    f"max_rate={others_handler.max_rate} bytes/s"
                )
            else:
                self.logger.warning("OthersHandler 未初始化，无法设置流量整形")

        except Exception as e:
            self.logger.error(f"设置流量整形参数失败: {e}")

        return result

    def get_stream_rate_limit_status(self) -> Dict[str, Any]:
        """
        获取当前流量整形状态

        Returns:
            包含流量整形配置和统计信息的字典
        """
        status = {
            'enabled': False,
            'max_rate': 0,
            'stats': {},
        }

        try:
            others_handler = None
            if hasattr(self.stream_handler, 'others_handler'):
                others_handler = self.stream_handler.others_handler

            if others_handler:
                status['enabled'] = others_handler.enable_rate_limit
                status['max_rate'] = others_handler.max_rate
                status['stats'] = {
                    'rate_limited_count': others_handler.stats.get('rate_limited', 0),
                    'bytes_transferred': others_handler.stats.get('bytes_transferred', 0),
                }
        except Exception as e:
            self.logger.error(f"获取流量整形状态失败: {e}")

        return status
