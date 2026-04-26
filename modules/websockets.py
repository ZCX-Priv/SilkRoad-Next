"""
WebSocket 协议支持模块

功能：
1. WebSocket 握手代理
2. 消息帧转发
3. 连接状态维护
4. 扩展协议支持（压缩等）
5. 心跳检测
6. 错误处理

Author: SilkRoad-Next Team
Version: 4.0.0
"""

import asyncio
import aiohttp
import hashlib
import base64
import struct
from typing import Optional, Dict, Any, List
from enum import Enum, IntEnum
from dataclasses import dataclass, field
import time
import logging
import uuid


class OpCode(IntEnum):
    """WebSocket 操作码"""
    CONTINUATION = 0x0
    TEXT = 0x1
    BINARY = 0x2
    CLOSE = 0x8
    PING = 0x9
    PONG = 0xA


class ConnectionState(Enum):
    """WebSocket 连接状态"""
    CONNECTING = "connecting"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass
class WebSocketFrame:
    """WebSocket 消息帧"""
    fin: bool
    opcode: OpCode
    masked: bool
    payload: bytes
    rsv1: bool = False
    rsv2: bool = False
    rsv3: bool = False


@dataclass
class WebSocketContext:
    """WebSocket 连接上下文"""
    connection_id: str
    target_url: str
    state: ConnectionState
    client_writer: asyncio.StreamWriter
    target_ws: Optional[aiohttp.ClientWebSocketResponse] = None
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    messages_sent: int = 0
    messages_received: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class WebSocketHandler:
    """
    WebSocket 协议处理器
    
    功能：
    1. WebSocket 握手代理
    2. 消息帧转发
    3. 连接状态管理
    4. 心跳检测
    5. 扩展协议支持
    """
    
    WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    
    def __init__(self, config, logger: Optional[logging.Logger] = None):
        """
        初始化 WebSocket 处理器
        
        Args:
            config: 配置管理器
            logger: 日志记录器
        """
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        
        self.max_connections = config.get('websocket.maxConnections', 500)
        self.max_message_size = config.get('websocket.maxMessageSize', 1048576)
        self.ping_interval = config.get('websocket.pingInterval', 30)
        self.pong_timeout = config.get('websocket.pongTimeout', 10)
        self.compression_enabled = config.get('websocket.compression.enabled', True)
        
        self._connections: Dict[str, WebSocketContext] = {}
        self._lock = asyncio.Lock()
        
        self.stats = {
            'total_connections': 0,
            'active_connections': 0,
            'messages_sent': 0,
            'messages_received': 0,
            'bytes_sent': 0,
            'bytes_received': 0,
            'errors': 0
        }
        
        self.logger.info("WebSocketHandler 初始化完成")
    
    async def handle_upgrade(self,
                            client_writer: asyncio.StreamWriter,
                            headers: Dict[str, str],
                            target_url: str) -> None:
        """
        处理 WebSocket 升级请求
        
        Args:
            client_writer: 客户端写入器
            headers: 请求头
            target_url: 目标 URL
        """
        async with self._lock:
            if len(self._connections) >= self.max_connections:
                self.logger.warning("WebSocket 连接数已达上限")
                await self._send_error(client_writer, 503, "Service Unavailable")
                return
        
        connection_id = self._generate_connection_id()
        
        try:
            if not self._validate_handshake(headers):
                await self._send_error(client_writer, 400, "Bad Request")
                return
            
            target_ws = await self._connect_to_target(target_url, headers)
            
            if target_ws is None:
                await self._send_error(client_writer, 502, "Bad Gateway")
                return
            
            context = WebSocketContext(
                connection_id=connection_id,
                target_url=target_url,
                state=ConnectionState.CONNECTING,
                client_writer=client_writer,
                target_ws=target_ws
            )
            
            await self._send_handshake_response(client_writer, headers)
            
            context.state = ConnectionState.OPEN
            
            async with self._lock:
                self._connections[connection_id] = context
                self.stats['total_connections'] += 1
                self.stats['active_connections'] += 1
            
            self.logger.info(f"WebSocket 连接建立: {connection_id} -> {target_url}")
            
            await self._start_message_forwarding(context)
            
        except Exception as e:
            self.logger.error(f"WebSocket 升级失败: {e}")
            self.stats['errors'] += 1
            await self._send_error(client_writer, 500, "Internal Server Error")
    
    def _validate_handshake(self, headers: Dict[str, str]) -> bool:
        """
        验证 WebSocket 握手请求
        
        Args:
            headers: 请求头
            
        Returns:
            握手是否有效
        """
        required_headers = ['Upgrade', 'Connection', 'Sec-WebSocket-Key', 'Sec-WebSocket-Version']
        
        for header in required_headers:
            if header not in headers:
                self.logger.warning(f"缺少必需的 WebSocket 头: {header}")
                return False
        
        if headers['Upgrade'].lower() != 'websocket':
            self.logger.warning("无效的 Upgrade 头")
            return False
        
        if 'upgrade' not in headers['Connection'].lower():
            self.logger.warning("无效的 Connection 头")
            return False
        
        if headers['Sec-WebSocket-Version'] != '13':
            self.logger.warning("不支持的 WebSocket 版本")
            return False
        
        return True
    
    async def _connect_to_target(self,
                                 target_url: str,
                                 headers: Dict[str, str]) -> Optional[aiohttp.ClientWebSocketResponse]:
        """
        与目标服务器建立 WebSocket 连接
        
        Args:
            target_url: 目标 URL
            headers: 请求头
            
        Returns:
            WebSocket 连接对象
        """
        try:
            ws_url = self._convert_to_ws_url(target_url)
            
            ws_headers = self._prepare_ws_headers(headers)
            
            session = aiohttp.ClientSession()
            
            ws = await session.ws_connect(
                ws_url,
                headers=ws_headers,
                max_msg_size=self.max_message_size,
                compress=self.compression_enabled,
                heartbeat=self.ping_interval
            )
            
            return ws
            
        except Exception as e:
            self.logger.error(f"连接目标服务器失败: {e}")
            return None
    
    def _convert_to_ws_url(self, http_url: str) -> str:
        """
        将 HTTP URL 转换为 WebSocket URL
        
        Args:
            http_url: HTTP URL
            
        Returns:
            WebSocket URL
        """
        if http_url.startswith('https://'):
            return http_url.replace('https://', 'wss://', 1)
        elif http_url.startswith('http://'):
            return http_url.replace('http://', 'ws://', 1)
        else:
            return http_url
    
    def _prepare_ws_headers(self, original_headers: Dict[str, str]) -> Dict[str, str]:
        """
        准备转发到目标服务器的 WebSocket 头
        
        Args:
            original_headers: 原始请求头
            
        Returns:
            转发的请求头
        """
        ws_headers = {}
        
        forward_headers = [
            'Origin', 'Cookie', 'Authorization',
            'Sec-WebSocket-Protocol', 'Sec-WebSocket-Extensions'
        ]
        
        for header in forward_headers:
            if header in original_headers:
                ws_headers[header] = original_headers[header]
        
        return ws_headers
    
    async def _send_handshake_response(self,
                                      writer: asyncio.StreamWriter,
                                      request_headers: Dict[str, str]) -> None:
        """
        发送 WebSocket 握手响应
        
        Args:
            writer: 客户端写入器
            request_headers: 请求头
        """
        client_key = request_headers['Sec-WebSocket-Key']
        accept_key = self._compute_accept_key(client_key)
        
        response = "HTTP/1.1 101 Switching Protocols\r\n"
        response += "Upgrade: websocket\r\n"
        response += "Connection: Upgrade\r\n"
        response += f"Sec-WebSocket-Accept: {accept_key}\r\n"
        
        if self.compression_enabled:
            response += "Sec-WebSocket-Extensions: permessage-deflate\r\n"
        
        response += "Via: SilkRoad-Next/4.0\r\n"
        response += "\r\n"
        
        writer.write(response.encode('utf-8'))
        await writer.drain()
    
    def _compute_accept_key(self, client_key: str) -> str:
        """
        计算 Sec-WebSocket-Accept 值
        
        Args:
            client_key: 客户端发送的 Sec-WebSocket-Key
            
        Returns:
            Accept 值
        """
        key = client_key + self.WEBSOCKET_GUID
        
        sha1 = hashlib.sha1(key.encode('utf-8')).digest()
        
        accept = base64.b64encode(sha1).decode('utf-8')
        
        return accept
    
    async def _start_message_forwarding(self, context: WebSocketContext) -> None:
        """
        启动双向消息转发
        
        Args:
            context: WebSocket 连接上下文
        """
        try:
            client_to_target = asyncio.create_task(
                self._forward_client_messages(context)
            )
            target_to_client = asyncio.create_task(
                self._forward_target_messages(context)
            )
            
            done, pending = await asyncio.wait(
                [client_to_target, target_to_client],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            
        except Exception as e:
            self.logger.error(f"消息转发错误 [{context.connection_id}]: {e}")
            self.stats['errors'] += 1
        
        finally:
            await self._close_connection(context)
    
    async def _forward_client_messages(self, context: WebSocketContext) -> None:
        """
        转发客户端消息到目标服务器
        
        Args:
            context: WebSocket 连接上下文
        """
        try:
            reader = context.client_writer._transport.get_extra_info('reader')
            
            while context.state == ConnectionState.OPEN:
                frame = await self._read_frame(reader)
                
                if frame is None:
                    break
                
                context.last_activity = time.time()
                
                if frame.opcode == OpCode.CLOSE:
                    await self._handle_close_frame(context, frame)
                    break
                elif frame.opcode == OpCode.PING:
                    await self._handle_ping_frame(context, frame)
                    continue
                elif frame.opcode == OpCode.PONG:
                    await self._handle_pong_frame(context, frame)
                    continue
                
                if frame.opcode in [OpCode.TEXT, OpCode.BINARY, OpCode.CONTINUATION]:
                    if context.target_ws and not context.target_ws.closed:
                        if frame.opcode == OpCode.TEXT:
                            await context.target_ws.send_str(frame.payload.decode('utf-8'))
                        else:
                            await context.target_ws.send_bytes(frame.payload)
                        
                        context.messages_sent += 1
                        context.bytes_sent += len(frame.payload)
                        self.stats['messages_sent'] += 1
                        self.stats['bytes_sent'] += len(frame.payload)
        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"客户端消息转发错误: {e}")
    
    async def _forward_target_messages(self, context: WebSocketContext) -> None:
        """
        转发目标服务器消息到客户端
        
        Args:
            context: WebSocket 连接上下文
        """
        try:
            while context.state == ConnectionState.OPEN:
                if context.target_ws is None or context.target_ws.closed:
                    break
                
                msg = await context.target_ws.receive()
                
                context.last_activity = time.time()
                
                if msg.type == aiohttp.WSMsgType.TEXT:
                    frame = WebSocketFrame(
                        fin=True,
                        opcode=OpCode.TEXT,
                        masked=False,
                        payload=msg.data.encode('utf-8')
                    )
                    await self._send_frame(context.client_writer, frame)
                    
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    frame = WebSocketFrame(
                        fin=True,
                        opcode=OpCode.BINARY,
                        masked=False,
                        payload=msg.data
                    )
                    await self._send_frame(context.client_writer, frame)
                    
                elif msg.type == aiohttp.WSMsgType.PING:
                    frame = WebSocketFrame(
                        fin=True,
                        opcode=OpCode.PING,
                        masked=False,
                        payload=msg.data
                    )
                    await self._send_frame(context.client_writer, frame)
                    
                elif msg.type == aiohttp.WSMsgType.PONG:
                    frame = WebSocketFrame(
                        fin=True,
                        opcode=OpCode.PONG,
                        masked=False,
                        payload=msg.data
                    )
                    await self._send_frame(context.client_writer, frame)
                    
                elif msg.type == aiohttp.WSMsgType.CLOSE:
                    await self._handle_close_frame(context, None)
                    break
                
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    self.logger.error(f"目标服务器 WebSocket 错误: {context.target_ws.exception()}")
                    break
                
                context.messages_received += 1
                context.bytes_received += len(msg.data)
                self.stats['messages_received'] += 1
                self.stats['bytes_received'] += len(msg.data)
        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"目标服务器消息转发错误: {e}")
    
    async def _read_frame(self, reader: asyncio.StreamReader) -> Optional[WebSocketFrame]:
        """
        读取 WebSocket 帧
        
        Args:
            reader: 流读取器
            
        Returns:
            WebSocket 帧对象
        """
        try:
            header = await reader.readexactly(2)
            byte1, byte2 = struct.unpack('!BB', header)
            
            fin = (byte1 & 0x80) != 0
            rsv1 = (byte1 & 0x40) != 0
            rsv2 = (byte1 & 0x20) != 0
            rsv3 = (byte1 & 0x10) != 0
            opcode = OpCode(byte1 & 0x0F)
            
            masked = (byte2 & 0x80) != 0
            payload_len = byte2 & 0x7F
            
            if payload_len == 126:
                ext_len = await reader.readexactly(2)
                payload_len = struct.unpack('!H', ext_len)[0]
            elif payload_len == 127:
                ext_len = await reader.readexactly(8)
                payload_len = struct.unpack('!Q', ext_len)[0]
            
            if payload_len > self.max_message_size:
                self.logger.warning(f"消息大小超过限制: {payload_len} > {self.max_message_size}")
                return None
            
            mask_key = None
            if masked:
                mask_key = await reader.readexactly(4)
            
            payload = await reader.readexactly(payload_len)
            
            if masked and mask_key:
                payload = self._apply_mask(payload, mask_key)
            
            return WebSocketFrame(
                fin=fin,
                opcode=opcode,
                masked=masked,
                payload=payload,
                rsv1=rsv1,
                rsv2=rsv2,
                rsv3=rsv3
            )
            
        except asyncio.IncompleteReadError:
            return None
        except Exception as e:
            self.logger.error(f"读取 WebSocket 帧失败: {e}")
            return None
    
    async def _send_frame(self,
                         writer: asyncio.StreamWriter,
                         frame: WebSocketFrame) -> None:
        """
        发送 WebSocket 帧
        
        Args:
            writer: 流写入器
            frame: WebSocket 帧对象
        """
        try:
            byte1 = frame.opcode
            
            if frame.fin:
                byte1 |= 0x80
            if frame.rsv1:
                byte1 |= 0x40
            if frame.rsv2:
                byte1 |= 0x20
            if frame.rsv3:
                byte1 |= 0x10
            
            payload_len = len(frame.payload)
            
            if payload_len < 126:
                byte2 = payload_len
                header = struct.pack('!BB', byte1, byte2)
            elif payload_len < 65536:
                byte2 = 126
                header = struct.pack('!BBH', byte1, byte2, payload_len)
            else:
                byte2 = 127
                header = struct.pack('!BBQ', byte1, byte2, payload_len)
            
            writer.write(header + frame.payload)
            await writer.drain()
            
        except Exception as e:
            self.logger.error(f"发送 WebSocket 帧失败: {e}")
    
    def _apply_mask(self, data: bytes, mask: bytes) -> bytes:
        """
        应用掩码
        
        Args:
            data: 原始数据
            mask: 掩码
            
        Returns:
            掩码后的数据
        """
        masked = bytearray(len(data))
        for i in range(len(data)):
            masked[i] = data[i] ^ mask[i % 4]
        return bytes(masked)
    
    async def _handle_close_frame(self,
                                  context: WebSocketContext,
                                  frame: Optional[WebSocketFrame]) -> None:
        """
        处理关闭帧
        
        Args:
            context: WebSocket 连接上下文
            frame: 关闭帧
        """
        context.state = ConnectionState.CLOSING
        
        if frame:
            close_frame = WebSocketFrame(
                fin=True,
                opcode=OpCode.CLOSE,
                masked=False,
                payload=frame.payload
            )
            await self._send_frame(context.client_writer, close_frame)
        
        if context.target_ws and not context.target_ws.closed:
            await context.target_ws.close()
    
    async def _handle_ping_frame(self,
                                context: WebSocketContext,
                                frame: WebSocketFrame) -> None:
        """
        处理 Ping 帧
        
        Args:
            context: WebSocket 连接上下文
            frame: Ping 帧
        """
        pong_frame = WebSocketFrame(
            fin=True,
            opcode=OpCode.PONG,
            masked=False,
            payload=frame.payload
        )
        await self._send_frame(context.client_writer, pong_frame)
    
    async def _handle_pong_frame(self,
                                context: WebSocketContext,
                                frame: WebSocketFrame) -> None:
        """
        处理 Pong 帧
        
        Args:
            context: WebSocket 连接上下文
            frame: Pong 帧
        """
        context.last_activity = time.time()
    
    async def _close_connection(self, context: WebSocketContext) -> None:
        """
        关闭 WebSocket 连接
        
        Args:
            context: WebSocket 连接上下文
        """
        context.state = ConnectionState.CLOSED
        
        try:
            context.client_writer.close()
            await context.client_writer.wait_closed()
        except Exception:
            pass
        
        if context.target_ws and not context.target_ws.closed:
            try:
                await context.target_ws.close()
            except Exception:
                pass
        
        async with self._lock:
            if context.connection_id in self._connections:
                del self._connections[context.connection_id]
            self.stats['active_connections'] -= 1
        
        self.logger.info(
            f"WebSocket 连接关闭: {context.connection_id} | "
            f"发送={context.messages_sent}条/{context.bytes_sent}字节 | "
            f"接收={context.messages_received}条/{context.bytes_received}字节"
        )
    
    async def _send_error(self,
                         writer: asyncio.StreamWriter,
                         status_code: int,
                         message: str) -> None:
        """
        发送错误响应
        
        Args:
            writer: 客户端写入器
            status_code: 状态码
            message: 错误消息
        """
        response = f"HTTP/1.1 {status_code} {message}\r\n"
        response += "Content-Type: text/plain\r\n"
        response += f"Content-Length: {len(message)}\r\n"
        response += "\r\n"
        response += message
        
        writer.write(response.encode('utf-8'))
        await writer.drain()
    
    def _generate_connection_id(self) -> str:
        """生成唯一连接 ID"""
        return str(uuid.uuid4())[:8]
    
    async def get_active_connections(self) -> List[WebSocketContext]:
        """获取所有活跃连接"""
        async with self._lock:
            return list(self._connections.values())
    
    async def close_connection(self, connection_id: str) -> bool:
        """
        关闭指定连接
        
        Args:
            connection_id: 连接 ID
            
        Returns:
            是否成功关闭
        """
        async with self._lock:
            if connection_id in self._connections:
                context = self._connections[connection_id]
                context.state = ConnectionState.CLOSING
                return True
            return False
    
    def get_stats(self) -> dict:
        """获取 WebSocket 统计信息"""
        return {
            **self.stats,
            'active_connections_count': len(self._connections)
        }
