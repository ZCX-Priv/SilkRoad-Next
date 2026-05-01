"""
Location响应头处理器
处理HTTP重定向Location头中的URL
"""
import re
from typing import Dict, Any
from urllib.parse import urlsplit


class LocationHandler:
    """
    Location响应头处理器
    负责重写HTTP重定向Location头中的URL
    """

    def __init__(self):
        """初始化Location处理器，预编译所有正则表达式"""
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """
        预编译所有正则表达式，提升性能
        """
        # 特殊协议模式（这些协议的URL不应被重写）
        self.special_protocols = re.compile(
            r'^(javascript:|data:|blob:|mailto:|tel:)',
            re.IGNORECASE
        )

        # 空URL或仅空白字符
        self.empty_url_pattern = re.compile(
            r'^\s*$'
        )

        # 已经是代理URL的模式（避免重复处理）
        self.proxy_url_pattern = re.compile(
            r'^\/[^\/]+\/',
            re.IGNORECASE
        )

    def rewrite(self, location: str, base_url: str) -> str:
        """
        重写Location头中的URL

        Args:
            location: Location头的值
            base_url: 基础URL（原始请求的URL）

        Returns:
            重写后的Location URL
        """
        location = location.strip()

        if self.empty_url_pattern.match(location):
            return location

        if self.special_protocols.match(location):
            return location

        if not location.startswith(('http://', 'https://')):
            parsed_base = urlsplit(base_url)
            scheme = parsed_base.scheme
            netloc = parsed_base.netloc
            base_path = parsed_base.path

            if location.startswith('//'):
                location = f"{scheme}:{location}"
            elif location.startswith('/'):
                location = f"{scheme}://{netloc}{location}"
            else:
                if base_path and not base_path.endswith('/'):
                    base_path = base_path.rsplit('/', 1)[0] + '/'
                if not base_path:
                    base_path = '/'
                while location.startswith('./'):
                    location = location[2:]
                while location.startswith('../'):
                    if base_path != '/':
                        base_path = base_path.rsplit('/', 2)[0] + '/'
                    location = location[3:]
                location = f"{scheme}://{netloc}{base_path}{location}"

        return self._to_proxy_url(location)

    def _to_proxy_url(self, target_url: str) -> str:
        """
        将目标URL转换为代理URL格式

        Args:
            target_url: 目标URL

        Returns:
            代理URL格式: /domain/path?query#fragment
        """
        try:
            parsed = urlsplit(target_url)

            # 构建代理路径
            # 格式: /domain/path?query#fragment
            proxy_path = f"/{parsed.netloc}{parsed.path}"

            if parsed.query:
                proxy_path += f"?{parsed.query}"

            if parsed.fragment:
                proxy_path += f"#{parsed.fragment}"

            return proxy_path

        except Exception:
            # 解析失败，返回原始URL
            return target_url

    def rewrite_content_location(self, content_location: str, base_url: str) -> str:
        """
        重写Content-Location头中的URL

        Args:
            content_location: Content-Location头的值
            base_url: 基础URL

        Returns:
            重写后的Content-Location URL
        """
        # Content-Location的处理与Location类似
        return self.rewrite(content_location, base_url)

    def rewrite_refresh_header(self, refresh: str, base_url: str) -> str:
        """
        重写Refresh头中的URL
        格式: "5; url=http://example.com/"

        Args:
            refresh: Refresh头的值
            base_url: 基础URL

        Returns:
            重写后的Refresh头值
        """
        # 提取URL部分
        url_pattern = re.compile(
            r'url\s*=\s*([^;\s]+)',
            re.IGNORECASE
        )

        def replace_url(match):
            """替换URL部分"""
            url = match.group(1)

            # 去除可能的引号
            url = url.strip('"\'')

            # 重写URL
            rewritten_url = self.rewrite(url, base_url)

            return f'url={rewritten_url}'

        return url_pattern.sub(replace_url, refresh)
