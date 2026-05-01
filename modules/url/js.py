"""
JavaScript内容处理器
处理JavaScript代码中的URL字符串
"""
import re
from typing import Dict, Any
from urllib.parse import urlsplit


class JSHandler:
    """
    JavaScript内容处理器
    负责重写JavaScript代码中的URL字符串
    """

    def __init__(self):
        """初始化JavaScript处理器，预编译所有正则表达式"""
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """
        预编译所有正则表达式，提升性能
        """
        # 字符串中的URL模式
        # 匹配单引号或双引号中的http/https URL
        self.string_url_pattern = re.compile(
            r'(["\'])(https?://[^"\']+)\1',
            re.IGNORECASE
        )

        # 模板字符串中的URL模式
        # 匹配反引号中的http/https URL
        self.template_url_pattern = re.compile(
            r'`(https?://[^`]+)`',
            re.IGNORECASE
        )

        # 相对URL模式（在字符串中）
        # 匹配看起来像路径的字符串: "/path", "./path", "../path"
        self.relative_url_pattern = re.compile(
            r'(["\'])((?:\.\.\/|\.\/|\/)[^"\']+\.(?:js|css|png|jpg|jpeg|gif|svg|woff|woff2|ttf|eot|json|html|php|asp|aspx|jsp)(?:\?[^"\']*)?)\1',
            re.IGNORECASE
        )

        # API端点模式
        # 匹配 "/api/...", "/v1/...", 等常见的API路径
        self.api_endpoint_pattern = re.compile(
            r'(["\'])((?:\/api\/|\/v\d+\/|\/rest\/)[^"\']*)\1',
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

    async def rewrite(self, js: str, base_url: str, config: Dict[str, Any]) -> str:
        """
        重写JavaScript中的URL

        注意：JavaScript处理相对复杂，因为：
        1. URL可能动态生成
        2. 字符串拼接
        3. 模板字符串
        4. 注释中的URL

        这里采用保守策略，只处理明确的字符串字面量中的URL

        Args:
            js: JavaScript代码文本
            base_url: 基础URL，用于补全相对URL
            config: 配置字典，包含以下可选配置：
                - urlRewrite.enabled: 是否启用URL重写
                - urlRewrite.skipDomains: 跳过的域名列表
                - urlRewrite.customRules: 自定义URL重写规则

        Returns:
            重写后的JavaScript代码
        """
        url_rewrite_config = config.get('urlRewrite', {})
        
        if not url_rewrite_config.get('enabled', True):
            return js
        
        self.skip_domains = url_rewrite_config.get('skipDomains', [])
        self.custom_rules = url_rewrite_config.get('customRules', {})
        
        # 1. 处理字符串中的绝对URL
        js = await self._rewrite_absolute_urls(js, base_url)

        # 2. 处理模板字符串中的URL
        js = await self._rewrite_template_urls(js, base_url)

        # 3. 处理相对URL（资源文件）
        js = await self._rewrite_relative_urls(js, base_url)

        # 4. 处理API端点
        js = await self._rewrite_api_endpoints(js, base_url)

        return js

    async def _rewrite_absolute_urls(self, js: str, base_url: str) -> str:
        """
        重写字符串中的绝对URL

        Args:
            js: JavaScript代码
            base_url: 基础URL

        Returns:
            重写后的代码
        """

        def replace_url(match):
            """替换字符串中的URL"""
            quote = match.group(1)
            url = match.group(2)

            # 检查是否应该跳过
            if self._should_skip_url(url):
                return match.group(0)

            # 重写URL
            rewritten_url = self._rewrite_single_url(url, base_url)
            return f'{quote}{rewritten_url}{quote}'

        return self.string_url_pattern.sub(replace_url, js)

    async def _rewrite_template_urls(self, js: str, base_url: str) -> str:
        """
        重写模板字符串中的URL

        Args:
            js: JavaScript代码
            base_url: 基础URL

        Returns:
            重写后的代码
        """

        def replace_url(match):
            """替换模板字符串中的URL"""
            url = match.group(1)

            # 检查是否应该跳过
            if self._should_skip_url(url):
                return match.group(0)

            # 重写URL
            rewritten_url = self._rewrite_single_url(url, base_url)
            return f'`{rewritten_url}`'

        return self.template_url_pattern.sub(replace_url, js)

    async def _rewrite_relative_urls(self, js: str, base_url: str) -> str:
        """
        重写相对URL（资源文件路径）

        Args:
            js: JavaScript代码
            base_url: 基础URL

        Returns:
            重写后的代码
        """

        def replace_url(match):
            """替换相对URL"""
            quote = match.group(1)
            url = match.group(2)

            # 检查是否已经是代理URL
            if self.proxy_url_pattern.match(url):
                return match.group(0)

            # 重写URL
            rewritten_url = self._rewrite_single_url(url, base_url)
            return f'{quote}{rewritten_url}{quote}'

        return self.relative_url_pattern.sub(replace_url, js)

    async def _rewrite_api_endpoints(self, js: str, base_url: str) -> str:
        """
        重写API端点路径

        Args:
            js: JavaScript代码
            base_url: 基础URL

        Returns:
            重写后的代码
        """

        def replace_url(match):
            """替换API端点"""
            quote = match.group(1)
            url = match.group(2)

            # 检查是否已经是代理URL
            if self.proxy_url_pattern.match(url):
                return match.group(0)

            # 重写URL
            rewritten_url = self._rewrite_single_url(url, base_url)
            return f'{quote}{rewritten_url}{quote}'

        return self.api_endpoint_pattern.sub(replace_url, js)

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

        # 检查跳过域名列表
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

        if self._should_skip_url(url):
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
