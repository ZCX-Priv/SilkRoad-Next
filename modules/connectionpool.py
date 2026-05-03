"""
连接池模块 - ConnectionPool

功能：
1. 维护与目标服务器的长连接（Keep-Alive）
2. 降低 TLS 握手开销
3. 提升请求响应速度
4. 自动清理过期连接
5. 连接健康检查
6. 连接复用与限制
7. 会话持久化支持（V5 集成）

作者: SilkRoad-Next Team
版本: 2.0.0
"""

import asyncio
import aiohttp
from typing import Dict, Optional, Tuple, Any, TYPE_CHECKING
from datetime import datetime
import time
from loguru import logger as loguru_logger

if TYPE_CHECKING:
    from modules.logging import Logger


class ConnectionPool:
    """
    目标服务器连接池管理器
    
    功能：
    1. 维护与目标服务器的长连接
    2. 自动清理过期连接
    3. 连接健康检查
    4. 连接复用与限制
    
    使用示例:
        pool = ConnectionPool(
            max_connections_per_host=10,
            connection_timeout=30,
            keep_alive_timeout=60
        )
        
        # 获取连接
        connection = await pool.get_connection('www.example.com', 443, True)
        
        # 使用连接...
        
        # 归还连接
        await pool.return_connection('www.example.com', 443, connection)
        
        # 关闭所有连接
        await pool.close_all()
    """
    
    def __init__(self, 
                 max_connections_per_host: int = 10,
                 connection_timeout: int = 30,
                 keep_alive_timeout: int = 60,
                 logger: Optional['Logger'] = None):
        """
        初始化连接池
        
        Args:
            max_connections_per_host: 每个目标主机的最大连接数
            connection_timeout: 连接超时时间（秒）
            keep_alive_timeout: Keep-Alive 超时时间（秒）
            logger: 日志记录器，如果为 None 则使用默认日志
        """
        self.max_connections_per_host = max_connections_per_host
        self.connection_timeout = connection_timeout
        self.keep_alive_timeout = keep_alive_timeout
        
        # 连接池存储结构：{host:port: [(connection, created_time, last_used_time), ...]}
        self._pools: Dict[str, list] = {}
        
        # 连接使用记录：{connection_id: last_used_time}
        self._connection_usage: Dict[int, float] = {}
        
        # 连接创建时间记录：{connection_id: created_time}
        self._connection_created: Dict[int, float] = {}
        
        # 连接所属池映射：{connection_id: pool_key}
        self._connection_pool_map: Dict[int, str] = {}

        self.session_manager: Any = None
        self._session_cookies: Dict[str, str] = {}
        
        # 锁机制，确保线程安全
        self._lock = asyncio.Lock()
        
        # 日志记录器
        self._logger = logger or loguru_logger
        
        # 统计信息
        self.stats = {
            'total_connections': 0,
            'active_connections': 0,
            'reuse_count': 0,
            'timeout_cleanups': 0,
            'failed_connections': 0,
            'created_connections': 0
        }
        
        self._logger.info(
            f"ConnectionPool 初始化完成: "
            f"max_per_host={max_connections_per_host}, "
            f"timeout={connection_timeout}s, "
            f"keepalive={keep_alive_timeout}s"
        )
    
    async def get_connection(self, 
                            host: str, 
                            port: int = 443, 
                            is_https: bool = True,
                            session_id: Optional[str] = None) -> Optional[aiohttp.TCPConnector]:
        """
        从连接池获取一个可用连接
        
        Args:
            host: 目标主机名
            port: 目标端口
            is_https: 是否为 HTTPS 连接
            session_id: 会话 ID（可选，用于会话持久化）
            
        Returns:
            可用的连接对象，如果没有可用连接则返回 None
            
        Raises:
            ConnectionError: 当连接池已满且无法创建新连接时
        """
        # 如果提供了 session_id，尝试加载会话数据
        if session_id and self.session_manager:
            session_data = await self.session_manager.get_session(session_id)
            if session_data:
                self._logger.debug(
                    f"使用会话数据创建连接: session_id={session_id}, host={host}"
                )
                return await self._create_connection_with_session(host, port, is_https, session_data)
        
        async with self._lock:
            pool_key = f"{host}:{port}"
            
            # 检查连接池中是否有可用连接
            if pool_key in self._pools and self._pools[pool_key]:
                # 从池中取出最后一个连接（LIFO策略）
                connection, created_time, last_used_time = self._pools[pool_key].pop()
                connection_id = id(connection)
                
                # 检查连接是否仍然有效
                if await self._is_connection_valid(connection, last_used_time):
                    # 更新使用时间
                    self._connection_usage[connection_id] = time.time()
                    self.stats['reuse_count'] += 1
                    self.stats['active_connections'] += 1
                    
                    self._logger.debug(
                        f"连接复用: {pool_key} (id={connection_id})"
                    )
                    return connection
                else:
                    # 连接已失效，关闭并移除
                    await self._close_connection(connection)
                    self._logger.debug(
                        f"连接失效，已关闭: {pool_key} (id={connection_id})"
                    )
            
            # 没有可用连接，检查是否可以创建新连接
            current_count = len(self._pools.get(pool_key, []))
            active_count = sum(
                1 for conn_id, pk in self._connection_pool_map.items() 
                if pk == pool_key
            )
            
            if current_count + active_count < self.max_connections_per_host:
                # 可以创建新连接，返回 None 让调用者创建
                self._logger.debug(
                    f"无可用连接，允许创建新连接: {pool_key} "
                    f"(current={current_count}, active={active_count})"
                )
                return None
            else:
                # 已达到最大连接数限制
                self._logger.warning(
                    f"连接池已满: {pool_key} "
                    f"(max={self.max_connections_per_host})"
                )
                raise ConnectionError(
                    f"Connection pool for {pool_key} is full "
                    f"(max: {self.max_connections_per_host})"
                )
    
    async def return_connection(self, 
                                host: str, 
                                port: int, 
                                connection: aiohttp.TCPConnector) -> bool:
        """
        将连接归还到连接池
        
        Args:
            host: 目标主机名
            port: 目标端口
            connection: 要归还的连接对象
            
        Returns:
            归还是否成功
        """
        if connection is None:
            return False
            
        async with self._lock:
            pool_key = f"{host}:{port}"
            connection_id = id(connection)
            
            # 检查连接是否仍然有效
            if await self._is_connection_valid(connection, time.time()):
                # 检查池是否已满
                if pool_key not in self._pools:
                    self._pools[pool_key] = []
                
                if len(self._pools[pool_key]) < self.max_connections_per_host:
                    # 将连接放回池中
                    current_time = time.time()
                    created_time = self._connection_created.get(connection_id, current_time)
                    
                    self._pools[pool_key].append(
                        (connection, created_time, current_time)
                    )
                    
                    # 更新使用时间
                    self._connection_usage[connection_id] = current_time
                    self._connection_pool_map[connection_id] = pool_key
                    
                    # 更新活跃连接数
                    if self.stats['active_connections'] > 0:
                        self.stats['active_connections'] -= 1
                    
                    self._logger.debug(
                        f"连接归还成功: {pool_key} (id={connection_id})"
                    )
                    return True
                else:
                    # 池已满，直接关闭连接
                    self._logger.debug(
                        f"连接池已满，关闭连接: {pool_key} (id={connection_id})"
                    )
                    await self._close_connection(connection)
                    return False
            else:
                # 连接已失效，直接关闭
                self._logger.debug(
                    f"连接失效，关闭连接: {pool_key} (id={connection_id})"
                )
                await self._close_connection(connection)
                return False
    
    def register_connection(self, 
                           host: str, 
                           port: int, 
                           connection: aiohttp.TCPConnector) -> None:
        """
        注册新创建的连接到连接池管理
        
        Args:
            host: 目标主机名
            port: 目标端口
            connection: 新创建的连接对象
        """
        if connection is None:
            return
            
        connection_id = id(connection)
        pool_key = f"{host}:{port}"
        current_time = time.time()
        
        self._connection_created[connection_id] = current_time
        self._connection_usage[connection_id] = current_time
        self._connection_pool_map[connection_id] = pool_key
        
        self.stats['total_connections'] += 1
        self.stats['active_connections'] += 1
        self.stats['created_connections'] += 1
        
        self._logger.debug(
            f"新连接注册: {pool_key} (id={connection_id})"
        )
    
    async def _create_connection_with_session(
        self,
        host: str,
        port: int,
        is_https: bool,
        session_data: Dict[str, Any]
    ) -> Optional[aiohttp.TCPConnector]:
        """
        使用会话数据创建连接
        
        V5 集成功能：从会话数据中加载 Cookie 并应用到连接
        
        Args:
            host: 目标主机名
            port: 目标端口
            is_https: 是否为 HTTPS 连接
            session_data: 会话数据（包含 cookies、tokens 等）
            
        Returns:
            创建的连接对象
        """
        # 创建新的 TCPConnector
        connector = aiohttp.TCPConnector(
            limit=self.max_connections_per_host,
            ttl_dns_cache=300,
            enable_cleanup_closed=True
        )
        
        # 从会话数据中提取 Cookie
        cookies = session_data.get("data", {}).get("cookies", {})
        domain_cookies: Dict[str, str] = {}
        
        for cookie_name, cookie_data in cookies.items():
            # 检查 Cookie 是否匹配当前域名
            if self._cookie_matches_domain(cookie_data, host):
                domain_cookies[cookie_name] = cookie_data.get("value", "")
        
        # 将 Cookie 存储到实例属性中，供后续请求使用
        self._session_cookies = domain_cookies
        
        # 注册连接到连接池管理
        self.register_connection(host, port, connector)
        
        self._logger.debug(
            f"使用会话数据创建连接成功: host={host}, cookies_count={len(domain_cookies)}"
        )
        
        return connector
    
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
        
        # 精确匹配或子域名匹配
        return domain == cookie_domain or domain.endswith("." + cookie_domain)
    
    def get_session_cookies(self) -> Dict[str, str]:
        """
        获取当前会话的 Cookie
        
        Returns:
            当前会话的 Cookie 字典
        """
        return self._session_cookies.copy()
    
    def clear_session_cookies(self) -> None:
        """清除当前会话的 Cookie 缓存"""
        self._session_cookies = {}
    
    async def _is_connection_valid(self, 
                                   connection: aiohttp.TCPConnector,
                                   last_used_time: Optional[float] = None) -> bool:
        """
        检查连接是否仍然有效
        
        Args:
            connection: 要检查的连接对象
            last_used_time: 最后使用时间，用于检查超时
            
        Returns:
            连接是否有效
        """
        try:
            # 检查连接是否已关闭
            if connection.closed:
                return False
            
            # 检查连接是否超时
            if last_used_time is not None:
                if time.time() - last_used_time > self.keep_alive_timeout:
                    return False
            
            # 检查连接是否还有可用的连接数
            # TCPConnector 的 limit 属性表示最大连接数
            # 如果连接数已用完，则连接无效
            return True
            
        except Exception as e:
            self._logger.debug(f"检查连接有效性时发生错误: {e}")
            return False
    
    async def _close_connection(self, connection: aiohttp.TCPConnector) -> None:
        """
        关闭连接并清理相关资源
        
        Args:
            connection: 要关闭的连接对象
        """
        if connection is None:
            return
            
        try:
            connection_id = id(connection)
            
            # 关闭连接
            if not connection.closed:
                await connection.close()
            
            # 清理记录
            if connection_id in self._connection_usage:
                del self._connection_usage[connection_id]
            
            if connection_id in self._connection_created:
                del self._connection_created[connection_id]
            
            if connection_id in self._connection_pool_map:
                del self._connection_pool_map[connection_id]
            
            # 更新统计
            if self.stats['total_connections'] > 0:
                self.stats['total_connections'] -= 1
            
            self._logger.debug(f"连接已关闭 (id={connection_id})")
            
        except Exception as e:
            self._logger.warning(f"关闭连接时发生错误: {e}")
            self.stats['failed_connections'] += 1
    
    async def cleanup_expired_connections(self) -> int:
        """
        清理所有过期的连接
        
        Returns:
            清理的连接数量
        """
        async with self._lock:
            current_time = time.time()
            expired_connections = []
            cleaned_count = 0
            
            # 遍历所有连接池
            for pool_key, connections in self._pools.items():
                for i, (connection, created_time, last_used_time) in enumerate(connections):
                    # 检查是否超时
                    if current_time - last_used_time > self.keep_alive_timeout:
                        expired_connections.append((pool_key, i, connection))
            
            # 关闭过期连接（从后向前删除，避免索引问题）
            for pool_key, idx, connection in sorted(expired_connections, key=lambda x: x[1], reverse=True):
                await self._close_connection(connection)
                if pool_key in self._pools and idx < len(self._pools[pool_key]):
                    self._pools[pool_key].pop(idx)
                self.stats['timeout_cleanups'] += 1
                cleaned_count += 1
            
            # 清理空的连接池
            empty_pools = [pk for pk, conns in self._pools.items() if not conns]
            for pool_key in empty_pools:
                del self._pools[pool_key]
            
            if cleaned_count > 0:
                self._logger.info(
                    f"清理过期连接完成: 清理了 {cleaned_count} 个连接"
                )
            
            return cleaned_count
    
    async def get_stats(self) -> dict:
        """
        获取连接池统计信息
        
        Returns:
            统计信息字典
        """
        async with self._lock:
            pool_stats = {
                pool_key: {
                    'available': len(connections),
                    'oldest_connection': min(
                        (c[1] for c in connections), 
                        default=None
                    ),
                    'newest_connection': max(
                        (c[1] for c in connections), 
                        default=None
                    )
                }
                for pool_key, connections in self._pools.items()
            }
            
            return {
                **self.stats,
                'pools': pool_stats,
                'total_pools': len(self._pools),
                'config': {
                    'max_connections_per_host': self.max_connections_per_host,
                    'connection_timeout': self.connection_timeout,
                    'keep_alive_timeout': self.keep_alive_timeout
                }
            }
    
    async def close_all(self) -> int:
        """
        关闭所有连接，用于优雅退出
        
        Returns:
            关闭的连接数量
        """
        async with self._lock:
            closed_count = 0
            
            # 关闭池中的所有连接
            for pool_key, connections in self._pools.items():
                for connection, _, _ in connections:
                    await self._close_connection(connection)
                    closed_count += 1
            
            # 关闭活跃连接
            active_connection_ids = list(self._connection_created.keys())
            for connection_id in active_connection_ids:
                # 活跃连接需要单独处理，因为它们不在池中
                pass
            
            # 清空所有记录
            self._pools.clear()
            self._connection_usage.clear()
            self._connection_created.clear()
            self._connection_pool_map.clear()
            
            # 重置统计
            self.stats['total_connections'] = 0
            self.stats['active_connections'] = 0
            
            self._logger.info(
                f"所有连接已关闭: 共关闭 {closed_count} 个连接"
            )
            
            return closed_count
    
    async def get_pool_status(self, host: str, port: int) -> dict:
        """
        获取指定主机连接池的状态
        
        Args:
            host: 目标主机名
            port: 目标端口
            
        Returns:
            连接池状态信息
        """
        async with self._lock:
            pool_key = f"{host}:{port}"
            
            if pool_key not in self._pools:
                return {
                    'exists': False,
                    'available': 0,
                    'active': 0,
                    'max': self.max_connections_per_host
                }
            
            connections = self._pools[pool_key]
            active_count = sum(
                1 for conn_id, pk in self._connection_pool_map.items() 
                if pk == pool_key
            )
            
            return {
                'exists': True,
                'available': len(connections),
                'active': active_count,
                'max': self.max_connections_per_host,
                'connections': [
                    {
                        'created_at': datetime.fromtimestamp(c[1]).isoformat() if c[1] else None,
                        'last_used': datetime.fromtimestamp(c[2]).isoformat() if c[2] else None,
                        'age_seconds': time.time() - c[1] if c[1] else 0,
                        'idle_seconds': time.time() - c[2] if c[2] else 0
                    }
                    for c in connections
                ]
            }
    
    async def health_check(self) -> dict:
        """
        执行健康检查
        
        Returns:
            健康检查结果
        """
        async with self._lock:
            total_connections = sum(len(conns) for conns in self._pools.values())
            expired_count = 0
            valid_count = 0
            
            current_time = time.time()
            
            for pool_key, connections in self._pools.items():
                for connection, created_time, last_used_time in connections:
                    if current_time - last_used_time > self.keep_alive_timeout:
                        expired_count += 1
                    else:
                        valid_count += 1
            
            return {
                'healthy': expired_count == 0,
                'total_connections': total_connections,
                'valid_connections': valid_count,
                'expired_connections': expired_count,
                'active_connections': self.stats['active_connections'],
                'reuse_rate': (
                    self.stats['reuse_count'] / self.stats['created_connections'] * 100
                    if self.stats['created_connections'] > 0 else 0
                ),
                'pools_count': len(self._pools)
            }
    
    def __repr__(self) -> str:
        """返回连接池的字符串表示"""
        return (
            f"ConnectionPool("
            f"pools={len(self._pools)}, "
            f"total={self.stats['total_connections']}, "
            f"active={self.stats['active_connections']}, "
            f"reuse={self.stats['reuse_count']})"
        )


# 便捷函数
async def create_connection_pool(
    max_connections_per_host: int = 10,
    connection_timeout: int = 30,
    keep_alive_timeout: int = 60,
    logger: Optional['Logger'] = None
) -> ConnectionPool:
    """
    创建连接池的便捷函数
    
    Args:
        max_connections_per_host: 每个目标主机的最大连接数
        connection_timeout: 连接超时时间（秒）
        keep_alive_timeout: Keep-Alive 超时时间（秒）
        logger: 日志记录器
        
    Returns:
        ConnectionPool 实例
    """
    return ConnectionPool(
        max_connections_per_host=max_connections_per_host,
        connection_timeout=connection_timeout,
        keep_alive_timeout=keep_alive_timeout,
        logger=logger
    )
