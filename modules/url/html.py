"""
HTML内容处理器
处理HTML中的各种URL，包括标签属性、内联样式、srcset等
"""
import re
from typing import Dict, Any, List, Tuple
from urllib.parse import urlsplit


class HTMLHandler:
    """
    HTML内容处理器
    负责重写HTML中的所有URL引用
    """

    def __init__(self):
        """初始化HTML处理器，预编译所有正则表达式"""
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """
        预编译所有正则表达式，提升性能
        """
        # 标签属性URL模式列表
        # 每个元素是 (模式, 属性名) 的元组
        self.tag_patterns = [
            # <a href="...">
            (re.compile(r'(<a\s+[^>]*href=)(["\'])([^"\']+)(\2)', re.IGNORECASE), 'href'),
            # <img src="...">
            (re.compile(r'(<img\s+[^>]*src=)(["\'])([^"\']+)(\2)', re.IGNORECASE), 'src'),
            # <link href="...">
            (re.compile(r'(<link\s+[^>]*href=)(["\'])([^"\']+)(\2)', re.IGNORECASE), 'href'),
            # <script src="...">
            (re.compile(r'(<script\s+[^>]*src=)(["\'])([^"\']+)(\2)', re.IGNORECASE), 'src'),
            # <form action="...">
            (re.compile(r'(<form\s+[^>]*action=)(["\'])([^"\']+)(\2)', re.IGNORECASE), 'action'),
            # <iframe src="...">
            (re.compile(r'(<iframe\s+[^>]*src=)(["\'])([^"\']+)(\2)', re.IGNORECASE), 'src'),
            # <video src="...">
            (re.compile(r'(<video\s+[^>]*src=)(["\'])([^"\']+)(\2)', re.IGNORECASE), 'src'),
            # <audio src="...">
            (re.compile(r'(<audio\s+[^>]*src=)(["\'])([^"\']+)(\2)', re.IGNORECASE), 'src'),
            # <source src="...">
            (re.compile(r'(<source\s+[^>]*src=)(["\'])([^"\']+)(\2)', re.IGNORECASE), 'src'),
            # <embed src="...">
            (re.compile(r'(<embed\s+[^>]*src=)(["\'])([^"\']+)(\2)', re.IGNORECASE), 'src'),
            # <track src="...">
            (re.compile(r'(<track\s+[^>]*src=)(["\'])([^"\']+)(\2)', re.IGNORECASE), 'src'),
            # <object data="...">
            (re.compile(r'(<object\s+[^>]*data=)(["\'])([^"\']+)(\2)', re.IGNORECASE), 'data'),
            # <input src="..."> (type="image")
            (re.compile(r'(<input\s+[^>]*src=)(["\'])([^"\']+)(\2)', re.IGNORECASE), 'src'),
            # <img srcset="...">
            (re.compile(r'(<img\s+[^>]*srcset=)(["\'])([^"\']+)(\2)', re.IGNORECASE), 'srcset'),
            # <source srcset="...">
            (re.compile(r'(<source\s+[^>]*srcset=)(["\'])([^"\']+)(\2)', re.IGNORECASE), 'srcset'),
            # <poster src="...">
            (re.compile(r'(<video\s+[^>]*poster=)(["\'])([^"\']+)(\2)', re.IGNORECASE), 'poster'),
            # <background="..."> (已废弃但仍有使用)
            (re.compile(r'(background=)(["\'])([^"\']+)(\2)', re.IGNORECASE), 'background'),
        ]

        # 内联样式中的URL模式
        self.style_url_pattern = re.compile(
            r'url\(\s*["\']?([^)"\'\s]+)["\']?\s*\)',
            re.IGNORECASE
        )

        # style属性模式
        self.style_attr_pattern = re.compile(
            r'(style=)(["\'])([^"\']+)(\2)',
            re.IGNORECASE
        )

        # srcset属性模式（用于单独处理）
        self.srcset_pattern = re.compile(
            r'srcset\s*=\s*["\']([^"\']+)["\']',
            re.IGNORECASE
        )

        self.base_tag_pattern = re.compile(
            r'<base[^>]*>',
            re.IGNORECASE
        )

        self.csp_meta_pattern = re.compile(
            r'<meta[^>]*http-equiv=["\']?Content-Security-Policy[^>]*>',
            re.IGNORECASE
        )

        self.special_protocols = re.compile(
            r'^(javascript:|mailto:|tel:|data:|blob:|about:|#|ftp:)',
            re.IGNORECASE
        )

        # 空URL或仅空白字符
        self.empty_url_pattern = re.compile(
            r'^\s*$'
        )

    async def rewrite(self, html: str, base_url: str, config: Dict[str, Any]) -> str:
        """
        重写HTML中的所有URL

        Args:
            html: HTML文本内容
            base_url: 基础URL，用于补全相对URL
            config: 配置字典，包含以下可选配置：
                - urlRewrite.enabled: 是否启用URL重写
                - urlRewrite.skipDomains: 跳过的域名列表
                - urlRewrite.customRules: 自定义URL重写规则

        Returns:
            重写后的HTML文本
        """
        url_rewrite_config = config.get('urlRewrite', {})
        
        if not url_rewrite_config.get('enabled', True):
            return html
        
        self.skip_domains = url_rewrite_config.get('skipDomains', [])
        self.custom_rules = url_rewrite_config.get('customRules', {})
        
        html = await self._inject_csp_meta(html)
        
        for pattern, attr_name in self.tag_patterns:
            if attr_name == 'srcset':
                html = await self._rewrite_srcset_attr(html, pattern, base_url)
            else:
                html = await self._rewrite_tag_attr(html, pattern, base_url)

        html = await self._rewrite_style_urls(html, base_url)

        html = await self._rewrite_style_tag_urls(html, base_url)

        html = await self._handle_base_tag(html)

        return html

    async def _rewrite_style_tag_urls(self, html: str, base_url: str) -> str:
        """
        重写 <style> 标签内的 URL

        处理 <style> 标签内的 url() 引用，如 @font-face 和 background-image

        Args:
            html: HTML文本
            base_url: 基础URL

        Returns:
            重写后的HTML
        """
        style_tag_pattern = re.compile(r'(<style[^>]*>)(.*?)(</style>)', re.IGNORECASE | re.DOTALL)

        def replace_style_tag(match):
            """替换 <style> 标签内的 URL"""
            opening_tag = match.group(1)
            style_content = match.group(2)
            closing_tag = match.group(3)

            rewritten_content = self._rewrite_style_content(style_content, base_url)

            return f"{opening_tag}{rewritten_content}{closing_tag}"

        return style_tag_pattern.sub(replace_style_tag, html)

    async def _inject_csp_meta(self, html: str) -> str:
        """
        移除原始CSP meta标签并注入宽松的CSP

        Args:
            html: HTML文本

        Returns:
            处理后的HTML
        """
        html = self.csp_meta_pattern.sub('', html)

        csp_meta = '<meta http-equiv="Content-Security-Policy" content="default-src * \'unsafe-inline\' \'unsafe-eval\' data: blob:; img-src * data: blob:; media-src * data: blob:; font-src * data:;">'

        if '<head>' in html:
            html = html.replace('<head>', f'<head>\n    {csp_meta}')
        elif '<HEAD>' in html:
            html = html.replace('<HEAD>', f'<HEAD>\n    {csp_meta}')
        elif '<html>' in html:
            html = html.replace('<html>', f'<html>\n<head>\n    {csp_meta}\n</head>')
        else:
            html = csp_meta + '\n' + html

        return html

    async def _rewrite_tag_attr(
        self,
        html: str,
        pattern: re.Pattern,
        base_url: str
    ) -> str:
        """
        重写标签属性中的URL

        Args:
            html: HTML文本
            pattern: 匹配的正则表达式
            base_url: 基础URL

        Returns:
            重写后的HTML
        """

        def replace_url(match):
            """替换匹配到的URL"""
            prefix = match.group(1)  # <tag attr="
            quote1 = match.group(2)  # 引号
            url = match.group(3)     # URL值
            quote2 = match.group(4)  # 引号

            # 重写URL
            rewritten_url = self._rewrite_single_url(url, base_url)

            return f"{prefix}{quote1}{rewritten_url}{quote2}"

        return pattern.sub(replace_url, html)

    async def _rewrite_srcset_attr(
        self,
        html: str,
        pattern: re.Pattern,
        base_url: str
    ) -> str:
        """
        重写srcset属性中的URL
        srcset格式: "image.jpg 1x, image@2x.jpg 2x" 或 "image.jpg 100w, image@2x.jpg 200w"

        Args:
            html: HTML文本
            pattern: 匹配的正则表达式
            base_url: 基础URL

        Returns:
            重写后的HTML
        """

        def replace_srcset(match):
            """替换srcset中的所有URL"""
            prefix = match.group(1)
            quote1 = match.group(2)
            srcset = match.group(3)
            quote2 = match.group(4)

            # 分割srcset中的每个条目
            entries = srcset.split(',')
            rewritten_entries = []

            for entry in entries:
                entry = entry.strip()
                if not entry:
                    continue

                # 分离URL和描述符
                # 格式: "url descriptor" 或 "url"
                parts = entry.split()
                if len(parts) >= 2:
                    url = parts[0]
                    descriptor = ' '.join(parts[1:])
                else:
                    url = parts[0] if parts else ''
                    descriptor = ''

                # 重写URL
                rewritten_url = self._rewrite_single_url(url, base_url)

                # 重新组合
                if descriptor:
                    rewritten_entries.append(f"{rewritten_url} {descriptor}")
                else:
                    rewritten_entries.append(rewritten_url)

            # 重新组合srcset
            new_srcset = ', '.join(rewritten_entries)
            return f"{prefix}{quote1}{new_srcset}{quote2}"

        return pattern.sub(replace_srcset, html)

    async def _rewrite_style_urls(self, html: str, base_url: str) -> str:
        """
        重写内联样式中的URL

        Args:
            html: HTML文本
            base_url: 基础URL

        Returns:
            重写后的HTML
        """

        def replace_style_attr(match):
            """替换style属性中的URL"""
            prefix = match.group(1)
            quote1 = match.group(2)
            style_content = match.group(3)
            quote2 = match.group(4)

            # 重写style内容中的URL
            rewritten_style = self._rewrite_style_content(style_content, base_url)

            return f"{prefix}{quote1}{rewritten_style}{quote2}"

        # 处理style属性
        html = self.style_attr_pattern.sub(replace_style_attr, html)

        return html

    def _rewrite_style_content(self, style: str, base_url: str) -> str:
        """
        重写CSS样式内容中的URL

        Args:
            style: CSS样式字符串
            base_url: 基础URL

        Returns:
            重写后的样式字符串
        """

        def replace_url(match):
            """替换url()中的URL"""
            url = match.group(1)
            rewritten_url = self._rewrite_single_url(url, base_url)
            return f'url("{rewritten_url}")'

        return self.style_url_pattern.sub(replace_url, style)

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

            if not parsed.netloc:
                self._skip_debug_log = getattr(self, '_skip_debug_log', False)
                return target_url

            proxy_path = f"/{parsed.netloc}{parsed.path}"

            if parsed.query:
                proxy_path += f"?{parsed.query}"

            if parsed.fragment:
                proxy_path += f"#{parsed.fragment}"

            return proxy_path

        except Exception:
            return target_url

    async def _handle_base_tag(self, html: str) -> str:
        """
        处理HTML中的base标签
        移除base标签，因为它会干扰相对URL的计算

        Args:
            html: HTML文本

        Returns:
            处理后的HTML
        """
        # 移除所有base标签
        return self.base_tag_pattern.sub('', html)
