import asyncio
from typing import Optional, Dict, Any, Tuple, TYPE_CHECKING, Union
from urllib.parse import urlsplit, urljoin

import aiohttp
from loguru import logger as loguru_logger

from modules.url.handle import URLHandler
from modules.url.cookie import CookieHandler
from modules.ua import UAHandler

if TYPE_CHECKING:
    from modules.scripts import ScriptInjector
    from modules.connectionpool import ConnectionPool
    from modules.threadpool import ThreadPoolManager
    from modules.cachemanager import CacheManager


class NormalHandler:

    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger or loguru_logger

        self.session: Optional[aiohttp.ClientSession] = None
        self.url_handler: Optional[URLHandler] = None
        self.cookie_handler: Optional[CookieHandler] = None
        self.ua_handler: Optional[UAHandler] = None
        self.connection_pool: Optional['ConnectionPool'] = None
        self.thread_pool: Optional['ThreadPoolManager'] = None
        self.cache_manager: Optional['CacheManager'] = None
        self.script_injector: Optional['ScriptInjector'] = None

        self.timeout = config.get('server.proxy.connectionTimeout', 30)
        self.request_timeout = config.get('server.proxy.requestTimeout', 60)
        self.max_redirects = config.get('server.proxy.maxRedirects', 10)
        self.stream_threshold = config.get('urlRewrite.streamThreshold', 10485760)

    def set_session(self, session: aiohttp.ClientSession):
        self.session = session

    def set_url_handler(self, url_handler: URLHandler):
        self.url_handler = url_handler

    def set_cookie_handler(self, cookie_handler: CookieHandler):
        self.cookie_handler = cookie_handler

    def set_ua_handler(self, ua_handler: UAHandler):
        self.ua_handler = ua_handler

    def set_connection_pool(self, connection_pool: 'ConnectionPool'):
        self.connection_pool = connection_pool

    def set_thread_pool(self, thread_pool: 'ThreadPoolManager'):
        self.thread_pool = thread_pool

    def set_cache_manager(self, cache_manager: 'CacheManager'):
        self.cache_manager = cache_manager

    def set_script_injector(self, script_injector: 'ScriptInjector'):
        self.script_injector = script_injector

    async def handle(self, writer, method, target_url, headers, body, session_id=None):
        if self.connection_pool:
            await self._forward_with_pool(writer, method, target_url, headers, body, session_id)
        else:
            await self._forward_direct(writer, method, target_url, headers, body)

    async def _forward_direct(self, writer: asyncio.StreamWriter,
                               method: str, target_url: str,
                               headers: Dict[str, str],
                               body: Optional[bytes]) -> None:
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

                        parsed = urlsplit(current_url)
                        headers['Host'] = parsed.netloc

                        if response.status == 303:
                            method = 'GET'
                            body = None

                        continue

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

        self.logger.warning(f"重定向次数超过限制: {redirect_count}")
        await self._send_error(writer, 508, "Loop Detected")

    async def _forward_with_pool(self, writer: asyncio.StreamWriter,
                                  method: str, target_url: str,
                                  headers: Dict[str, str],
                                  body: Optional[bytes],
                                  session_id: Optional[str] = None) -> None:
        assert self.connection_pool is not None
        parsed = urlsplit(target_url)
        host = parsed.netloc
        port = 443 if parsed.scheme == 'https' else 80
        is_https = parsed.scheme == 'https'

        try:
            connection = await self.connection_pool.get_connection(
                host, port, is_https, session_id
            )

            if connection is None:
                connector = aiohttp.TCPConnector(
                    limit=100,
                    ttl_dns_cache=300,
                    enable_cleanup_closed=True
                )

                self.connection_pool.register_connection(host, port, connector)

                session = aiohttp.ClientSession(
                    connector=connector,
                    timeout=aiohttp.ClientTimeout(
                        total=self.request_timeout,
                        connect=self.timeout
                    )
                )
            else:
                session = aiohttp.ClientSession(
                    connector=connection,
                    timeout=aiohttp.ClientTimeout(
                        total=self.request_timeout,
                        connect=self.timeout
                    )
                )

            request_headers = headers.copy()
            if session_id:
                session_cookies = self.connection_pool.get_session_cookies()
                if session_cookies:
                    cookie_header = '; '.join(
                        f"{name}={value}" for name, value in session_cookies.items()
                    )
                    if 'Cookie' in request_headers:
                        request_headers['Cookie'] = f"{request_headers['Cookie']}; {cookie_header}"
                    else:
                        request_headers['Cookie'] = cookie_header
                    self.logger.debug(
                        f"V5 会话持久化: 添加 {len(session_cookies)} 个 Cookie 到请求"
                    )

            try:
                async with session.request(
                    method,
                    target_url,
                    headers=request_headers,
                    data=body,
                    allow_redirects=False,
                    ssl=False
                ) as response:
                    content = await response.read()

                    content_type = response.headers.get('Content-Type', '')
                    if self._should_rewrite(content_type) and self.url_handler:
                        try:
                            content = await self.url_handler.rewrite(
                                content, content_type, target_url
                            )
                        except Exception as e:
                            self.logger.error(f"URL 修正失败: {e}")

                    self.logger.debug(f"脚本注入检查: script_injector={self.script_injector is not None}, content_type={content_type}")
                    if self.script_injector and 'text/html' in content_type:
                        try:
                            self.logger.info(f"开始脚本注入: {target_url}")
                            encoding = 'utf-8'
                            if isinstance(content, bytes):
                                if 'charset=' in content_type:
                                    charset = content_type.split('charset=')[-1].split(';')[0].strip()
                                    if charset:
                                        encoding = charset
                                content_str = content.decode(encoding, errors='ignore')
                            else:
                                content_str = content

                            content_str = await self.script_injector.inject_scripts(
                                content_str, target_url, content_type
                            )

                            if isinstance(content, bytes):
                                content = content_str.encode(encoding, errors='ignore')
                            else:
                                content = content_str

                            self.logger.info(f"脚本注入完成: {target_url}")
                        except Exception as e:
                            import traceback
                            self.logger.error(f"脚本注入失败: {e}\n{traceback.format_exc()}")

                    if isinstance(content, str):
                        content = content.encode('utf-8', errors='ignore')

                    response_headers = dict(response.headers)
                    response_headers['Content-Length'] = str(len(content))
                    response_headers.pop('Content-Encoding', None)
                    response_headers['Via'] = 'SilkRoad-Next/2.0'
                    response_headers.pop('Transfer-Encoding', None)

                    if session_id and 'Set-Cookie' in response_headers:
                        try:
                            set_cookie_header = response_headers.get('Set-Cookie', '')
                            if set_cookie_header:
                                cookies = {}
                                for cookie_str in set_cookie_header.split(','):
                                    if '=' in cookie_str:
                                        cookie_parts = cookie_str.strip().split(';')[0]
                                        if '=' in cookie_parts:
                                            name, value = cookie_parts.split('=', 1)
                                            cookies[name.strip()] = {
                                                'value': value.strip(),
                                                'domain': host
                                            }

                                if cookies and self.connection_pool:
                                    _sm = getattr(self.connection_pool, 'session_manager', None)  # type: ignore[attr-defined]
                                    if _sm:
                                        existing_session = await _sm.get_session(session_id)
                                        existing_cookies = (existing_session or {}).get('data', {}).get('cookies', {})
                                        existing_cookies.update(cookies)
                                        await _sm.update_session(session_id, {'cookies': existing_cookies})
                                    self.logger.debug(
                                        f"V5 会话持久化: 保存 {len(cookies)} 个 Cookie 到会话 {session_id}"
                                    )
                        except Exception as e:
                            self.logger.warning(f"保存会话 Cookie 失败: {e}")
                    response_headers.pop('Content-Security-Policy', None)
                    response_headers.pop('Content-Security-Policy-Report-Only', None)

                    if 'Location' in response_headers and self.url_handler:
                        response_headers['Location'] = self.url_handler.rewrite_location_header(
                            response_headers['Location'], target_url
                        )
                        self.logger.debug(f"Location 头重写（连接池）: {response_headers['Location']}")

                    if 'Content-Location' in response_headers and self.url_handler:
                        response_headers['Content-Location'] = self.url_handler.rewrite_content_location_header(
                            response_headers['Content-Location'], target_url
                        )

                    if 'Refresh' in response_headers and self.url_handler and hasattr(self.url_handler, 'location_handler') and self.url_handler.location_handler:
                        response_headers['Refresh'] = self.url_handler.location_handler.rewrite_refresh_header(
                            response_headers['Refresh'], target_url
                        )

                    target_domain = self.cookie_handler.extract_domain_from_url(target_url) if self.cookie_handler else None
                    set_cookie_values = None
                    if 'Set-Cookie' in response_headers:
                        set_cookie_values = response_headers.pop('Set-Cookie')
                    elif 'set-cookie' in response_headers:
                        set_cookie_values = response_headers.pop('set-cookie')

                    status_line = f"HTTP/1.1 {response.status} {response.reason}\r\n"
                    writer.write(status_line.encode('utf-8'))

                    for key, value in response_headers.items():
                        if key.lower() in ['transfer-encoding', 'set-cookie']:
                            continue
                        writer.write(f"{key}: {value}\r\n".encode('utf-8'))

                    if set_cookie_values and target_domain:
                        if isinstance(set_cookie_values, str):
                            set_cookie_values = [set_cookie_values]

                        for cookie_value in set_cookie_values:
                            rewritten_cookie = self.cookie_handler.rewrite_set_cookie(
                                cookie_value, target_domain
                            ) if self.cookie_handler else cookie_value
                            writer.write(f"Set-Cookie: {rewritten_cookie}\r\n".encode('utf-8'))

                    writer.write(b"\r\n")
                    writer.write(content)
                    await writer.drain()

                    self.logger.debug(f"响应已发送（连接池）: {response.status} {len(content)} bytes")

                    if self.cache_manager and method == 'GET':
                        await self.cache_manager.set(
                            target_url, content, method, headers,
                            ttl=self.config.get('cache.defaultTTL', 3600)
                        )

            finally:
                if self.connection_pool and session.connector:
                    await self.connection_pool.return_connection(
                        host, port, session.connector  # type: ignore[arg-type]
                    )
                await session.close()

        except ConnectionError as e:
            self.logger.warning(f"连接池已满，降级到 V1 方式: {e}")
            await self._forward_direct(writer, method, target_url, headers, body)

        except asyncio.TimeoutError:
            self.logger.error(f"请求超时: {target_url}")
            await self._send_error(writer, 504, "Gateway Timeout")

        except aiohttp.ClientError as e:
            self.logger.error(f"目标服务器错误 [{target_url}]: {e}")
            await self._send_error(writer, 502, "Bad Gateway")

        except Exception as e:
            self.logger.error(f"转发请求失败 [{target_url}]: {e}")
            await self._send_error(writer, 500, "Internal Server Error")

    async def _send_response(self, writer: asyncio.StreamWriter,
                              response: aiohttp.ClientResponse,
                              target_url: str) -> None:
        try:
            content_length = int(response.headers.get('Content-Length', 0))

            if content_length > self.stream_threshold:
                await self._stream_response(writer, response)
                return

            content = await response.read()

            content_type = response.headers.get('Content-Type', '')
            if self._should_rewrite(content_type) and self.url_handler:
                try:
                    content = await self.url_handler.rewrite(
                        content,
                        content_type,
                        target_url
                    )
                except Exception as e:
                    self.logger.error(f"URL 修正失败: {e}")

            if isinstance(content, str):
                content = content.encode('utf-8', errors='ignore')

            headers = dict(response.headers)

            headers['Content-Length'] = str(len(content))
            headers.pop('Content-Encoding', None)

            headers['Via'] = 'SilkRoad-Next/1.0'

            headers.pop('Transfer-Encoding', None)
            headers.pop('Content-Security-Policy', None)
            headers.pop('Content-Security-Policy-Report-Only', None)

            if 'Location' in headers and self.url_handler:
                headers['Location'] = self.url_handler.rewrite_location_header(
                    headers['Location'], target_url
                )
                self.logger.debug(f"Location 头重写: {headers['Location']}")

            if 'Content-Location' in headers and self.url_handler:
                headers['Content-Location'] = self.url_handler.rewrite_content_location_header(
                    headers['Content-Location'], target_url
                )

            if 'Refresh' in headers and self.url_handler and hasattr(self.url_handler, 'location_handler') and self.url_handler.location_handler:
                headers['Refresh'] = self.url_handler.location_handler.rewrite_refresh_header(
                    headers['Refresh'], target_url
                )

            target_domain = self.cookie_handler.extract_domain_from_url(target_url) if self.cookie_handler else None

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
                    ) if self.cookie_handler else cookie_value
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
        try:
            status_line = f"HTTP/1.1 {response.status} {response.reason}\r\n"
            writer.write(status_line.encode('utf-8'))

            for key, value in response.headers.items():
                key_lower = key.lower()
                if key_lower in ['transfer-encoding', 'content-security-policy', 'content-security-policy-report-only', 'set-cookie']:
                    continue

                if key_lower == 'location' and self.url_handler:
                    value = self.url_handler.rewrite_location_header(value, '')
                elif key_lower == 'content-location' and self.url_handler:
                    value = self.url_handler.rewrite_content_location_header(value, '')
                elif key_lower == 'refresh' and self.url_handler and hasattr(self.url_handler, 'location_handler') and self.url_handler.location_handler:
                    value = self.url_handler.location_handler.rewrite_refresh_header(value, '')

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

    async def _send_cached_response(self, writer: asyncio.StreamWriter,
                                     cached_data: bytes,
                                     _target_url: str) -> None:
        try:
            headers = {
                'Content-Type': 'text/html; charset=utf-8',
                'Content-Length': str(len(cached_data)),
                'Connection': 'keep-alive',
                'Via': 'SilkRoad-Next/2.0 (cached)',
                'X-Cache': 'HIT'
            }

            status_line = "HTTP/1.1 200 OK\r\n"
            writer.write(status_line.encode('utf-8'))

            for key, value in headers.items():
                writer.write(f"{key}: {value}\r\n".encode('utf-8'))

            writer.write(b"\r\n")
            writer.write(cached_data)
            await writer.drain()

            self.logger.debug(f"缓存响应已发送: {len(cached_data)} bytes")

        except Exception as e:
            self.logger.error(f"发送缓存响应失败: {e}")
            raise

    def _should_rewrite(self, content_type: str) -> bool:
        if not content_type:
            return False

        if not self.config.get('urlRewrite.enabled', True):
            return False

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

        content_type_lower = content_type.lower()
        for ct in process_types:
            if ct in content_type_lower:
                return True

        return False

    def _resolve_redirect_url(self, base_url: str, location: str) -> str:
        if location.startswith('http://') or location.startswith('https://'):
            return location

        if location.startswith('//'):
            parsed = urlsplit(base_url)
            return f"{parsed.scheme}:{location}"

        return urljoin(base_url, location)

    async def _send_error(self, writer: asyncio.StreamWriter,
                          status_code: int, message: str) -> None:
        try:
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

            content = error_html.encode('utf-8')

            response = f"HTTP/1.1 {status_code} {message}\r\n"
            response += "Content-Type: text/html; charset=utf-8\r\n"
            response += f"Content-Length: {len(content)}\r\n"
            response += "Connection: close\r\n"
            response += "Via: SilkRoad-Next/1.0\r\n"
            response += "\r\n"

            writer.write(response.encode('utf-8'))
            writer.write(content)
            await writer.drain()

        except Exception as e:
            self.logger.error(f"发送错误响应失败: {e}")

    def get_stats(self) -> dict:
        return {
            'timeout': self.timeout,
            'request_timeout': self.request_timeout,
            'max_redirects': self.max_redirects,
            'stream_threshold': self.stream_threshold,
            'has_connection_pool': self.connection_pool is not None,
            'has_thread_pool': self.thread_pool is not None,
            'has_cache_manager': self.cache_manager is not None,
            'has_script_injector': self.script_injector is not None,
        }
