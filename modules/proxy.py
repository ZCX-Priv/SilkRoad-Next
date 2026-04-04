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
import gzip
import json
import zlib
from typing import Optional, Dict, Any, Tuple, TYPE_CHECKING
from urllib.parse import urlparse, urljoin
import aiohttp

from modules.url.handle import URLHandler
from modules.url.cookie import CookieHandler
from modules.ua import UAHandler
from modules.pageserver import PageServer

if TYPE_CHECKING:
    from modules.command import CommandHandler


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
        self.logger = logger

        self.server = None
        self.session = None

        self.url_handler = URLHandler(config, logger)
        self.ua_handler = UAHandler()
        self.cookie_handler = CookieHandler()
        self.page_server = PageServer(config, logger)
        self.command_handler: Optional['CommandHandler'] = None

        self.active_connections = 0
        self.is_running = False

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

        # 检查是否为静态页面请求
        static_result = await self.page_server.handle_request(path)
        if static_result:
            content, mime_type = static_result
            await self._send_static_response(writer, content, mime_type)
            return

        try:
            headers = await self._parse_headers(reader)
        except Exception as e:
            self.logger.warning(f"解析请求头失败: {e}")
            await self._send_error(writer, 400, "Bad Request")
            return

        # 3. 解析目标 URL
        target_url = self._parse_target_url(path, headers)
        if not target_url:
            self.logger.warning(f"无效的目标 URL: {path}")
            await self._send_error(writer, 400, "Invalid URL")
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

        # 6. 发送请求到目标服务器（支持重定向）
        await self._forward_request(writer, method, target_url, forward_headers, body)

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
            parsed = urlparse(referer)
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

        parsed = urlparse(target_url)

        forward_headers['Host'] = parsed.netloc

        forward_headers['Connection'] = 'keep-alive'

        forward_headers['Accept-Encoding'] = 'gzip, deflate'

        if 'User-Agent' not in forward_headers:
            forward_headers['User-Agent'] = self.ua_handler.get_random_ua()

        return forward_headers

    async def _forward_request(self, writer: asyncio.StreamWriter,
                                method: str, target_url: str,
                                headers: Dict[str, str],
                                body: Optional[bytes]) -> None:
        """
        转发请求到目标服务器

        支持重定向处理，最多跟随 max_redirects 次重定向。

        Args:
            writer: 流写入器
            method: HTTP 方法
            target_url: 目标 URL
            headers: 请求头
            body: 请求体
        """
        assert self.session is not None
        current_url = target_url
        redirect_count = 0

        while redirect_count <= self.max_redirects:
            try:
                # 发送请求
                async with self.session.request(
                    method,
                    current_url,
                    headers=headers,
                    data=body,
                    allow_redirects=False,  # 手动处理重定向
                    ssl=False  # 允许自签名证书
                ) as response:
                    # 检查是否为重定向
                    if response.status in [301, 302, 303, 307, 308]:
                        redirect_count += 1

                        if redirect_count > self.max_redirects:
                            self.logger.warning(f"重定向次数过多: {redirect_count}")
                            await self._send_error(writer, 508, "Loop Detected")
                            return

                        # 获取重定向 URL
                        location = response.headers.get('Location')
                        if not location:
                            self.logger.warning("重定向响应缺少 Location 头")
                            await self._send_error(writer, 502, "Bad Gateway")
                            return

                        # 解析重定向 URL
                        current_url = self._resolve_redirect_url(current_url, location)
                        self.logger.debug(f"重定向到: {current_url}")

                        # 更新 Host 头
                        parsed = urlparse(current_url)
                        headers['Host'] = parsed.netloc

                        # 303 重定向需要改为 GET 方法
                        if response.status == 303:
                            method = 'GET'
                            body = None

                        continue

                    # 正常响应，处理并发送
                    await self._send_response(writer, response, current_url)
                    return

            except asyncio.TimeoutError:
                self.logger.error(f"请求超时: {current_url}")
                await self._send_error(writer, 504, "Gateway Timeout")
                return

            except aiohttp.ClientError as e:
                self.logger.error(f"目标服务器错误 [{current_url}]: {e}")
                await self._send_error(writer, 502, "Bad Gateway")
                return

            except Exception as e:
                self.logger.error(f"转发请求失败 [{current_url}]: {e}")
                await self._send_error(writer, 500, "Internal Server Error")
                return

        # 超过最大重定向次数
        self.logger.warning(f"重定向次数超过限制: {redirect_count}")
        await self._send_error(writer, 508, "Loop Detected")

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
            parsed = urlparse(base_url)
            return f"{parsed.scheme}:{location}"

        # 相对路径 URL
        return urljoin(base_url, location)

    async def _send_response(self, writer: asyncio.StreamWriter,
                              response: aiohttp.ClientResponse,
                              target_url: str) -> None:
        """
        发送响应给客户端

        处理响应体、解压缩、URL修正、重新压缩等。

        Args:
            writer: 流写入器
            response: 目标服务器的响应对象
            target_url: 目标 URL
        """
        try:
            content_length = int(response.headers.get('Content-Length', 0))

            if content_length > self.stream_threshold:
                await self._stream_response(writer, response)
                return

            content = await response.read()

            content = await self._decompress_content(
                content,
                response.headers.get('Content-Encoding')
            )

            content_type = response.headers.get('Content-Type', '')
            if self._should_rewrite(content_type):
                try:
                    content = await self.url_handler.rewrite(
                        content,
                        content_type,
                        target_url
                    )
                except Exception as e:
                    self.logger.error(f"URL 修正失败: {e}")

            content, encoding = await self._compress_content(content)

            headers = dict(response.headers)

            headers['Content-Length'] = str(len(content))
            if encoding and encoding != 'identity':
                headers['Content-Encoding'] = encoding
            else:
                headers.pop('Content-Encoding', None)

            headers['Via'] = 'SilkRoad-Next/1.0'

            headers.pop('Transfer-Encoding', None)
            headers.pop('Content-Security-Policy', None)
            headers.pop('Content-Security-Policy-Report-Only', None)

            target_domain = self.cookie_handler.extract_domain_from_url(target_url)

            set_cookie_values = None
            if 'Set-Cookie' in headers:
                set_cookie_values = headers.pop('Set-Cookie')
            elif 'set-cookie' in headers:
                set_cookie_values = headers.pop('set-cookie')

            status_line = f"HTTP/1.1 {response.status} {response.reason}\r\n"
            writer.write(status_line.encode('utf-8'))

            for key, value in headers.items():
                if key.lower() in ['transfer-encoding', 'set-cookie']:
                    continue
                writer.write(f"{key}: {value}\r\n".encode('utf-8'))

            if set_cookie_values and target_domain:
                if isinstance(set_cookie_values, str):
                    set_cookie_values = [set_cookie_values]
                
                for cookie_value in set_cookie_values:
                    rewritten_cookie = self.cookie_handler.rewrite_set_cookie(
                        cookie_value, target_domain
                    )
                    writer.write(f"Set-Cookie: {rewritten_cookie}\r\n".encode('utf-8'))

            writer.write(b"\r\n")

            writer.write(content)
            await writer.drain()

            self.logger.debug(f"响应已发送: {response.status} {len(content)} bytes")

        except Exception as e:
            self.logger.error(f"发送响应失败: {e}")
            raise

    async def _stream_response(self, writer: asyncio.StreamWriter,
                                response: aiohttp.ClientResponse) -> None:
        """
        流式传输大文件响应

        对于大文件（>10MB），直接流式传输，不进行 URL 修正。

        Args:
            writer: 流写入器
            response: 目标服务器的响应对象
        """
        try:
            status_line = f"HTTP/1.1 {response.status} {response.reason}\r\n"
            writer.write(status_line.encode('utf-8'))

            for key, value in response.headers.items():
                if key.lower() in ['transfer-encoding', 'content-security-policy', 'content-security-policy-report-only', 'set-cookie']:
                    continue
                writer.write(f"{key}: {value}\r\n".encode('utf-8'))

            writer.write(b"Via: SilkRoad-Next/1.0\r\n")

            writer.write(b"\r\n")

            chunk_size = 8192
            total_bytes = 0

            async for chunk in response.content.iter_chunked(chunk_size):
                writer.write(chunk)
                await writer.drain()
                total_bytes += len(chunk)

            self.logger.info(f"流式传输完成: {total_bytes} bytes")

        except Exception as e:
            self.logger.error(f"流式传输失败: {e}")
            raise

    async def _decompress_content(self, content: bytes,
                                   encoding: Optional[str]) -> bytes:
        """
        解压缩响应内容

        支持 gzip 和 deflate 压缩格式。
        注意：aiohttp 默认会自动解压，此方法作为备用检查。

        Args:
            content: 压缩的内容
            encoding: 压缩编码（gzip 或 deflate）

        Returns:
            解压缩后的内容
        """
        if not encoding:
            return content

        encoding = encoding.lower()

        if encoding not in ('gzip', 'deflate', 'x-gzip'):
            self.logger.debug(f"不支持的压缩格式: {encoding}")
            return content

        try:
            if encoding in ('gzip', 'x-gzip'):
                if len(content) < 2:
                    return content
                if content[:2] != b'\x1f\x8b':
                    self.logger.debug(f"内容非gzip格式，跳过解压")
                    return content
                return gzip.decompress(content)
            elif encoding == 'deflate':
                if len(content) < 2:
                    return content
                return zlib.decompress(content)
            else:
                return content

        except Exception as e:
            self.logger.debug(f"解压缩失败，使用原始内容: {e}")
            return content

    async def _compress_content(self, content: bytes) -> Tuple[bytes, str]:
        """
        压缩响应内容

        使用 gzip 压缩内容。

        Args:
            content: 原始内容

        Returns:
            (压缩后的内容, 压缩编码) 元组
        """
        # 检查是否启用压缩
        if not self.config.get('proxy.enableCompression', True):
            return content, 'identity'

        # 检查内容大小，小内容不压缩
        if len(content) < 1024:  # 小于 1KB 不压缩
            return content, 'identity'

        try:
            # 使用 gzip 压缩
            compression_level = self.config.get('proxy.compressionLevel', 6)
            compressed = gzip.compress(content, compresslevel=compression_level)

            # 只有压缩后更小才使用压缩
            if len(compressed) < len(content):
                return compressed, 'gzip'
            else:
                return content, 'identity'

        except Exception as e:
            self.logger.error(f"压缩失败: {e}")
            return content, 'identity'

    def _should_rewrite(self, content_type: str) -> bool:
        """
        判断是否需要进行 URL 修正

        根据内容类型判断是否需要修正 URL。

        Args:
            content_type: 内容类型

        Returns:
            是否需要修正
        """
        if not content_type:
            return False

        # 检查是否启用 URL 重写
        if not self.config.get('urlRewrite.enabled', True):
            return False

        # 需要处理的内容类型
        process_types = self.config.get('urlRewrite.processContentTypes', [
            'text/html',
            'text/css',
            'text/javascript',
            'application/javascript',
            'application/x-javascript',
            'text/xml',
            'application/xml',
            'application/json',
            'application/xhtml+xml'
        ])

        # 检查是否匹配
        content_type_lower = content_type.lower()
        for ct in process_types:
            if ct in content_type_lower:
                return True

        return False

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

    def get_stats(self) -> Dict[str, Any]:
        """
        获取服务器统计信息

        Returns:
            包含服务器状态信息的字典
        """
        return {
            'host': self.host,
            'port': self.port,
            'is_running': self.is_running,
            'active_connections': self.active_connections,
            'max_connections': self.config.get('server.proxy.maxConnections', 2000),
            'timeout': self.timeout,
            'request_timeout': self.request_timeout,
            'max_redirects': self.max_redirects
        }
