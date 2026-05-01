"""
流处理核心引擎

功能：
1. 流类型识别与路由
2. 统一的流式传输接口
3. 缓冲区管理
4. 流量控制与限速
5. 错误处理与恢复
6. 统计与监控
7. WAF 检测与拦截处理 (V5)

作者: SilkRoad-Next Team
版本: 3.0.0
"""

import asyncio
import aiohttp
import uuid
import time
from typing import Optional, Dict, Any, TYPE_CHECKING
import logging

from modules.stream import StreamType, StreamContext
from modules.wafpasser import WAFDetector, WAFPasser

if TYPE_CHECKING:
    from modules.logging import Logger


class StreamHandler:
    """
    流处理核心管理器
    
    功能：
    1. 流类型识别与路由
    2. 统一的流式传输接口
    3. 缓冲区管理
    4. 流量控制
    5. 错误处理
    
    Attributes:
        config: 配置管理器
        logger: 日志记录器
        media_handler: 媒体流处理器
        sse_handler: SSE 处理器
        others_handler: 其他流处理器
        _active_streams: 活跃流字典
        _lock: 异步锁
        stats: 统计信息字典
        buffer_size: 缓冲区大小
        max_buffer_size: 最大缓冲区大小
        stream_timeout: 流超时时间
    """
    
    def __init__(self, config, logger: Optional['Logger'] = None):
        """
        初始化流处理器
        
        Args:
            config: 配置管理器，需支持 get 方法获取配置项
            logger: 日志记录器，如果为 None 则使用默认 logger
        """
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        
        # 子处理器（由外部注入）
        self.media_handler = None
        self.sse_handler = None
        self.others_handler = None
        
        # WAF 检测器 (V5)
        self.waf_detector = WAFDetector(WAFPasser())
        
        # 活跃流管理
        self._active_streams: Dict[str, StreamContext] = {}
        self._lock = asyncio.Lock()
        
        # 统计信息
        self.stats = {
            'total_streams': 0,
            'active_streams': 0,
            'media_streams': 0,
            'sse_streams': 0,
            'bytes_transferred': 0,
            'errors': 0,
            'waf_blocked': 0  # WAF 拦截统计
        }
        
        # 配置参数（使用安全的 get 方法，提供默认值）
        self.buffer_size = self._get_config('stream.chunked.defaultChunkSize', 8192)
        self.max_buffer_size = self._get_config('stream.media.maxBufferSize', 10485760)
        self.stream_timeout = self._get_config('stream.media.timeout', 3600)
        
        self.logger.info("StreamHandler 初始化完成 (WAF 检测已启用)")
    
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
    
    def set_media_handler(self, handler) -> None:
        """
        设置媒体流处理器
        
        Args:
            handler: MediaHandler 实例
        """
        self.media_handler = handler
        self.logger.debug("媒体流处理器已设置")
    
    def set_sse_handler(self, handler) -> None:
        """
        设置 SSE 处理器
        
        Args:
            handler: SSEHandler 实例
        """
        self.sse_handler = handler
        self.logger.debug("SSE 处理器已设置")
    
    def set_others_handler(self, handler) -> None:
        """
        设置其他流处理器
        
        Args:
            handler: OthersHandler 实例
        """
        self.others_handler = handler
        self.logger.debug("其他流处理器已设置")
    
    def identify_stream_type(self, 
                            headers: Dict[str, str], 
                            url: str) -> StreamType:
        """
        识别流类型
        
        根据响应头和 URL 判断流的类型，优先级如下：
        1. SSE (text/event-stream)
        2. 媒体流 (video/*, audio/*, HLS 等)
        3. 分块传输 (Transfer-Encoding: chunked)
        4. WebSocket 升级 (Upgrade: websocket)
        5. URL 后缀判断
        6. Range 相关头判断
        7. 默认返回 CHUNKED
        
        Args:
            headers: 响应头字典
            url: 请求 URL
            
        Returns:
            流类型枚举值
        """
        content_type = headers.get('Content-Type', '').lower()
        
        # 1. 检查 SSE
        if 'text/event-stream' in content_type:
            return StreamType.SSE
        
        # 2. 检查媒体流
        media_types = [
            'video/', 
            'audio/', 
            'application/x-mpegurl',
            'application/vnd.apple.mpegurl'
        ]
        for media_type in media_types:
            if media_type in content_type:
                return StreamType.MEDIA
        
        # 3. 检查分块传输
        transfer_encoding = headers.get('Transfer-Encoding', '').lower()
        if 'chunked' in transfer_encoding:
            return StreamType.CHUNKED
        
        # 4. 检查 WebSocket 升级
        if headers.get('Upgrade', '').lower() == 'websocket':
            return StreamType.WEBSOCKET
        
        # 5. 检查 URL 后缀
        media_extensions = [
            '.mp4', '.mp3', '.avi', '.mov', '.flv',
            '.m3u8', '.ts', '.webm', '.ogg', '.mkv',
            '.wav', '.aac', '.flac', '.m4a', '.m4v'
        ]
        url_lower = url.lower()
        if any(url_lower.endswith(ext) for ext in media_extensions):
            return StreamType.MEDIA
        
        # 6. 检查 Range 相关头
        if 'Content-Range' in headers or 'Accept-Ranges' in headers:
            return StreamType.MEDIA
        
        # 7. 默认返回分块传输类型
        return StreamType.CHUNKED
    
    async def handle_stream(self,
                           writer: asyncio.StreamWriter,
                           response: aiohttp.ClientResponse,
                           target_url: str,
                           request_headers: Dict[str, str]) -> None:
        """
        处理流式响应
        
        这是流处理的主入口方法，负责：
        1. 识别流类型
        2. 创建流上下文
        3. 注册活跃流
        4. 路由到对应的子处理器
        5. 清理流上下文
        
        Args:
            writer: 客户端写入器，用于向客户端发送数据
            response: 目标服务器响应对象
            target_url: 目标 URL
            request_headers: 原始请求头
            
        Raises:
            asyncio.TimeoutError: 流处理超时
            Exception: 其他处理错误
        """
        # 识别流类型
        stream_type = self.identify_stream_type(
            dict(response.headers), 
            target_url
        )
        
        # 创建流上下文
        stream_id = self._generate_stream_id()
        context = StreamContext(
            stream_id=stream_id,
            stream_type=stream_type,
            target_url=target_url,
            content_type=response.headers.get('Content-Type', ''),
            content_length=response.content_length,
            start_time=time.time(),
            bytes_transferred=0,
            is_active=True,
            metadata={
                'request_headers': request_headers
            }
        )
        
        # 注册活跃流
        async with self._lock:
            self._active_streams[stream_id] = context
            self.stats['total_streams'] += 1
            self.stats['active_streams'] += 1
            
            # 更新类型统计
            if stream_type == StreamType.MEDIA:
                self.stats['media_streams'] += 1
            elif stream_type == StreamType.SSE:
                self.stats['sse_streams'] += 1
        
        self.logger.info(
            f"开始处理流: {stream_id} | "
            f"类型={stream_type.value} | "
            f"URL={target_url}"
        )
        
        try:
            # WAF 检测 (V5)
            if await self._is_stream_blocked(response):
                await self._handle_stream_block(writer, response, context)
                return
            
            # 根据流类型路由到对应处理器
            if stream_type == StreamType.MEDIA and self.media_handler:
                await self.media_handler.handle(
                    writer, response, context
                )
            elif stream_type == StreamType.SSE and self.sse_handler:
                await self.sse_handler.handle(
                    writer, response, context
                )
            elif stream_type == StreamType.CHUNKED and self.others_handler:
                await self.others_handler.handle(
                    writer, response, context
                )
            else:
                # 默认处理（包括 WEBSOCKET 和 UNKNOWN 类型）
                await self._handle_default(writer, response, context)
            
            # 记录完成信息
            duration = time.time() - context.start_time
            self.logger.info(
                f"流处理完成: {stream_id} | "
                f"类型={stream_type.value} | "
                f"大小={context.bytes_transferred} bytes | "
                f"耗时={duration:.2f}s"
            )
            
        except asyncio.TimeoutError:
            self.logger.warning(f"流超时: {stream_id}")
            self.stats['errors'] += 1
            raise
            
        except ConnectionResetError:
            self.logger.warning(f"连接被重置: {stream_id}")
            self.stats['errors'] += 1
            raise
            
        except Exception as e:
            self.logger.error(f"流处理错误 [{stream_id}]: {e}", exc_info=True)
            self.stats['errors'] += 1
            raise
            
        finally:
            # 清理流上下文
            context.is_active = False
            async with self._lock:
                if stream_id in self._active_streams:
                    del self._active_streams[stream_id]
                self.stats['active_streams'] = max(0, self.stats['active_streams'] - 1)
                self.stats['bytes_transferred'] += context.bytes_transferred
    
    async def _handle_default(self,
                             writer: asyncio.StreamWriter,
                             response: aiohttp.ClientResponse,
                             context: StreamContext) -> None:
        """
        默认流处理方法
        
        当没有对应的子处理器时，使用此方法进行基本的流式传输。
        
        Args:
            writer: 客户端写入器
            response: 目标服务器响应
            context: 流上下文
            
        Raises:
            Exception: 传输过程中的错误
        """
        try:
            # 发送响应头
            await self._send_stream_headers(writer, response)
            
            # 流式传输数据
            chunk_count = 0
            async for chunk in response.content.iter_chunked(self.buffer_size):
                # 检查流是否仍然活跃
                if not context.is_active:
                    self.logger.info(f"流被中断: {context.stream_id}")
                    break
                
                # 写入数据
                writer.write(chunk)
                await writer.drain()
                
                # 更新统计
                context.bytes_transferred += len(chunk)
                chunk_count += 1
                
                # 定期记录进度（每 100 个块）
                if chunk_count % 100 == 0:
                    self.logger.debug(
                        f"流传输进度: {context.stream_id} | "
                        f"已传输={context.bytes_transferred} bytes"
                    )
            
            self.logger.info(
                f"默认流传输完成: {context.stream_id} | "
                f"类型={context.stream_type.value} | "
                f"大小={context.bytes_transferred} bytes | "
                f"块数={chunk_count}"
            )
            
        except Exception as e:
            self.logger.error(f"默认流处理错误 [{context.stream_id}]: {e}")
            raise
    
    async def _send_stream_headers(self,
                                   writer: asyncio.StreamWriter,
                                   response: aiohttp.ClientResponse) -> None:
        """
        发送流式响应头
        
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
            'public-key-pins',             # HPKP
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
    
    def _generate_stream_id(self) -> str:
        """
        生成唯一流 ID
        
        使用 UUID 生成短格式的唯一标识符。
        
        Returns:
            8 字符的流 ID 字符串
        """
        return str(uuid.uuid4())[:8]
    
    async def get_active_streams(self) -> Dict[str, StreamContext]:
        """
        获取所有活跃流
        
        返回当前所有活跃流的上下文信息副本。
        
        Returns:
            流 ID 到流上下文的映射字典
        """
        async with self._lock:
            return dict(self._active_streams)
    
    async def close_stream(self, stream_id: str) -> bool:
        """
        关闭指定流
        
        将指定流标记为非活跃状态，流会在下一次检查时停止传输。
        
        Args:
            stream_id: 流 ID
            
        Returns:
            是否成功关闭（如果流不存在则返回 False）
        """
        async with self._lock:
            if stream_id in self._active_streams:
                self._active_streams[stream_id].is_active = False
                self.logger.info(f"流已标记为关闭: {stream_id}")
                return True
            
            self.logger.warning(f"尝试关闭不存在的流: {stream_id}")
            return False
    
    async def close_all_streams(self) -> int:
        """
        关闭所有活跃流
        
        将所有活跃流标记为非活跃状态。
        
        Returns:
            关闭的流数量
        """
        async with self._lock:
            count = len(self._active_streams)
            for stream_id, context in self._active_streams.items():
                context.is_active = False
                self.logger.debug(f"流已标记为关闭: {stream_id}")
            
            self.logger.info(f"已关闭 {count} 个活跃流")
            return count
    
    def get_stats(self) -> dict:
        """
        获取流处理统计信息
        
        返回包含流处理统计数据的字典，包括：
        - 总流数、活跃流数
        - 各类型流数量
        - 传输字节数
        - 错误数
        
        Returns:
            统计信息字典
        """
        return {
            **self.stats,
            'active_streams_count': len(self._active_streams),
            'buffer_size': self.buffer_size,
            'max_buffer_size': self.max_buffer_size,
            'stream_timeout': self.stream_timeout
        }
    
    def get_stream_info(self, stream_id: str) -> Optional[StreamContext]:
        """
        获取指定流的信息
        
        Args:
            stream_id: 流 ID
            
        Returns:
            流上下文，如果流不存在则返回 None
        """
        return self._active_streams.get(stream_id)
    
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
        
        关闭所有活跃流。
        
        Args:
            exc_type: 异常类型
            exc_val: 异常值
            exc_tb: 异常回溯
        """
        await self.close_all_streams()
        return False
    
    async def _is_stream_blocked(
        self,
        response: aiohttp.ClientResponse
    ) -> bool:
        """
        检测流媒体请求是否被 WAF 拦截
        
        检测逻辑:
        1. 检查状态码是否为 403 或 503
        2. 如果 Content-Type 是 text/html，读取前 1024 字节
        3. 使用 waf_detector.is_blocked_response 检测
        
        Args:
            response: 目标服务器响应对象
            
        Returns:
            如果检测到 WAF 拦截则返回 True，否则返回 False
        """
        status_code = response.status
        
        # 检查状态码是否为常见的 WAF 拦截状态码
        if status_code not in [403, 503]:
            return False
        
        # 获取 Content-Type
        content_type = response.headers.get('Content-Type', '').lower()
        
        # 如果是 HTML 响应，可能包含 WAF 拦截页面
        if 'text/html' in content_type:
            try:
                # 读取前 1024 字节进行检测
                # 注意：这会消耗响应流，需要特殊处理
                preview = await response.content.read(1024)
                
                if preview:
                    preview_text = preview.decode('utf-8', errors='ignore')
                    
                    # 使用 WAF 检测器判断是否被拦截
                    is_blocked = self.waf_detector.is_blocked_response(
                        dict(response.headers),
                        preview_text,
                        status_code
                    )
                    
                    if is_blocked:
                        self.logger.warning(
                            f"WAF 拦截检测 | 状态码: {status_code} | "
                            f"Content-Type: {content_type}"
                        )
                        return True
                    
            except Exception as e:
                self.logger.error(f"WAF 检测时发生错误: {e}")
                return False
        
        return False
    
    async def _handle_stream_block(
        self,
        writer: asyncio.StreamWriter,
        response: aiohttp.ClientResponse,
        context: StreamContext
    ) -> None:
        """
        处理 WAF 拦截的流媒体请求
        
        处理流程:
        1. 记录 WAF 拦截日志
        2. 获取详细的 WAF 检测结果
        3. 返回错误响应给客户端
        
        Args:
            writer: 客户端写入器
            response: 目标服务器响应对象
            context: 流上下文
        """
        # 更新统计
        self.stats['waf_blocked'] += 1
        
        # 获取详细的 WAF 检测结果
        try:
            preview = await response.content.read(1024)
            preview_text = preview.decode('utf-8', errors='ignore') if preview else ''
            
            detection_result = self.waf_detector.detect_waf(
                dict(response.headers),
                preview_text,
                response.status
            )
            
            # 记录详细的 WAF 拦截日志
            self.logger.warning(
                f"WAF 拦截 | 流ID: {context.stream_id} | "
                f"类型: {detection_result.waf_type.value} | "
                f"置信度: {detection_result.confidence:.2f} | "
                f"URL: {context.target_url} | "
                f"检测方法: {', '.join(detection_result.detection_methods)} | "
                f"拦截指标: {', '.join(detection_result.blocked_indicators)}"
            )
            
        except Exception as e:
            self.logger.error(f"获取 WAF 检测结果时发生错误: {e}")
            detection_result = None
        
        # 构建错误响应
        error_status = 502  # Bad Gateway
        error_reason = "WAF Blocked"
        error_body = self._generate_waf_error_page(context, detection_result)
        
        # 发送错误响应头
        status_line = f"HTTP/1.1 {error_status} {error_reason}\r\n"
        writer.write(status_line.encode('utf-8'))
        
        # 发送响应头
        headers = {
            'Content-Type': 'text/html; charset=utf-8',
            'Content-Length': str(len(error_body)),
            'Connection': 'close',
            'X-WAF-Blocked': 'true'
        }
        
        for key, value in headers.items():
            writer.write(f"{key}: {value}\r\n".encode('utf-8'))
        
        # 添加代理标识
        writer.write(b"Via: SilkRoad-Next/3.0 (WAF Detection Enabled)\r\n")
        
        # 结束响应头
        writer.write(b"\r\n")
        
        # 发送错误页面内容
        writer.write(error_body.encode('utf-8'))
        await writer.drain()
        
        self.logger.info(
            f"WAF 拦截响应已发送 | 流ID: {context.stream_id} | "
            f"目标URL: {context.target_url}"
        )
    
    def _generate_waf_error_page(
        self,
        context: StreamContext,
        detection_result: Optional[Any]
    ) -> str:
        """
        生成 WAF 拦截错误页面
        
        Args:
            context: 流上下文
            detection_result: WAF 检测结果（可选）
            
        Returns:
            HTML 错误页面内容
        """
        waf_type = detection_result.waf_type.value if detection_result else "unknown"
        confidence = f"{detection_result.confidence:.2f}" if detection_result else "0.00"
        
        error_page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>WAF Blocked - SilkRoad-Next</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e0e0e0;
        }}
        .container {{
            text-align: center;
            padding: 40px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 16px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
            max-width: 600px;
        }}
        .error-code {{
            font-size: 72px;
            font-weight: bold;
            color: #e74c3c;
            margin-bottom: 20px;
        }}
        .error-title {{
            font-size: 24px;
            margin-bottom: 16px;
            color: #fff;
        }}
        .error-message {{
            font-size: 16px;
            color: #b0b0b0;
            margin-bottom: 24px;
            line-height: 1.6;
        }}
        .details {{
            background: rgba(0, 0, 0, 0.2);
            padding: 16px;
            border-radius: 8px;
            text-align: left;
            font-size: 14px;
        }}
        .detail-item {{
            margin: 8px 0;
        }}
        .detail-label {{
            color: #888;
        }}
        .detail-value {{
            color: #e0e0e0;
            word-break: break-all;
        }}
        .footer {{
            margin-top: 24px;
            font-size: 12px;
            color: #666;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="error-code">502</div>
        <div class="error-title">WAF Blocked</div>
        <div class="error-message">
            The requested resource has been blocked by a Web Application Firewall (WAF).
            <br>Please try again later or contact the administrator.
        </div>
        <div class="details">
            <div class="detail-item">
                <span class="detail-label">WAF Type: </span>
                <span class="detail-value">{waf_type}</span>
            </div>
            <div class="detail-item">
                <span class="detail-label">Confidence: </span>
                <span class="detail-value">{confidence}</span>
            </div>
            <div class="detail-item">
                <span class="detail-label">Stream ID: </span>
                <span class="detail-value">{context.stream_id}</span>
            </div>
            <div class="detail-item">
                <span class="detail-label">Target URL: </span>
                <span class="detail-value">{context.target_url}</span>
            </div>
        </div>
        <div class="footer">
            SilkRoad-Next Proxy v3.0 | WAF Detection Enabled
        </div>
    </div>
</body>
</html>"""
        
        return error_page
