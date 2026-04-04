"""
静态网站服务器模块

提供静态文件托管服务，支持：
- 多路由映射
- MIME类型自动识别
- 默认首页（index.html）
- 目录遍历防护
- 大文件流式传输
- SPA应用路由支持

Author: SilkRoad-Next Team
Version: 1.0.0
"""

import os
import mimetypes
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, Set
import asyncio


class PageServer:
    """
    静态网站服务器

    负责处理静态文件请求，支持多路由映射、MIME类型自动识别、
    默认首页、目录遍历防护和大文件流式传输。

    Attributes:
        config: 配置管理器对象
        logger: 日志管理器对象
        pages_dir (Path): 静态资源根目录
        routes (Dict[str, str]): 路由映射表
        large_file_threshold (int): 大文件阈值（字节）
        default_index (str): 默认首页文件名
        spa_extensions (Set[str]): SPA应用需要排除的静态资源扩展名
    """

    def __init__(self, config, logger):
        """
        初始化静态网站服务器

        Args:
            config: 配置管理器对象，用于获取路由配置等
            logger: 日志管理器对象，用于记录日志
        """
        self.config = config
        self.logger = logger

        # 静态资源根目录
        self.pages_dir = Path('pages')

        # 获取路由配置
        self.routes: Dict[str, str] = config.get('pageRoutes', {
            "/": "main",
            "/admin": "admin",
            "/error": "error"
        })

        # 大文件阈值（默认 10MB）
        self.large_file_threshold: int = config.get(
            'urlRewrite.streamThreshold',
            10 * 1024 * 1024
        )

        # 默认首页文件名
        self.default_index: str = 'index.html'

        # SPA应用需要排除的静态资源扩展名
        # 这些扩展名的文件如果不存在，不应该返回 index.html
        self.spa_extensions: Set[str] = {
            '.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg',
            '.ico', '.woff', '.woff2', '.ttf', '.eot', '.otf',
            '.mp4', '.webm', '.mp3', '.wav', '.pdf', '.zip'
        }

        # 初始化MIME类型
        self._init_mime_types()

    def _init_mime_types(self) -> None:
        """
        初始化MIME类型映射

        扩展标准MIME类型库，添加常见文件类型的映射。
        """
        # 初始化标准MIME类型
        mimetypes.init()

        # 添加额外的MIME类型映射
        additional_types = {
            # Web字体
            '.woff': 'font/woff',
            '.woff2': 'font/woff2',
            '.ttf': 'font/ttf',
            '.otf': 'font/otf',
            '.eot': 'application/vnd.ms-fontobject',

            # 现代图片格式
            '.webp': 'image/webp',
            '.avif': 'image/avif',
            '.svg': 'image/svg+xml',

            # 视频格式
            '.webm': 'video/webm',
            '.mp4': 'video/mp4',
            '.ogg': 'video/ogg',

            # 音频格式
            '.mp3': 'audio/mpeg',
            '.wav': 'audio/wav',
            '.flac': 'audio/flac',

            # 文档格式
            '.pdf': 'application/pdf',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',

            # 压缩格式
            '.zip': 'application/zip',
            '.rar': 'application/vnd.rar',
            '.7z': 'application/x-7z-compressed',
            '.tar': 'application/x-tar',
            '.gz': 'application/gzip',

            # JavaScript模块
            '.mjs': 'application/javascript',
            '.cjs': 'application/javascript',

            # JSON
            '.json': 'application/json',
            '.map': 'application/json',

            # WebAssembly
            '.wasm': 'application/wasm',

            # Manifest
            '.manifest': 'text/cache-manifest',
            '.webmanifest': 'application/manifest+json',
        }

        # 注册额外的MIME类型
        for ext, mime_type in additional_types.items():
            mimetypes.add_type(mime_type, ext)

        self.logger.debug(f"MIME类型初始化完成，已注册 {len(additional_types)} 种额外类型")

    async def handle_request(self, path: str) -> Optional[Tuple[bytes, str]]:
        """
        处理静态文件请求

        根据请求路径匹配路由，查找并返回对应的静态文件内容。
        支持默认首页和SPA应用路由。

        Args:
            path: 请求路径，如 "/" 或 "/admin/dashboard"

        Returns:
            Optional[Tuple[bytes, str]]: 如果找到文件，返回 (文件内容, MIME类型)；
                                         如果未找到，返回 None

        Examples:
            >>> content, mime_type = await page_server.handle_request("/")
            >>> print(mime_type)  # "text/html"
        """
        # 1. 匹配路由
        route_name = self._match_route(path)
        if not route_name:
            self.logger.debug(f"路由未匹配: {path}")
            return None

        # 2. 构建文件路径
        file_path = self._build_file_path(path, route_name)

        # 3. 安全检查（防止目录遍历攻击）
        if not self._is_safe_path(file_path):
            self.logger.warning(f"路径遍历攻击尝试: {path} -> {file_path}")
            return None

        # 4. 检查文件是否存在
        if not file_path.exists():
            # 如果是SPA应用路由，尝试返回index.html
            if self._is_spa_route(path):
                index_path = self.pages_dir / route_name / self.default_index
                if index_path.exists() and self._is_safe_path(index_path):
                    self.logger.debug(f"SPA路由回退到首页: {path}")
                    file_path = index_path
                else:
                    return None
            else:
                self.logger.debug(f"文件不存在: {file_path}")
                return None

        # 5. 处理目录请求
        if file_path.is_dir():
            # 尝试返回目录下的默认首页
            index_path = file_path / self.default_index
            if index_path.exists() and self._is_safe_path(index_path):
                file_path = index_path
            else:
                self.logger.debug(f"目录缺少默认首页: {file_path}")
                return None

        # 6. 确保是文件（不是目录或其他）
        if not file_path.is_file():
            self.logger.warning(f"请求的不是文件: {file_path}")
            return None

        # 7. 读取文件内容
        try:
            content = file_path.read_bytes()
        except PermissionError:
            self.logger.error(f"无权限读取文件: {file_path}")
            return None
        except OSError as e:
            self.logger.error(f"读取文件失败: {file_path}, 错误: {e}")
            return None

        # 8. 获取MIME类型
        mime_type = self._get_mime_type(file_path)

        self.logger.debug(f"静态文件服务: {path} -> {file_path} ({mime_type})")

        return content, mime_type

    def _match_route(self, path: str) -> Optional[str]:
        """
        匹配路由

        支持精确匹配和前缀匹配两种方式：
        1. 精确匹配：路径完全相同
        2. 前缀匹配：路径以路由模式开头

        匹配优先级：精确匹配 > 最长前缀匹配 > 最短前缀匹配

        Args:
            path: 请求路径

        Returns:
            Optional[str]: 匹配的路由名称，如果未匹配则返回 None

        Examples:
            >>> page_server._match_route("/")
            "main"
            >>> page_server._match_route("/admin/users")
            "admin"
        """
        # 规范化路径（移除尾部斜杠，但保留根路径）
        normalized_path = path.rstrip('/') if len(path) > 1 else path

        # 1. 尝试精确匹配
        if normalized_path in self.routes:
            return self.routes[normalized_path]

        # 2. 尝试前缀匹配（按长度降序排列，优先匹配最长的前缀）
        sorted_routes = sorted(
            self.routes.keys(),
            key=lambda r: len(r.rstrip('/') if len(r) > 1 else r),
            reverse=True
        )

        for route_pattern in sorted_routes:
            # 规范化路由模式
            normalized_pattern = route_pattern.rstrip('/') if len(route_pattern) > 1 else route_pattern

            # 检查前缀匹配
            if normalized_path.startswith(normalized_pattern):
                # 确保匹配的是完整的路径段
                # 例如：/admin 应该匹配 /admin/users，但不应该匹配 /administrator
                next_char_index = len(normalized_pattern)
                if next_char_index >= len(normalized_path):
                    # 完全匹配
                    return self.routes[route_pattern]
                elif normalized_path[next_char_index] == '/':
                    # 路径段匹配
                    return self.routes[route_pattern]

        return None

    def _build_file_path(self, path: str, route_name: str) -> Path:
        """
        构建文件路径

        根据请求路径和路由名称，构建实际的文件系统路径。
        移除路由前缀后，将剩余路径拼接到对应的静态资源目录。

        Args:
            path: 请求路径
            route_name: 路由名称（对应 pages 目录下的子目录名）

        Returns:
            Path: 文件系统路径

        Examples:
            >>> page_server._build_file_path("/", "main")
            Path("pages/main")
            >>> page_server._build_file_path("/admin/dashboard.html", "admin")
            Path("pages/admin/dashboard.html")
        """
        # 找到匹配的路由模式
        matched_pattern = None
        for route_pattern in self.routes.keys():
            normalized_pattern = route_pattern.rstrip('/') if len(route_pattern) > 1 else route_pattern
            normalized_path = path.rstrip('/') if len(path) > 1 else path

            # 精确匹配或前缀匹配
            if normalized_path == normalized_pattern or normalized_path.startswith(normalized_pattern + '/'):
                matched_pattern = route_pattern
                break

        # 计算相对路径
        if matched_pattern:
            # 移除路由前缀
            normalized_pattern = matched_pattern.rstrip('/') if len(matched_pattern) > 1 else matched_pattern
            relative_path = path[len(normalized_pattern):]
        else:
            relative_path = path

        # 移除开头的斜杠
        relative_path = relative_path.lstrip('/')

        # 构建完整路径
        if relative_path:
            file_path = self.pages_dir / route_name / relative_path
        else:
            file_path = self.pages_dir / route_name

        return file_path

    def _is_safe_path(self, file_path: Path) -> bool:
        """
        检查路径安全性

        防止目录遍历攻击（Path Traversal），确保请求的文件路径
        在允许的静态资源目录内。

        检查方式：
        1. 解析真实路径（解析符号链接和相对路径）
        2. 检查真实路径是否在静态资源根目录内

        Args:
            file_path: 待检查的文件路径

        Returns:
            bool: 路径是否安全

        Examples:
            >>> page_server._is_safe_path(Path("pages/main/index.html"))
            True
            >>> page_server._is_safe_path(Path("pages/main/../../../etc/passwd"))
            False
        """
        try:
            # 解析真实路径（解析符号链接和相对路径）
            # 使用 resolve() 会将路径转换为绝对路径
            real_path = file_path.resolve()
            pages_real_path = self.pages_dir.resolve()

            # 检查真实路径是否在静态资源根目录内
            # 使用字符串比较，确保路径前缀匹配
            real_path_str = str(real_path)
            pages_real_path_str = str(pages_real_path)

            # 确保路径以根目录开头（防止 /pages-other 绕过）
            if not real_path_str.startswith(pages_real_path_str + os.sep) and \
               real_path_str != pages_real_path_str:
                return False

            return True

        except (OSError, ValueError) as e:
            # 路径解析失败，可能是无效路径
            self.logger.warning(f"路径安全检查失败: {file_path}, 错误: {e}")
            return False

    def _get_mime_type(self, file_path: Path) -> str:
        """
        获取MIME类型

        根据文件扩展名自动识别MIME类型。
        如果无法识别，返回默认的 'application/octet-stream'。

        Args:
            file_path: 文件路径

        Returns:
            str: MIME类型字符串

        Examples:
            >>> page_server._get_mime_type(Path("index.html"))
            "text/html"
            >>> page_server._get_mime_type(Path("style.css"))
            "text/css"
            >>> page_server._get_mime_type(Path("unknown.xyz"))
            "application/octet-stream"
        """
        # 使用 mimetypes 库猜测MIME类型
        mime_type, _ = mimetypes.guess_type(str(file_path))

        # 如果无法识别，使用默认类型
        if mime_type is None:
            mime_type = 'application/octet-stream'

        return mime_type

    def _is_spa_route(self, path: str) -> bool:
        """
        判断是否为SPA应用路由

        SPA（单页应用）的路由由前端处理，后端应该返回 index.html。
        通过检查文件扩展名来判断是否为静态资源请求。

        Args:
            path: 请求路径

        Returns:
            bool: 是否为SPA路由（需要返回 index.html）

        Examples:
            >>> page_server._is_spa_route("/dashboard")
            True
            >>> page_server._is_spa_route("/app.js")
            False
        """
        # 获取文件扩展名（转小写）
        ext = os.path.splitext(path)[1].lower()

        # 如果有扩展名且在静态资源扩展名集合中，则不是SPA路由
        if ext and ext in self.spa_extensions:
            return False

        return True

    async def handle_large_file(
        self,
        file_path: Path,
        writer: asyncio.StreamWriter
    ) -> bool:
        """
        流式传输大文件

        对于大文件，使用流式传输避免一次性加载到内存。
        直接将文件内容写入到响应流中。

        Args:
            file_path: 文件路径
            writer: asyncio StreamWriter 对象，用于写入响应

        Returns:
            bool: 传输是否成功

        Examples:
            >>> success = await page_server.handle_large_file(
            ...     Path("pages/main/video.mp4"),
            ...     writer
            ... )
        """
        # 检查文件是否存在
        if not file_path.exists() or not file_path.is_file():
            self.logger.error(f"大文件传输失败：文件不存在 {file_path}")
            return False

        # 安全检查
        if not self._is_safe_path(file_path):
            self.logger.warning(f"大文件传输失败：路径不安全 {file_path}")
            return False

        try:
            # 获取文件大小
            file_size = file_path.stat().st_size

            # 获取MIME类型
            mime_type = self._get_mime_type(file_path)

            # 构建响应头
            headers = [
                "HTTP/1.1 200 OK",
                f"Content-Type: {mime_type}",
                f"Content-Length: {file_size}",
                "Connection: keep-alive",
                "",  # 空行分隔头部和正文
            ]

            # 发送响应头
            header_bytes = "\r\n".join(headers).encode('utf-8')
            writer.write(header_bytes)
            await writer.drain()

            # 流式读取并发送文件内容
            chunk_size = 65536  # 64KB 块大小
            bytes_sent = 0

            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break

                    writer.write(chunk)
                    await writer.drain()

                    bytes_sent += len(chunk)

            self.logger.debug(
                f"大文件传输完成: {file_path} "
                f"({bytes_sent} bytes, {mime_type})"
            )

            return True

        except PermissionError:
            self.logger.error(f"大文件传输失败：无权限读取文件 {file_path}")
            return False
        except ConnectionResetError:
            self.logger.warning(f"大文件传输中断：客户端断开连接 {file_path}")
            return False
        except OSError as e:
            self.logger.error(f"大文件传输失败：IO错误 {file_path}, 错误: {e}")
            return False
        except Exception as e:
            self.logger.error(f"大文件传输失败：未知错误 {file_path}, 错误: {e}")
            return False

    def is_large_file(self, file_path: Path) -> bool:
        """
        判断是否为大文件

        根据配置的阈值判断文件是否需要流式传输。

        Args:
            file_path: 文件路径

        Returns:
            bool: 是否为大文件

        Examples:
            >>> page_server.is_large_file(Path("large_video.mp4"))
            True
        """
        try:
            if not file_path.exists() or not file_path.is_file():
                return False

            file_size = file_path.stat().st_size
            return file_size > self.large_file_threshold

        except OSError:
            return False

    def get_file_info(self, path: str) -> Optional[Dict[str, Any]]:
        """
        获取文件信息

        返回文件的元数据信息，包括大小、MIME类型、修改时间等。
        用于实现条件请求（如 If-Modified-Since）和范围请求。

        Args:
            path: 请求路径

        Returns:
            Optional[Dict[str, Any]]: 文件信息字典，如果文件不存在则返回 None

        Examples:
            >>> info = page_server.get_file_info("/style.css")
            >>> print(info['size'], info['mime_type'])
        """
        # 匹配路由
        route_name = self._match_route(path)
        if not route_name:
            return None

        # 构建文件路径
        file_path = self._build_file_path(path, route_name)

        # 安全检查
        if not self._is_safe_path(file_path):
            return None

        # 检查文件是否存在
        if not file_path.exists():
            # 尝试默认首页
            if file_path.is_dir():
                file_path = file_path / self.default_index
            else:
                return None

        if not file_path.exists() or not file_path.is_file():
            return None

        try:
            stat = file_path.stat()

            return {
                'path': str(file_path),
                'size': stat.st_size,
                'mime_type': self._get_mime_type(file_path),
                'modified_time': stat.st_mtime,
                'is_large': stat.st_size > self.large_file_threshold,
            }

        except OSError:
            return None

    def __repr__(self) -> str:
        """返回静态网站服务器的字符串表示"""
        return (
            f"PageServer("
            f"pages_dir='{self.pages_dir}', "
            f"routes={len(self.routes)}, "
            f"large_file_threshold={self.large_file_threshold}"
            f")"
        )
