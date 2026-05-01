"""
XML内容处理器
处理XML文档中的URL
"""
import re
from typing import Dict, Any
from urllib.parse import urlsplit


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
        self.attribute_url_pattern = re.compile(
            r'(\w+)\s*=\s*(["\'])(https?://[^"\']+)\2',
            re.IGNORECASE
        )

        self.special_protocols = re.compile(
            r'^(javascript:|data:|blob:)',
            re.IGNORECASE
        )

        self.empty_url_pattern = re.compile(
            r'^\s*$'
        )

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
            config: 配置字典，包含以下可选配置：
                - urlRewrite.enabled: 是否启用URL重写
                - urlRewrite.skipDomains: 跳过的域名列表
                - urlRewrite.customRules: 自定义URL重写规则

        Returns:
            重写后的XML文本
        """
        url_rewrite_config = config.get('urlRewrite', {})
        
        if not url_rewrite_config.get('enabled', True):
            return xml
        
        self.skip_domains = url_rewrite_config.get('skipDomains', [])
        self.custom_rules = url_rewrite_config.get('customRules', {})
        
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
        if self.special_protocols.match(url):
            return True

        if self.proxy_url_pattern.match(url):
            return True

        skip_domains = getattr(self, 'skip_domains', [])
        if skip_domains:
            try:
                parsed = urlsplit(url if url.startswith('http') else f'http://{url}')
                domain = parsed.netloc.lower()
                for skip_domain in skip_domains:
                    if domain == skip_domain.lower() or domain.endswith('.' + skip_domain.lower()):
                        return True
            except Exception:
                pass

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
        url = url.strip()

        if self.empty_url_pattern.match(url):
            return url

        if self.special_protocols.match(url):
            return url

        if not url.startswith(('http://', 'https://')):
            parsed_base = urlsplit(base_url)
            scheme = parsed_base.scheme
            netloc = parsed_base.netloc
            base_path = parsed_base.path

            if url.startswith('//'):
                url = f"{scheme}:{url}"
            elif url.startswith('/'):
                url = f"{scheme}://{netloc}{url}"
            else:
                if base_path and not base_path.endswith('/'):
                    base_path = base_path.rsplit('/', 1)[0] + '/'
                if not base_path:
                    base_path = '/'
                while url.startswith('./'):
                    url = url[2:]
                while url.startswith('../'):
                    if base_path != '/':
                        base_path = base_path.rsplit('/', 2)[0] + '/'
                    url = url[3:]
                url = f"{scheme}://{netloc}{base_path}{url}"

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
