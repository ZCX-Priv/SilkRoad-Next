"""
WAF 穿透模块

功能:
1. WAF 类型识别与指纹检测
2. 请求特征混淆
3. 反爬虫机制绕过
4. 智能请求调度
5. 自适应策略调整

版本: V5
"""

import asyncio
import json
import os
import pickle
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

# 尝试导入 execjs，如果不存在则设置为 None
try:
    import execjs
    EXECJS_AVAILABLE = True
except ImportError:
    execjs = None
    EXECJS_AVAILABLE = False

from loguru import logger


class WAFType(Enum):
    """
    WAF 类型枚举
    
    支持检测的主流 WAF 类型:
    - CLOUDFLARE: Cloudflare WAF
    - AKAMAI: Akamai Bot Manager
    - IMPERVA: Imperva (Incapsula) WAF
    - F5_BIGIP: F5 BIG-IP ASM
    - BARRACUDA: Barracuda WAF
    - MODSECURITY: ModSecurity WAF
    - GENERIC: 通用/未知 WAF
    """
    
    CLOUDFLARE = "cloudflare"
    AKAMAI = "akamai"
    IMPERVA = "imperva"
    F5_BIGIP = "f5_bigip"
    BARRACUDA = "barracuda"
    MODSECURITY = "modsecurity"
    GENERIC = "generic"


@dataclass
class WAFDetectionResult:
    """
    WAF 检测结果数据类
    
    Attributes:
        waf_type: 检测到的 WAF 类型
        confidence: 检测置信度 (0.0 - 1.0)
        detection_methods: 使用的检测方法列表
        blocked_indicators: 检测到的拦截指标列表
    """
    
    waf_type: WAFType
    confidence: float
    detection_methods: List[str] = field(default_factory=list)
    blocked_indicators: List[str] = field(default_factory=list)
    
    def __post_init__(self) -> None:
        """初始化后验证数据"""
        # 确保 confidence 在有效范围内
        self.confidence = max(0.0, min(1.0, self.confidence))
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "waf_type": self.waf_type.value,
            "confidence": self.confidence,
            "detection_methods": self.detection_methods,
            "blocked_indicators": self.blocked_indicators
        }


@dataclass
class EvasionStrategy:
    """
    绕过策略数据类
    
    定义 WAF 绕过策略的配置参数
    
    Attributes:
        name: 策略名称
        description: 策略描述
        priority: 优先级 (数字越小优先级越高)
        success_rate: 历史成功率 (0.0 - 1.0)
        required_headers: 策略所需的请求头
        request_delay: 请求延迟时间 (秒)
        retry_count: 重试次数
    """
    
    name: str
    description: str
    priority: int
    success_rate: float
    required_headers: Dict[str, str] = field(default_factory=dict)
    request_delay: float = 0.0
    retry_count: int = 3
    
    def __post_init__(self) -> None:
        """初始化后验证数据"""
        # 确保 success_rate 在有效范围内
        self.success_rate = max(0.0, min(1.0, self.success_rate))
        # 确保 request_delay 非负
        self.request_delay = max(0.0, self.request_delay)
        # 确保 retry_count 为正整数
        self.retry_count = max(1, self.retry_count)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "name": self.name,
            "description": self.description,
            "priority": self.priority,
            "success_rate": self.success_rate,
            "required_headers": self.required_headers,
            "request_delay": self.request_delay,
            "retry_count": self.retry_count
        }


class WAFPasser:
    """
    WAF 穿透核心模块
    
    功能:
    1. WAF 类型识别与指纹检测
    2. 请求特征混淆
    3. 反爬虫机制绕过
    4. 智能请求调度
    5. 自适应策略调整
    
    衔接关系:
    - 依赖 V1 的配置系统 (cfg.py) 和代理核心 (proxy.py)
    - 利用 V2 的连接池 (connectionpool.py) 和会话管理 (sessions.py)
    - 适配 V3 的流媒体处理 (stream/)
    - 配合 V4 的流量控制器 (controler.py)
    """
    
    def __init__(self, config_path: str = "databases/config.json") -> None:
        """
        初始化 WAF 穿透模块
        
        Args:
            config_path: 配置文件路径，默认为 "databases/config.json"
        """
        self.config_path = config_path
        self.config: Dict[str, Any] = self._load_config(config_path)
        self.waf_signatures: Dict[WAFType, Dict[str, Any]] = self._init_waf_signatures()
        self.evasion_strategies: List[EvasionStrategy] = self._init_evasion_strategies()
        
        # 请求历史记录: domain -> list of timestamps
        self.request_history: Dict[str, List[float]] = {}
        
        # 成功统计: domain -> {strategy_name: count}
        self.success_stats: Dict[str, Dict[str, int]] = {}
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """
        加载配置文件
        
        衔接 V1 cfg.py，读取 WAF 穿透相关配置
        
        Args:
            config_path: 配置文件路径
            
        Returns:
            配置字典，如果加载失败则返回默认配置
        """
        default_config: Dict[str, Any] = {
            "waf_evasion": {
                "enabled": True,
                "aggressive_mode": False
            }
        }
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config
        except FileNotFoundError:
            # 配置文件不存在，返回默认配置
            return default_config
        except json.JSONDecodeError:
            # JSON 解析错误，返回默认配置
            return default_config
        except Exception:
            # 其他异常，返回默认配置
            return default_config
    
    def _init_waf_signatures(self) -> Dict[WAFType, Dict[str, Any]]:
        """
        初始化 WAF 指纹库
        
        包含主流 WAF 的检测特征:
        - 响应头特征
        - 响应状态码
        - 页面内容模式
        - JavaScript 挑战标识
        
        Returns:
            WAF 指纹字典，键为 WAFType，值为特征配置
        """
        return {
            WAFType.CLOUDFLARE: {
                "headers": {
                    "Server": ["cloudflare"],
                    "CF-RAY": [r".+"],
                    "Set-Cookie": [r"__cfduid", r"cf_clearance"]
                },
                "response_codes": [403, 503],
                "page_patterns": [
                    r"cloudflare",
                    r"cf-browser-verification",
                    r"challenge-platform",
                    r"ray id:",
                    r"checking your browser"
                ],
                "js_challenge": True
            },
            WAFType.AKAMAI: {
                "headers": {
                    "Server": ["AkamaiGHost"],
                    "X-Akamai-Transformed": [r".+"]
                },
                "response_codes": [403],
                "page_patterns": [
                    r"access denied",
                    r"akamai",
                    r"reference #\d+\.\w+"
                ]
            },
            WAFType.IMPERVA: {
                "headers": {
                    "X-CDN": ["Incapsula"],
                    "Set-Cookie": [r"incap_ses_", r"visid_incap_"]
                },
                "response_codes": [403, 503],
                "page_patterns": [
                    r"incapsula incident id",
                    r"request blocked",
                    r"imperva"
                ]
            },
            WAFType.F5_BIGIP: {
                "headers": {
                    "Server": [r"BigIP"],
                    "Set-Cookie": [r"BigIPServer"]
                },
                "response_codes": [403],
                "page_patterns": [
                    r"bigip",
                    r"request rejected"
                ]
            },
            WAFType.BARRACUDA: {
                "headers": {
                    "Server": ["Barracuda"],
                    "Set-Cookie": [r"barra_counter"]
                },
                "response_codes": [403],
                "page_patterns": [
                    r"barracuda",
                    r"block reference"
                ]
            },
            WAFType.MODSECURITY: {
                "headers": {
                    "Server": [r".*mod_security.*", r".*ModSecurity.*"]
                },
                "response_codes": [403, 406],
                "page_patterns": [
                    r"mod_security",
                    r"modsecurity",
                    r"not acceptable",
                    r"anomaly score exceeded"
                ]
            },
            WAFType.GENERIC: {
                "headers": {},
                "response_codes": [403, 406, 429, 503],
                "page_patterns": [
                    r"access denied",
                    r"forbidden",
                    r"blocked",
                    r"security",
                    r"firewall",
                    r"rate limit",
                    r"too many requests"
                ]
            }
        }
    
    def _init_evasion_strategies(self) -> List[EvasionStrategy]:
        """
        初始化绕过策略库
        
        策略按优先级排序，包含:
        1. User-Agent 轮换伪装
        2. 请求头混淆与伪装
        3. Referer 伪造
        4. 请求速率控制
        5. Cookie 智能处理
        6. TLS 指纹随机化
        7. JavaScript 挑战求解
        8. 会话持久化
        
        Returns:
            绕过策略列表
        """
        return [
            EvasionStrategy(
                name="user_agent_rotation",
                description="User-Agent 轮换伪装",
                priority=1,
                success_rate=0.85,
                required_headers={},
                request_delay=0.0,
                retry_count=3
            ),
            EvasionStrategy(
                name="header_obfuscation",
                description="请求头混淆与伪装",
                priority=2,
                success_rate=0.75,
                required_headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
                    "Accept-Encoding": "gzip, deflate, br",
                    "DNT": "1",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1"
                },
                request_delay=0.0,
                retry_count=3
            ),
            EvasionStrategy(
                name="referer_spoofing",
                description="Referer 伪造",
                priority=3,
                success_rate=0.70,
                required_headers={},
                request_delay=0.5,
                retry_count=3
            ),
            EvasionStrategy(
                name="request_pacing",
                description="请求速率控制",
                priority=4,
                success_rate=0.90,
                required_headers={},
                request_delay=2.0,
                retry_count=3
            ),
            EvasionStrategy(
                name="cookie_handling",
                description="Cookie 智能处理",
                priority=5,
                success_rate=0.80,
                required_headers={},
                request_delay=0.0,
                retry_count=3
            ),
            EvasionStrategy(
                name="tls_fingerprint_randomization",
                description="TLS 指纹随机化",
                priority=6,
                success_rate=0.65,
                required_headers={},
                request_delay=0.0,
                retry_count=3
            ),
            EvasionStrategy(
                name="javascript_challenge_solver",
                description="JavaScript 挑战求解",
                priority=7,
                success_rate=0.95,
                required_headers={},
                request_delay=5.0,
                retry_count=3
            ),
            EvasionStrategy(
                name="session_persistence",
                description="会话持久化",
                priority=8,
                success_rate=0.85,
                required_headers={},
                request_delay=0.0,
                retry_count=3
            )
        ]
    
    def get_strategy_by_name(self, name: str) -> EvasionStrategy | None:
        """
        根据名称获取绕过策略
        
        Args:
            name: 策略名称
            
        Returns:
            匹配的策略对象，如果未找到则返回 None
        """
        for strategy in self.evasion_strategies:
            if strategy.name == name:
                return strategy
        return None
    
    def get_strategies_sorted_by_priority(self) -> List[EvasionStrategy]:
        """
        获取按优先级排序的策略列表
        
        Returns:
            按优先级升序排列的策略列表
        """
        return sorted(self.evasion_strategies, key=lambda s: s.priority)
    
    def get_strategies_sorted_by_success_rate(self) -> List[EvasionStrategy]:
        """
        获取按成功率排序的策略列表
        
        Returns:
            按成功率降序排列的策略列表
        """
        return sorted(self.evasion_strategies, key=lambda s: s.success_rate, reverse=True)
    
    def is_waf_evasion_enabled(self) -> bool:
        """
        检查 WAF 穿透功能是否启用
        
        Returns:
            如果启用则返回 True，否则返回 False
        """
        return self.config.get("waf_evasion", {}).get("enabled", False)
    
    def is_aggressive_mode(self) -> bool:
        """
        检查是否启用激进模式
        
        Returns:
            如果启用激进模式则返回 True，否则返回 False
        """
        return self.config.get("waf_evasion", {}).get("aggressive_mode", False)


class JavaScriptChallengeSolver:
    """
    JavaScript 挑战求解器
    
    主要用于解决 Cloudflare 等 WAF 的 JavaScript 挑战验证
    
    功能:
    1. 检测页面是否包含 JavaScript 挑战
    2. 提取挑战参数（jschl_vc、pass、action_url 等）
    3. 执行挑战 JavaScript 代码
    4. 异步求解挑战，支持超时控制
    """
    
    def __init__(self) -> None:
        """
        初始化 JavaScript 挑战求解器
        
        初始化 JavaScript 运行时和挑战模式匹配规则
        """
        self.js_runtime = self._init_js_runtime()
        self.challenge_patterns = {
            "cloudflare": {
                "challenge_form": re.compile(r'<form.*?action="([^"]*?__cf_chl_tk[^"]*?)".*?>', re.DOTALL),
                "challenge_script": re.compile(r'<script.*?>(.*?)</script>', re.DOTALL),
                "ray_id": re.compile(r'rayId:\s*["\']([^"\']+)["\']'),
                "challenge_platform": re.compile(r'challenge-platform'),
                "jschl_vc": re.compile(r'name="jschl_vc"\s*value="([^"]+)"'),
                "pass": re.compile(r'name="pass"\s*value="([^"]+)"'),
                "jschl_answer": re.compile(r'name="jschl_answer"')
            }
        }
    
    def _init_js_runtime(self):
        """
        初始化 JavaScript 运行时
        
        使用 execjs 库获取可用的 JavaScript 运行时环境
        
        Returns:
            execjs 运行时对象，如果 execjs 不可用则返回 None
        """
        if not EXECJS_AVAILABLE:
            logger.warning("execjs 库不可用，JavaScript 挑战求解功能将受限")
            return None
        
        try:
            runtime = execjs.get()
            logger.debug(f"JavaScript 运行时初始化成功: {runtime}")
            return runtime
        except Exception as e:
            logger.warning(f"JavaScript 运行时初始化失败: {e}")
            return None
    
    def detect_js_challenge(self, html_content: str) -> Optional[Dict[str, Any]]:
        """
        检测页面是否包含 JavaScript 挑战
        
        Args:
            html_content: HTML 页面内容
            
        Returns:
            挑战信息字典，包含以下字段:
            - waf_type: WAF 类型
            - action_url: 挑战表单提交地址
            - ray_id: Cloudflare Ray ID
            - jschl_vc: 挑战验证码
            - pass: 挑战通行证参数
            
            如果未检测到挑战则返回 None
        """
        for waf_name, patterns in self.challenge_patterns.items():
            if patterns["challenge_platform"].search(html_content):
                challenge_info: Dict[str, Any] = {"waf_type": waf_name}
                
                # 提取表单提交地址
                form_match = patterns["challenge_form"].search(html_content)
                if form_match:
                    challenge_info["action_url"] = form_match.group(1)
                
                # 提取 Ray ID
                ray_match = patterns["ray_id"].search(html_content)
                if ray_match:
                    challenge_info["ray_id"] = ray_match.group(1)
                
                # 提取 jschl_vc 参数
                jschl_vc_match = patterns["jschl_vc"].search(html_content)
                if jschl_vc_match:
                    challenge_info["jschl_vc"] = jschl_vc_match.group(1)
                
                # 提取 pass 参数
                pass_match = patterns["pass"].search(html_content)
                if pass_match:
                    challenge_info["pass"] = pass_match.group(1)
                
                logger.debug(f"检测到 {waf_name} JavaScript 挑战: {challenge_info}")
                return challenge_info
        
        return None
    
    def solve_cloudflare_challenge(
        self, 
        html_content: str, 
        target_domain: str
    ) -> Optional[str]:
        """
        求解 Cloudflare JavaScript 挑战
        
        Args:
            html_content: 包含挑战的 HTML 内容
            target_domain: 目标域名
            
        Returns:
            求解后的答案字符串，如果求解失败则返回 None
        """
        # 检测挑战
        challenge_info = self.detect_js_challenge(html_content)
        if not challenge_info:
            logger.warning("未检测到 Cloudflare 挑战")
            return None
        
        # 提取挑战脚本
        script_match = self.challenge_patterns["cloudflare"]["challenge_script"].search(html_content)
        if not script_match:
            logger.warning("未找到挑战脚本")
            return None
        
        script_content = script_match.group(1)
        
        try:
            answer = self._execute_challenge_js(script_content, target_domain)
            if answer is not None:
                logger.info(f"Cloudflare 挑战求解成功: {answer}")
                return str(answer)
            return None
        except Exception as e:
            logger.error(f"Cloudflare 挑战求解失败: {e}")
            return None
    
    def _execute_challenge_js(self, script_content: str, domain: str) -> Optional[float]:
        """
        执行挑战 JavaScript 代码
        
        Args:
            script_content: JavaScript 脚本内容
            domain: 目标域名
            
        Returns:
            求解结果（浮点数），如果执行失败则返回 None
        """
        if not self.js_runtime:
            logger.warning("JavaScript 运行时不可用，无法执行挑战代码")
            return None
        
        try:
            # 构建完整的 JavaScript 代码
            js_code = f"""
            var domain = '{domain}';
            var solve = function() {{
                {script_content}
                return result;
            }};
            solve();
            """
            
            result = self.js_runtime.eval(js_code)
            return float(result)
        except Exception as e:
            logger.error(f"JavaScript 执行失败: {e}")
            return None
    
    async def solve_challenge_async(
        self, 
        html_content: str, 
        target_domain: str,
        timeout: float = 10.0
    ) -> Optional[str]:
        """
        异步求解挑战
        
        使用异步执行器运行同步的挑战求解方法，支持超时控制
        
        Args:
            html_content: HTML 内容
            target_domain: 目标域名
            timeout: 超时时间（秒），默认 10 秒
            
        Returns:
            求解结果字符串，如果超时或失败则返回 None
        """
        loop = asyncio.get_event_loop()
        
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None, 
                    self.solve_cloudflare_challenge, 
                    html_content, 
                    target_domain
                ),
                timeout=timeout
            )
            return result
        except asyncio.TimeoutError:
            logger.warning(f"挑战求解超时（{timeout}秒）")
            return None
        except Exception as e:
            logger.error(f"异步挑战求解失败: {e}")
            return None


class RequestObfuscator:
    """
    请求特征混淆器
    
    功能:
    1. User-Agent 轮换伪装
    2. 请求头混淆与伪装
    3. Referer 伪造
    4. URL 混淆处理
    5. 为不同 WAF 类型添加特定请求头
    
    衔接关系:
    - 衔接 V1 的 UA 处理器 (ua.py)
    - 从 databases/ua.json 加载 UA 池
    """
    
    def __init__(self, waf_passer: WAFPasser) -> None:
        """
        初始化请求混淆器
        
        Args:
            waf_passer: WAFPasser 实例，用于获取 WAF 配置和策略
        """
        self.waf_passer = waf_passer
        self.ua_pool: List[str] = self._load_ua_pool()
        self.browser_profiles: Dict[str, Dict[str, str]] = self._init_browser_profiles()
    
    def _load_ua_pool(self) -> List[str]:
        """
        加载 UA 池 - 衔接 V1 ua.py
        
        从 databases/ua.json 加载 User-Agent 池，支持按浏览器类型分类。
        V1 已实现 UA 随机化处理，此处复用其数据源。
        
        Returns:
            UA 字符串列表，如果加载失败则返回默认 UA 列表
        """
        default_ua_pool: List[str] = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15"
        ]
        
        ua_file_path = "databases/ua.json"
        
        try:
            with open(ua_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # 支持两种格式：
                # 1. 按类别组织的格式 (chrome/firefox/safari/mobile)
                # 2. 包含 user_agents 字段的格式
                if isinstance(data, dict):
                    ua_list: List[str] = []
                    
                    # 检查是否为旧格式（包含 user_agents 字段）
                    if 'user_agents' in data:
                        return data.get('user_agents', default_ua_pool)
                    elif 'userAgents' in data:
                        return data.get('userAgents', default_ua_pool)
                    else:
                        # 新格式：直接按类别组织，合并所有类别
                        for category, uas in data.items():
                            if isinstance(uas, list):
                                ua_list.extend(uas)
                        
                        if ua_list:
                            return ua_list
                
                return default_ua_pool
                
        except FileNotFoundError:
            # UA 文件不存在，返回默认 UA 池
            return default_ua_pool
        except json.JSONDecodeError:
            # JSON 解析错误，返回默认 UA 池
            return default_ua_pool
        except Exception:
            # 其他异常，返回默认 UA 池
            return default_ua_pool
    
    def _init_browser_profiles(self) -> Dict[str, Dict[str, str]]:
        """
        初始化浏览器指纹配置
        
        为 Chrome、Firefox、Safari、Edge 四种主流浏览器配置完整的指纹信息，
        包括 User-Agent、Sec-CH-UA、Accept 等关键请求头。
        
        Returns:
            浏览器指纹配置字典，键为浏览器名称，值为请求头配置字典
        """
        return {
            "chrome": {
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "accept_language": "en-US,en;q=0.9",
                "accept_encoding": "gzip, deflate, br",
                "connection": "keep-alive",
                "upgrade_insecure_requests": "1"
            },
            "firefox": {
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "accept_language": "en-US,en;q=0.5",
                "accept_encoding": "gzip, deflate, br",
                "connection": "keep-alive",
                "upgrade_insecure_requests": "1"
            },
            "safari": {
                "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "accept_language": "en-US,en;q=0.9",
                "accept_encoding": "gzip, deflate",
                "connection": "keep-alive"
            },
            "edge": {
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
                "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Microsoft Edge";v="120"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
                "accept_language": "en-US,en;q=0.9",
                "accept_encoding": "gzip, deflate, br",
                "connection": "keep-alive"
            }
        }
    
    def obfuscate_headers(
        self,
        original_headers: Dict[str, str],
        target_url: str,
        waf_type: WAFType = WAFType.GENERIC
    ) -> Dict[str, str]:
        """
        混淆请求头
        
        根据目标 WAF 类型对请求头进行混淆处理，包括：
        1. 随机选择浏览器指纹
        2. 添加 WAF 特定请求头
        3. 设置 Host 和 Origin
        4. 随机添加伪造 Referer
        
        Args:
            original_headers: 原始请求头字典
            target_url: 目标 URL
            waf_type: WAF 类型，默认为 GENERIC
            
        Returns:
            混淆后的请求头字典
        """
        import random
        from urllib.parse import urlparse
        
        obfuscated_headers = original_headers.copy()
        
        # 随机选择浏览器指纹
        browser = random.choice(["chrome", "firefox", "safari", "edge"])
        profile = self.browser_profiles[browser]
        
        # 更新浏览器指纹请求头
        obfuscated_headers.update(profile)
        
        # 根据 WAF 类型添加特定请求头
        if waf_type == WAFType.CLOUDFLARE:
            obfuscated_headers.update(self._cloudflare_specific_headers(target_url))
        elif waf_type == WAFType.AKAMAI:
            obfuscated_headers.update(self._akamai_specific_headers(target_url))
        elif waf_type == WAFType.IMPERVA:
            obfuscated_headers.update(self._imperva_specific_headers(target_url))
        
        # 设置 Host 和 Origin
        parsed_url = urlparse(target_url)
        obfuscated_headers["Host"] = parsed_url.netloc
        obfuscated_headers["Origin"] = f"{parsed_url.scheme}://{parsed_url.netloc}"
        
        # 70% 概率添加伪造 Referer
        if random.random() > 0.7:
            referer = self._generate_fake_referer(target_url)
            obfuscated_headers["Referer"] = referer
        
        return obfuscated_headers
    
    def _cloudflare_specific_headers(self, target_url: str) -> Dict[str, str]:
        """
        Cloudflare 特定请求头
        
        生成用于绕过 Cloudflare WAF 的特定请求头，包括：
        - CF-Connecting-IP: 伪造的客户端 IP
        - X-Forwarded-For: 伪造的转发 IP
        - X-Real-IP: 伪造的真实 IP
        - CF-IPCountry: 随机国家代码
        - CF-RAY: 伪造的 Cloudflare Ray ID
        
        Args:
            target_url: 目标 URL
            
        Returns:
            Cloudflare 特定请求头字典
        """
        import random
        
        return {
            "CF-Connecting-IP": self._generate_random_ip(),
            "X-Forwarded-For": self._generate_random_ip(),
            "X-Real-IP": self._generate_random_ip(),
            "CF-IPCountry": random.choice(["US", "GB", "DE", "FR", "JP", "AU"]),
            "CF-RAY": self._generate_cf_ray()
        }
    
    def _akamai_specific_headers(self, target_url: str) -> Dict[str, str]:
        """
        Akamai 特定请求头
        
        生成用于绕过 Akamai Bot Manager 的特定请求头。
        
        Args:
            target_url: 目标 URL
            
        Returns:
            Akamai 特定请求头字典
        """
        return {
            "X-Akamai-Transformed": "1 0 0",
            "Pragma": "akamai-x-get-cache-key",
            "X-Akamai-SR-HOP": "1"
        }
    
    def _imperva_specific_headers(self, target_url: str) -> Dict[str, str]:
        """
        Imperva 特定请求头
        
        生成用于绕过 Imperva (Incapsula) WAF 的特定请求头。
        
        Args:
            target_url: 目标 URL
            
        Returns:
            Imperva 特定请求头字典
        """
        return {
            "X-Forwarded-For": self._generate_random_ip(),
            "X-CDN": "Incapsula"
        }
    
    def _generate_random_ip(self) -> str:
        """
        生成随机 IP 地址
        
        生成一个随机的 IPv4 地址，避免使用保留地址段。
        
        Returns:
            随机 IP 地址字符串
        """
        import random
        
        return f"{random.randint(1, 223)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
    
    def _generate_cf_ray(self) -> str:
        """
        生成 Cloudflare Ray ID
        
        生成一个伪造的 Cloudflare Ray ID，格式为：
        {8位数字}-{数据中心代码}
        
        Returns:
            伪造的 Cloudflare Ray ID 字符串
        """
        import random
        
        data_centers = ["LAX", "SJC", "SEA", "ORD", "DFW", "IAD", "JFK", "LHR", "FRA", "NRT"]
        return f"{random.randint(100000000, 999999999)}-{random.choice(data_centers)}"
    
    def _generate_fake_referer(self, target_url: str) -> str:
        """
        生成伪造的 Referer
        
        基于目标 URL 生成一个伪造的 Referer，用于绕过 Referer 检测。
        
        Args:
            target_url: 目标 URL
            
        Returns:
            伪造的 Referer URL 字符串
        """
        import random
        from urllib.parse import urlparse
        
        parsed = urlparse(target_url)
        
        # 常见路径列表
        paths = [
            "/",
            "/index.html",
            "/search",
            "/home",
            "/page/1",
            f"/{random.choice(['news', 'blog', 'article', 'post'])}/{random.randint(1000, 9999)}"
        ]
        
        return f"{parsed.scheme}://{parsed.netloc}{random.choice(paths)}"
    
    def obfuscate_url(self, url: str) -> str:
        """
        URL 混淆处理
        
        对 URL 进行混淆处理，包括：
        1. 添加随机时间戳参数绕过缓存
        2. 添加随机数参数
        
        Args:
            url: 原始 URL
            
        Returns:
            混淆后的 URL 字符串
        """
        import random
        import time
        from urllib.parse import urlparse
        
        parsed = urlparse(url)
        
        # 生成随机参数
        random_param = f"_t={int(time.time() * 1000)}"
        random_param += f"&_r={random.randint(100000, 999999)}"
        
        # 合并查询参数
        if parsed.query:
            new_query = f"{parsed.query}&{random_param}"
        else:
            new_query = random_param
        
        # 重建 URL
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{new_query}"


class SessionPersistenceManager:
    """
    会话持久化管理器
    
    衔接 V2 sessions.py
    V2 已实现会话管理，此处扩展持久化功能
    
    功能:
    1. 会话数据持久化存储
    2. 会话有效期检查
    3. 过期会话自动清理
    4. 域名匹配 Cookie 提取
    """
    
    def __init__(self, storage_path: str = "databases/sessions") -> None:
        """
        初始化会话持久化管理器
        
        Args:
            storage_path: 会话存储目录路径，默认为 "databases/sessions"
        """
        self.storage_path = storage_path
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self._ensure_storage_dir()
    
    def _ensure_storage_dir(self) -> None:
        """确保存储目录存在"""
        if not os.path.exists(self.storage_path):
            os.makedirs(self.storage_path)
    
    def save_session(self, session_id: str, session_data: Dict[str, Any]) -> None:
        """
        保存会话数据到文件
        
        Args:
            session_id: 会话 ID
            session_data: 会话数据（包含 cookies、tokens 等）
        """
        session_data["last_updated"] = datetime.now().isoformat()
        self.sessions[session_id] = session_data
        
        session_file = os.path.join(self.storage_path, f"{session_id}.pkl")
        with open(session_file, 'wb') as f:
            pickle.dump(session_data, f)
    
    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        从文件加载会话数据
        
        Args:
            session_id: 会话 ID
            
        Returns:
            会话数据字典，如果不存在则返回 None
        """
        # 优先从内存缓存读取
        if session_id in self.sessions:
            return self.sessions[session_id]
        
        # 从文件加载
        session_file = os.path.join(self.storage_path, f"{session_id}.pkl")
        if os.path.exists(session_file):
            with open(session_file, 'rb') as f:
                session_data = pickle.load(f)
                self.sessions[session_id] = session_data
                return session_data
        
        return None
    
    def is_session_valid(self, session_id: str, max_age_hours: int = 24) -> bool:
        """
        检查会话是否有效
        
        Args:
            session_id: 会话 ID
            max_age_hours: 最大有效期（小时），默认 24 小时
            
        Returns:
            如果会话有效则返回 True，否则返回 False
        """
        session_data = self.load_session(session_id)
        if not session_data:
            return False
        
        last_updated_str = session_data.get("last_updated", "1970-01-01")
        last_updated = datetime.fromisoformat(last_updated_str)
        age = datetime.now() - last_updated
        
        return age < timedelta(hours=max_age_hours)
    
    def cleanup_expired_sessions(self, max_age_hours: int = 48) -> None:
        """
        清理过期会话
        
        Args:
            max_age_hours: 最大保留时间（小时），默认 48 小时
        """
        expired_sessions: List[str] = []
        
        # 收集过期会话
        for session_id, session_data in self.sessions.items():
            if not self.is_session_valid(session_id, max_age_hours):
                expired_sessions.append(session_id)
        
        # 删除过期会话
        for session_id in expired_sessions:
            del self.sessions[session_id]
            session_file = os.path.join(self.storage_path, f"{session_id}.pkl")
            if os.path.exists(session_file):
                os.remove(session_file)
    
    def get_cookies_for_request(self, session_id: str, domain: str) -> Dict[str, str]:
        """
        获取请求所需的 Cookies
        
        Args:
            session_id: 会话 ID
            domain: 目标域名
            
        Returns:
            匹配域名的 Cookies 字典
        """
        session_data = self.load_session(session_id)
        if not session_data:
            return {}
        
        cookies = session_data.get("cookies", {})
        domain_cookies: Dict[str, str] = {}
        
        for cookie_name, cookie_data in cookies.items():
            if self._cookie_matches_domain(cookie_data, domain):
                domain_cookies[cookie_name] = cookie_data.get("value", "")
        
        return domain_cookies
    
    def _cookie_matches_domain(self, cookie_data: Dict[str, Any], domain: str) -> bool:
        """
        检查 Cookie 是否匹配域名
        
        Args:
            cookie_data: Cookie 数据字典
            domain: 目标域名
            
        Returns:
            如果 Cookie 匹配域名则返回 True，否则返回 False
        """
        cookie_domain = cookie_data.get("domain", "")
        
        # 如果 Cookie 没有指定域名，则匹配所有域名
        if not cookie_domain:
            return True
        
        # 处理以点开头的域名（如 .example.com）
        if cookie_domain.startswith("."):
            return domain.endswith(cookie_domain[1:]) or domain == cookie_domain[1:]
        
        # 精确匹配
        return domain == cookie_domain


class WAFPerformanceMonitor:
    """
    WAF 穿透性能监控器
    
    功能:
    1. 记录检测耗时
    2. 记录绕过尝试
    3. 统计策略成功率
    4. 性能指标存储在内存中
    5. 限制历史记录数量（最多 1000 条）
    """
    
    MAX_HISTORY_SIZE: int = 1000
    
    def __init__(self) -> None:
        """
        初始化性能监控器
        
        初始化 metrics 字典，包含:
        - detection_time: 检测耗时列表
        - evasion_time: 绕过耗时列表
        - success_rate: 成功率统计
        - strategy_performance: 策略性能统计
        """
        self.metrics: Dict[str, Any] = {
            "detection_time": [],
            "evasion_time": [],
            "success_rate": {},
            "strategy_performance": {}
        }
    
    def record_detection_time(self, duration: float) -> None:
        """
        记录检测耗时
        
        Args:
            duration: 检测耗时（秒）
        """
        self.metrics["detection_time"].append(duration)
        
        # 限制历史记录数量，超过 1000 条时保留最新 500 条
        if len(self.metrics["detection_time"]) > self.MAX_HISTORY_SIZE:
            self.metrics["detection_time"] = self.metrics["detection_time"][-500:]
    
    def record_evasion_attempt(
        self,
        strategy: str,
        success: bool,
        duration: float
    ) -> None:
        """
        记录绕过尝试
        
        Args:
            strategy: 策略名称
            success: 是否成功
            duration: 绕过耗时（秒）
        """
        if strategy not in self.metrics["strategy_performance"]:
            self.metrics["strategy_performance"][strategy] = {
                "attempts": 0,
                "successes": 0,
                "total_time": 0.0
            }
        
        self.metrics["strategy_performance"][strategy]["attempts"] += 1
        if success:
            self.metrics["strategy_performance"][strategy]["successes"] += 1
        self.metrics["strategy_performance"][strategy]["total_time"] += duration
    
    def get_average_detection_time(self) -> float:
        """
        获取平均检测耗时
        
        Returns:
            平均检测耗时（秒），如果没有记录则返回 0.0
        """
        if not self.metrics["detection_time"]:
            return 0.0
        return sum(self.metrics["detection_time"]) / len(self.metrics["detection_time"])
    
    def get_strategy_success_rate(self, strategy: str) -> float:
        """
        获取策略成功率
        
        Args:
            strategy: 策略名称
            
        Returns:
            策略成功率（0.0 - 1.0），如果没有尝试记录则返回 0.0
        """
        perf = self.metrics["strategy_performance"].get(strategy, {})
        attempts = perf.get("attempts", 0)
        if attempts == 0:
            return 0.0
        return perf.get("successes", 0) / attempts
    
    def get_all_metrics(self) -> Dict[str, Any]:
        """
        获取所有性能指标
        
        Returns:
            性能指标字典
        """
        return self.metrics.copy()
    
    def reset_metrics(self) -> None:
        """
        重置所有性能指标
        """
        self.metrics = {
            "detection_time": [],
            "evasion_time": [],
            "success_rate": {},
            "strategy_performance": {}
        }


class WAFLogger:
    """
    WAF 穿透日志记录器
    
    使用 loguru 库实现日志记录功能
    
    功能:
    1. 记录 WAF 检测结果
    2. 记录绕过尝试
    3. 记录会话创建
    4. 记录挑战求解成功
    """
    
    @staticmethod
    def log_waf_detection(result: WAFDetectionResult) -> None:
        """
        记录 WAF 检测结果
        
        Args:
            result: WAF 检测结果对象
        """
        logger.info(
            f"WAF Detected | Type: {result.waf_type.value} | "
            f"Confidence: {result.confidence:.2f} | "
            f"Methods: {', '.join(result.detection_methods)}"
        )
    
    @staticmethod
    def log_evasion_attempt(
        strategy: str,
        success: bool,
        duration: float
    ) -> None:
        """
        记录绕过尝试
        
        Args:
            strategy: 策略名称
            success: 是否成功
            duration: 绕过耗时（秒）
        """
        status = "SUCCESS" if success else "FAILED"
        logger.info(
            f"Evasion Attempt | Strategy: {strategy} | "
            f"Status: {status} | Duration: {duration:.3f}s"
        )
    
    @staticmethod
    def log_session_created(session_id: str, domain: str) -> None:
        """
        记录会话创建
        
        Args:
            session_id: 会话 ID
            domain: 目标域名
        """
        logger.info(f"Session Created | ID: {session_id} | Domain: {domain}")
    
    @staticmethod
    def log_challenge_solved(waf_type: str, domain: str) -> None:
        """
        记录挑战求解成功
        
        Args:
            waf_type: WAF 类型
            domain: 目标域名
        """
        logger.info(
            f"Challenge Solved | WAF: {waf_type} | Domain: {domain}"
        )


class WAFDetector:
    """
    WAF 检测引擎
    
    功能:
    1. 预编译正则表达式以提高检测性能
    2. 多维度检测 WAF 拦截（响应头、状态码、页面内容）
    3. 计算检测置信度
    4. 支持主流 WAF 类型识别
    
    衔接关系:
    - 依赖 WAFPasser 的指纹库配置
    - 符合 V1 性能要求（正则表达式预编译）
    """
    
    def __init__(self, waf_passer: WAFPasser) -> None:
        """
        初始化 WAF 检测引擎
        
        Args:
            waf_passer: WAFPasser 实例，提供 WAF 指纹库配置
        """
        self.waf_passer = waf_passer
        self.compiled_patterns: Dict[WAFType, Dict[str, Any]] = {}
        self._precompile_patterns()
    
    def _precompile_patterns(self) -> None:
        """
        预编译所有正则表达式
        
        衔接 V1 性能要求: 所有正则表达式必须预编译以提高检测性能
        
        将 WAF 指纹库中的字符串模式预编译为正则表达式对象，
        避免每次检测时重复编译，显著提升检测效率。
        """
        for waf_type, signatures in self.waf_passer.waf_signatures.items():
            self.compiled_patterns[waf_type] = {
                "header_patterns": {},
                "page_patterns": []
            }
            
            # 预编译响应头匹配模式
            for header, patterns in signatures.get("headers", {}).items():
                self.compiled_patterns[waf_type]["header_patterns"][header] = [
                    re.compile(pattern, re.IGNORECASE) for pattern in patterns
                ]
            
            # 预编译页面内容匹配模式
            for pattern in signatures.get("page_patterns", []):
                self.compiled_patterns[waf_type]["page_patterns"].append(
                    re.compile(pattern, re.IGNORECASE)
                )
    
    def detect_waf(
        self, 
        response_headers: Dict[str, str], 
        response_body: str, 
        status_code: int
    ) -> WAFDetectionResult:
        """
        检测响应是否来自 WAF 拦截
        
        通过多维度检测判断响应是否被 WAF 拦截:
        1. HTTP 状态码匹配
        2. 响应头特征匹配
        3. 页面内容模式匹配
        
        Args:
            response_headers: 响应头字典
            response_body: 响应体内容
            status_code: HTTP 状态码
            
        Returns:
            WAFDetectionResult: 包含 WAF 类型、置信度、检测方法和拦截指标的检测结果
        """
        detection_methods: List[str] = []
        blocked_indicators: List[str] = []
        best_match: WAFType | None = None
        best_confidence: float = 0.0
        
        for waf_type, signatures in self.waf_passer.waf_signatures.items():
            confidence: float = 0.0
            methods: List[str] = []
            indicators: List[str] = []
            
            # 检测状态码匹配
            if status_code in signatures.get("response_codes", []):
                confidence += 0.3
                methods.append("status_code_match")
                indicators.append(f"HTTP {status_code}")
            
            # 检测响应头匹配
            for header, patterns in signatures.get("headers", {}).items():
                if header in response_headers:
                    header_value = response_headers[header]
                    compiled_patterns = self.compiled_patterns[waf_type]["header_patterns"].get(header, [])
                    
                    for pattern in compiled_patterns:
                        if pattern.search(header_value):
                            confidence += 0.4
                            methods.append(f"header_match:{header}")
                            indicators.append(f"{header}: {header_value[:50]}")
            
            # 检测页面内容模式匹配
            compiled_page_patterns = self.compiled_patterns[waf_type]["page_patterns"]
            for pattern in compiled_page_patterns:
                if pattern.search(response_body):
                    confidence += 0.3
                    methods.append("page_pattern_match")
                    indicators.append(f"Pattern: {pattern.pattern}")
            
            # 更新最佳匹配
            if confidence > best_confidence:
                best_confidence = confidence
                best_match = waf_type
                detection_methods = methods
                blocked_indicators = indicators
        
        # 如果没有匹配到特定 WAF，则标记为通用 WAF
        if best_match is None:
            best_match = WAFType.GENERIC
            best_confidence = 0.1
            detection_methods = ["no_specific_match"]
            blocked_indicators = ["Unknown blocking mechanism"]
        
        return WAFDetectionResult(
            waf_type=best_match,
            confidence=min(best_confidence, 1.0),
            detection_methods=detection_methods,
            blocked_indicators=blocked_indicators
        )
    
    def is_blocked_response(
        self, 
        response_headers: Dict[str, str], 
        response_body: str, 
        status_code: int,
        threshold: float = 0.5
    ) -> bool:
        """
        判断响应是否被 WAF 拦截
        
        基于检测结果和置信度阈值判断响应是否被 WAF 拦截。
        
        Args:
            response_headers: 响应头字典
            response_body: 响应体内容
            status_code: HTTP 状态码
            threshold: 置信度阈值，默认 0.5
            
        Returns:
            如果置信度大于等于阈值则返回 True，否则返回 False
        """
        result = self.detect_waf(response_headers, response_body, status_code)
        return result.confidence >= threshold
