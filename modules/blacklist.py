"""
黑名单拦截模块

功能：
1. IP 黑名单（单 IP 和 CIDR 范围）
2. 域名黑名单
3. URL 黑名单（精确匹配和正则表达式）
4. 白名单优先级机制
5. 热重载配置
6. 拦截统计信息

Author: SilkRoad-Next Team
Version: 2.0.0
"""

import asyncio
import json
import re
import ipaddress
from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime
from pathlib import Path
import time

from modules.exit import GracefulExit


class BlacklistManager:
    """
    黑名单管理器
    
    功能：
    1. IP 黑名单（单 IP 和 CIDR 范围）
    2. URL 黑名单
    3. 域名黑名单
    4. 正则表达式匹配
    5. 白名单优先级机制
    6. 黑名单热重载
    7. 拦截统计信息
    """
    
    def __init__(self, 
                 config_file: str = 'databases/blacklist.json',
                 auto_reload: bool = False,
                 reload_interval: int = 300):
        """
        初始化黑名单管理器
        
        Args:
            config_file: 黑名单配置文件路径
            auto_reload: 是否启用自动重载
            reload_interval: 自动重载间隔（秒）
        """
        self.config_file = config_file
        self.auto_reload = auto_reload
        self.reload_interval = reload_interval
        
        # 黑名单存储
        self._ip_blacklist: Set[str] = set()
        self._ip_range_blacklist: List[str] = []
        self._domain_blacklist: Set[str] = set()
        self._url_blacklist: Set[str] = set()
        self._url_pattern_blacklist: List[re.Pattern] = []
        
        # 白名单（优先级高于黑名单）
        self._ip_whitelist: Set[str] = set()
        self._ip_range_whitelist: List[str] = []
        self._domain_whitelist: Set[str] = set()
        
        # 锁机制，确保线程安全
        self._lock = asyncio.Lock()
        
        # 配置加载状态
        self._config_loaded = False
        self._last_load_time: Optional[float] = None
        
        # 统计信息
        self.stats = {
            'total_blocked': 0,
            'ip_blocked': 0,
            'domain_blocked': 0,
            'url_blocked': 0,
            'url_pattern_blocked': 0,
            'whitelist_allowed': 0,
            'config_reloads': 0
        }
        
        # 自动重载任务
        self._reload_task: Optional[asyncio.Task] = None
    
    async def load_config(self) -> bool:
        """
        加载黑名单配置
        
        Returns:
            是否加载成功
        """
        async with self._lock:
            try:
                config_path = Path(self.config_file)
                
                if not config_path.exists():
                    # 配置文件不存在，创建默认配置
                    await self._create_default_config()
                    return True
                
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                # 加载 IP 黑名单
                self._ip_blacklist = set(config.get('ip_blacklist', []))
                
                # 加载 IP 范围黑名单（CIDR 格式）
                self._ip_range_blacklist = config.get('ip_range_blacklist', [])
                
                # 加载域名黑名单
                self._domain_blacklist = set(config.get('domain_blacklist', []))
                
                # 加载 URL 黑名单
                self._url_blacklist = set(config.get('url_blacklist', []))
                
                # 编译 URL 正则表达式
                url_patterns = config.get('url_pattern_blacklist', [])
                self._url_pattern_blacklist = []
                for pattern in url_patterns:
                    try:
                        compiled = re.compile(pattern, re.IGNORECASE)
                        self._url_pattern_blacklist.append(compiled)
                    except re.error:
                        # 正则表达式编译失败，跳过该模式
                        continue
                
                # 加载白名单
                self._ip_whitelist = set(config.get('ip_whitelist', []))
                self._ip_range_whitelist = config.get('ip_range_whitelist', [])
                self._domain_whitelist = set(config.get('domain_whitelist', []))
                
                # 更新状态
                self._config_loaded = True
                self._last_load_time = time.time()
                
                return True
                
            except json.JSONDecodeError:
                # JSON 解析错误
                return False
            except Exception:
                # 其他错误
                return False
    
    async def _create_default_config(self) -> None:
        """
        创建默认黑名单配置
        """
        default_config = {
            "ip_blacklist": [
                "192.168.1.100",
                "10.0.0.50"
            ],
            "ip_range_blacklist": [
                "192.168.2.0/24",
                "10.1.0.0/16"
            ],
            "domain_blacklist": [
                "malicious-site.com",
                "spam-domain.net"
            ],
            "url_blacklist": [
                "/admin/config",
                "/private/data"
            ],
            "url_pattern_blacklist": [
                r"/admin/.*",
                r"/private/.*",
                r".*\.bak$",
                r".*\.backup$",
                r".*\.old$"
            ],
            "ip_whitelist": [
                "127.0.0.1",
                "::1"
            ],
            "ip_range_whitelist": [
                "192.168.0.0/16"
            ],
            "domain_whitelist": [
                "trusted-site.com"
            ]
        }
        
        # 确保目录存在
        config_path = Path(self.config_file)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, ensure_ascii=False, indent=2)
        
        # 加载默认配置
        self._ip_blacklist = set(default_config['ip_blacklist'])
        self._ip_range_blacklist = default_config['ip_range_blacklist']
        self._domain_blacklist = set(default_config['domain_blacklist'])
        self._url_blacklist = set(default_config['url_blacklist'])
        self._url_pattern_blacklist = [
            re.compile(p, re.IGNORECASE) for p in default_config['url_pattern_blacklist']
        ]
        self._ip_whitelist = set(default_config['ip_whitelist'])
        self._ip_range_whitelist = default_config['ip_range_whitelist']
        self._domain_whitelist = set(default_config['domain_whitelist'])
        
        self._config_loaded = True
        self._last_load_time = time.time()
    
    async def reload_config(self) -> bool:
        """
        热重载黑名单配置
        
        Returns:
            是否重载成功
        """
        result = await self.load_config()
        if result:
            self.stats['config_reloads'] += 1
        return result
    
    async def is_blocked(self, 
                        client_ip: str, 
                        url: str, 
                        domain: str) -> Tuple[bool, str]:
        """
        检查是否被黑名单拦截
        
        Args:
            client_ip: 客户端 IP 地址
            url: 请求 URL（路径部分，如 /admin/config）
            domain: 目标域名
            
        Returns:
            (is_blocked: bool, reason: str) - 是否被拦截及原因
        """
        async with self._lock:
            # 确保配置已加载
            if not self._config_loaded:
                return False, "Config not loaded"
            
            # ========== 白名单检查（优先级最高）==========
            
            # 1. 检查 IP 白名单
            if client_ip in self._ip_whitelist:
                self.stats['whitelist_allowed'] += 1
                return False, "IP in whitelist"
            
            # 2. 检查 IP 范围白名单
            try:
                client_ip_obj = ipaddress.ip_address(client_ip)
                for ip_range in self._ip_range_whitelist:
                    try:
                        if client_ip_obj in ipaddress.ip_network(ip_range, strict=False):
                            self.stats['whitelist_allowed'] += 1
                            return False, f"IP {client_ip} in whitelist range {ip_range}"
                    except ValueError:
                        continue
            except ValueError:
                # 无效的 IP 地址，跳过范围检查
                pass
            
            # 3. 检查域名白名单
            if domain in self._domain_whitelist:
                self.stats['whitelist_allowed'] += 1
                return False, "Domain in whitelist"
            
            # ========== 黑名单检查 ==========
            
            # 4. 检查 IP 黑名单
            if client_ip in self._ip_blacklist:
                self.stats['total_blocked'] += 1
                self.stats['ip_blocked'] += 1
                return True, f"IP {client_ip} is blacklisted"
            
            # 5. 检查 IP 范围黑名单
            try:
                client_ip_obj = ipaddress.ip_address(client_ip)
                for ip_range in self._ip_range_blacklist:
                    try:
                        if client_ip_obj in ipaddress.ip_network(ip_range, strict=False):
                            self.stats['total_blocked'] += 1
                            self.stats['ip_blocked'] += 1
                            return True, f"IP {client_ip} in blacklisted range {ip_range}"
                    except ValueError:
                        continue
            except ValueError:
                pass
            
            # 6. 检查域名黑名单
            if domain in self._domain_blacklist:
                self.stats['total_blocked'] += 1
                self.stats['domain_blocked'] += 1
                return True, f"Domain {domain} is blacklisted"
            
            # 7. 检查 URL 黑名单（精确匹配）
            if url in self._url_blacklist:
                self.stats['total_blocked'] += 1
                self.stats['url_blocked'] += 1
                return True, f"URL {url} is blacklisted"
            
            # 8. 检查 URL 正则表达式
            for pattern in self._url_pattern_blacklist:
                if pattern.search(url):
                    self.stats['total_blocked'] += 1
                    self.stats['url_pattern_blocked'] += 1
                    return True, f"URL {url} matches blacklisted pattern {pattern.pattern}"
            
            # 未被拦截
            return False, "Allowed"
    
    async def add_to_blacklist(self, 
                               item: str, 
                               blacklist_type: str,
                               save: bool = True) -> bool:
        """
        添加到黑名单
        
        Args:
            item: 要添加的项目
            blacklist_type: 黑名单类型 (ip, ip_range, domain, url, url_pattern)
            save: 是否保存到配置文件
            
        Returns:
            是否添加成功
        """
        async with self._lock:
            try:
                if blacklist_type == 'ip':
                    self._ip_blacklist.add(item)
                elif blacklist_type == 'ip_range':
                    # 验证 CIDR 格式
                    ipaddress.ip_network(item, strict=False)
                    if item not in self._ip_range_blacklist:
                        self._ip_range_blacklist.append(item)
                elif blacklist_type == 'domain':
                    self._domain_blacklist.add(item)
                elif blacklist_type == 'url':
                    self._url_blacklist.add(item)
                elif blacklist_type == 'url_pattern':
                    # 编译并添加正则表达式
                    compiled = re.compile(item, re.IGNORECASE)
                    self._url_pattern_blacklist.append(compiled)
                else:
                    return False
                
                # 保存到配置文件
                if save:
                    await self._save_config()
                
                return True
                
            except ValueError:
                # IP 范围格式无效
                return False
            except re.error:
                # 正则表达式无效
                return False
            except Exception:
                return False
    
    async def remove_from_blacklist(self, 
                                    item: str, 
                                    blacklist_type: str,
                                    save: bool = True) -> bool:
        """
        从黑名单移除
        
        Args:
            item: 要移除的项目
            blacklist_type: 黑名单类型 (ip, ip_range, domain, url, url_pattern)
            save: 是否保存到配置文件
            
        Returns:
            是否移除成功
        """
        async with self._lock:
            try:
                if blacklist_type == 'ip':
                    self._ip_blacklist.discard(item)
                elif blacklist_type == 'ip_range':
                    if item in self._ip_range_blacklist:
                        self._ip_range_blacklist.remove(item)
                elif blacklist_type == 'domain':
                    self._domain_blacklist.discard(item)
                elif blacklist_type == 'url':
                    self._url_blacklist.discard(item)
                elif blacklist_type == 'url_pattern':
                    # 移除匹配的正则表达式
                    self._url_pattern_blacklist = [
                        p for p in self._url_pattern_blacklist 
                        if p.pattern != item
                    ]
                else:
                    return False
                
                # 保存到配置文件
                if save:
                    await self._save_config()
                
                return True
                
            except Exception:
                return False
    
    async def add_to_whitelist(self, 
                               item: str, 
                               whitelist_type: str,
                               save: bool = True) -> bool:
        """
        添加到白名单
        
        Args:
            item: 要添加的项目
            whitelist_type: 白名单类型 (ip, ip_range, domain)
            save: 是否保存到配置文件
            
        Returns:
            是否添加成功
        """
        async with self._lock:
            try:
                if whitelist_type == 'ip':
                    self._ip_whitelist.add(item)
                elif whitelist_type == 'ip_range':
                    # 验证 CIDR 格式
                    ipaddress.ip_network(item, strict=False)
                    if item not in self._ip_range_whitelist:
                        self._ip_range_whitelist.append(item)
                elif whitelist_type == 'domain':
                    self._domain_whitelist.add(item)
                else:
                    return False
                
                # 保存到配置文件
                if save:
                    await self._save_config()
                
                return True
                
            except ValueError:
                return False
            except Exception:
                return False
    
    async def remove_from_whitelist(self, 
                                    item: str, 
                                    whitelist_type: str,
                                    save: bool = True) -> bool:
        """
        从白名单移除
        
        Args:
            item: 要移除的项目
            whitelist_type: 白名单类型 (ip, ip_range, domain)
            save: 是否保存到配置文件
            
        Returns:
            是否移除成功
        """
        async with self._lock:
            try:
                if whitelist_type == 'ip':
                    self._ip_whitelist.discard(item)
                elif whitelist_type == 'ip_range':
                    if item in self._ip_range_whitelist:
                        self._ip_range_whitelist.remove(item)
                elif whitelist_type == 'domain':
                    self._domain_whitelist.discard(item)
                else:
                    return False
                
                # 保存到配置文件
                if save:
                    await self._save_config()
                
                return True
                
            except Exception:
                return False
    
    async def _save_config(self) -> None:
        """
        保存黑名单配置到文件
        """
        config = {
            "ip_blacklist": list(self._ip_blacklist),
            "ip_range_blacklist": self._ip_range_blacklist,
            "domain_blacklist": list(self._domain_blacklist),
            "url_blacklist": list(self._url_blacklist),
            "url_pattern_blacklist": [p.pattern for p in self._url_pattern_blacklist],
            "ip_whitelist": list(self._ip_whitelist),
            "ip_range_whitelist": self._ip_range_whitelist,
            "domain_whitelist": list(self._domain_whitelist)
        }
        
        # 确保目录存在
        config_path = Path(self.config_file)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    
    def get_stats(self) -> Dict:
        """
        获取黑名单统计信息
        
        Returns:
            统计信息字典
        """
        return {
            **self.stats,
            'ip_blacklist_count': len(self._ip_blacklist),
            'ip_range_blacklist_count': len(self._ip_range_blacklist),
            'domain_blacklist_count': len(self._domain_blacklist),
            'url_blacklist_count': len(self._url_blacklist),
            'url_pattern_count': len(self._url_pattern_blacklist),
            'ip_whitelist_count': len(self._ip_whitelist),
            'ip_range_whitelist_count': len(self._ip_range_whitelist),
            'domain_whitelist_count': len(self._domain_whitelist),
            'config_loaded': self._config_loaded,
            'last_load_time': datetime.fromtimestamp(self._last_load_time).isoformat() 
                              if self._last_load_time else None
        }
    
    def get_blacklist(self, blacklist_type: str) -> List[str]:
        """
        获取指定类型的黑名单列表
        
        Args:
            blacklist_type: 黑名单类型 (ip, ip_range, domain, url, url_pattern)
            
        Returns:
            黑名单列表
        """
        if blacklist_type == 'ip':
            return list(self._ip_blacklist)
        elif blacklist_type == 'ip_range':
            return self._ip_range_blacklist.copy()
        elif blacklist_type == 'domain':
            return list(self._domain_blacklist)
        elif blacklist_type == 'url':
            return list(self._url_blacklist)
        elif blacklist_type == 'url_pattern':
            return [p.pattern for p in self._url_pattern_blacklist]
        else:
            return []
    
    def get_whitelist(self, whitelist_type: str) -> List[str]:
        """
        获取指定类型的白名单列表
        
        Args:
            whitelist_type: 白名单类型 (ip, ip_range, domain)
            
        Returns:
            白名单列表
        """
        if whitelist_type == 'ip':
            return list(self._ip_whitelist)
        elif whitelist_type == 'ip_range':
            return self._ip_range_whitelist.copy()
        elif whitelist_type == 'domain':
            return list(self._domain_whitelist)
        else:
            return []
    
    async def start_auto_reload(self) -> None:
        """
        启动自动重载任务
        """
        if self._reload_task is None or self._reload_task.done():
            self._reload_task = asyncio.create_task(self._auto_reload_loop())
            if GracefulExit.is_initialized():
                GracefulExit.register_task(self._reload_task)
    
    async def stop_auto_reload(self) -> None:
        """
        停止自动重载任务
        """
        if self._reload_task and not self._reload_task.done():
            self._reload_task.cancel()
            try:
                await self._reload_task
            except asyncio.CancelledError:
                pass
    
    async def _auto_reload_loop(self) -> None:
        """
        自动重载循环
        """
        while True:
            try:
                await asyncio.sleep(self.reload_interval)
                await self.reload_config()
            except asyncio.CancelledError:
                break
            except Exception:
                # 重载失败，继续下一次循环
                continue
    
    async def clear_all_blacklists(self) -> None:
        """
        清空所有黑名单
        """
        async with self._lock:
            self._ip_blacklist.clear()
            self._ip_range_blacklist.clear()
            self._domain_blacklist.clear()
            self._url_blacklist.clear()
            self._url_pattern_blacklist.clear()
            await self._save_config()
    
    async def clear_all_whitelists(self) -> None:
        """
        清空所有白名单
        """
        async with self._lock:
            self._ip_whitelist.clear()
            self._ip_range_whitelist.clear()
            self._domain_whitelist.clear()
            await self._save_config()
    
    async def import_config(self, config_data: Dict) -> bool:
        """
        导入配置
        
        Args:
            config_data: 配置数据字典
            
        Returns:
            是否导入成功
        """
        async with self._lock:
            try:
                # 导入黑名单
                if 'ip_blacklist' in config_data:
                    self._ip_blacklist = set(config_data['ip_blacklist'])
                if 'ip_range_blacklist' in config_data:
                    self._ip_range_blacklist = config_data['ip_range_blacklist']
                if 'domain_blacklist' in config_data:
                    self._domain_blacklist = set(config_data['domain_blacklist'])
                if 'url_blacklist' in config_data:
                    self._url_blacklist = set(config_data['url_blacklist'])
                if 'url_pattern_blacklist' in config_data:
                    self._url_pattern_blacklist = []
                    for pattern in config_data['url_pattern_blacklist']:
                        try:
                            self._url_pattern_blacklist.append(
                                re.compile(pattern, re.IGNORECASE)
                            )
                        except re.error:
                            continue
                
                # 导入白名单
                if 'ip_whitelist' in config_data:
                    self._ip_whitelist = set(config_data['ip_whitelist'])
                if 'ip_range_whitelist' in config_data:
                    self._ip_range_whitelist = config_data['ip_range_whitelist']
                if 'domain_whitelist' in config_data:
                    self._domain_whitelist = set(config_data['domain_whitelist'])
                
                await self._save_config()
                return True
                
            except Exception:
                return False
    
    async def export_config(self) -> Dict:
        """
        导出配置
        
        Returns:
            配置数据字典
        """
        async with self._lock:
            return {
                "ip_blacklist": list(self._ip_blacklist),
                "ip_range_blacklist": self._ip_range_blacklist.copy(),
                "domain_blacklist": list(self._domain_blacklist),
                "url_blacklist": list(self._url_blacklist),
                "url_pattern_blacklist": [p.pattern for p in self._url_pattern_blacklist],
                "ip_whitelist": list(self._ip_whitelist),
                "ip_range_whitelist": self._ip_range_whitelist.copy(),
                "domain_whitelist": list(self._domain_whitelist)
            }
    
    async def is_ip_in_range(self, ip: str, ip_range: str) -> bool:
        """
        检查 IP 是否在指定范围内
        
        Args:
            ip: IP 地址
            ip_range: IP 范围（CIDR 格式）
            
        Returns:
            是否在范围内
        """
        try:
            ip_obj = ipaddress.ip_address(ip)
            network = ipaddress.ip_network(ip_range, strict=False)
            return ip_obj in network
        except ValueError:
            return False
    
    async def check_ip(self, client_ip: str) -> Tuple[bool, str]:
        """
        仅检查 IP 是否被拦截
        
        Args:
            client_ip: 客户端 IP 地址
            
        Returns:
            (is_blocked: bool, reason: str)
        """
        async with self._lock:
            # 检查 IP 白名单
            if client_ip in self._ip_whitelist:
                return False, "IP in whitelist"
            
            # 检查 IP 范围白名单
            try:
                client_ip_obj = ipaddress.ip_address(client_ip)
                for ip_range in self._ip_range_whitelist:
                    try:
                        if client_ip_obj in ipaddress.ip_network(ip_range, strict=False):
                            return False, f"IP in whitelist range {ip_range}"
                    except ValueError:
                        continue
            except ValueError:
                pass
            
            # 检查 IP 黑名单
            if client_ip in self._ip_blacklist:
                return True, f"IP {client_ip} is blacklisted"
            
            # 检查 IP 范围黑名单
            try:
                client_ip_obj = ipaddress.ip_address(client_ip)
                for ip_range in self._ip_range_blacklist:
                    try:
                        if client_ip_obj in ipaddress.ip_network(ip_range, strict=False):
                            return True, f"IP in blacklisted range {ip_range}"
                    except ValueError:
                        continue
            except ValueError:
                pass
            
            return False, "Allowed"
    
    async def check_domain(self, domain: str) -> Tuple[bool, str]:
        """
        仅检查域名是否被拦截
        
        Args:
            domain: 目标域名
            
        Returns:
            (is_blocked: bool, reason: str)
        """
        async with self._lock:
            # 检查域名白名单
            if domain in self._domain_whitelist:
                return False, "Domain in whitelist"
            
            # 检查域名黑名单
            if domain in self._domain_blacklist:
                return True, f"Domain {domain} is blacklisted"
            
            return False, "Allowed"
    
    async def check_url(self, url: str) -> Tuple[bool, str]:
        """
        仅检查 URL 是否被拦截
        
        Args:
            url: 请求 URL（路径部分）
            
        Returns:
            (is_blocked: bool, reason: str)
        """
        async with self._lock:
            # 检查 URL 黑名单
            if url in self._url_blacklist:
                return True, f"URL {url} is blacklisted"
            
            # 检查 URL 正则表达式
            for pattern in self._url_pattern_blacklist:
                if pattern.search(url):
                    return True, f"URL matches blacklisted pattern {pattern.pattern}"
            
            return False, "Allowed"
