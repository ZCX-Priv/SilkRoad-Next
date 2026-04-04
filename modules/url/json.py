"""
JSON内容处理器
处理JSON数据中的URL字符串
"""
import re
import json
from typing import Dict, Any, Union
from urllib.parse import urlparse


class JSONHandler:
    """
    JSON内容处理器
    负责重写JSON数据中的URL字符串
    """

    def __init__(self):
        """初始化JSON处理器，预编译所有正则表达式"""
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """
        预编译所有正则表达式，提升性能
        """
        # JSON字符串中的URL模式
        # 匹配: "key": "http://..." 或 "http://..."
        self.url_string_pattern = re.compile(
            r'"([^"]*)"\s*:\s*"((https?:)?//[^"]+)"',
            re.IGNORECASE
        )

        # 数组中的URL模式
        self.url_array_pattern = re.compile(
            r'"((https?:)?//[^"]+)"',
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

        # URL键名模式（常见的URL字段名）
        self.url_key_pattern = re.compile(
            r'^(url|link|href|src|source|image|img|icon|logo|thumbnail|avatar|'
            r'video|audio|media|file|download|redirect|callback|api|endpoint|'
            r'uri|location|next|previous|back|forward)$',
            re.IGNORECASE
        )

    async def rewrite(self, json_str: str, base_url: str, config: Dict[str, Any]) -> str:
        """
        重写JSON中的URL

        采用两种策略：
        1. 基于正则的快速处理（适用于简单JSON）
        2. 基于AST的深度处理（适用于复杂JSON）

        Args:
            json_str: JSON文本内容
            base_url: 基础URL，用于补全相对URL
            config: 配置字典

        Returns:
            重写后的JSON文本
        """
        try:
            # 尝试解析JSON并进行深度处理
            data = json.loads(json_str)
            rewritten_data = await self._rewrite_json_object(data, base_url)
            return json.dumps(rewritten_data, ensure_ascii=False, indent=None)

        except (json.JSONDecodeError, TypeError):
            # JSON解析失败，使用正则表达式处理
            return await self._rewrite_with_regex(json_str, base_url)

    async def _rewrite_json_object(
        self,
        data: Union[dict, list, str, int, float, bool, None],
        base_url: str
    ) -> Union[dict, list, str, int, float, bool, None]:
        """
        递归重写JSON对象中的URL

        Args:
            data: JSON数据（可能是任何类型）
            base_url: 基础URL

        Returns:
            重写后的数据
        """
        if isinstance(data, dict):
            # 处理字典
            result = {}
            for key, value in data.items():
                # 如果值是字符串且键名暗示是URL
                if isinstance(value, str) and self._is_url_key(key):
                    result[key] = self._rewrite_single_url(value, base_url)
                else:
                    result[key] = await self._rewrite_json_object(value, base_url)
            return result

        elif isinstance(data, list):
            # 处理数组
            return [await self._rewrite_json_object(item, base_url) for item in data]

        elif isinstance(data, str):
            # 处理字符串
            # 检查是否是URL
            if self._looks_like_url(data):
                return self._rewrite_single_url(data, base_url)
            return data

        else:
            # 其他类型直接返回
            return data

    async def _rewrite_with_regex(self, json_str: str, base_url: str) -> str:
        """
        使用正则表达式重写JSON中的URL

        Args:
            json_str: JSON文本
            base_url: 基础URL

        Returns:
            重写后的JSON文本
        """

        def replace_key_value(match):
            """替换键值对中的URL"""
            key = match.group(1)
            url = match.group(2)
            protocol = match.group(3)  # 可能是 None, 'http:', 'https:'

            # 检查是否应该跳过
            if self._should_skip_url(url):
                return match.group(0)

            # 如果是协议相对URL，补全协议
            if protocol is None or protocol == '':
                parsed_base = urlparse(base_url)
                url = f"{parsed_base.scheme}:{url}"

            # 重写URL
            rewritten_url = self._rewrite_single_url(url, base_url)
            return f'"{key}": "{rewritten_url}"'

        def replace_array_item(match):
            """替换数组中的URL"""
            url = match.group(1)
            protocol = match.group(2)

            # 检查是否应该跳过
            if self._should_skip_url(url):
                return match.group(0)

            # 如果是协议相对URL，补全协议
            if protocol is None or protocol == '':
                parsed_base = urlparse(base_url)
                url = f"{parsed_base.scheme}:{url}"

            # 重写URL
            rewritten_url = self._rewrite_single_url(url, base_url)
            return f'"{rewritten_url}"'

        # 先处理键值对
        json_str = self.url_string_pattern.sub(replace_key_value, json_str)

        # 再处理数组中的URL（避免重复处理）
        # 这里需要更精确的模式来避免处理已经处理过的

        return json_str

    def _is_url_key(self, key: str) -> bool:
        """
        判断键名是否暗示值是URL

        Args:
            key: 键名

        Returns:
            True表示可能是URL键，False表示不是
        """
        return bool(self.url_key_pattern.match(key))

    def _looks_like_url(self, value: str) -> bool:
        """
        判断字符串是否看起来像URL

        Args:
            value: 字符串值

        Returns:
            True表示可能是URL，False表示不是
        """
        # 检查是否以http://或https://开头
        if value.startswith(('http://', 'https://')):
            return True

        # 检查是否是协议相对URL
        if value.startswith('//') and '/' in value[2:]:
            return True

        # 检查是否包含常见URL特征
        url_indicators = [
            '.com', '.org', '.net', '.edu', '.gov',
            '.jpg', '.png', '.gif', '.svg', '.css', '.js',
            '/api/', '/v1/', '/v2/', '/static/', '/assets/',
            '?', '=', '&'
        ]

        return any(indicator in value.lower() for indicator in url_indicators)

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
        url = url.strip()

        if self.empty_url_pattern.match(url):
            return url

        if self.special_protocols.match(url):
            return url

        if not url.startswith(('http://', 'https://')):
            parsed_base = urlparse(base_url)
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
