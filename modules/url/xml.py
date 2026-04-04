"""
XML内容处理器
处理XML文档中的URL
"""
import re
from typing import Dict, Any
from urllib.parse import urlparse, urljoin


class XMLHandler:
    """
    XML内容处理器
    负责重写XML文档中的URL
    """

    def __init__(self):
        """初始化XML处理器，预编译所有正则表达式"""
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """
        预编译所有正则表达式，提升性能
        """
        # XML属性中的URL模式
        # 匹配: attr="http://..." 或 attr='http://...'
        self.attribute_url_pattern = re.compile(
            r'(\w+)\s*=\s*(["\'])(https?://[^"\']+)\2',
            re.IGNORECASE
        )

        # XML命名空间声明中的URL（通常不应重写）
        self.namespace_pattern = re.compile(
            r'(xmlns(?::\w+)?)\s*=\s*(["\'])([^"\']+)\2',
            re.IGNORECASE
        )

        # 特殊协议模式（这些协议的URL不应被重写）
        self.special_protocols = re.compile(
            r'^(javascript:|data:|blob:)',
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

    async def rewrite(self, xml: str, base_url: str, config: Dict[str, Any]) -> str:
        """
        重写XML中的URL

        Args:
            xml: XML文本内容
            base_url: 基础URL，用于补全相对URL
            config: 配置字典

        Returns:
            重写后的XML文本
        """
        # 1. 处理属性中的URL
        xml = await self._rewrite_attribute_urls(xml, base_url)

        return xml

    async def _rewrite_attribute_urls(self, xml: str, base_url: str) -> str:
        """
        重写XML属性中的URL

        Args:
            xml: XML文本
            base_url: 基础URL

        Returns:
            重写后的XML
        """

        def replace_url(match):
            """替换属性中的URL"""
            attr_name = match.group(1)
            quote = match.group(2)
            url = match.group(3)

            # 跳过命名空间声明
            if attr_name.lower().startswith('xmlns'):
                return match.group(0)

            # 检查是否应该跳过
            if self._should_skip_url(url):
                return match.group(0)

            # 重写URL
            rewritten_url = self._rewrite_single_url(url, base_url)
            return f'{attr_name}={quote}{rewritten_url}{quote}'

        return self.attribute_url_pattern.sub(replace_url, xml)

    def _should_skip_url(self, url: str) -> bool:
        """
        判断是否应该跳过URL重写

        Args:
            url: URL字符串

        Returns:
            True表示跳过，False表示需要重写
        """
        # 跳过特殊协议
        if self.special_protocols.match(url):
            return True

        # 跳过已经是代理URL的
        if self.proxy_url_pattern.match(url):
            return True

        return False

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

        # 4. 补全相对URL（如果需要）
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
