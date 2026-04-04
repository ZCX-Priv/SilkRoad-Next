"""
Cookie处理器
实现按目标域名隔离Cookie的机制
"""
import re
from typing import Optional
from urllib.parse import urlparse


class CookieHandler:
    """
    Cookie处理器
    
    负责重写Set-Cookie响应头和过滤请求Cookie，
    实现不同网站的Cookie相互隔离。
    """

    def __init__(self):
        """初始化Cookie处理器，预编译正则表达式"""
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """预编译正则表达式以提升性能"""
        self.domain_pattern = re.compile(
            r';\s*Domain\s*=\s*[^;]+',
            re.IGNORECASE
        )
        
        self.path_pattern = re.compile(
            r';\s*Path\s*=\s*([^;]+)',
            re.IGNORECASE
        )
        
        self.cookie_name_pattern = re.compile(
            r'^([^=]+)=.*$'
        )

    def rewrite_set_cookie(
        self,
        set_cookie: str,
        target_domain: str
    ) -> str:
        """
        重写Set-Cookie响应头
        
        修改Path属性，添加目标域名前缀，实现Cookie隔离。
        移除Domain属性，让Cookie对代理服务器域名有效。
        
        Args:
            set_cookie: 原始Set-Cookie头的值
            target_domain: 目标域名（如 example.com）
            
        Returns:
            重写后的Set-Cookie值
        """
        if not set_cookie or not target_domain:
            return set_cookie
        
        set_cookie = self.domain_pattern.sub('', set_cookie)
        
        path_match = self.path_pattern.search(set_cookie)
        
        if path_match:
            original_path = path_match.group(1).strip()
            if original_path.startswith('/'):
                original_path = original_path[1:]
            
            new_path = f'/{target_domain}/{original_path}'
            new_path = new_path.rstrip('/')
            if not new_path.endswith('/'):
                new_path += '/'
            
            set_cookie = self.path_pattern.sub(
                f'; Path={new_path}',
                set_cookie
            )
        else:
            set_cookie = f'{set_cookie}; Path=/{target_domain}/'
        
        return set_cookie

    def filter_request_cookies(
        self,
        cookie_header: str,
        target_domain: str
    ) -> Optional[str]:
        """
        过滤请求Cookie头
        
        浏览器会根据Cookie的Path属性自动过滤Cookie：
        - Path=/example.com/ 的Cookie只在访问 /example.com/* 时发送
        - Path=/ 的Cookie会在所有请求时发送
        
        此方法主要用于清理和格式化Cookie头。
        
        Args:
            cookie_header: 原始Cookie头的值
            target_domain: 目标域名（如 example.com）
            
        Returns:
            清理后的Cookie值，如果没有有效Cookie则返回None
        """
        if not cookie_header:
            return None
        
        if not target_domain:
            return cookie_header
        
        cookies = []
        
        for cookie in cookie_header.split(';'):
            cookie = cookie.strip()
            if not cookie:
                continue
            
            if '=' in cookie:
                cookies.append(cookie)
        
        if not cookies:
            return None
        
        return '; '.join(cookies)

    def extract_domain_from_url(self, url: str) -> Optional[str]:
        """
        从URL中提取域名
        
        Args:
            url: 完整URL
            
        Returns:
            域名（如 example.com）
        """
        if not url:
            return None
        
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            
            if ':' in domain:
                domain = domain.split(':')[0]
            
            return domain
        except Exception:
            return None
