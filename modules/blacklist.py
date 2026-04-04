"""
黑名单拦截模块

实现多层次访问控制，支持：
- IP 黑名单（单 IP 和 IP 范围）
- URL 黑名单（精确匹配和正则匹配）
- 域名黑名单
- 白名单优先级机制
- 配置热重载
- 拦截统计信息查询
- 动态添加和移除黑名单项

Author: SilkRoad-Next Team
Version: 2.0.0
"""

import asyncio
import json
import re
import ipaddress
import os
from typing import Dict, List, Optional, Set, Tuple, Any
from datetime import datetime
from pathlib import Path
import time


class BlacklistError(Exception):
    """黑名单错误异常"""
    pass


class BlacklistConfigError(BlacklistError):
    """黑名单配置错误异常"""
    pass


class BlacklistManager:
    """
    黑名单管理器

    实现多层次访问控制，支持 IP、URL、域名等多种拦截策略。

    Attributes:
        config_file (str): 黑名单配置文件路径
        _ip_blacklist (Set[str]): IP 黑名单集合
        _ip_range_blacklist (List[str]): IP 范围黑名单列表
        _domain_blacklist (Set[str]): 域名黑名单集合
        _url_blacklist (Set[str]): URL 黑名单集合
        _url_pattern_blacklist (List[re.Pattern]): URL 正则表达式黑名单列表
        _ip_whitelist (Set[str]): IP 白名单集合
        _domain_whitelist (Set[str]): 域名白名单集合
        _lock (asyncio.Lock): 异步锁，确保线程安全
        stats (Dict[str, int]): 统计信息字典
    """

    def __init__(self, config_file: str = 'databases/blacklist.json'):
        """
        初始化黑名单管理器

        Args:
            config_file: 黑名单配置文件路径，默认为 'databases/blacklist.json'
        """
        self.config_file = config_file

        # 黑名单存储
        self._ip_blacklist: Set[str] = set()
        self._ip_range_blacklist: List[str] = []
        self._domain_blacklist: Set[str] = set()
        self._url_blacklist: Set[str] = set()
        self._url_pattern_blacklist: List[re.Pattern] = []

        # 白名单（优先级高于黑名单）
        self._ip_whitelist: Set[str] = set()
        self._domain_whitelist: Set[str] = set()

        # 锁机制
        self._lock = asyncio.Lock()

        # 统计信息
        self.stats: Dict[str, int] = {
            'total_blocked': 0,
            'ip_blocked': 0,
            'domain_blocked': 0,
            'url_blocked': 0,
            'whitelist_allowed': 0,
            'config_reloads': 0
        }

        # 配置文件最后修改时间（用于热重载检测）
        self._last_modified: float = 0.0

        # 初始化标志
        self._initialized = False

    async def initialize(self) -> None:
        """
        初始化黑名单管理器

        加载配置文件并初始化黑名单数据。

        Raises:
            BlacklistConfigError: 配置文件格式错误或加载失败
        """
        if self._initialized:
            return

        await self.load_config()
        self._initialized = True

    async def load_config(self) -> None:
        """
        加载黑名单配置

        从配置文件加载黑名单和白名单数据。

        Raises:
            BlacklistConfigError: 配置文件格式错误或加载失败
        """
        async with self._lock:
            try:
                # 检查配置文件是否存在
                if not os.path.exists(self.config_file):
                    # 配置文件不存在，创建默认配置
                    await self._create_default_config()
                    return

                # 读取配置文件
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                # 验证配置格式
                self._validate_config(config)

                # 加载 IP 黑名单
                self._ip_blacklist = set(config.get('ip_blacklist', []))

                # 加载 IP 范围黑名单
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
                        compiled = re.compile(pattern)
                        self._url_pattern_blacklist.append(compiled)
                    except re.error as e:
                        raise BlacklistConfigError(f"无效的正则表达式 '{pattern}': {e}")

                # 加载白名单
                self._ip_whitelist = set(config.get('ip_whitelist', []))
                self._domain_whitelist = set(config.get('domain_whitelist', []))

                # 更新最后修改时间
                self._last_modified = os.path.getmtime(self.config_file)

            except json.JSONDecodeError as e:
                raise BlacklistConfigError(f"配置文件格式错误: {e}")
            except PermissionError:
                raise BlacklistConfigError(f"无权限读取配置文件: {self.config_file}")
            except Exception as e:
                if isinstance(e, BlacklistConfigError):
                    raise
                raise BlacklistConfigError(f"加载配置文件失败: {e}")

    def _validate_config(self, config: Dict[str, Any]) -> None:
        """
        验证配置格式

        Args:
            config: 配置字典

        Raises:
            BlacklistConfigError: 配置格式无效
        """
        # 验证 IP 黑名单格式
        ip_blacklist = config.get('ip_blacklist', [])
        if not isinstance(ip_blacklist, list):
            raise BlacklistConfigError("ip_blacklist 必须是列表类型")

        for ip in ip_blacklist:
            if not isinstance(ip, str):
                raise BlacklistConfigError(f"IP 地址必须是字符串类型: {ip}")
            # 验证 IP 地址格式
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                raise BlacklistConfigError(f"无效的 IP 地址: {ip}")

        # 验证 IP 范围黑名单格式
        ip_range_blacklist = config.get('ip_range_blacklist', [])
        if not isinstance(ip_range_blacklist, list):
            raise BlacklistConfigError("ip_range_blacklist 必须是列表类型")

        for ip_range in ip_range_blacklist:
            if not isinstance(ip_range, str):
                raise BlacklistConfigError(f"IP 范围必须是字符串类型: {ip_range}")
            # 验证 IP 范围格式
            try:
                ipaddress.ip_network(ip_range, strict=False)
            except ValueError:
                raise BlacklistConfigError(f"无效的 IP 范围: {ip_range}")

        # 验证域名黑名单格式
        domain_blacklist = config.get('domain_blacklist', [])
        if not isinstance(domain_blacklist, list):
            raise BlacklistConfigError("domain_blacklist 必须是列表类型")

        for domain in domain_blacklist:
            if not isinstance(domain, str):
                raise BlacklistConfigError(f"域名必须是字符串类型: {domain}")

        # 验证 URL 黑名单格式
        url_blacklist = config.get('url_blacklist', [])
        if not isinstance(url_blacklist, list):
            raise BlacklistConfigError("url_blacklist 必须是列表类型")

        for url in url_blacklist:
            if not isinstance(url, str):
                raise BlacklistConfigError(f"URL 必须是字符串类型: {url}")

        # 验证 URL 正则表达式黑名单格式
        url_pattern_blacklist = config.get('url_pattern_blacklist', [])
        if not isinstance(url_pattern_blacklist, list):
            raise BlacklistConfigError("url_pattern_blacklist 必须是列表类型")

        for pattern in url_pattern_blacklist:
            if not isinstance(pattern, str):
                raise BlacklistConfigError(f"URL 正则表达式必须是字符串类型: {pattern}")

        # 验证白名单格式
        ip_whitelist = config.get('ip_whitelist', [])
        if not isinstance(ip_whitelist, list):
            raise BlacklistConfigError("ip_whitelist 必须是列表类型")

        for ip in ip_whitelist:
            if not isinstance(ip, str):
                raise BlacklistConfigError(f"白名单 IP 地址必须是字符串类型: {ip}")

        domain_whitelist = config.get('domain_whitelist', [])
        if not isinstance(domain_whitelist, list):
            raise BlacklistConfigError("domain_whitelist 必须是列表类型")

        for domain in domain_whitelist:
            if not isinstance(domain, str):
                raise BlacklistConfigError(f"白名单域名必须是字符串类型: {domain}")

    async def _create_default_config(self) -> None:
        """
        创建默认黑名单配置

        当配置文件不存在时，创建包含默认值的配置文件。

        Raises:
            BlacklistConfigError: 创建配置文件失败
        """
        default_config = {
            "_comment": "SilkRoad-Next V2 黑名单配置文件",
            "_description": "用于访问控制的黑名单和白名单配置，支持 IP、域名、URL 等多种拦截策略",
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
                r".*\.backup$"
            ],
            "ip_whitelist": [
                "127.0.0.1",
                "::1"
            ],
            "domain_whitelist": [
                "trusted-site.com"
            ]
        }

        try:
            # 创建配置文件目录
            config_dir = os.path.dirname(self.config_file)
            if config_dir:
                os.makedirs(config_dir, exist_ok=True)

            # 保存配置到文件
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, ensure_ascii=False, indent=2)

            # 更新最后修改时间
            self._last_modified = os.path.getmtime(self.config_file)

        except PermissionError:
            raise BlacklistConfigError(f"无权限创建配置文件: {self.config_file}")
        except OSError as e:
            raise BlacklistConfigError(f"创建配置文件失败: {e}")

    async def reload_config(self) -> bool:
        """
        热重载黑名单配置

        检查配置文件是否已修改，如果已修改则重新加载。

        Returns:
            bool: 是否成功重载配置
        """
        async with self._lock:
            try:
                # 检查配置文件是否存在
                if not os.path.exists(self.config_file):
                    return False

                # 检查文件是否已修改
                current_modified = os.path.getmtime(self.config_file)
                if current_modified <= self._last_modified:
                    return False

                # 重新加载配置
                await self.load_config()

                # 更新统计信息
                self.stats['config_reloads'] += 1

                return True

            except Exception as e:
                raise BlacklistConfigError(f"热重载配置失败: {e}")

    async def check_config_modified(self) -> bool:
        """
        检查配置文件是否已修改

        Returns:
            bool: 配置文件是否已修改
        """
        try:
            if not os.path.exists(self.config_file):
                return False

            current_modified = os.path.getmtime(self.config_file)
            return current_modified > self._last_modified

        except Exception:
            return False

    async def is_blocked(self,
                         client_ip: str,
                         url: str,
                         domain: str) -> Tuple[bool, str]:
        """
        检查是否被黑名单拦截

        按以下优先级检查：
        1. IP 白名单
        2. 域名白名单
        3. IP 黑名单
        4. IP 范围黑名单
        5. 域名黑名单
        6. URL 黑名单
        7. URL 正则表达式黑名单

        Args:
            client_ip: 客户端 IP 地址
            url: 请求 URL（路径部分）
            domain: 目标域名

        Returns:
            Tuple[bool, str]: (是否被拦截, 拦截原因)

        Examples:
            >>> is_blocked, reason = await manager.is_blocked('192.168.1.100', '/page', 'example.com')
            >>> if is_blocked:
            ...     print(f"Blocked: {reason}")
        """
        async with self._lock:
            # 1. 检查白名单（优先级最高）
            if client_ip in self._ip_whitelist:
                self.stats['whitelist_allowed'] += 1
                return False, f"IP {client_ip} in whitelist"

            if domain in self._domain_whitelist:
                self.stats['whitelist_allowed'] += 1
                return False, f"Domain {domain} in whitelist"

            # 2. 检查 IP 黑名单
            if client_ip in self._ip_blacklist:
                self.stats['total_blocked'] += 1
                self.stats['ip_blocked'] += 1
                return True, f"IP {client_ip} is blacklisted"

            # 3. 检查 IP 范围黑名单
            try:
                client_ip_obj = ipaddress.ip_address(client_ip)

                for ip_range in self._ip_range_blacklist:
                    try:
                        network = ipaddress.ip_network(ip_range, strict=False)
                        if client_ip_obj in network:
                            self.stats['total_blocked'] += 1
                            self.stats['ip_blocked'] += 1
                            return True, f"IP {client_ip} in blacklisted range {ip_range}"
                    except ValueError:
                        # 忽略无效的 IP 范围
                        continue

            except ValueError:
                # 无效的 IP 地址格式，跳过 IP 范围检查
                pass

            # 4. 检查域名黑名单
            if domain in self._domain_blacklist:
                self.stats['total_blocked'] += 1
                self.stats['domain_blocked'] += 1
                return True, f"Domain {domain} is blacklisted"

            # 5. 检查 URL 黑名单（精确匹配）
            if url in self._url_blacklist:
                self.stats['total_blocked'] += 1
                self.stats['url_blocked'] += 1
                return True, f"URL {url} is blacklisted"

            # 6. 检查 URL 正则表达式
            for pattern in self._url_pattern_blacklist:
                if pattern.search(url):
                    self.stats['total_blocked'] += 1
                    self.stats['url_blocked'] += 1
                    return True, f"URL {url} matches blacklisted pattern {pattern.pattern}"

            # 7. 未被拦截
            return False, "Allowed"

    async def add_to_blacklist(self,
                               item: str,
                               blacklist_type: str,
                               save: bool = True) -> bool:
        """
        添加到黑名单

        Args:
            item: 要添加的项目
            blacklist_type: 黑名单类型，可选值：'ip', 'ip_range', 'domain', 'url', 'url_pattern'
            save: 是否保存到配置文件，默认为 True

        Returns:
            bool: 是否成功添加

        Raises:
            BlacklistError: 黑名单类型无效或项目格式错误

        Examples:
            >>> await manager.add_to_blacklist('192.168.1.100', 'ip')
            >>> await manager.add_to_blacklist('malicious.com', 'domain')
        """
        async with self._lock:
            try:
                if blacklist_type == 'ip':
                    # 验证 IP 地址格式
                    ipaddress.ip_address(item)
                    self._ip_blacklist.add(item)

                elif blacklist_type == 'ip_range':
                    # 验证 IP 范围格式
                    ipaddress.ip_network(item, strict=False)
                    if item not in self._ip_range_blacklist:
                        self._ip_range_blacklist.append(item)

                elif blacklist_type == 'domain':
                    if not item or not isinstance(item, str):
                        raise BlacklistError(f"无效的域名: {item}")
                    self._domain_blacklist.add(item)

                elif blacklist_type == 'url':
                    if not item or not isinstance(item, str):
                        raise BlacklistError(f"无效的 URL: {item}")
                    self._url_blacklist.add(item)

                elif blacklist_type == 'url_pattern':
                    # 验证正则表达式格式
                    try:
                        compiled = re.compile(item)
                        if compiled not in self._url_pattern_blacklist:
                            self._url_pattern_blacklist.append(compiled)
                    except re.error as e:
                        raise BlacklistError(f"无效的正则表达式 '{item}': {e}")

                else:
                    raise BlacklistError(f"无效的黑名单类型: {blacklist_type}")

                # 保存到配置文件
                if save:
                    await self._save_config()

                return True

            except ValueError as e:
                raise BlacklistError(f"无效的项目格式: {e}")
            except Exception as e:
                if isinstance(e, BlacklistError):
                    raise
                raise BlacklistError(f"添加到黑名单失败: {e}")

    async def remove_from_blacklist(self,
                                    item: str,
                                    blacklist_type: str,
                                    save: bool = True) -> bool:
        """
        从黑名单移除

        Args:
            item: 要移除的项目
            blacklist_type: 黑名单类型，可选值：'ip', 'ip_range', 'domain', 'url', 'url_pattern'
            save: 是否保存到配置文件，默认为 True

        Returns:
            bool: 是否成功移除

        Raises:
            BlacklistError: 黑名单类型无效

        Examples:
            >>> await manager.remove_from_blacklist('192.168.1.100', 'ip')
            >>> await manager.remove_from_blacklist('malicious.com', 'domain')
        """
        async with self._lock:
            try:
                removed = False

                if blacklist_type == 'ip':
                    if item in self._ip_blacklist:
                        self._ip_blacklist.discard(item)
                        removed = True

                elif blacklist_type == 'ip_range':
                    if item in self._ip_range_blacklist:
                        self._ip_range_blacklist.remove(item)
                        removed = True

                elif blacklist_type == 'domain':
                    if item in self._domain_blacklist:
                        self._domain_blacklist.discard(item)
                        removed = True

                elif blacklist_type == 'url':
                    if item in self._url_blacklist:
                        self._url_blacklist.discard(item)
                        removed = True

                elif blacklist_type == 'url_pattern':
                    # 查找并移除匹配的正则表达式
                    for i, pattern in enumerate(self._url_pattern_blacklist):
                        if pattern.pattern == item:
                            self._url_pattern_blacklist.pop(i)
                            removed = True
                            break

                else:
                    raise BlacklistError(f"无效的黑名单类型: {blacklist_type}")

                # 保存到配置文件
                if save and removed:
                    await self._save_config()

                return removed

            except Exception as e:
                if isinstance(e, BlacklistError):
                    raise
                raise BlacklistError(f"从黑名单移除失败: {e}")

    async def add_to_whitelist(self,
                               item: str,
                               whitelist_type: str,
                               save: bool = True) -> bool:
        """
        添加到白名单

        Args:
            item: 要添加的项目
            whitelist_type: 白名单类型，可选值：'ip', 'domain'
            save: 是否保存到配置文件，默认为 True

        Returns:
            bool: 是否成功添加

        Raises:
            BlacklistError: 白名单类型无效或项目格式错误

        Examples:
            >>> await manager.add_to_whitelist('192.168.1.100', 'ip')
            >>> await manager.add_to_whitelist('trusted.com', 'domain')
        """
        async with self._lock:
            try:
                if whitelist_type == 'ip':
                    # 验证 IP 地址格式
                    ipaddress.ip_address(item)
                    self._ip_whitelist.add(item)

                elif whitelist_type == 'domain':
                    if not item or not isinstance(item, str):
                        raise BlacklistError(f"无效的域名: {item}")
                    self._domain_whitelist.add(item)

                else:
                    raise BlacklistError(f"无效的白名单类型: {whitelist_type}")

                # 保存到配置文件
                if save:
                    await self._save_config()

                return True

            except ValueError as e:
                raise BlacklistError(f"无效的项目格式: {e}")
            except Exception as e:
                if isinstance(e, BlacklistError):
                    raise
                raise BlacklistError(f"添加到白名单失败: {e}")

    async def remove_from_whitelist(self,
                                    item: str,
                                    whitelist_type: str,
                                    save: bool = True) -> bool:
        """
        从白名单移除

        Args:
            item: 要移除的项目
            whitelist_type: 白名单类型，可选值：'ip', 'domain'
            save: 是否保存到配置文件，默认为 True

        Returns:
            bool: 是否成功移除

        Raises:
            BlacklistError: 白名单类型无效

        Examples:
            >>> await manager.remove_from_whitelist('192.168.1.100', 'ip')
        """
        async with self._lock:
            try:
                removed = False

                if whitelist_type == 'ip':
                    if item in self._ip_whitelist:
                        self._ip_whitelist.discard(item)
                        removed = True

                elif whitelist_type == 'domain':
                    if item in self._domain_whitelist:
                        self._domain_whitelist.discard(item)
                        removed = True

                else:
                    raise BlacklistError(f"无效的白名单类型: {whitelist_type}")

                # 保存到配置文件
                if save and removed:
                    await self._save_config()

                return removed

            except Exception as e:
                if isinstance(e, BlacklistError):
                    raise
                raise BlacklistError(f"从白名单移除失败: {e}")

    async def _save_config(self) -> None:
        """
        保存黑名单配置到文件

        Raises:
            BlacklistConfigError: 保存配置文件失败
        """
        try:
            # 构建配置字典
            config = {
                "_comment": "SilkRoad-Next V2 黑名单配置文件",
                "_description": "用于访问控制的黑名单和白名单配置，支持 IP、域名、URL 等多种拦截策略",
                "ip_blacklist": list(self._ip_blacklist),
                "ip_range_blacklist": self._ip_range_blacklist,
                "domain_blacklist": list(self._domain_blacklist),
                "url_blacklist": list(self._url_blacklist),
                "url_pattern_blacklist": [p.pattern for p in self._url_pattern_blacklist],
                "ip_whitelist": list(self._ip_whitelist),
                "domain_whitelist": list(self._domain_whitelist)
            }

            # 创建配置文件目录
            config_dir = os.path.dirname(self.config_file)
            if config_dir:
                os.makedirs(config_dir, exist_ok=True)

            # 保存到文件
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

            # 更新最后修改时间
            self._last_modified = os.path.getmtime(self.config_file)

        except PermissionError:
            raise BlacklistConfigError(f"无权限保存配置文件: {self.config_file}")
        except OSError as e:
            raise BlacklistConfigError(f"保存配置文件失败: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """
        获取黑名单统计信息

        Returns:
            Dict[str, Any]: 统计信息字典

        Examples:
            >>> stats = manager.get_stats()
            >>> print(f"Total blocked: {stats['total_blocked']}")
        """
        return {
            **self.stats,
            'ip_blacklist_count': len(self._ip_blacklist),
            'ip_range_blacklist_count': len(self._ip_range_blacklist),
            'domain_blacklist_count': len(self._domain_blacklist),
            'url_blacklist_count': len(self._url_blacklist),
            'url_pattern_count': len(self._url_pattern_blacklist),
            'ip_whitelist_count': len(self._ip_whitelist),
            'domain_whitelist_count': len(self._domain_whitelist)
        }

    def get_blacklist_items(self, blacklist_type: str) -> List[str]:
        """
        获取黑名单项目列表

        Args:
            blacklist_type: 黑名单类型，可选值：'ip', 'ip_range', 'domain', 'url', 'url_pattern'

        Returns:
            List[str]: 黑名单项目列表

        Examples:
            >>> ips = manager.get_blacklist_items('ip')
            >>> print(f"Blocked IPs: {ips}")
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

    def get_whitelist_items(self, whitelist_type: str) -> List[str]:
        """
        获取白名单项目列表

        Args:
            whitelist_type: 白名单类型，可选值：'ip', 'domain'

        Returns:
            List[str]: 白名单项目列表

        Examples:
            >>> ips = manager.get_whitelist_items('ip')
            >>> print(f"Whitelisted IPs: {ips}")
        """
        if whitelist_type == 'ip':
            return list(self._ip_whitelist)
        elif whitelist_type == 'domain':
            return list(self._domain_whitelist)
        else:
            return []

    async def clear_blacklist(self, blacklist_type: str, save: bool = True) -> bool:
        """
        清空指定类型的黑名单

        Args:
            blacklist_type: 黑名单类型，可选值：'ip', 'ip_range', 'domain', 'url', 'url_pattern', 'all'
            save: 是否保存到配置文件，默认为 True

        Returns:
            bool: 是否成功清空

        Examples:
            >>> await manager.clear_blacklist('ip')
            >>> await manager.clear_blacklist('all')
        """
        async with self._lock:
            try:
                if blacklist_type == 'ip':
                    self._ip_blacklist.clear()
                elif blacklist_type == 'ip_range':
                    self._ip_range_blacklist.clear()
                elif blacklist_type == 'domain':
                    self._domain_blacklist.clear()
                elif blacklist_type == 'url':
                    self._url_blacklist.clear()
                elif blacklist_type == 'url_pattern':
                    self._url_pattern_blacklist.clear()
                elif blacklist_type == 'all':
                    self._ip_blacklist.clear()
                    self._ip_range_blacklist.clear()
                    self._domain_blacklist.clear()
                    self._url_blacklist.clear()
                    self._url_pattern_blacklist.clear()
                else:
                    return False

                # 保存到配置文件
                if save:
                    await self._save_config()

                return True

            except Exception:
                return False

    async def clear_whitelist(self, whitelist_type: str, save: bool = True) -> bool:
        """
        清空指定类型的白名单

        Args:
            whitelist_type: 白名单类型，可选值：'ip', 'domain', 'all'
            save: 是否保存到配置文件，默认为 True

        Returns:
            bool: 是否成功清空

        Examples:
            >>> await manager.clear_whitelist('ip')
            >>> await manager.clear_whitelist('all')
        """
        async with self._lock:
            try:
                if whitelist_type == 'ip':
                    self._ip_whitelist.clear()
                elif whitelist_type == 'domain':
                    self._domain_whitelist.clear()
                elif whitelist_type == 'all':
                    self._ip_whitelist.clear()
                    self._domain_whitelist.clear()
                else:
                    return False

                # 保存到配置文件
                if save:
                    await self._save_config()

                return True

            except Exception:
                return False

    def reset_stats(self) -> None:
        """
        重置统计信息

        将所有统计计数器归零。
        """
        self.stats = {
            'total_blocked': 0,
            'ip_blocked': 0,
            'domain_blocked': 0,
            'url_blocked': 0,
            'whitelist_allowed': 0,
            'config_reloads': 0
        }

    def is_ip_in_blacklist(self, ip: str) -> Tuple[bool, str]:
        """
        检查 IP 是否在黑名单中（同步方法）

        Args:
            ip: IP 地址

        Returns:
            Tuple[bool, str]: (是否在黑名单中, 原因)
        """
        # 检查白名单
        if ip in self._ip_whitelist:
            return False, f"IP {ip} in whitelist"

        # 检查 IP 黑名单
        if ip in self._ip_blacklist:
            return True, f"IP {ip} is blacklisted"

        # 检查 IP 范围黑名单
        try:
            ip_obj = ipaddress.ip_address(ip)
            for ip_range in self._ip_range_blacklist:
                try:
                    network = ipaddress.ip_network(ip_range, strict=False)
                    if ip_obj in network:
                        return True, f"IP {ip} in blacklisted range {ip_range}"
                except ValueError:
                    continue
        except ValueError:
            pass

        return False, "Not in blacklist"

    def is_domain_in_blacklist(self, domain: str) -> Tuple[bool, str]:
        """
        检查域名是否在黑名单中（同步方法）

        Args:
            domain: 域名

        Returns:
            Tuple[bool, str]: (是否在黑名单中, 原因)
        """
        # 检查白名单
        if domain in self._domain_whitelist:
            return False, f"Domain {domain} in whitelist"

        # 检查域名黑名单
        if domain in self._domain_blacklist:
            return True, f"Domain {domain} is blacklisted"

        return False, "Not in blacklist"

    def is_url_in_blacklist(self, url: str) -> Tuple[bool, str]:
        """
        检查 URL 是否在黑名单中（同步方法）

        Args:
            url: URL 路径

        Returns:
            Tuple[bool, str]: (是否在黑名单中, 原因)
        """
        # 检查 URL 黑名单（精确匹配）
        if url in self._url_blacklist:
            return True, f"URL {url} is blacklisted"

        # 检查 URL 正则表达式
        for pattern in self._url_pattern_blacklist:
            if pattern.search(url):
                return True, f"URL {url} matches blacklisted pattern {pattern.pattern}"

        return False, "Not in blacklist"

    def __repr__(self) -> str:
        """返回黑名单管理器的字符串表示"""
        return (
            f"BlacklistManager("
            f"config_file='{self.config_file}', "
            f"ip_blacklist={len(self._ip_blacklist)}, "
            f"ip_range_blacklist={len(self._ip_range_blacklist)}, "
            f"domain_blacklist={len(self._domain_blacklist)}, "
            f"url_blacklist={len(self._url_blacklist)}, "
            f"url_pattern_blacklist={len(self._url_pattern_blacklist)}, "
            f"ip_whitelist={len(self._ip_whitelist)}, "
            f"domain_whitelist={len(self._domain_whitelist)})"
        )


async def create_blacklist_manager(config_file: str = 'databases/blacklist.json') -> BlacklistManager:
    """
    创建并初始化黑名单管理器

    Args:
        config_file: 黑名单配置文件路径

    Returns:
        BlacklistManager: 初始化后的黑名单管理器

    Examples:
        >>> manager = await create_blacklist_manager('databases/blacklist.json')
        >>> is_blocked, reason = await manager.is_blocked('192.168.1.1', '/page', 'example.com')
    """
    manager = BlacklistManager(config_file)
    await manager.initialize()
    return manager
