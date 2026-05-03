"""
核心代理转发引擎

实现反向代理的核心逻辑，包括：
- 接收客户端请求
- 转发请求到目标服务器
- 处理响应并返回给客户端
- 协调URL修正模块

Author: SilkRoad-Next Team
Version: 1.0.0
"""

import asyncio
import json
from typing import Optional, Dict, Any, Tuple, TYPE_CHECKING
from urllib.parse import urlsplit, urljoin
import aiohttp
from loguru import logger as loguru_logger

from modules.url.handle import URLHandler
from modules.url.cookie import CookieHandler
from modules.ua import UAHandler
from modules.pageserver import PageServer

if TYPE_CHECKING:
    from modules.command import CommandHandler
    from modules.scripts import ScriptInjector
    from modules.connectionpool import ConnectionPool
    from modules.threadpool import ThreadPoolManager
    from modules.sessions import SessionManager
    from modules.cachemanager import CacheManager
    from modules.blacklist import BlacklistManager
    from modules.flow.router import FlowRouter
    from modules.flow.normal import NormalHandler
    from modules.flow.websocket import WebSocketHandler


class ProxyServer:
    """
    代理服务器核心类

    负责处理客户端请求、转发到目标服务器、处理响应并返回给客户端。
    支持HTTP/HTTPS协议、重定向处理、大文件流式传输、URL修正等功能。

    Attributes:
        host (str): 监听地址
        port (int): 监听端口
        config: 配置管理器对象
        logger: 日志记录器对象
        server: asyncio.Server 对象
        session: aiohttp.ClientSession 对象
        url_handler: URL处理器对象
        ua_handler: UA处理器对象
        command_handler: 命令处理器对象
        active_connections (int): 当前活动连接数
        is_running (bool): 服务器运行状态
    """

    def __init__(self, host: str, port: int, config, logger):
        """
        初始化代理服务器

        Args:
            host: 监听地址，如 '0.0.0.0'
            port: 监听端口，如 8080
            config: 配置管理器对象
            logger: 日志记录器对象
        """
        self.host = host
        self.port = port
        self.config = config
        self.logger = logger or loguru_logger

        self.server = None
        self.session = None

        self.url_handler = URLHandler(config, logger)
        self.ua_handler = UAHandler()
        self.cookie_handler = CookieHandler()
        self.page_server = PageServer(config, logger)
        self.command_handler: Optional['CommandHandler'] = None

        self.active_connections = 0
        self.is_running = False

        # V2 新增组件属性
        self.connection_pool: Optional['ConnectionPool'] = None
        self.thread_pool: Optional['ThreadPoolManager'] = None
        self.session_manager: Optional['SessionManager'] = None
        self.cache_manager: Optional['CacheManager'] = None
        self.blacklist_manager: Optional['BlacklistManager'] = None
        self.script_injector: Optional['ScriptInjector'] = None

        # V3 新增流处理器属性
        self.flow_router: Optional['FlowRouter'] = None
        self.normal_handler: Optional['NormalHandler'] = None

        # V4 新增组件属性
        self.websocket_handler: Optional['WebSocketHandler'] = None

        # 配置参数
        self.timeout = config.get('server.proxy.connectionTimeout', 30)
        self.request_timeout = config.get('server.proxy.requestTimeout', 60)
        self.max_redirects = config.get('server.proxy.maxRedirects', 10)
        self.stream_threshold = config.get('urlRewrite.streamThreshold', 10485760)  # 10MB

    async def start(self) -> None:
        """
        启动代理服务器

        创建 aiohttp.ClientSession 和 asyncio.Server，开始监听连接。
        """
        try:
            # 创建 HTTP 客户端会话
            timeout = aiohttp.ClientTimeout(
                total=self.request_timeout,
                connect=self.timeout
            )
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                connector=aiohttp.TCPConnector(
                    limit=100,  # 连接池大小
                    ttl_dns_cache=300,  # DNS缓存时间
                    enable_cleanup_closed=True
                )
            )

            # 启动 TCP 服务器
            self.server = await asyncio.start_server(
                self._handle_connection,
                self.host,
                self.port,
                backlog=self.config.get('server.proxy.backlog', 2048)
            )

            self.is_running = True

            # 获取实际监听地址
            addr = self.server.sockets[0].getsockname()
            self.logger.info(f"代理服务器启动成功: {addr[0]}:{addr[1]}")
            self.logger.info(f"最大并发连接数: {self.config.get('server.proxy.maxConnections', 2000)}")

            # 开始服务
            async with self.server:
                await self.server.serve_forever()

        except OSError as e:
            if e.errno == 10048:  # Windows 端口占用
                self.logger.error(f"端口 {self.port} 已被占用")
            elif e.errno == 98:  # Linux 端口占用
                self.logger.error(f"端口 {self.port} 已被占用")
            else:
                self.logger.error(f"启动代理服务器失败: {e}")
            if self.session:
                await self.session.close()
            raise
        except Exception as e:
            self.logger.error(f"启动代理服务器失败: {e}")
            if self.session:
                await self.session.close()
            raise

    async def stop(self) -> None:
        """
        停止代理服务器

        关闭服务器和客户端会话，等待所有连接处理完成。
        """
        self.is_running = False
        self.logger.info("正在停止代理服务器...")

        # 关闭服务器
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.logger.info("TCP 服务器已关闭")

        # 关闭客户端会话
        if self.session:
            await self.session.close()
            self.logger.info("HTTP 客户端会话已关闭")

        self.logger.info("代理服务器已停止")

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        """
        处理客户端连接

        接收客户端连接，处理请求，确保资源正确释放。

        Args:
            reader: 流读取器
            writer: 流写入器
        """
        self.active_connections += 1
        client_addr = writer.get_extra_info('peername')

        try:
            self.logger.debug(f"新连接来自: {client_addr}")

            # 处理请求
            await self._process_request(reader, writer)

        except asyncio.TimeoutError:
            self.logger.warning(f"客户端超时: {client_addr}")
            await self._send_error(writer, 408, "Request Timeout")
        except Exception as e:
            self.logger.error(f"处理连接错误 [{client_addr}]: {e}")
            try:
                await self._send_error(writer, 500, "Internal Server Error")
            except Exception:
                pass
        finally:
            # 确保连接关闭
            self.active_connections -= 1
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            self.logger.debug(f"连接关闭: {client_addr}")

    async def _process_request(self, reader: asyncio.StreamReader,
                                writer: asyncio.StreamWriter) -> None:
        """
        处理 HTTP 请求

        完整的请求处理流程：
        1. 解析请求行
        2. 解析请求头
        3. 解析目标 URL
        4. 读取请求体（如果有）
        5. 构建转发请求
        6. 发送请求到目标服务器
        7. 处理响应并返回

        Args:
            reader: 流读取器
            writer: 流写入器
        """
        # 1. 解析请求行
        request_line = await asyncio.wait_for(
            reader.readline(),
            timeout=self.timeout
        )

        if not request_line or request_line == b'\r\n':
            # 空请求或心跳包
            return

        try:
            method, path, version = self._parse_request_line(request_line)
        except ValueError as e:
            self.logger.warning(f"解析请求行失败: {e}")
            await self._send_error(writer, 400, "Bad Request")
            return

        self.logger.debug(f"请求: {method} {path}")

        if path.startswith('/command'):
            if self.command_handler and self.config.get('server.command.enabled', True):
                await self._handle_command(writer, path, method)
                return
            else:
                await self._send_error(writer, 404, "Command Interface Disabled")
                return

        try:
            headers = await self._parse_headers(reader)
        except Exception as e:
            self.logger.warning(f"解析请求头失败: {e}")
            await self._send_error(writer, 400, "Bad Request")
            return

        # 检查是否为静态页面请求
        static_result = await self.page_server.handle_request(path, headers)
        if static_result:
            # 处理不同类型的返回值
            result_type = static_result[0]
            
            if result_type == 'STREAM':
                # 大文件流式传输
                _, file_path, mime_type, file_size = static_result
                await self.page_server.handle_large_file(file_path, writer)
                return
            
            elif result_type == 'NOT_MODIFIED':
                # 文件未修改，返回 304
                await self._send_304_response(writer)
                return
            
            elif result_type == 'RANGE':
                # 范围请求
                _, file_path, mime_type, start, end, total_size = static_result
                await self.page_server.handle_range_request(
                    file_path, writer, start, end, total_size, mime_type
                )
                return
            
            else:
                # 普通文件
                content, mime_type = static_result
                await self._send_static_response(writer, content, mime_type)
                return

        # 3. 解析目标 URL
        target_url = self._parse_target_url(path, headers)
        if not target_url:
            self.logger.warning(f"无效的目标 URL: {path}")
            await self._send_error(writer, 400, "Invalid URL")
            return

        # 获取客户端 IP（用于 V2 功能）
        client_addr = writer.get_extra_info('peername')
        client_ip = client_addr[0] if client_addr else 'unknown'

        # ========== V2: 黑名单检查 ==========
        if self.blacklist_manager:
            parsed = urlsplit(target_url)
            domain = parsed.netloc

            is_blocked, reason = await self.blacklist_manager.is_blocked(
                client_ip, target_url, domain
            )

            if is_blocked:
                self.logger.warning(f"黑名单拦截: {client_ip} -> {target_url} | {reason}")
                await self._send_error(writer, 403, f"Forbidden: {reason}")
                return

        # ========== V2: 会话管理 ==========
        session_id = None
        if self.session_manager:
            from datetime import datetime
            session = await self.session_manager.get_session_by_ip(client_ip)

            if session is None:
                # 创建新会话
                session_id = await self.session_manager.create_session(
                    client_ip=client_ip,
                    user_agent=headers.get('User-Agent', ''),
                    initial_data={'first_visit': datetime.now().isoformat()}
                )
                self.logger.debug(f"创建新会话: {session_id} for {client_ip}")
            else:
                # 更新会话
                session_id = session['session_id']
                await self.session_manager.update_session(
                    session['session_id'],
                    {'last_visit': datetime.now().isoformat()}
                )

        # ========== V2: 缓存检查 ==========
        if self.cache_manager and method == 'GET':
            cached_data = await self.cache_manager.get(target_url, method, headers)

            if cached_data is not None:
                self.logger.debug(f"缓存命中: {target_url}")
                if self.normal_handler:
                    await self.normal_handler._send_cached_response(writer, cached_data, target_url)
                return

        # 4. 读取请求体（如果有）
        body = None
        if method in ['POST', 'PUT', 'PATCH']:
            content_length = int(headers.get('Content-Length', 0))
            if content_length > 0:
                # 检查请求体大小限制
                max_request_size = self.config.get('security.maxRequestSize', 52428800)
                if content_length > max_request_size:
                    self.logger.warning(f"请求体过大: {content_length} bytes")
                    await self._send_error(writer, 413, "Payload Too Large")
                    return

                try:
                    body = await asyncio.wait_for(
                        reader.read(content_length),
                        timeout=self.timeout
                    )
                except asyncio.TimeoutError:
                    self.logger.warning("读取请求体超时")
                    await self._send_error(writer, 408, "Request Timeout")
                    return

        # 5. 构建转发请求头
        forward_headers = self._build_forward_headers(headers, target_url)

        if self.flow_router:
            await self.flow_router.route(
                writer, method, target_url, forward_headers, body,
                session_id=session_id, reader=reader
            )
        else:
            await self._send_error(writer, 502, "Bad Gateway: No flow router")

    def _parse_request_line(self, request_line: bytes) -> Tuple[str, str, str]:
        """
        解析 HTTP 请求行

        Args:
            request_line: 请求行字节

        Returns:
            (method, path, version) 元组

        Raises:
            ValueError: 请求行格式错误
        """
        try:
            parts = request_line.decode('utf-8').strip().split(' ')
            if len(parts) != 3:
                raise ValueError(f"请求行格式错误: {parts}")

            method, path, version = parts

            # 验证 HTTP 方法
            allowed_methods = self.config.get('security.allowedMethods',
                                               ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'])
            if method.upper() not in allowed_methods:
                raise ValueError(f"不支持的 HTTP 方法: {method}")

            return method.upper(), path, version

        except UnicodeDecodeError as e:
            raise ValueError(f"请求行编码错误: {e}")

    async def _parse_headers(self, reader: asyncio.StreamReader) -> Dict[str, str]:
        """
        解析 HTTP 请求头

        Args:
            reader: 流读取器

        Returns:
            请求头字典（键名保持原始大小写）
        """
        headers = {}

        while True:
            line = await reader.readline()

            # 空行表示请求头结束
            if line == b'\r\n' or line == b'\n' or not line:
                break

            try:
                # 解析请求头
                line_str = line.decode('utf-8').strip()
                if ':' in line_str:
                    key, value = line_str.split(':', 1)
                    headers[key.strip()] = value.strip()
            except UnicodeDecodeError:
                self.logger.warning(f"请求头编码错误: {line}")
                continue

        return headers

    def _parse_target_url(self, path: str, headers: Dict[str, str]) -> Optional[str]:
        """
        解析目标 URL

        支持三种格式：
        1. 绝对路径（标准代理格式）：http://example.com/path
        2. 相对路径带域名（反向代理格式）：/example.com/path
        3. 相对路径无域名：/path（需要从 Referer 头提取域名）

        Args:
            path: 请求路径
            headers: 请求头字典

        Returns:
            完整的目标 URL，如果解析失败则返回 None
        """
        if path.startswith('http://') or path.startswith('https://'):
            return path

        path = path.lstrip('/')

        if not path:
            return None

        parts = path.split('/', 1)
        first_segment = parts[0]
        target_path = '/' + parts[1] if len(parts) > 1 else '/'

        if self._is_valid_host(first_segment):
            target_host = first_segment
        else:
            referer = headers.get('Referer', '')
            referer_domain = self._extract_domain_from_referer(referer)

            if referer_domain:
                target_host = referer_domain
                target_path = '/' + path
            else:
                return None

        if not target_host.startswith('http://') and not target_host.startswith('https://'):
            if ':80' in target_host:
                target_host = 'http://' + target_host
            else:
                target_host = 'https://' + target_host

        return f"{target_host}{target_path}"

    def _is_valid_host(self, segment: str) -> bool:
        """
        判断字符串是否是有效的主机名

        有效主机名：
        - 包含至少一个点，且不以点开头（如 www.apple.com）
        - IPv6 地址（以 [ 开头）
        - 包含端口号（如 example.com:8080）

        Args:
            segment: 路径的第一段

        Returns:
            是否是有效的主机名
        """
        if not segment:
            return False

        if segment.startswith('['):
            return True

        if segment.startswith('.'):
            return False

        if ':' in segment:
            host_part = segment.rsplit(':', 1)[0]
            return '.' in host_part

        if '.' not in segment:
            return False

        file_extensions = {
            'js', 'css', 'html', 'htm', 'xml', 'json', 'txt', 'md',
            'png', 'jpg', 'jpeg', 'gif', 'svg', 'ico', 'webp', 'bmp',
            'mp4', 'mp3', 'avi', 'mov', 'wmv', 'flv', 'wav', 'ogg',
            'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
            'zip', 'rar', 'tar', 'gz', 'bz2', '7z',
            'woff', 'woff2', 'ttf', 'eot', 'otf',
            'php', 'asp', 'aspx', 'jsp', 'cgi', 'pl', 'py', 'rb',
            'map', 'manifest', 'appcache', 'webmanifest'
        }

        parts = segment.split('.')
        if len(parts) >= 2:
            last_part = parts[-1].lower()
            if last_part in file_extensions:
                return False

        tlds = {
            'com', 'org', 'net', 'edu', 'gov', 'mil', 'io', 'co', 'ai', 'dev',
            'app', 'tech', 'info', 'biz', 'me', 'tv', 'cc', 'cn', 'jp', 'uk',
            'de', 'fr', 'ru', 'br', 'in', 'au', 'ca', 'nl', 'es', 'it', 'ch',
            'se', 'no', 'dk', 'pl', 'be', 'at', 'eu', 'us', 'mx', 'tw', 'hk',
            'sg', 'kr', 'my', 'id', 'th', 'vn', 'ph', 'nz', 'za', 'ar', 'cl',
            'pe', 've', 'ec', 'pt', 'gr', 'tr', 'ro', 'hu', 'cz', 'sk', 'ua',
            'by', 'kz', 'ir', 'sa', 'ae', 'eg', 'ng', 'ke'
        }

        if len(parts) >= 2:
            potential_tld = parts[-1].lower()
            if potential_tld in tlds:
                return True
            if potential_tld.isdigit():
                return True
            if len(potential_tld) == 2:
                return True

        return False

    def _extract_domain_from_referer(self, referer: str) -> Optional[str]:
        """
        从 Referer 头中提取域名

        Referer 格式: http://localhost:8080/www.apple.com/path
        提取: www.apple.com

        Args:
            referer: Referer 头的值

        Returns:
            域名字符串，如果提取失败则返回 None
        """
        if not referer:
            return None

        try:
            parsed = urlsplit(referer)
            referer_path = parsed.path.lstrip('/')

            if not referer_path:
                return None

            parts = referer_path.split('/', 1)
            first_segment = parts[0]

            if '.' in first_segment or first_segment.startswith('['):
                return first_segment

            return None

        except Exception:
            return None

    def _build_forward_headers(self, original_headers: Dict[str, str],
                                target_url: str) -> Dict[str, str]:
        """
        构建转发请求头

        过滤不需要转发的请求头，添加必要的请求头。

        Args:
            original_headers: 原始请求头
            target_url: 目标 URL

        Returns:
            转发请求头字典
        """
        forward_headers = {}

        skip_headers = {
            'Host', 'Connection', 'Keep-Alive', 'Proxy-Connection',
            'Proxy-Authorization', 'TE', 'Transfer-Encoding', 'Upgrade'
        }

        target_domain = self.cookie_handler.extract_domain_from_url(target_url)

        for key, value in original_headers.items():
            if key in skip_headers:
                continue
            
            if key.lower() == 'cookie' and target_domain:
                filtered_cookie = self.cookie_handler.filter_request_cookies(
                    value, target_domain
                )
                if filtered_cookie:
                    forward_headers[key] = filtered_cookie
                continue
            
            forward_headers[key] = value

        parsed = urlsplit(target_url)

        forward_headers['Host'] = parsed.netloc

        forward_headers['Connection'] = 'keep-alive'

        forward_headers['Accept-Encoding'] = 'gzip, deflate'

        if 'User-Agent' not in forward_headers:
            forward_headers['User-Agent'] = self.ua_handler.get_random_ua()

        # 重写 Referer 头以匹配目标域名（防盗链绕过）
        if 'Referer' in forward_headers:
            forward_headers['Referer'] = self._rewrite_referer(
                forward_headers['Referer'], target_url
            )

        return forward_headers

    def _rewrite_referer(self, referer: str, target_url: str) -> str:
        """
        重写 Referer 头以匹配目标域名

        将代理格式的 Referer (如 http://127.0.0.1:8080/www.baidu.com/path)
        转换为真实目标的 Referer (如 https://www.baidu.com/path)

        Args:
            referer: 原始 Referer 头
            target_url: 当前请求的目标 URL

        Returns:
            重写后的 Referer
        """
        try:
            parsed_target = urlsplit(target_url)
            target_scheme = parsed_target.scheme
            target_netloc = parsed_target.netloc

            parsed_referer = urlsplit(referer)
            referer_path = parsed_referer.path

            if not referer_path or referer_path == '/':
                return f"{target_scheme}://{target_netloc}/"

            referer_path = referer_path.lstrip('/')

            parts = referer_path.split('/', 1)
            first_segment = parts[0]

            if self._is_valid_host(first_segment):
                referer_host = first_segment
                referer_remaining = '/' + parts[1] if len(parts) > 1 else '/'

                if not referer_host.startswith('http://') and not referer_host.startswith('https://'):
                    if ':80' in referer_host:
                        referer_host = 'http://' + referer_host
                    else:
                        referer_host = 'https://' + referer_host

                return f"{referer_host}{referer_remaining}"
            else:
                return f"{target_scheme}://{target_netloc}{referer_path}"

        except Exception:
            return referer

    def _resolve_redirect_url(self, base_url: str, location: str) -> str:
        """
        解析重定向 URL

        处理相对路径和绝对路径的重定向 URL。

        Args:
            base_url: 基础 URL
            location: Location 头的值

        Returns:
            完整的重定向 URL
        """
        # 已经是绝对 URL
        if location.startswith('http://') or location.startswith('https://'):
            return location

        # 协议相对 URL
        if location.startswith('//'):
            parsed = urlsplit(base_url)
            return f"{parsed.scheme}:{location}"

        # 相对路径 URL
        return urljoin(base_url, location)

    async def _handle_command(self, writer: asyncio.StreamWriter,
                               path: str, method: str) -> None:
        """
        处理命令请求

        Args:
            writer: 流写入器
            path: 请求路径
            method: HTTP 方法
        """
        assert self.command_handler is not None
        try:
            status_code, response_data = await self.command_handler.handle_request(path, method)

            content = json.dumps(response_data, ensure_ascii=False, indent=2).encode('utf-8')

            status_messages = {
                200: 'OK',
                403: 'Forbidden',
                404: 'Not Found',
                500: 'Internal Server Error'
            }
            status_msg = status_messages.get(status_code, 'Unknown')

            response = f"HTTP/1.1 {status_code} {status_msg}\r\n"
            response += "Content-Type: application/json; charset=utf-8\r\n"
            response += f"Content-Length: {len(content)}\r\n"
            response += "Connection: close\r\n"
            response += "Access-Control-Allow-Origin: *\r\n"
            response += "Via: SilkRoad-Next/1.0\r\n"
            response += "\r\n"

            writer.write(response.encode('utf-8'))
            writer.write(content)
            await writer.drain()

            self.logger.debug(f"命令响应已发送: {path} -> {status_code}")

        except Exception as e:
            self.logger.error(f"处理命令请求失败: {e}")
            await self._send_error(writer, 500, "Internal Server Error")

    async def _send_static_response(self, writer: asyncio.StreamWriter,
                                     content: bytes, mime_type: str) -> None:
        """
        发送静态文件响应

        Args:
            writer: 流写入器
            content: 文件内容
            mime_type: MIME类型
        """
        try:
            # 构建响应
            response = f"HTTP/1.1 200 OK\r\n"
            response += f"Content-Type: {mime_type}\r\n"
            response += f"Content-Length: {len(content)}\r\n"
            response += "Connection: keep-alive\r\n"
            response += "Cache-Control: public, max-age=3600\r\n"
            response += "Accept-Ranges: bytes\r\n"
            response += "Via: SilkRoad-Next/1.0\r\n"
            response += "\r\n"

            # 发送响应头
            writer.write(response.encode('utf-8'))
            # 发送响应体
            writer.write(content)
            await writer.drain()

            self.logger.debug(f"静态文件响应已发送: {mime_type}, {len(content)} bytes")

        except Exception as e:
            self.logger.error(f"发送静态文件响应失败: {e}")
            raise

    async def _send_304_response(self, writer: asyncio.StreamWriter) -> None:
        """
        发送 304 Not Modified 响应

        当文件未修改时，返回 304 状态码，客户端可以使用缓存。

        Args:
            writer: 流写入器
        """
        try:
            # 构建 304 响应
            response = "HTTP/1.1 304 Not Modified\r\n"
            response += "Connection: keep-alive\r\n"
            response += "Via: SilkRoad-Next/1.0\r\n"
            response += "\r\n"

            # 发送响应
            writer.write(response.encode('utf-8'))
            await writer.drain()

            self.logger.debug("304 Not Modified 响应已发送")

        except Exception as e:
            self.logger.error(f"发送 304 响应失败: {e}")
            raise

    async def _send_error(self, writer: asyncio.StreamWriter,
                          status_code: int, message: str) -> None:
        """
        发送错误响应

        构建错误页面并发送给客户端。

        Args:
            writer: 流写入器
            status_code: HTTP 状态码
            message: 错误消息
        """
        try:
            # 构建错误页面
            error_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Error {status_code}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            text-align: center;
            padding: 50px;
            background-color: #f5f5f5;
        }}
        .error-container {{
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            max-width: 600px;
            margin: 0 auto;
        }}
        h1 {{
            color: #e74c3c;
            margin-bottom: 20px;
        }}
        p {{
            color: #666;
            margin-bottom: 30px;
        }}
        .powered-by {{
            color: #999;
            font-size: 12px;
            margin-top: 30px;
        }}
    </style>
</head>
<body>
    <div class="error-container">
        <h1>Error {status_code}</h1>
        <p>{message}</p>
        <div class="powered-by">
            Powered by SilkRoad-Next/1.0
        </div>
    </div>
</body>
</html>"""

            # 编码
            content = error_html.encode('utf-8')

            # 构建响应
            response = f"HTTP/1.1 {status_code} {message}\r\n"
            response += "Content-Type: text/html; charset=utf-8\r\n"
            response += f"Content-Length: {len(content)}\r\n"
            response += "Connection: close\r\n"
            response += "Via: SilkRoad-Next/1.0\r\n"
            response += "\r\n"

            # 发送响应
            writer.write(response.encode('utf-8'))
            writer.write(content)
            await writer.drain()

        except Exception as e:
            self.logger.error(f"发送错误响应失败: {e}")

    async def get_stats(self) -> Dict[str, Any]:
        """
        获取服务器统计信息

        Returns:
            包含服务器状态信息的字典
        """
        stats = {
            'host': self.host,
            'port': self.port,
            'is_running': self.is_running,
            'active_connections': self.active_connections,
            'max_connections': self.config.get('server.proxy.maxConnections', 2000),
            'timeout': self.timeout,
            'request_timeout': self.request_timeout,
            'max_redirects': self.max_redirects,
            'v2_components': {
                'connection_pool': self.connection_pool is not None,
                'thread_pool': self.thread_pool is not None,
                'session_manager': self.session_manager is not None,
                'cache_manager': self.cache_manager is not None,
                'blacklist_manager': self.blacklist_manager is not None,
                'script_injector': self.script_injector is not None
            },
            'flow_components': {
                'flow_router': self.flow_router is not None,
                'normal_handler': self.normal_handler is not None,
            }
        }

        if self.connection_pool:
            try:
                stats['connection_pool'] = await self.connection_pool.get_stats()
            except Exception as e:
                self.logger.warning(f"获取连接池统计信息失败: {e}")

        if self.thread_pool:
            try:
                stats['thread_pool'] = self.thread_pool.get_stats()
            except Exception as e:
                self.logger.warning(f"获取线程池统计信息失败: {e}")

        if self.session_manager:
            try:
                stats['session'] = self.session_manager.get_stats()
            except Exception as e:
                self.logger.warning(f"获取会话统计信息失败: {e}")

        if self.cache_manager:
            try:
                stats['cache'] = self.cache_manager.get_stats()
            except Exception as e:
                self.logger.warning(f"获取缓存统计信息失败: {e}")

        if self.blacklist_manager:
            try:
                stats['blacklist'] = self.blacklist_manager.get_stats()
            except Exception as e:
                self.logger.warning(f"获取黑名单统计信息失败: {e}")

        if self.script_injector:
            try:
                stats['scripts'] = self.script_injector.get_stats()
            except Exception as e:
                self.logger.warning(f"获取脚本注入统计信息失败: {e}")

        if self.flow_router:
            try:
                stats['flow'] = self.flow_router.get_stats()
            except Exception as e:
                self.logger.warning(f"获取流量路由统计信息失败: {e}")

        return stats

    def reset_stream_stats(self) -> Dict[str, bool]:
        """
        重置所有流处理器的统计信息
        
        Returns:
            包含各处理器重置状态的字典
        """
        if self.flow_router:
            return self.flow_router.reset_stream_stats()
        return {'stream': False, 'media': False, 'sse': False, 'others': False}

    def set_stream_rate_limit(
        self, 
        enabled: bool, 
        max_rate: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        动态设置流处理器的流量整形参数
        
        Args:
            enabled: 是否启用流量整形
            max_rate: 最大传输速率（字节/秒），如果为 None 则保持当前值
            
        Returns:
            包含设置结果和当前配置的字典
        """
        if self.flow_router:
            return self.flow_router.set_stream_rate_limit(enabled, max_rate)
        result = {'success': False, 'enabled': enabled, 'max_rate': max_rate, 'previous_config': {}, 'current_config': {}}
        return result

    def get_stream_rate_limit_status(self) -> Dict[str, Any]:
        """
        获取当前流量整形状态
        
        Returns:
            包含流量整形配置和统计信息的字典
        """
        if self.flow_router:
            return self.flow_router.get_stream_rate_limit_status()
        return {'enabled': False, 'max_rate': 0, 'stats': {}}
