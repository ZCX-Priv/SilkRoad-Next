"""
Server-Sent Events 处理模块

功能：
1. SSE 连接代理
2. 事件过滤与转发
3. 心跳检测
4. 自动重连
5. 事件缓存与回放

作者: SilkRoad-Next Team
版本: 3.0.0
"""

import asyncio
import aiohttp
from typing import Optional, Dict, List, AsyncIterator, Any, TYPE_CHECKING
import time
from loguru import logger as loguru_logger
from dataclasses import dataclass, field

from modules.stream import StreamContext

if TYPE_CHECKING:
    from modules.logging import Logger


@dataclass
class SSEEvent:
    """
    SSE 事件数据类
    
    表示一个 Server-Sent Events 事件，包含事件的所有字段。
    
    Attributes:
        id: 事件 ID，用于重连时恢复（可选）
        event: 事件类型名称（可选）
        data: 事件数据内容
        retry: 客户端重连超时时间（毫秒，可选）
        timestamp: 事件创建时间戳
    """
    id: Optional[str] = None
    event: Optional[str] = None
    data: str = ""
    retry: Optional[int] = None
    timestamp: float = field(default_factory=time.time)
    
    def __str__(self) -> str:
        """返回事件的字符串表示"""
        parts = []
        if self.id:
            parts.append(f"id={self.id}")
        if self.event:
            parts.append(f"event={self.event}")
        parts.append(f"data={self.data[:50]}{'...' if len(self.data) > 50 else ''}")
        return f"SSEEvent({', '.join(parts)})"


class SSEHandler:
    """
    Server-Sent Events 处理器
    
    处理 SSE 长连接，支持事件解析、转发、心跳检测和重连恢复。
    
    功能：
    1. SSE 连接代理
    2. 事件解析与转发
    3. 心跳检测
    4. 事件过滤
    5. 事件缓存（用于重连）
    
    Attributes:
        config: 配置管理器
        logger: 日志记录器
        heartbeat_interval: 心跳间隔（秒）
        reconnect_timeout: 重连超时（毫秒）
        max_connections: 最大连接数
        _active_connections: 活跃连接字典
        _lock: 异步锁
        _event_cache: 事件缓存字典
        _cache_lock: 缓存锁
        stats: 统计信息字典
    """
    
    def __init__(self, config, logger: Optional['Logger'] = None):
        """
        初始化 SSE 处理器
        
        Args:
            config: 配置管理器，需支持 get 方法获取配置项
            logger: 日志记录器，如果为 None 则使用默认 logger
        """
        self.config = config
        self.logger = logger or loguru_logger
        
        # 配置参数
        self.heartbeat_interval = self._get_config('stream.sse.heartbeatInterval', 15)
        self.reconnect_timeout = self._get_config('stream.sse.reconnectTimeout', 3000)
        self.max_connections = self._get_config('stream.sse.maxConnections', 100)
        self.max_cached_events = self._get_config('stream.sse.maxCachedEvents', 100)
        
        # 活跃连接管理
        self._active_connections: Dict[str, StreamContext] = {}
        self._lock = asyncio.Lock()
        
        # 事件缓存（用于重连恢复）
        self._event_cache: Dict[str, List[SSEEvent]] = {}
        self._cache_lock = asyncio.Lock()
        
        # 统计信息
        self.stats = {
            'total_connections': 0,
            'active_connections': 0,
            'events_sent': 0,
            'events_received': 0,
            'reconnects': 0,
            'heartbeats_sent': 0,
            'errors': 0
        }
        
        self.logger.info(
            f"SSEHandler 初始化完成 | "
            f"心跳间隔={self.heartbeat_interval}s | "
            f"最大连接数={self.max_connections}"
        )
    
    def _get_config(self, key: str, default: Any) -> Any:
        """
        安全获取配置项
        
        Args:
            key: 配置键名
            default: 默认值
            
        Returns:
            配置值，如果不存在则返回默认值
        """
        try:
            if hasattr(self.config, 'get'):
                return self.config.get(key, default)
            elif isinstance(self.config, dict):
                # 支持嵌套键访问
                keys = key.split('.')
                value = self.config
                for k in keys:
                    if isinstance(value, dict) and k in value:
                        value = value[k]
                    else:
                        return default
                return value
            return default
        except Exception as e:
            self.logger.warning(f"获取配置项 {key} 失败: {e}，使用默认值 {default}")
            return default
    
    async def handle(self,
                    writer: asyncio.StreamWriter,
                    response: aiohttp.ClientResponse,
                    context: StreamContext) -> None:
        """
        处理 SSE 流
        
        这是 SSE 处理的主入口方法，负责：
        1. 检查连接数限制
        2. 发送 SSE 响应头
        3. 重连恢复（如果客户端发送了 Last-Event-ID）
        4. 启动心跳任务
        5. 解析并转发 SSE 事件
        6. 清理连接
        
        Args:
            writer: 客户端写入器，用于向客户端发送数据
            response: 目标服务器响应对象
            context: 流上下文
            
        Raises:
            Exception: 处理过程中的错误
        """
        # 检查连接数限制
        async with self._lock:
            if len(self._active_connections) >= self.max_connections:
                self.logger.warning(
                    f"SSE 连接数已达上限 ({self.max_connections})，拒绝新连接"
                )
                await self._send_error(writer, 503, "Service Unavailable: Too many SSE connections")
                return
            
            # 注册连接
            self._active_connections[context.stream_id] = context
            self.stats['total_connections'] += 1
            self.stats['active_connections'] += 1
        
        self.logger.info(
            f"SSE 连接建立: {context.stream_id} | "
            f"活跃连接数={len(self._active_connections)} | "
            f"URL={context.target_url}"
        )
        
        heartbeat_task = None
        recovered_events = 0
        
        try:
            # 发送 SSE 响应头
            await self._send_sse_headers(writer, response)
            
            # 检查是否为重连请求（Last-Event-ID）
            request_headers = context.metadata.get('request_headers', {})
            last_event_id = request_headers.get('Last-Event-ID') or request_headers.get('last-event-id')
            
            if last_event_id:
                self.logger.info(
                    f"SSE 重连恢复: {context.stream_id} | "
                    f"Last-Event-ID={last_event_id}"
                )
                self.stats['reconnects'] += 1
                
                # 发送缓存的事件
                cached_events = await self.get_cached_events(context.stream_id, last_event_id)
                for event in cached_events:
                    await self._forward_event(writer, event)
                    recovered_events += 1
                    self.stats['events_sent'] += 1
                    context.bytes_transferred += len(event.data)
                
                if recovered_events > 0:
                    self.logger.info(
                        f"SSE 重连恢复完成: {context.stream_id} | "
                        f"恢复事件数={recovered_events}"
                    )
            
            # 启动心跳任务
            heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(writer, context)
            )
            
            # 解析并转发 SSE 事件
            event_count = 0
            async for event in self._parse_sse_stream(response):
                # 检查连接是否仍然活跃
                if not context.is_active:
                    self.logger.info(f"SSE 连接被中断: {context.stream_id}")
                    break
                
                # 转发事件到客户端
                await self._forward_event(writer, event)
                event_count += 1
                
                # 缓存事件（用于重连恢复）
                await self._cache_event(context.stream_id, event)
                
                # 更新统计
                self.stats['events_sent'] += 1
                context.bytes_transferred += len(event.data)
                
                # 定期记录进度
                if event_count % 50 == 0:
                    self.logger.debug(
                        f"SSE 事件进度: {context.stream_id} | "
                        f"已发送={event_count} 个事件"
                    )
            
            self.logger.info(
                f"SSE 连接关闭: {context.stream_id} | "
                f"发送事件数={event_count} | "
                f"恢复事件数={recovered_events} | "
                f"传输大小={context.bytes_transferred} bytes"
            )
            
        except asyncio.CancelledError:
            self.logger.debug(f"SSE 连接被取消: {context.stream_id}")
            raise
            
        except ConnectionResetError:
            self.logger.warning(f"SSE 连接被重置: {context.stream_id}")
            self.stats['errors'] += 1
            
        except Exception as e:
            self.logger.opt(exception=True).error(f"SSE 处理错误 [{context.stream_id}]: {e}")
            self.stats['errors'] += 1
            raise
            
        finally:
            # 取消心跳任务
            if heartbeat_task:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
            
            # 清理连接
            async with self._lock:
                if context.stream_id in self._active_connections:
                    del self._active_connections[context.stream_id]
                self.stats['active_connections'] = max(0, self.stats['active_connections'] - 1)
    
    async def _send_sse_headers(self,
                               writer: asyncio.StreamWriter,
                               response: aiohttp.ClientResponse) -> None:
        """
        发送 SSE 响应头
        
        SSE 必须使用特定的响应头：
        - Content-Type: text/event-stream
        - Cache-Control: no-cache
        - Connection: keep-alive
        
        Args:
            writer: 客户端写入器
            response: 目标服务器响应（用于获取其他可能的头信息）
        """
        # SSE 必须使用 200 状态码
        status_line = "HTTP/1.1 200 OK\r\n"
        writer.write(status_line.encode('utf-8'))
        
        # SSE 必需的响应头
        headers = {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*',
            'X-Accel-Buffering': 'no',  # 禁用 Nginx 缓冲
            'Via': 'SilkRoad-Next/3.0'
        }
        
        for key, value in headers.items():
            writer.write(f"{key}: {value}\r\n".encode('utf-8'))
        
        # 结束响应头
        writer.write(b"\r\n")
        await writer.drain()
        
        self.logger.debug("SSE 响应头已发送")
    
    async def _parse_sse_stream(self,
                               response: aiohttp.ClientResponse) -> AsyncIterator[SSEEvent]:
        """
        解析 SSE 流
        
        SSE 流格式规范：
        - 事件以双换行符分隔
        - 每个事件包含多个字段（id, event, data, retry）
        - 以冒号开头的行是注释
        
        Args:
            response: 目标服务器响应
            
        Yields:
            SSEEvent 对象
            
        Raises:
            Exception: 解析错误
        """
        buffer = ""
        
        try:
            async for chunk in response.content.iter_chunked(1024):
                try:
                    # 解码数据
                    text = chunk.decode('utf-8', errors='ignore')
                    buffer += text
                    
                    # 解析完整的事件（以双换行符分隔）
                    while '\n\n' in buffer:
                        event_text, buffer = buffer.split('\n\n', 1)
                        event = self._parse_event(event_text)
                        
                        if event:
                            self.stats['events_received'] += 1
                            yield event
                            
                except UnicodeDecodeError as e:
                    self.logger.warning(f"SSE 数据解码错误: {e}")
                    continue
                except Exception as e:
                    self.logger.error(f"解析 SSE 事件失败: {e}")
                    continue
                    
        except asyncio.CancelledError:
            self.logger.debug("SSE 流解析被取消")
            raise
        except Exception as e:
            self.logger.error(f"SSE 流解析错误: {e}")
            raise
    
    def _parse_event(self, event_text: str) -> Optional[SSEEvent]:
        """
        解析单个 SSE 事件
        
        SSE 事件格式：
        - id: 事件ID
        - event: 事件类型
        - data: 事件数据（可以有多行）
        - retry: 重连超时
        
        Args:
            event_text: 事件文本（不含结束的双换行符）
            
        Returns:
            SSEEvent 对象，如果事件无效（无 data 字段）则返回 None
        """
        event = SSEEvent()
        
        for line in event_text.split('\n'):
            line = line.strip()
            
            # 跳过空行和注释
            if not line or line.startswith(':'):
                continue
            
            # 解析字段
            if ':' in line:
                field, value = line.split(':', 1)
                field = field.strip()
                value = value.strip()
                
                if field == 'id':
                    event.id = value
                elif field == 'event':
                    event.event = value
                elif field == 'data':
                    # data 字段可以有多行，用换行符连接
                    if event.data:
                        event.data += '\n' + value
                    else:
                        event.data = value
                elif field == 'retry':
                    try:
                        event.retry = int(value)
                    except ValueError:
                        self.logger.warning(f"无效的 retry 值: {value}")
            else:
                # 没有冒号的行，视为空字段名
                # 例如 "data" 等同于 "data:"
                if line == 'data':
                    if event.data:
                        event.data += '\n'
                else:
                    self.logger.debug(f"忽略无效的 SSE 行: {line}")
        
        # 返回事件（必须有 data 字段才有效）
        return event if event.data else None
    
    async def _forward_event(self,
                            writer: asyncio.StreamWriter,
                            event: SSEEvent) -> None:
        """
        转发 SSE 事件到客户端
        
        构建 SSE 事件文本并发送给客户端。
        
        Args:
            writer: 客户端写入器
            event: SSE 事件
        """
        # 构建事件文本
        event_lines = []
        
        # 添加 id 字段（如果有）
        if event.id:
            event_lines.append(f"id: {event.id}")
        
        # 添加 event 字段（如果有）
        if event.event:
            event_lines.append(f"event: {event.event}")
        
        # 添加 data 字段（可能包含多行）
        for data_line in event.data.split('\n'):
            event_lines.append(f"data: {data_line}")
        
        # 添加 retry 字段（如果有）
        if event.retry:
            event_lines.append(f"retry: {event.retry}")
        
        # 组合事件文本，以双换行符结束
        event_text = '\n'.join(event_lines) + '\n\n'
        
        # 发送事件
        writer.write(event_text.encode('utf-8'))
        await writer.drain()
    
    async def _heartbeat_loop(self,
                             writer: asyncio.StreamWriter,
                             context: StreamContext) -> None:
        """
        心跳循环
        
        定期发送心跳注释以保持连接活跃，检测连接是否断开。
        心跳格式为 SSE 注释：": heartbeat\n\n"
        
        Args:
            writer: 客户端写入器
            context: 流上下文
        """
        try:
            while context.is_active:
                # 等待心跳间隔
                await asyncio.sleep(self.heartbeat_interval)
                
                # 再次检查连接状态
                if not context.is_active:
                    break
                
                try:
                    # 发送心跳注释（SSE 格式的注释）
                    writer.write(b": heartbeat\n\n")
                    await writer.drain()
                    
                    self.stats['heartbeats_sent'] += 1
                    self.logger.debug(f"SSE 心跳: {context.stream_id}")
                    
                except ConnectionResetError:
                    self.logger.warning(f"SSE 心跳失败，连接已断开: {context.stream_id}")
                    context.is_active = False
                    break
                except Exception as e:
                    self.logger.error(f"SSE 心跳发送错误: {e}")
                    context.is_active = False
                    break
                    
        except asyncio.CancelledError:
            # 正常取消，不记录错误
            pass
        except Exception as e:
            self.logger.error(f"心跳循环错误 [{context.stream_id}]: {e}")
    
    async def _cache_event(self, stream_id: str, event: SSEEvent) -> None:
        """
        缓存事件（用于重连恢复）
        
        只缓存有 ID 的事件，因为这些事件可以在重连时被识别和跳过。
        
        Args:
            stream_id: 流 ID
            event: SSE 事件
        """
        # 只缓存有 ID 的事件
        if not event.id:
            return
        
        async with self._cache_lock:
            if stream_id not in self._event_cache:
                self._event_cache[stream_id] = []
            
            # 添加事件到缓存
            self._event_cache[stream_id].append(event)
            
            # 限制缓存大小，只保留最近的事件
            if len(self._event_cache[stream_id]) > self.max_cached_events:
                self._event_cache[stream_id] = self._event_cache[stream_id][-self.max_cached_events:]
    
    async def get_cached_events(self, stream_id: str, last_event_id: str) -> List[SSEEvent]:
        """
        获取缓存的事件（用于重连恢复）
        
        返回指定事件 ID 之后的所有缓存事件，用于客户端重连后恢复。
        
        Args:
            stream_id: 流 ID
            last_event_id: 客户端最后接收到的事件 ID
            
        Returns:
            事件列表（last_event_id 之后的事件）
        """
        async with self._cache_lock:
            if stream_id not in self._event_cache:
                return []
            
            events = self._event_cache[stream_id]
            
            # 如果没有指定 last_event_id，返回所有缓存事件
            if not last_event_id:
                return list(events)
            
            # 找到 last_event_id 之后的事件
            for i, event in enumerate(events):
                if event.id == last_event_id:
                    # 返回该事件之后的所有事件
                    return list(events[i + 1:])
            
            # 如果没找到 last_event_id，返回所有事件
            return list(events)
    
    async def clear_cache(self, stream_id: str) -> None:
        """
        清除指定流的事件缓存
        
        Args:
            stream_id: 流 ID
        """
        async with self._cache_lock:
            if stream_id in self._event_cache:
                del self._event_cache[stream_id]
                self.logger.debug(f"已清除 SSE 缓存: {stream_id}")
    
    async def _send_error(self, writer: asyncio.StreamWriter, 
                         status_code: int, message: str) -> None:
        """
        发送错误响应
        
        当发生错误时，发送 HTTP 错误响应给客户端。
        
        Args:
            writer: 客户端写入器
            status_code: HTTP 状态码
            message: 错误消息
        """
        response = f"HTTP/1.1 {status_code} {message}\r\n"
        response += "Content-Type: text/plain\r\n"
        response += f"Content-Length: {len(message)}\r\n"
        response += "\r\n"
        response += message
        
        writer.write(response.encode('utf-8'))
        await writer.drain()
    
    def get_stats(self) -> dict:
        """
        获取 SSE 统计信息
        
        返回包含 SSE 处理统计数据的字典，包括：
        - 连接统计
        - 事件统计
        - 缓存统计
        
        Returns:
            统计信息字典
        """
        return {
            **self.stats,
            'active_connections_count': len(self._active_connections),
            'cached_streams': len(self._event_cache),
            'cached_events': sum(len(events) for events in self._event_cache.values()),
            'max_connections': self.max_connections,
            'heartbeat_interval': self.heartbeat_interval,
            'reconnect_timeout': self.reconnect_timeout
        }
    
    async def get_active_connections(self) -> Dict[str, StreamContext]:
        """
        获取所有活跃连接
        
        Returns:
            流 ID 到流上下文的映射字典
        """
        async with self._lock:
            return dict(self._active_connections)
    
    async def close_connection(self, stream_id: str) -> bool:
        """
        关闭指定连接
        
        将指定连接标记为非活跃状态。
        
        Args:
            stream_id: 流 ID
            
        Returns:
            是否成功关闭
        """
        async with self._lock:
            if stream_id in self._active_connections:
                self._active_connections[stream_id].is_active = False
                self.logger.info(f"SSE 连接已标记为关闭: {stream_id}")
                return True
            return False
    
    async def close_all_connections(self) -> int:
        """
        关闭所有活跃连接
        
        Returns:
            关闭的连接数量
        """
        async with self._lock:
            count = len(self._active_connections)
            for stream_id, context in self._active_connections.items():
                context.is_active = False
                self.logger.debug(f"SSE 连接已标记为关闭: {stream_id}")
            
            self.logger.info(f"已关闭 {count} 个 SSE 连接")
            return count
    
    async def __aenter__(self):
        """
        异步上下文管理器入口
        
        Returns:
            self
        """
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """
        异步上下文管理器出口
        
        关闭所有活跃连接并清理缓存。
        
        Args:
            exc_type: 异常类型
            exc_val: 异常值
            exc_tb: 异常回溯
        """
        await self.close_all_connections()
        self._event_cache.clear()
        return False
