"""
其他流类型处理模块

功能：
1. 分块传输编码处理
2. Multipart 响应处理
3. 大文件下载优化
4. WebSocket 升级准备（V4）
5. 流量整形

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
class ChunkInfo:
    """
    分块信息数据类
    
    用于存储单个分块的传输统计信息。
    
    Attributes:
        size: 分块大小（字节）
        duration: 传输耗时（秒）
        rate: 传输速率（字节/秒）
    """
    size: int
    duration: float
    rate: float  # bytes/s


class OthersHandler:
    """
    其他流类型处理器
    
    处理除媒体流和 SSE 之外的其他流类型，包括：
    - 分块传输编码 (Transfer-Encoding: chunked)
    - Multipart 响应
    - 大文件下载
    - 流量整形
    
    Attributes:
        config: 配置管理器
        logger: 日志记录器
        default_chunk_size: 默认分块大小
        max_chunk_size: 最大分块大小
        enable_rate_limit: 是否启用流量整形
        max_rate: 最大传输速率（字节/秒）
        stats: 统计信息字典
    """
    
    def __init__(self, config, logger: Optional['Logger'] = None):
        """
        初始化其他流处理器
        
        Args:
            config: 配置管理器，需支持 get 方法获取配置项
            logger: 日志记录器，如果为 None 则使用默认 logger
        """
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        
        # 配置参数（使用安全的 get 方法，提供默认值）
        self.default_chunk_size = self._get_config('stream.chunked.defaultChunkSize', 8192)
        self.max_chunk_size = self._get_config('stream.chunked.maxChunkSize', 65536)
        self.enable_rate_limit = self._get_config('stream.rateLimit.enabled', False)
        self.max_rate = self._get_config('stream.rateLimit.maxRate', 10485760)  # 10MB/s
        
        # 统计信息
        self.stats = {
            'total_streams': 0,
            'chunked_streams': 0,
            'multipart_streams': 0,
            'bytes_transferred': 0,
            'rate_limited': 0,
            'errors': 0
        }
        
        self.logger.info("OthersHandler 初始化完成")
    
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
                # 支持嵌套键访问，如 'stream.chunked.defaultChunkSize'
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
        处理其他流类型
        
        根据响应头判断流类型，并路由到对应的处理方法：
        - Transfer-Encoding: chunked -> _handle_chunked
        - Content-Type: multipart/* -> _handle_multipart
        - 其他 -> _handle_default
        
        Args:
            writer: 客户端写入器，用于向客户端发送数据
            response: 目标服务器响应对象
            context: 流上下文，包含流的相关信息
            
        Raises:
            Exception: 处理过程中的错误
        """
        self.stats['total_streams'] += 1
        
        try:
            # 检查传输类型
            transfer_encoding = response.headers.get('Transfer-Encoding', '').lower()
            content_type = response.headers.get('Content-Type', '').lower()
            
            self.logger.debug(
                f"处理流: {context.stream_id} | "
                f"Transfer-Encoding={transfer_encoding} | "
                f"Content-Type={content_type}"
            )
            
            if 'chunked' in transfer_encoding:
                await self._handle_chunked(writer, response, context)
            elif 'multipart' in content_type:
                await self._handle_multipart(writer, response, context)
            else:
                await self._handle_default(writer, response, context)
            
        except Exception as e:
            self.logger.error(f"其他流处理错误 [{context.stream_id}]: {e}", exc_info=True)
            self.stats['errors'] += 1
            raise
    
    async def _handle_chunked(self,
                             writer: asyncio.StreamWriter,
                             response: aiohttp.ClientResponse,
                             context: StreamContext) -> None:
        """
        处理分块传输
        
        实现 HTTP 分块传输编码，格式为：
        <chunk-size-hex>\r\n
        <chunk-data>\r\n
        ...
        0\r\n
        \r\n
        
        Args:
            writer: 客户端写入器
            response: 目标服务器响应
            context: 流上下文
        """
        self.stats['chunked_streams'] += 1
        
        # 发送响应头
        await self._send_headers(writer, response)
        
        # 分块传输
        chunk_count = 0
        start_time = time.time()
        chunk_infos: list = []  # 存储分块信息用于统计
        
        try:
            async for chunk in response.content.iter_chunked(self.default_chunk_size):
                # 检查流是否仍然活跃
                if not context.is_active:
                    self.logger.info(f"分块传输被中断: {context.stream_id}")
                    break
                
                chunk_start = time.time()
                
                # 应用流量整形
                if self.enable_rate_limit:
                    await self._apply_rate_limit(len(chunk), start_time, chunk_count)
                
                # 发送分块
                # 格式: <size>\r\n<data>\r\n
                chunk_size_hex = format(len(chunk), 'x')
                writer.write(f"{chunk_size_hex}\r\n".encode('utf-8'))
                writer.write(chunk)
                writer.write(b"\r\n")
                await writer.drain()
                
                # 计算分块信息
                chunk_duration = time.time() - chunk_start
                chunk_rate = len(chunk) / chunk_duration if chunk_duration > 0 else 0
                chunk_info = ChunkInfo(
                    size=len(chunk),
                    duration=chunk_duration,
                    rate=chunk_rate
                )
                chunk_infos.append(chunk_info)
                
                # 更新统计
                context.bytes_transferred += len(chunk)
                self.stats['bytes_transferred'] += len(chunk)
                chunk_count += 1
                
                # 定期记录进度（每 50 个块）
                if chunk_count % 50 == 0:
                    self.logger.debug(
                        f"分块传输进度: {context.stream_id} | "
                        f"块数={chunk_count} | "
                        f"已传输={context.bytes_transferred} bytes"
                    )
            
            # 发送结束标记
            writer.write(b"0\r\n\r\n")
            await writer.drain()
            
            # 计算统计信息
            duration = time.time() - start_time
            avg_rate = context.bytes_transferred / duration if duration > 0 else 0
            
            # 计算平均分块信息
            if chunk_infos:
                avg_chunk_size = sum(c.size for c in chunk_infos) / len(chunk_infos)
                avg_chunk_duration = sum(c.duration for c in chunk_infos) / len(chunk_infos)
            else:
                avg_chunk_size = 0
                avg_chunk_duration = 0
            
            self.logger.info(
                f"分块传输完成: {context.stream_id} | "
                f"块数={chunk_count} | "
                f"大小={context.bytes_transferred} bytes | "
                f"耗时={duration:.2f}s | "
                f"速率={avg_rate:.2f} bytes/s | "
                f"平均块大小={avg_chunk_size:.0f} bytes"
            )
            
        except Exception as e:
            self.logger.error(f"分块传输错误 [{context.stream_id}]: {e}")
            raise
    
    async def _handle_multipart(self,
                               writer: asyncio.StreamWriter,
                               response: aiohttp.ClientResponse,
                               context: StreamContext) -> None:
        """
        处理 Multipart 响应
        
        Multipart 响应通常用于：
        - 表单文件上传响应
        - MJPEG 视频流
        - 混合内容响应
        
        Args:
            writer: 客户端写入器
            response: 目标服务器响应
            context: 流上下文
        """
        self.stats['multipart_streams'] += 1
        
        # 发送响应头
        await self._send_headers(writer, response)
        
        # 获取 boundary
        content_type = response.headers.get('Content-Type', '')
        boundary = self._extract_boundary(content_type)
        
        if not boundary:
            # 无法解析 boundary，降级到默认处理
            self.logger.warning(
                f"无法解析 multipart boundary: {context.stream_id}，"
                f"降级到默认处理"
            )
            await self._handle_default(writer, response, context)
            return
        
        self.logger.debug(f"Multipart boundary: {boundary}")
        
        # 流式传输 multipart 数据
        part_count = 0
        start_time = time.time()
        boundary_bytes = f'--{boundary}'.encode('utf-8')
        
        try:
            async for chunk in response.content.iter_chunked(self.default_chunk_size):
                # 检查流是否仍然活跃
                if not context.is_active:
                    self.logger.info(f"Multipart 传输被中断: {context.stream_id}")
                    break
                
                # 应用流量整形
                if self.enable_rate_limit:
                    await self._apply_rate_limit(len(chunk), start_time, 0)
                
                # 写入数据
                writer.write(chunk)
                await writer.drain()
                
                # 统计 part 数量（通过检测 boundary 出现次数）
                part_count += chunk.count(boundary_bytes)
                
                # 更新统计
                context.bytes_transferred += len(chunk)
                self.stats['bytes_transferred'] += len(chunk)
            
            # 计算统计信息
            duration = time.time() - start_time
            avg_rate = context.bytes_transferred / duration if duration > 0 else 0
            
            self.logger.info(
                f"Multipart 传输完成: {context.stream_id} | "
                f"parts={part_count} | "
                f"大小={context.bytes_transferred} bytes | "
                f"耗时={duration:.2f}s | "
                f"速率={avg_rate:.2f} bytes/s"
            )
            
        except Exception as e:
            self.logger.error(f"Multipart 传输错误 [{context.stream_id}]: {e}")
            raise
    
    async def _handle_default(self,
                             writer: asyncio.StreamWriter,
                             response: aiohttp.ClientResponse,
                             context: StreamContext) -> None:
        """
        默认流处理
        
        对于无法识别的流类型，使用简单的流式传输方式。
        
        Args:
            writer: 客户端写入器
            response: 目标服务器响应
            context: 流上下文
        """
        # 发送响应头
        await self._send_headers(writer, response)
        
        # 流式传输
        start_time = time.time()
        chunk_count = 0
        
        try:
            async for chunk in response.content.iter_chunked(self.default_chunk_size):
                # 检查流是否仍然活跃
                if not context.is_active:
                    self.logger.info(f"默认流传输被中断: {context.stream_id}")
                    break
                
                # 应用流量整形
                if self.enable_rate_limit:
                    await self._apply_rate_limit(len(chunk), start_time, chunk_count)
                
                # 写入数据
                writer.write(chunk)
                await writer.drain()
                
                # 更新统计
                context.bytes_transferred += len(chunk)
                self.stats['bytes_transferred'] += len(chunk)
                chunk_count += 1
                
                # 定期记录进度（每 100 个块）
                if chunk_count % 100 == 0:
                    self.logger.debug(
                        f"默认流传输进度: {context.stream_id} | "
                        f"已传输={context.bytes_transferred} bytes"
                    )
            
            # 计算统计信息
            duration = time.time() - start_time
            avg_rate = context.bytes_transferred / duration if duration > 0 else 0
            
            self.logger.info(
                f"默认流传输完成: {context.stream_id} | "
                f"大小={context.bytes_transferred} bytes | "
                f"耗时={duration:.2f}s | "
                f"速率={avg_rate:.2f} bytes/s | "
                f"块数={chunk_count}"
            )
            
        except Exception as e:
            self.logger.error(f"默认流传输错误 [{context.stream_id}]: {e}")
            raise
    
    async def _send_headers(self,
                           writer: asyncio.StreamWriter,
                           response: aiohttp.ClientResponse) -> None:
        """
        发送响应头
        
        构建并发送 HTTP 响应头到客户端，过滤掉不应转发的头。
        
        Args:
            writer: 客户端写入器
            response: 目标服务器响应
        """
        # 发送状态行
        status_line = f"HTTP/1.1 {response.status} {response.reason}\r\n"
        writer.write(status_line.encode('utf-8'))
        
        # 需要跳过的响应头（不应转发给客户端）
        skip_headers = {
            'transfer-encoding',           # 传输编码由我们控制
            'content-security-policy',     # 安全策略
            'content-security-policy-report-only',
            'set-cookie',                  # Cookie 由 CookieHandler 处理
            'strict-transport-security',   # HSTS
        }
        
        # 转发响应头
        for key, value in response.headers.items():
            if key.lower() in skip_headers:
                continue
            writer.write(f"{key}: {value}\r\n".encode('utf-8'))
        
        # 添加代理标识
        writer.write(b"Via: SilkRoad-Next/3.0\r\n")
        
        # 结束响应头
        writer.write(b"\r\n")
        await writer.drain()
    
    async def _apply_rate_limit(self,
                               chunk_size: int,
                               start_time: float,
                               chunk_count: int) -> None:
        """
        应用流量整形
        
        通过计算期望传输时间和实际传输时间的差异，
        在必要时暂停传输以限制带宽使用。
        
        流量整形算法：
        1. 计算已传输的总字节数
        2. 根据最大速率计算期望传输时间
        3. 如果实际传输时间小于期望时间，则等待差值
        
        Args:
            chunk_size: 当前分块大小（字节）
            start_time: 传输开始时间（秒）
            chunk_count: 已传输的块数
        """
        if not self.enable_rate_limit or self.max_rate <= 0:
            return
        
        # 计算已传输的总字节数（估算）
        total_bytes = chunk_size * (chunk_count + 1)
        
        # 计算期望时间（根据最大速率）
        expected_time = total_bytes / self.max_rate
        
        # 计算实际已用时间
        elapsed = time.time() - start_time
        
        # 如果传输过快，等待
        if elapsed < expected_time:
            sleep_time = expected_time - elapsed
            # 限制单次等待时间，避免阻塞过久
            sleep_time = min(sleep_time, 1.0)
            await asyncio.sleep(sleep_time)
            self.stats['rate_limited'] += 1
            
            self.logger.debug(
                f"流量整形: 等待 {sleep_time:.3f}s | "
                f"速率限制={self.max_rate} bytes/s"
            )
    
    def _extract_boundary(self, content_type: str) -> Optional[str]:
        """
        从 Content-Type 中提取 boundary
        
        Multipart 响应的 Content-Type 格式为：
        multipart/...; boundary=xxx
        
        Args:
            content_type: Content-Type 头的值
            
        Returns:
            boundary 字符串，如果提取失败则返回 None
            
        Examples:
            >>> handler._extract_boundary('multipart/form-data; boundary=----WebKitFormBoundary')
            '----WebKitFormBoundary'
            >>> handler._extract_boundary('multipart/mixed; boundary="my-boundary"')
            'my-boundary'
        """
        if not content_type:
            return None
        
        # 格式: multipart/...; boundary=xxx 或 boundary="xxx"
        match = re.search(r'boundary=([^\s;]+)', content_type, re.IGNORECASE)
        
        if match:
            boundary = match.group(1)
            # 移除可能的引号
            boundary = boundary.strip('"\'')
            return boundary
        
        return None
    
    def get_stats(self) -> dict:
        """
        获取统计信息
        
        返回包含处理器统计数据的字典，包括：
        - 总流数、分块流数、multipart 流数
        - 传输字节数
        - 流量整形次数
        - 错误数
        
        Returns:
            统计信息字典
        """
        return {
            **self.stats,
            'default_chunk_size': self.default_chunk_size,
            'max_chunk_size': self.max_chunk_size,
            'enable_rate_limit': self.enable_rate_limit,
            'max_rate': self.max_rate
        }
    
    def reset_stats(self) -> None:
        """
        重置统计信息
        
        将所有统计计数器归零。
        """
        self.stats = {
            'total_streams': 0,
            'chunked_streams': 0,
            'multipart_streams': 0,
            'bytes_transferred': 0,
            'rate_limited': 0,
            'errors': 0
        }
        self.logger.info("统计信息已重置")
    
    def set_rate_limit(self, enabled: bool, max_rate: Optional[int] = None) -> None:
        """
        动态设置流量整形参数
        
        Args:
            enabled: 是否启用流量整形
            max_rate: 最大传输速率（字节/秒），如果为 None 则保持当前值
        """
        self.enable_rate_limit = enabled
        if max_rate is not None:
            self.max_rate = max_rate
        
        self.logger.info(
            f"流量整形设置已更新: enabled={enabled}, "
            f"max_rate={self.max_rate} bytes/s"
        )
    
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
        
        Args:
            exc_type: 异常类型
            exc_val: 异常值
            exc_tb: 异常回溯
        """
        # 记录最终统计信息
        self.logger.info(f"OthersHandler 关闭，最终统计: {self.get_stats()}")
        return False
