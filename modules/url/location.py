"""
Location响应头处理器
处理HTTP重定向Location头中的URL
"""
import re
from typing import Dict, Any
from urllib.parse import urlparse, urljoin


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
        # 1. 去除首尾空白
        location = location.strip()

        # 2. 检查空URL
        if self.empty_url_pattern.match(location):
            return location

        # 3. 跳过特殊协议
        if self.special_protocols.match(location):
            return location

        # 4. 补全相对URL
        if not location.startswith(('http://', 'https://')):
            # 处理协议相对URL (//example.com/path)
            if location.startswith('//'):
                # 使用基础URL的协议
                parsed_base = urlparse(base_url)
                location = f"{parsed_base.scheme}:{location}"
            else:
                # 相对路径，使用urljoin补全
                location = urljoin(base_url, location)

        # 5. 转换为代理URL格式
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
            parsed = urlparse(target_url)

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

    def rewrite_set_cookie_domain(
        self,
        set_cookie: str,
        original_domain: str,
        proxy_domain: str
    ) -> str:
        """
        重写Set-Cookie头中的Domain属性

        Args:
            set_cookie: Set-Cookie头的值
            original_domain: 原始域名
            proxy_domain: 代理服务器域名

        Returns:
            重写后的Set-Cookie值
        """
        # 移除或修改Domain属性
        # Domain=example.com -> Domain=proxy.com
        # 或者直接移除Domain属性（让cookie对当前域名有效）

        # 简单策略：移除Domain属性
        domain_pattern = re.compile(
            r';\s*Domain=[^;]+',
            re.IGNORECASE
        )

        return domain_pattern.sub('', set_cookie)

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
