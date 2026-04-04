"""
CSS内容处理器
处理CSS文件中的URL，包括url()和@import语句
"""
import re
from typing import Dict, Any
from urllib.parse import urlparse, urljoin


class CSSHandler:
    """
    CSS内容处理器
    负责重写CSS中的所有URL引用
    """

    def __init__(self):
        """初始化CSS处理器，预编译所有正则表达式"""
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """
        预编译所有正则表达式，提升性能
        """
        # url() 模式
        # 匹配: url("..."), url('...'), url(...)
        self.url_pattern = re.compile(
            r'url\(\s*["\']?([^)"\'\s]+)["\']?\s*\)',
            re.IGNORECASE
        )

        # @import 模式
        # 匹配: @import "...", @import '...', @import url(...)
        self.import_pattern = re.compile(
            r'@import\s+(?:url\(\s*)?["\']?([^)"\'\s;]+)["\']?\s*\)?;',
            re.IGNORECASE
        )

        # 特殊协议模式（这些协议的URL不应被重写）
        self.special_protocols = re.compile(
            r'^(data:|blob:|about:)',
            re.IGNORECASE
        )

        # 空URL或仅空白字符
        self.empty_url_pattern = re.compile(
            r'^\s*$'
        )

    async def rewrite(self, css: str, base_url: str, config: Dict[str, Any]) -> str:
        """
        重写CSS中的所有URL

        Args:
            css: CSS文本内容
            base_url: 基础URL，用于补全相对URL
            config: 配置字典

        Returns:
            重写后的CSS文本
        """
        # 1. 处理@import语句
        css = await self._rewrite_imports(css, base_url)

        # 2. 处理url()中的URL
        css = await self._rewrite_urls(css, base_url)

        return css

    async def _rewrite_imports(self, css: str, base_url: str) -> str:
        """
        重写@import语句中的URL

        Args:
            css: CSS文本
            base_url: 基础URL

        Returns:
            重写后的CSS
        """

        def replace_import(match):
            """替换@import中的URL"""
            url = match.group(1)
            rewritten_url = self._rewrite_single_url(url, base_url)
            return f'@import url("{rewritten_url}");'

        return self.import_pattern.sub(replace_import, css)

    async def _rewrite_urls(self, css: str, base_url: str) -> str:
        """
        重写url()中的URL

        Args:
            css: CSS文本
            base_url: 基础URL

        Returns:
            重写后的CSS
        """

        def replace_url(match):
            """替换url()中的URL"""
            url = match.group(1)
            rewritten_url = self._rewrite_single_url(url, base_url)
            return f'url("{rewritten_url}")'

        return self.url_pattern.sub(replace_url, css)

    def _rewrite_single_url(self, url: str, base_url: str) -> str:
        """
        重写单个URL

        Args:
            url: 原始URL
            base_url: 基础URL

        Returns:
            重写后的URL
        """
        # 1. 去除首尾空白
        url = url.strip()

        # 2. 检查空URL
        if self.empty_url_pattern.match(url):
            return url

        # 3. 跳过特殊协议
        if self.special_protocols.match(url):
            return url

        # 4. 补全相对URL
        if not url.startswith(('http://', 'https://')):
            # 处理协议相对URL (//example.com/path)
            if url.startswith('//'):
                # 使用基础URL的协议
                parsed_base = urlparse(base_url)
                url = f"{parsed_base.scheme}:{url}"
            else:
                # 相对路径，使用urljoin补全
                url = urljoin(base_url, url)

        # 5. 转换为代理URL格式
        return self._to_proxy_url(url)

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
