"""
URL处理入口模块
负责协调各种内容类型的URL重写处理
"""
import re
import chardet
from typing import Optional, Dict, Any
from urllib.parse import urlparse

from .html import HTMLHandler
from .css import CSSHandler
from .js import JSHandler
from .xml import XMLHandler
from .json import JSONHandler
from .location import LocationHandler


class URLHandler:
    """
    URL处理入口类
    负责根据内容类型选择合适的处理器进行URL重写
    """

    def __init__(self, config: Dict[str, Any], logger):
        """
        初始化URL处理器

        Args:
            config: 配置字典
            logger: 日志记录器实例
        """
        self.config = config
        self.logger = logger

        # 初始化各种内容类型的处理器
        self.handlers = {
            'text/html': HTMLHandler(),
            'text/css': CSSHandler(),
            'application/javascript': JSHandler(),
            'application/x-javascript': JSHandler(),
            'text/javascript': JSHandler(),
            'application/xml': XMLHandler(),
            'text/xml': XMLHandler(),
            'application/json': JSONHandler(),
            'text/json': JSONHandler(),
        }

        # Location头处理器
        self.location_handler = LocationHandler()

        # 预编译正则表达式
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """
        预编译所有正则表达式，提升性能
        """
        # 绝对URL模式
        self.absolute_url_pattern = re.compile(
            r'https?://[^\s<>"\'\)]+',
            re.IGNORECASE
        )

        # 相对URL模式（用于检测）
        self.relative_url_pattern = re.compile(
            r'(href|src|action)=["\']([^"\']+)["\']',
            re.IGNORECASE
        )

        # Content-Type中的charset提取模式
        self.charset_pattern = re.compile(
            r'charset=["\']?([^"\'\s;]+)',
            re.IGNORECASE
        )

        # HTML meta标签中的charset提取模式
        self.meta_charset_pattern = re.compile(
            r'<meta[^>]+charset=["\']?([^"\'\s>]+)',
            re.IGNORECASE
        )

        # HTML meta标签中的http-equiv charset提取模式
        self.meta_http_equiv_pattern = re.compile(
            r'<meta[^>]+http-equiv=["\']?content-type["\']?[^>]+content=["\'][^"\']*charset=([^"\'\s;]+)',
            re.IGNORECASE
        )

    async def rewrite(
        self,
        content: bytes,
        content_type: str,
        base_url: str
    ) -> bytes:
        """
        重写内容中的URL

        Args:
            content: 原始内容（字节）
            content_type: 内容类型（如 text/html; charset=utf-8）
            base_url: 基础URL，用于补全相对URL

        Returns:
            重写后的内容（字节）
        """
        try:
            # 1. 检测字符集
            encoding = self._detect_encoding(content, content_type)

            # 2. 解码为字符串
            try:
                text = content.decode(encoding)
            except (UnicodeDecodeError, LookupError) as e:
                self.logger.warning(f"解码失败，尝试其他编码: {e}")
                # 尝试常见编码
                text = self._try_decode_with_fallback(content)

            # 3. 获取对应的处理器
            handler = self._get_handler(content_type)
            if not handler:
                # 没有匹配的处理器，返回原始内容
                self.logger.debug(f"无处理器匹配内容类型: {content_type}")
                return content

            # 4. 执行URL重写
            rewritten_text = await handler.rewrite(text, base_url, self.config)

            # 5. 重新编码
            return rewritten_text.encode(encoding)

        except Exception as e:
            self.logger.error(f"URL重写失败: {e}")
            # 发生错误时返回原始内容
            return content

    def rewrite_location_header(self, location: str, base_url: str) -> str:
        """
        重写Location响应头中的URL

        Args:
            location: Location头的值
            base_url: 基础URL

        Returns:
            重写后的Location URL
        """
        return self.location_handler.rewrite(location, base_url)

    def _detect_encoding(self, content: bytes, content_type: str) -> str:
        """
        检测内容的字符编码

        Args:
            content: 内容字节
            content_type: Content-Type头

        Returns:
            检测到的编码名称
        """
        # 1. 优先从Content-Type中提取
        if content_type:
            charset_match = self.charset_pattern.search(content_type)
            if charset_match:
                charset = charset_match.group(1).strip()
                # 验证编码是否有效
                try:
                    content.decode(charset)
                    return charset
                except (UnicodeDecodeError, LookupError):
                    self.logger.warning(f"Content-Type声明的编码无效: {charset}")

        # 2. 对于HTML内容，检查meta标签
        if 'html' in content_type.lower():
            try:
                # 先用ASCII解码以查找meta标签
                ascii_text = content.decode('ascii', errors='ignore')

                # 检查 <meta charset="...">
                meta_match = self.meta_charset_pattern.search(ascii_text)
                if meta_match:
                    charset = meta_match.group(1)
                    try:
                        content.decode(charset)
                        return charset
                    except (UnicodeDecodeError, LookupError):
                        pass

                # 检查 <meta http-equiv="Content-Type" content="...charset=...">
                http_equiv_match = self.meta_http_equiv_pattern.search(ascii_text)
                if http_equiv_match:
                    charset = http_equiv_match.group(1)
                    try:
                        content.decode(charset)
                        return charset
                    except (UnicodeDecodeError, LookupError):
                        pass
            except Exception as e:
                self.logger.debug(f"解析HTML meta标签失败: {e}")

        # 3. 使用chardet自动检测
        try:
            detected = chardet.detect(content)
            if detected is not None:
                confidence = detected.get('confidence', 0)

                # 只有在置信度较高时才使用检测结果
                if confidence > 0.9:
                    encoding = detected.get('encoding', 'utf-8')
                    if encoding:
                        return encoding.lower()
        except Exception as e:
            self.logger.debug(f"chardet检测失败: {e}")

        # 4. 默认使用UTF-8
        return 'utf-8'

    def _try_decode_with_fallback(self, content: bytes) -> str:
        """
        尝试使用多种编码解码内容

        Args:
            content: 内容字节

        Returns:
            解码后的文本
        """
        # 常见编码列表（按优先级排序）
        encodings_to_try = [
            'utf-8',
            'gbk',
            'gb2312',
            'gb18030',
            'big5',
            'shift-jis',
            'euc-jp',
            'euc-kr',
            'iso-8859-1',
            'windows-1252',
        ]

        for encoding in encodings_to_try:
            try:
                return content.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue

        # 最后使用replace模式解码
        return content.decode('utf-8', errors='replace')

    def _get_handler(self, content_type: str):
        """
        根据内容类型获取对应的处理器

        Args:
            content_type: 内容类型字符串

        Returns:
            对应的处理器实例，如果没有匹配则返回None
        """
        if not content_type:
            return None

        # 标准化content_type（移除参数部分）
        content_type_lower = content_type.lower()

        # 查找匹配的处理器
        for ct, handler in self.handlers.items():
            if ct in content_type_lower:
                return handler

        return None
