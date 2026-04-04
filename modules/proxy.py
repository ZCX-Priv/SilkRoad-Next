"""
核心代理转发引擎

实现反向代理的核心逻辑，包括：
- 接收客户端请求
- 转发请求到目标服务器
- 处理响应并返回给客户端
- 协调URL修正模块

V2 扩展功能：
- 连接池管理（ConnectionPool）
- 线程池管理（ThreadPoolManager）
- 会话管理（SessionManager）
- 缓存管理（CacheManager）
- 黑名单拦截（BlacklistManager）
- 脚本注入（ScriptInjector）

Author: SilkRoad-Next Team
Version: 2.0.0
"""

import asyncio
import gzip
import json
import zlib
import re
from typing import Optional, Dict, Any, Tuple, TYPE_CHECKING
from urllib.parse import urlparse, urljoin
import aiohttp

from modules.url.handle import URLHandler
from modules.url.cookie import CookieHandler
from modules.ua import UAHandler
from modules.pageserver import PageServer

# V2 模块导入
from modules.connectionpool import ConnectionPool, ConnectionPoolFullError
from modules.threadpool import ThreadPoolManager
from modules.sessions import SessionManager
from modules.cachemanager import CacheManager
from modules.blacklist import BlacklistManager, BlacklistError
from modules.scripts import ScriptInjector

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

        # V1 模块初始化
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

        # ========== V2 模块初始化 ==========
        # 连接池管理器
        self.connection_pool: Optional[ConnectionPool] = None
        # 线程池管理器
        self.thread_pool: Optional[ThreadPoolManager] = None
        # 会话管理器
        self.session_manager: Optional[SessionManager] = None
        # 缓存管理器
        self.cache_manager: Optional[CacheManager] = None
        # 黑名单管理器
        self.blacklist_manager: Optional[BlacklistManager] = None
        # 脚本注入器
        self.script_injector: Optional[ScriptInjector] = None

        # V2 功能启用标志
        self.v2_enabled = config.get('v2.enabled', True)

        # 初始化 V2 模块
        if self.v2_enabled:
            self._init_v2_modules()

    def _init_v2_modules(self) -> None:
        """
        初始化所有 V2 模块

        根据配置文件初始化连接池、线程池、会话管理、缓存管理、黑名单和脚本注入模块。
        """
        try:
            # 连接池管理器
            connection_pool_config = self.config.get('connectionPool', {})
            self.connection_pool = ConnectionPool(
                max_connections_per_host=connection_pool_config.get('maxConnectionsPerHost', 10),
                connection_timeout=connection_pool_config.get('connectionTimeout', 30),
                keep_alive_timeout=connection_pool_config.get('keepAliveTimeout', 60)
            )
            self.logger.info(f"连接池管理器初始化完成: {connection_pool_config}")

            # 线程池管理器
            thread_pool_config = self.config.get('threadPool', {})
            self.thread_pool = ThreadPoolManager(
                max_workers=thread_pool_config.get('maxWorkers', None)
            )
            self.logger.info(f"线程池管理器初始化完成: max_workers={thread_pool_config.get('maxWorkers', 'auto')}")

            # 会话管理器
            session_config = self.config.get('session', {})
            self.session_manager = SessionManager(
                session_timeout=session_config.get('timeout', 1800),
                cleanup_interval=session_config.get('cleanupInterval', 60),
                max_data_size=session_config.get('maxDataSize', 1024 * 1024)  # 1MB
            )
            self.logger.info(f"会话管理器初始化完成: timeout={session_config.get('timeout', 1800)}s")

            # 缓存管理器
            cache_config = self.config.get('cache', {})
            self.cache_manager = CacheManager(
                max_memory_cache_size=cache_config.get('maxMemoryCacheSize', 100 * 1024 * 1024),  # 100MB
                max_disk_cache_size=cache_config.get('maxDiskCacheSize', 1024 * 1024 * 1024),  # 1GB
                default_ttl=cache_config.get('defaultTTL', 3600),
                disk_cache_dir=cache_config.get('diskCacheDir', './cache')
            )
            self.logger.info(f"缓存管理器初始化完成: memory={cache_config.get('maxMemoryCacheSize', 100 * 1024 * 1024) // (100 * 1024 * 1024)} bytes")

            # 黑名单管理器
            blacklist_config = self.config.get('blacklist', {})
            if blacklist_config.get('enabled', True):
                self.blacklist_manager = BlacklistManager(
                    config_file=blacklist_config.get('configFile', 'databases/blacklist.json')
                )
                self.logger.info(f"黑名单管理器初始化完成: {blacklist_config.get('configFile', 'databases/blacklist.json')}")
            else:
                self.blacklist_manager = None
                self.logger.info("黑名单管理器已禁用")

            # 脚本注入器
            scripts_config = self.config.get('scripts', {})
            if scripts_config.get('enabled', True):
                self.script_injector = ScriptInjector(
                    config_file=scripts_config.get('configFile', 'databases/scripts.json')
                )
                self.logger.info(f"脚本注入器初始化完成: {scripts_config.get('configFile', 'databases/scripts.json')}")
            else:
                self.script_injector = None
                self.logger.info("脚本注入器已禁用")

            self.logger.info("V2 模块初始化完成")

        except Exception as e:
            self.logger.error(f"V2 模块初始化失败: {e}")
            raise

    async def start(self) -> None:
        """
        启动代理服务器

        创建 aiohttp.ClientSession 和 asyncio.Server，开始监听连接。
        同时启动 V2 模块的清理任务。
        """
        try:
            timeout = aiohttp.ClientTimeout(
                total=self.request_timeout,
                connect=self.timeout
            )
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                connector=aiohttp.TCPConnector(
                    limit=100,
                    ttl_dns_cache=300,
                    enable_cleanup_closed=True
                )
            )

            self.server = await asyncio.start_server(
                self._handle_connection,
                self.host,
                self.port,
                backlog=self.config.get('server.proxy.backlog', 2048)
            )

            self.is_running = True

            addr = self.server.sockets[0].getsockname()
            self.logger.info(f"代理服务器启动成功: {addr[0]}:{addr[1]}")
            self.logger.info(f"最大并发连接数: {self.config.get('server.proxy.maxConnections', 2000)}")

            if self.session_manager:
                await self.session_manager.start_cleanup_task()
                self.logger.info("会话管理器清理任务已启动")

            if self.cache_manager:
                asyncio.create_task(self._cache_cleanup_task())
                self.logger.info("缓存管理器清理任务已启动")

            if self.blacklist_manager:
                asyncio.create_task(self._blacklist_reload_task())
                self.logger.info("黑名单管理器热重载任务已启动")

            async with self.server:
                await self.server.serve_forever()

        except OSError as e:
            if e.errno == 10048:
                self.logger.error(f"端口 {self.port} 已被占用")
            elif e.errno == 98:
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

    async def _cache_cleanup_task(self) -> None:
        """
        缓存清理任务

        定期清理过期的缓存项。
        """
        while self.is_running:
            try:
                await asyncio.sleep(300)  # 每5分钟清理一次
                if self.cache_manager:
                    await self.cache_manager.cleanup_expired()
                    self.logger.debug("缓存清理任务执行完成")
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"缓存清理任务错误: {e}")

    async def _blacklist_reload_task(self) -> None:
        """
        黑名单热重载任务

        定期检查并重载黑名单配置。
        """
        while self.is_running:
            try:
                await asyncio.sleep(60)  # 每60秒检查一次
                if self.blacklist_manager:
                    if await self.blacklist_manager.check_config_modified():
                        await self.blacklist_manager.reload_config()
                        self.logger.info("黑名单配置已热重载")
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"黑名单热重载任务错误: {e}")

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

        # ========== 关闭 V2 模块 ==========
        # 匉止会话清理任务
        if self.session_manager:
            await self.session_manager.stop_cleanup_task()
            self.logger.info("会话管理器清理任务已停止")

        # 关闭连接池
        if self.connection_pool:
            await self.connection_pool.close_all()
            self.logger.info("连接池已关闭")

        # 关闭线程池
        if self.thread_pool:
            self.thread_pool.shutdown(wait=True)
            self.logger.info("线程池已关闭")

        # 清空缓存（可选）
        if self.cache_manager:
            await self.cache_manager.clear_all()
            self.logger.info("缓存管理器已清空")

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

        完整的请求处理流程（V2增强版）：
        1. 解析请求行
        2. 解析请求头
        3. 解析目标 URL
        4. V2: 黑名单检查
        5. V2: 会话管理
        6. V2: 缓存检查
        7. 读取请求体（如果有）
        8. 构建转发请求
        9. 发送请求到目标服务器
        10. V2: 脚本注入
        11. V2: 缓存结果
        12. 处理响应并返回

        Args:
            reader: 流读取器
            writer: 流写入器
        """
        client_ip = writer.get_extra_info('peername')[0] if writer.get_extra_info('peername') else 'unknown'
        
        request_line = await asyncio.wait_for(
            reader.readline(),
            timeout=self.timeout
        )

        if not request_line or request_line == b'\r\n':
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

        target_url = self._parse_target_url(path, headers)
        if not target_url:
            self.logger.warning(f"无效的目标 URL: {path}")
            await self._send_error(writer, 400, "Invalid URL")
            return

        # ========== V2: 黑名单检查 ==========
        if self.blacklist_manager:
            try:
                from urllib.parse import urlparse
                parsed_url = urlparse(target_url)
                domain = parsed_url.netloc.split(':')[0] if ':' in parsed_url.netloc else parsed_url.netloc
                is_blocked, reason = await self.blacklist_manager.is_blocked(client_ip, target_url, domain)
                if is_blocked:
                    self.logger.warning(f"黑名单拦截: {reason} - {target_url}")
                    await self._send_blocked_response(writer, reason, reason)
                    return
            except Exception as e:
                self.logger.error(f"黑名单检查错误: {e}")

        # ========== V2: 会话管理 ==========
        session_id = None
        session_data = None
        if self.session_manager:
            session_id = headers.get('X-Session-ID') or headers.get('Cookie', '').split('session=')[-1].split(';')[0] if 'session=' in headers.get('Cookie', '') else None
            if session_id:
                session_data = await self.session_manager.get_session(session_id)
            if not session_id or not session_data:
                session_id = await self.session_manager.create_session(client_ip=client_ip)
                session_data = {}

        # ========== V2: 缓存检查 ==========
        cache_key = None
        if self.cache_manager and method == 'GET':
            cache_key = target_url
            cached_response = await self.cache_manager.get(cache_key)
            if cached_response:
                self.logger.debug(f"缓存命中: {target_url}")
                await self._send_cached_response(writer, cached_response, session_id)
                return

        body = None
        if method in ['POST', 'PUT', 'PATCH']:
            content_length = int(headers.get('Content-Length', 0))
            if content_length > 0:
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

        forward_headers = self._build_forward_headers(headers, target_url)
        
        if session_id and self.session_manager:
            forward_headers['X-Session-ID'] = session_id

        await self._forward_request_v2(writer, method, target_url, forward_headers, body, 
                                        cache_key, session_id)

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
        await self._forward_request_v2(writer, method, target_url, headers, body, None, None)

    async def _forward_request_v2(self, writer: asyncio.StreamWriter,
                                   method: str, target_url: str,
                                   headers: Dict[str, str],
                                   body: Optional[bytes],
                                   cache_key: Optional[str],
                                   session_id: Optional[str]) -> None:
        """
        V2增强版请求转发

        在原有转发基础上增加：
        - 连接池管理
        - 脚本注入
        - 响应缓存

        Args:
            writer: 流写入器
            method: HTTP 方法
            target_url: 目标 URL
            headers: 请求头
            body: 请求体
            cache_key: 缓存键
            session_id: 会话ID
        """
        assert self.session is not None
        current_url = target_url
        redirect_count = 0

        while redirect_count <= self.max_redirects:
            try:
                async with self.session.request(
                    method,
                    current_url,
                    headers=headers,
                    data=body,
                    allow_redirects=False,
                    ssl=False
                ) as response:
                    if response.status in [301, 302, 303, 307, 308]:
                        redirect_count += 1

                        if redirect_count > self.max_redirects:
                            self.logger.warning(f"重定向次数过多: {redirect_count}")
                            await self._send_error(writer, 508, "Loop Detected")
                            return

                        location = response.headers.get('Location')
                        if not location:
                            self.logger.warning("重定向响应缺少 Location 头")
                            await self._send_error(writer, 502, "Bad Gateway")
                            return

                        current_url = self._resolve_redirect_url(current_url, location)
                        self.logger.debug(f"重定向到: {current_url}")

                        parsed = urlparse(current_url)
                        headers['Host'] = parsed.netloc

                        if response.status == 303:
                            method = 'GET'
                            body = None

                        continue

                    await self._send_response_v2(writer, response, current_url, 
                                                  cache_key, session_id)
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
        await self._send_response_v2(writer, response, target_url, None, None)

    async def _send_response_v2(self, writer: asyncio.StreamWriter,
                                 response: aiohttp.ClientResponse,
                                 target_url: str,
                                 cache_key: Optional[str],
                                 session_id: Optional[str]) -> None:
        """
        V2增强版响应发送

        在原有响应发送基础上增加：
        - 脚本注入
        - 响应缓存

        Args:
            writer: 流写入器
            response: 目标服务器的响应对象
            target_url: 目标 URL
            cache_key: 缓存键
            session_id: 会话ID
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

            # ========== V2: 脚本注入 ==========
            if self.script_injector and self._should_inject_script(content_type):
                try:
                    content = await self.script_injector.inject_scripts(content, target_url, content_type)
                    self.logger.debug(f"脚本注入完成: {target_url}")
                except Exception as e:
                    self.logger.error(f"脚本注入失败: {e}")

            content, encoding = await self._compress_content(content)

            headers = dict(response.headers)

            headers['Content-Length'] = str(len(content))
            if encoding and encoding != 'identity':
                headers['Content-Encoding'] = encoding
            else:
                headers.pop('Content-Encoding', None)

            headers['Via'] = 'SilkRoad-Next/2.0'

            headers.pop('Transfer-Encoding', None)
            headers.pop('Content-Security-Policy', None)
            headers.pop('Content-Security-Policy-Report-Only', None)

            target_domain = self.cookie_handler.extract_domain_from_url(target_url)

            set_cookie_values = None
            if 'Set-Cookie' in headers:
                set_cookie_values = headers.pop('Set-Cookie')
            elif 'set-cookie' in headers:
                set_cookie_values = headers.pop('set-cookie')

            # ========== V2: 添加会话Cookie ==========
            if session_id and self.session_manager:
                session_cookie = f"session={session_id}; Path=/; HttpOnly"
                if set_cookie_values is None:
                    set_cookie_values = [session_cookie]
                elif isinstance(set_cookie_values, str):
                    set_cookie_values = [set_cookie_values, session_cookie]
                else:
                    set_cookie_values.append(session_cookie)

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

            # ========== V2: 缓存响应 ==========
            if cache_key and self.cache_manager and response.status == 200:
                try:
                    await self.cache_manager.set(cache_key, content, ttl=self.config.get('cache.defaultTTL', 3600))
                    self.logger.debug(f"响应已缓存: {target_url}")
                except Exception as e:
                    self.logger.error(f"缓存响应失败: {e}")

            self.logger.debug(f"响应已发送: {response.status} {len(content)} bytes")

        except Exception as e:
            self.logger.error(f"发送响应失败: {e}")
            raise

    def _should_inject_script(self, content_type: str) -> bool:
        """
        判断是否需要注入脚本

        Args:
            content_type: 内容类型

        Returns:
            是否需要注入
        """
        if not content_type:
            return False

        inject_types = ['text/html', 'application/xhtml+xml']
        content_type_lower = content_type.lower()
        
        for ct in inject_types:
            if ct in content_type_lower:
                return True

        return False

    async def _send_blocked_response(self, writer: asyncio.StreamWriter,
                                      message: str, reason: str) -> None:
        """
        发送黑名单拦截响应

        Args:
            writer: 流写入器
            message: 拦截消息
            reason: 拦截原因
        """
        try:
            blocked_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Access Blocked</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            text-align: center;
            padding: 50px;
            background-color: #1a1a2e;
            color: #eee;
        }}
        .blocked-container {{
            background: #16213e;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.3);
            max-width: 600px;
            margin: 0 auto;
            border: 1px solid #e94560;
        }}
        h1 {{
            color: #e94560;
            margin-bottom: 20px;
        }}
        p {{
            color: #aaa;
            margin-bottom: 15px;
        }}
        .reason {{
            background: #0f3460;
            padding: 15px;
            border-radius: 5px;
            margin: 20px 0;
            color: #e94560;
            font-family: monospace;
        }}
        .powered-by {{
            color: #666;
            font-size: 12px;
            margin-top: 30px;
        }}
    </style>
</head>
<body>
    <div class="blocked-container">
        <h1>🚫 Access Blocked</h1>
        <p>Your request has been blocked by the proxy server.</p>
        <div class="reason">{reason}</div>
        <p>{message}</p>
        <div class="powered-by">
            Powered by SilkRoad-Next/2.0
        </div>
    </div>
</body>
</html>"""

            content = blocked_html.encode('utf-8')

            response = f"HTTP/1.1 403 Forbidden\r\n"
            response += "Content-Type: text/html; charset=utf-8\r\n"
            response += f"Content-Length: {len(content)}\r\n"
            response += "Connection: close\r\n"
            response += "Via: SilkRoad-Next/2.0\r\n"
            response += "\r\n"

            writer.write(response.encode('utf-8'))
            writer.write(content)
            await writer.drain()

        except Exception as e:
            self.logger.error(f"发送拦截响应失败: {e}")

    async def _send_cached_response(self, writer: asyncio.StreamWriter,
                                     cached_data: bytes,
                                     session_id: Optional[str]) -> None:
        """
        发送缓存响应

        Args:
            writer: 流写入器
            cached_data: 缓存数据（bytes）
            session_id: 会话ID
        """
        try:
            headers = {
                'Content-Type': 'text/html; charset=utf-8',
                'Content-Length': str(len(cached_data)),
                'X-Cache': 'HIT',
                'Via': 'SilkRoad-Next/2.0'
            }

            if session_id and self.session_manager:
                session_cookie = f"session={session_id}; Path=/; HttpOnly"
                headers['Set-Cookie'] = session_cookie

            status_line = "HTTP/1.1 200 OK\r\n"
            writer.write(status_line.encode('utf-8'))

            for key, value in headers.items():
                writer.write(f"{key}: {value}\r\n".encode('utf-8'))

            writer.write(b"\r\n")
            writer.write(cached_data)
            await writer.drain()

            self.logger.debug(f"缓存响应已发送: 200 {len(cached_data)} bytes")

        except Exception as e:
            self.logger.error(f"发送缓存响应失败: {e}")
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
        stats = {
            'host': self.host,
            'port': self.port,
            'is_running': self.is_running,
            'active_connections': self.active_connections,
            'max_connections': self.config.get('server.proxy.maxConnections', 2000),
            'timeout': self.timeout,
            'request_timeout': self.request_timeout,
            'max_redirects': self.max_redirects,
            'v2_enabled': self.v2_enabled
        }

        # 添加 V2 模块统计信息
        if self.v2_enabled:
            if self.connection_pool:
                stats['connection_pool'] = self.connection_pool.get_stats()
            if self.thread_pool:
                stats['thread_pool'] = self.thread_pool.get_stats()
            if self.session_manager:
                stats['session_manager'] = self.session_manager.get_stats()
            if self.cache_manager:
                stats['cache_manager'] = self.cache_manager.get_stats()
            if self.blacklist_manager:
                stats['blacklist_manager'] = self.blacklist_manager.get_stats()
            if self.script_injector:
                stats['script_injector'] = self.script_injector.get_stats()

        return stats
