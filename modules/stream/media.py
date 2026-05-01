"""
媒体流处理模块

功能：
1. 视频流代理（MP4, WebM, HLS, DASH）
2. 音频流代理（MP3, AAC, OGG）
3. Range 请求支持（断点续传）
4. 自适应缓冲
5. 多码率支持
6. 流式缓存

作者: SilkRoad-Next Team
版本: 3.0.0
"""

import asyncio
import aiohttp
import re
import time
import logging
from typing import Optional, Dict, Any, TYPE_CHECKING
from dataclasses import dataclass

from modules.stream import StreamContext

if TYPE_CHECKING:
    from modules.logging import Logger


@dataclass
class RangeInfo:
    """
    Range 请求信息数据类
    
    用于存储 HTTP Range 请求的解析结果，支持断点续传功能。
    
    Attributes:
        start: 请求范围的起始字节位置
        end: 请求范围的结束字节位置（可选）
        total: 文件总大小（可选）
        is_valid: Range 请求是否有效
    """
    start: int
    end: Optional[int]
    total: Optional[int]
    is_valid: bool


class MediaHandler:
    """
    媒体流处理器
    
    处理视频/音频流媒体，支持 Range 请求（断点续传）、自适应缓冲、
    多码率切换等功能。
    
    功能：
    1. 处理视频/音频流
    2. 支持 Range 请求
    3. 自适应缓冲
    4. 流式缓存
    
    Attributes:
        config: 配置管理器
        logger: 日志记录器
        buffer_size: 缓冲区大小
        max_buffer_size: 最大缓冲区大小
        enable_range: 是否启用 Range 支持
        timeout: 流超时时间
        stats: 统计信息字典
        _cache: 流式缓存字典
        _cache_lock: 缓存锁
    """
    
    def __init__(self, config, logger: Optional['Logger'] = None):
        """
        初始化媒体流处理器
        
        Args:
            config: 配置管理器，需支持 get 方法获取配置项
            logger: 日志记录器，如果为 None 则使用默认 logger
        """
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        
        # 配置参数（使用安全的 get 方法，提供默认值）
        self.buffer_size = self._get_config('stream.media.bufferSize', 65536)
        self.max_buffer_size = self._get_config('stream.media.maxBufferSize', 10485760)
        self.enable_range = self._get_config('stream.media.enableRange', True)
        self.timeout = self._get_config('stream.media.timeout', 3600)
        
        # 统计信息
        self.stats = {
            'total_media_streams': 0,
            'range_requests': 0,
            'normal_requests': 0,
            'bytes_streamed': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'errors': 0
        }
        
        # 流式缓存（简单的内存缓存）
        self._cache: Dict[str, bytes] = {}
        self._cache_lock = asyncio.Lock()
        
        # 缓存配置
        self._max_cache_size = self._get_config('stream.buffer.memoryLimit', 104857600)
        self._current_cache_size = 0
        
        self.logger.info(
            f"MediaHandler 初始化完成 | "
            f"buffer_size={self.buffer_size} | "
            f"max_buffer_size={self.max_buffer_size} | "
            f"enable_range={self.enable_range}"
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
                # 支持嵌套键访问，如 'stream.media.bufferSize'
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
        处理媒体流
        
        这是媒体流处理的主入口方法，负责：
        1. 检查是否为 Range 请求
        2. 路由到对应的处理方法
        3. 更新统计信息
        
        Args:
            writer: 客户端写入器，用于向客户端发送数据
            response: 目标服务器响应对象
            context: 流上下文
            
        Raises:
            Exception: 处理过程中的错误
        """
        self.stats['total_media_streams'] += 1
        
        try:
            # 检查是否为 Range 请求
            content_range = response.headers.get('Content-Range')
            is_range_request = content_range is not None
            
            if is_range_request and self.enable_range:
                self.stats['range_requests'] += 1
                self.logger.debug(
                    f"处理 Range 请求: {context.stream_id} | "
                    f"Content-Range: {content_range}"
                )
                await self._handle_range_response(writer, response, context)
            else:
                self.stats['normal_requests'] += 1
                await self._handle_normal_response(writer, response, context)
            
            # 记录完成信息
            duration = time.time() - context.start_time
            self.logger.info(
                f"媒体流处理完成: {context.stream_id} | "
                f"类型={'Range' if is_range_request else 'Normal'} | "
                f"大小={context.bytes_transferred} bytes | "
                f"耗时={duration:.2f}s"
            )
            
        except Exception as e:
            self.logger.error(f"媒体流处理错误 [{context.stream_id}]: {e}", exc_info=True)
            self.stats['errors'] += 1
            raise
    
    async def _handle_range_response(self,
                                    writer: asyncio.StreamWriter,
                                    response: aiohttp.ClientResponse,
                                    context: StreamContext) -> None:
        """
        处理 Range 响应
        
        解析 Content-Range 头，发送 206 Partial Content 响应，
        并流式传输数据。
        
        Args:
            writer: 客户端写入器
            response: 目标服务器响应
            context: 流上下文
            
        Raises:
            Exception: 处理过程中的错误
        """
        # 解析 Content-Range
        content_range = response.headers.get('Content-Range', '')
        range_info = self._parse_content_range(content_range)
        
        if not range_info.is_valid:
            # 无效的 Range，降级到普通处理
            self.logger.warning(
                f"无效的 Range 响应，降级到普通处理: {context.stream_id}"
            )
            await self._handle_normal_response(writer, response, context)
            return
        
        self.logger.debug(
            f"Range 请求: {range_info.start}-{range_info.end}/{range_info.total}"
        )
        
        # 发送 206 Partial Content 响应头
        await self._send_range_headers(writer, response, range_info)
        
        # 流式传输数据
        await self._stream_content(writer, response, context)
    
    async def _handle_normal_response(self,
                                     writer: asyncio.StreamWriter,
                                     response: aiohttp.ClientResponse,
                                     context: StreamContext) -> None:
        """
        处理普通媒体响应
        
        发送 200 OK 响应头，并流式传输数据。
        
        Args:
            writer: 客户端写入器
            response: 目标服务器响应
            context: 流上下文
            
        Raises:
            Exception: 处理过程中的错误
        """
        # 发送响应头
        await self._send_normal_headers(writer, response)
        
        # 流式传输数据
        await self._stream_content(writer, response, context)
    
    async def _send_range_headers(self,
                                 writer: asyncio.StreamWriter,
                                 response: aiohttp.ClientResponse,
                                 range_info: RangeInfo) -> None:
        """
        发送 Range 响应头
        
        构建并发送 206 Partial Content 响应头到客户端。
        
        Args:
            writer: 客户端写入器
            response: 目标服务器响应
            range_info: Range 信息
        """
        # 发送 206 状态行
        status_line = "HTTP/1.1 206 Partial Content\r\n"
        writer.write(status_line.encode('utf-8'))
        
        # 需要跳过的响应头（我们会自己设置）
        skip_headers = {
            'transfer-encoding',
            'content-security-policy',
            'content-security-policy-report-only',
            'content-length',
            'content-range',
            'set-cookie'
        }
        
        # 转发响应头
        for key, value in response.headers.items():
            if key.lower() in skip_headers:
                continue
            writer.write(f"{key}: {value}\r\n".encode('utf-8'))
        
        # 设置正确的 Content-Length 和 Content-Range
        content_length = 0
        if range_info.end is not None:
            content_length = range_info.end - range_info.start + 1
        
        writer.write(f"Content-Length: {content_length}\r\n".encode('utf-8'))
        
        if range_info.total is not None and range_info.end is not None:
            content_range = f"bytes {range_info.start}-{range_info.end}/{range_info.total}"
            writer.write(f"Content-Range: {content_range}\r\n".encode('utf-8'))
        
        # 添加 Accept-Ranges 头，告知客户端支持 Range 请求
        writer.write(b"Accept-Ranges: bytes\r\n")
        
        # 添加代理标识
        writer.write(b"Via: SilkRoad-Next/3.0\r\n")
        
        # 结束响应头
        writer.write(b"\r\n")
        await writer.drain()
    
    async def _send_normal_headers(self,
                                  writer: asyncio.StreamWriter,
                                  response: aiohttp.ClientResponse) -> None:
        """
        发送普通响应头
        
        构建并发送 200 OK 响应头到客户端。
        
        Args:
            writer: 客户端写入器
            response: 目标服务器响应
        """
        # 发送状态行
        status_line = f"HTTP/1.1 {response.status} {response.reason}\r\n"
        writer.write(status_line.encode('utf-8'))
        
        # 需要跳过的响应头
        skip_headers = {
            'transfer-encoding',
            'content-security-policy',
            'content-security-policy-report-only',
            'set-cookie'
        }
        
        # 转发响应头
        for key, value in response.headers.items():
            if key.lower() in skip_headers:
                continue
            writer.write(f"{key}: {value}\r\n".encode('utf-8'))
        
        # 添加 Accept-Ranges 头，告知客户端支持 Range 请求
        writer.write(b"Accept-Ranges: bytes\r\n")
        
        # 添加代理标识
        writer.write(b"Via: SilkRoad-Next/3.0\r\n")
        
        # 结束响应头
        writer.write(b"\r\n")
        await writer.drain()
    
    async def _stream_content(self,
                             writer: asyncio.StreamWriter,
                             response: aiohttp.ClientResponse,
                             context: StreamContext) -> None:
        """
        流式传输内容
        
        使用自适应缓冲策略流式传输数据，支持流量控制和进度监控。
        
        缓冲策略：
        1. 数据首先写入缓冲区
        2. 当缓冲区达到阈值或超时时刷新
        3. 最后刷新剩余数据
        
        Args:
            writer: 客户端写入器
            response: 目标服务器响应
            context: 流上下文
            
        Raises:
            Exception: 传输过程中的错误
        """
        buffer = bytearray()
        last_flush_time = time.time()
        flush_interval = 0.1  # 100ms 刷新间隔
        chunk_count = 0
        
        try:
            async for chunk in response.content.iter_chunked(self.buffer_size):
                # 检查流是否仍然活跃
                if not context.is_active:
                    self.logger.info(f"媒体流被中断: {context.stream_id}")
                    break
                
                # 添加到缓冲区
                buffer.extend(chunk)
                
                # 检查是否需要刷新缓冲区
                current_time = time.time()
                should_flush = (
                    len(buffer) >= self.max_buffer_size or
                    (current_time - last_flush_time) >= flush_interval
                )
                
                if should_flush:
                    # 写入客户端
                    writer.write(bytes(buffer))
                    await writer.drain()
                    
                    # 更新统计
                    bytes_written = len(buffer)
                    context.bytes_transferred += bytes_written
                    self.stats['bytes_streamed'] += bytes_written
                    chunk_count += 1
                    
                    # 清空缓冲区
                    buffer.clear()
                    last_flush_time = current_time
                    
                    # 定期记录进度（每 50 个块）
                    if chunk_count % 50 == 0:
                        self.logger.debug(
                            f"媒体流传输进度: {context.stream_id} | "
                            f"已传输={context.bytes_transferred} bytes"
                        )
            
            # 刷新剩余数据
            if buffer:
                writer.write(bytes(buffer))
                await writer.drain()
                
                bytes_written = len(buffer)
                context.bytes_transferred += bytes_written
                self.stats['bytes_streamed'] += bytes_written
            
            self.logger.info(
                f"媒体流传输完成: {context.stream_id} | "
                f"大小={context.bytes_transferred} bytes | "
                f"块数={chunk_count}"
            )
            
        except ConnectionResetError:
            self.logger.warning(f"客户端连接被重置: {context.stream_id}")
            raise
            
        except Exception as e:
            self.logger.error(f"媒体流传输错误 [{context.stream_id}]: {e}")
            raise
    
    def _parse_content_range(self, content_range: str) -> RangeInfo:
        """
        解析 Content-Range 头
        
        支持以下格式：
        - bytes start-end/total
        - bytes start-*/total
        
        Args:
            content_range: Content-Range 头的值
            
        Returns:
            RangeInfo 对象
        """
        if not content_range:
            return RangeInfo(
                start=0,
                end=None,
                total=None,
                is_valid=False
            )
        
        try:
            # 格式: bytes start-end/total
            match = re.match(r'bytes\s+(\d+)-(\d+)/(\d+)', content_range.strip())
            
            if match:
                start = int(match.group(1))
                end = int(match.group(2))
                total = int(match.group(3))
                
                # 验证范围有效性
                if start <= end and end < total:
                    return RangeInfo(
                        start=start,
                        end=end,
                        total=total,
                        is_valid=True
                    )
            
            # 格式: bytes start-*/total
            match = re.match(r'bytes\s+(\d+)-\*/(\d+)', content_range.strip())
            
            if match:
                start = int(match.group(1))
                total = int(match.group(2))
                
                if start < total:
                    return RangeInfo(
                        start=start,
                        end=total - 1,
                        total=total,
                        is_valid=True
                    )
            
            # 格式: bytes */total（表示无效范围，但告知文件大小）
            match = re.match(r'bytes\s+\*/(\d+)', content_range.strip())
            
            if match:
                total = int(match.group(1))
                return RangeInfo(
                    start=0,
                    end=None,
                    total=total,
                    is_valid=False
                )
            
            self.logger.warning(f"无法解析 Content-Range: {content_range}")
            return RangeInfo(
                start=0,
                end=None,
                total=None,
                is_valid=False
            )
            
        except Exception as e:
            self.logger.error(f"解析 Content-Range 失败: {e}")
            return RangeInfo(
                start=0,
                end=None,
                total=None,
                is_valid=False
            )
    
    def parse_range_header(self, range_header: str, total_size: int) -> RangeInfo:
        """
        解析 Range 请求头
        
        支持以下格式：
        - bytes=start-end
        - bytes=start-
        - bytes=-end（从末尾计算）
        
        Args:
            range_header: Range 头的值
            total_size: 文件总大小
            
        Returns:
            RangeInfo 对象
        """
        if not range_header:
            return RangeInfo(
                start=0,
                end=None,
                total=total_size,
                is_valid=False
            )
        
        try:
            # 格式: bytes=start-end
            match = re.match(r'bytes=(\d+)-(\d+)', range_header.strip())
            
            if match:
                start = int(match.group(1))
                end = int(match.group(2))
                
                # 验证范围
                if start >= total_size or start > end:
                    return RangeInfo(
                        start=0,
                        end=None,
                        total=total_size,
                        is_valid=False
                    )
                
                # 限制结束位置不超过文件末尾
                end = min(end, total_size - 1)
                
                return RangeInfo(
                    start=start,
                    end=end,
                    total=total_size,
                    is_valid=True
                )
            
            # 格式: bytes=start-
            match = re.match(r'bytes=(\d+)-$', range_header.strip())
            
            if match:
                start = int(match.group(1))
                
                if start >= total_size:
                    return RangeInfo(
                        start=0,
                        end=None,
                        total=total_size,
                        is_valid=False
                    )
                
                return RangeInfo(
                    start=start,
                    end=total_size - 1,
                    total=total_size,
                    is_valid=True
                )
            
            # 格式: bytes=-end（从末尾计算）
            match = re.match(r'bytes=-(\d+)', range_header.strip())
            
            if match:
                suffix_length = int(match.group(1))
                start = max(0, total_size - suffix_length)
                
                return RangeInfo(
                    start=start,
                    end=total_size - 1,
                    total=total_size,
                    is_valid=True
                )
            
            self.logger.warning(f"无法解析 Range 头: {range_header}")
            return RangeInfo(
                start=0,
                end=None,
                total=total_size,
                is_valid=False
            )
            
        except Exception as e:
            self.logger.error(f"解析 Range 头失败: {e}")
            return RangeInfo(
                start=0,
                end=None,
                total=total_size,
                is_valid=False
            )
    
    async def cache_content(self, cache_key: str, content: bytes) -> bool:
        """
        缓存媒体内容
        
        将媒体内容缓存到内存中，用于后续请求的快速响应。
        
        Args:
            cache_key: 缓存键
            content: 要缓存的内容
            
        Returns:
            是否成功缓存
        """
        async with self._cache_lock:
            # 检查缓存大小限制
            content_size = len(content)
            if self._current_cache_size + content_size > self._max_cache_size:
                self.logger.warning(
                    f"缓存大小超限，无法缓存: {cache_key} | "
                    f"当前={self._current_cache_size} | "
                    f"请求={content_size} | "
                    f"限制={self._max_cache_size}"
                )
                return False
            
            self._cache[cache_key] = content
            self._current_cache_size += content_size
            
            self.logger.debug(
                f"已缓存内容: {cache_key} | "
                f"大小={content_size} | "
                f"总缓存={self._current_cache_size}"
            )
            return True
    
    async def get_cached_content(self, cache_key: str) -> Optional[bytes]:
        """
        获取缓存的媒体内容
        
        Args:
            cache_key: 缓存键
            
        Returns:
            缓存的内容，如果不存在则返回 None
        """
        async with self._cache_lock:
            if cache_key in self._cache:
                self.stats['cache_hits'] += 1
                self.logger.debug(f"缓存命中: {cache_key}")
                return self._cache[cache_key]
            
            self.stats['cache_misses'] += 1
            return None
    
    async def clear_cache(self, cache_key: Optional[str] = None) -> int:
        """
        清除缓存
        
        Args:
            cache_key: 要清除的缓存键，如果为 None 则清除所有缓存
            
        Returns:
            清除的字节数
        """
        async with self._cache_lock:
            if cache_key is not None:
                # 清除指定缓存
                if cache_key in self._cache:
                    size = len(self._cache[cache_key])
                    del self._cache[cache_key]
                    self._current_cache_size -= size
                    self.logger.debug(f"已清除缓存: {cache_key} | 大小={size}")
                    return size
                return 0
            else:
                # 清除所有缓存
                total_size = self._current_cache_size
                self._cache.clear()
                self._current_cache_size = 0
                self.logger.info(f"已清除所有缓存 | 大小={total_size}")
                return total_size
    
    def get_stats(self) -> dict:
        """
        获取媒体流统计信息
        
        返回包含媒体流处理统计数据的字典，包括：
        - 总流数、Range 请求数
        - 传输字节数
        - 缓存命中/未命中数
        - 错误数
        
        Returns:
            统计信息字典
        """
        return {
            **self.stats,
            'cache_size': len(self._cache),
            'cache_bytes': self._current_cache_size,
            'max_cache_bytes': self._max_cache_size,
            'buffer_size': self.buffer_size,
            'max_buffer_size': self.max_buffer_size,
            'enable_range': self.enable_range
        }
    
    def get_cache_info(self) -> Dict[str, Any]:
        """
        获取缓存信息
        
        Returns:
            缓存信息字典
        """
        return {
            'entries': len(self._cache),
            'total_bytes': self._current_cache_size,
            'max_bytes': self._max_cache_size,
            'usage_percent': (self._current_cache_size / self._max_cache_size * 100) 
                            if self._max_cache_size > 0 else 0,
            'hits': self.stats['cache_hits'],
            'misses': self.stats['cache_misses'],
            'hit_rate': (
                self.stats['cache_hits'] / 
                (self.stats['cache_hits'] + self.stats['cache_misses']) * 100
            ) if (self.stats['cache_hits'] + self.stats['cache_misses']) > 0 else 0
        }
    
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
        
        清除所有缓存。
        
        Args:
            exc_type: 异常类型
            exc_val: 异常值
            exc_tb: 异常回溯
        """
        await self.clear_cache()
        return False
