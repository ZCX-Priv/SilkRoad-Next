"""
连接池管理模块

该模块实现了目标服务器连接池管理器，用于维护与高频目标服务器的长连接（Keep-Alive），
降低 TLS 握手开销，提升请求响应速度。

主要功能：
1. 按主机名维护连接池
2. 最大连接数限制（每主机默认 10 个）
3. 连接超时检测（默认 60 秒）
4. 连接健康检查
5. 连接复用和归还
6. 自动清理过期连接
7. 连接统计信息查询
8. 关闭所有连接

作者: SilkRoad-Next Team
版本: V2.0
"""

import asyncio
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime

try:
    import aiohttp
except ImportError:
    aiohttp = None


class ConnectionPoolError(Exception):
    """连接池相关错误的基类"""
    pass


class ConnectionPoolFullError(ConnectionPoolError):
    """连接池已满错误"""
    pass


class ConnectionInvalidError(ConnectionPoolError):
    """连接无效错误"""
    pass


class ConnectionPool:
    """
    目标服务器连接池管理器
    
    该类负责管理与目标服务器的长连接，支持连接复用、健康检查、超时清理等功能。
    使用异步锁确保线程安全，适用于高并发场景。
    
    Attributes:
        max_connections_per_host (int): 每个目标主机的最大连接数
        connection_timeout (int): 连接超时时间（秒）
        keep_alive_timeout (int): Keep-Alive 超时时间（秒）
        stats (dict): 连接池统计信息
    
    Example:
        >>> pool = ConnectionPool(max_connections_per_host=10)
        >>> connection = await pool.get_connection('www.example.com', 443, True)
        >>> # 使用连接...
        >>> await pool.return_connection('www.example.com', 443, connection)
    """
    
    def __init__(self, 
                 max_connections_per_host: int = 10,
                 connection_timeout: int = 30,
                 keep_alive_timeout: int = 60):
        """
        初始化连接池
        
        Args:
            max_connections_per_host: 每个目标主机的最大连接数，默认为 10
            connection_timeout: 连接超时时间（秒），默认为 30 秒
            keep_alive_timeout: Keep-Alive 超时时间（秒），默认为 60 秒
            
        Raises:
            ValueError: 如果参数值无效
        """
        # 参数验证
        if max_connections_per_host <= 0:
            raise ValueError("max_connections_per_host must be positive")
        if connection_timeout <= 0:
            raise ValueError("connection_timeout must be positive")
        if keep_alive_timeout <= 0:
            raise ValueError("keep_alive_timeout must be positive")
        
        self.max_connections_per_host = max_connections_per_host
        self.connection_timeout = connection_timeout
        self.keep_alive_timeout = keep_alive_timeout
        
        # 连接池存储结构：{host:port: [connection1, connection2, ...]}
        self._pools: Dict[str, List] = {}
        
        # 连接使用记录：{connection_id: last_used_time}
        self._connection_usage: Dict[int, float] = {}
        
        # 连接创建时间记录：{connection_id: created_time}
        self._connection_created: Dict[int, float] = {}
        
        # 连接元数据：{connection_id: (host, port)}
        self._connection_metadata: Dict[int, Tuple[str, int]] = {}
        
        # 锁机制，确保线程安全
        self._lock = asyncio.Lock()
        
        # 统计信息
        self.stats = {
            'total_connections': 0,
            'active_connections': 0,
            'reuse_count': 0,
            'timeout_cleanups': 0,
            'failed_connections': 0
        }
    
    def _get_pool_key(self, host: str, port: int) -> str:
        """
        生成连接池键
        
        Args:
            host: 目标主机名
            port: 目标端口
            
        Returns:
            连接池键字符串
        """
        return f"{host}:{port}"
    
    async def get_connection(self, 
                            host: str, 
                            port: int = 443, 
                            is_https: bool = True) -> Optional['aiohttp.TCPConnector']:
        """
        从连接池获取一个可用连接
        
        该方法尝试从连接池中获取一个可用的连接。如果连接池中有可用连接，
        则返回该连接；如果没有可用连接且未达到最大连接数限制，则返回 None，
        允许调用者创建新连接；如果已达到最大连接数限制，则抛出异常。
        
        Args:
            host: 目标主机名
            port: 目标端口，默认为 443
            is_https: 是否为 HTTPS 连接，默认为 True
            
        Returns:
            可用的连接对象，如果没有可用连接则返回 None
            
        Raises:
            ConnectionPoolFullError: 连接池已满，无法创建新连接
            ConnectionInvalidError: 连接验证失败
            
        Note:
            使用 LIFO（后进先出）策略，优先使用最近归还的连接
        """
        async with self._lock:
            pool_key = self._get_pool_key(host, port)
            
            # 检查连接池中是否有可用连接
            if pool_key in self._pools and self._pools[pool_key]:
                # 从池中取出最后一个连接（LIFO策略）
                connection = self._pools[pool_key].pop()
                
                # 检查连接是否仍然有效
                if await self._is_connection_valid(connection):
                    # 更新使用时间
                    connection_id = id(connection)
                    self._connection_usage[connection_id] = time.time()
                    
                    # 更新统计
                    self.stats['reuse_count'] += 1
                    self.stats['active_connections'] += 1
                    
                    return connection
                else:
                    # 连接已失效，关闭并移除
                    await self._close_connection(connection)
                    # 递归尝试获取下一个连接
                    if self._pools.get(pool_key):
                        return await self.get_connection(host, port, is_https)
            
            # 没有可用连接，检查是否可以创建新连接
            current_count = self._count_active_connections(pool_key)
            if current_count < self.max_connections_per_host:
                # 可以创建新连接，返回 None 让调用者创建
                return None
            else:
                # 已达到最大连接数限制
                raise ConnectionPoolFullError(
                    f"Connection pool for {pool_key} is full "
                    f"(max: {self.max_connections_per_host})"
                )
    
    def _count_active_connections(self, pool_key: str) -> int:
        """
        计算指定连接池的活跃连接数
        
        Args:
            pool_key: 连接池键
            
        Returns:
            活跃连接数
        """
        # 池中的空闲连接数
        idle_count = len(self._pools.get(pool_key, []))
        
        # 正在使用的连接数（需要从元数据中统计）
        active_count = 0
        for conn_id, (host, port) in self._connection_metadata.items():
            if self._get_pool_key(host, port) == pool_key:
                if conn_id not in [id(c) for c in self._pools.get(pool_key, [])]:
                    active_count += 1
        
        return idle_count + active_count
    
    async def return_connection(self, 
                                host: str, 
                                port: int, 
                                connection: 'aiohttp.TCPConnector') -> bool:
        """
        将连接归还到连接池
        
        该方法将使用完毕的连接归还到连接池中，以便后续复用。
        如果连接已失效，则会直接关闭而不归还。
        
        Args:
            host: 目标主机名
            port: 目标端口
            connection: 要归还的连接对象
            
        Returns:
            连接是否成功归还到池中
            
        Note:
            归还前会自动检查连接有效性
        """
        if connection is None:
            return False
        
        async with self._lock:
            pool_key = self._get_pool_key(host, port)
            
            # 检查连接是否仍然有效
            if await self._is_connection_valid(connection):
                # 初始化连接池（如果不存在）
                if pool_key not in self._pools:
                    self._pools[pool_key] = []
                
                # 检查连接池是否已满
                if len(self._pools[pool_key]) >= self.max_connections_per_host:
                    # 连接池已满，直接关闭连接
                    await self._close_connection(connection)
                    return False
                
                # 将连接放回池中
                self._pools[pool_key].append(connection)
                
                # 更新使用时间和元数据
                connection_id = id(connection)
                self._connection_usage[connection_id] = time.time()
                self._connection_metadata[connection_id] = (host, port)
                
                # 更新统计
                if self.stats['active_connections'] > 0:
                    self.stats['active_connections'] -= 1
                
                return True
            else:
                # 连接已失效，直接关闭
                await self._close_connection(connection)
                return False
    
    async def _is_connection_valid(self, connection: 'aiohttp.TCPConnector') -> bool:
        """
        检查连接是否仍然有效
        
        该方法通过多个维度检查连接的有效性：
        1. 连接是否已关闭
        2. 连接是否超时
        3. 连接是否有异常
        
        Args:
            connection: 要检查的连接对象
            
        Returns:
            连接是否有效
        """
        try:
            # 检查连接对象是否存在
            if connection is None:
                return False
            
            # 检查连接是否已关闭
            if hasattr(connection, 'closed') and connection.closed:
                return False
            
            # 检查连接是否超时
            connection_id = id(connection)
            if connection_id in self._connection_usage:
                last_used = self._connection_usage[connection_id]
                idle_time = time.time() - last_used
                
                # 如果空闲时间超过 keep_alive_timeout，则认为连接已超时
                if idle_time > self.keep_alive_timeout:
                    return False
            
            # 检查连接创建时间
            if connection_id in self._connection_created:
                created_time = self._connection_created[connection_id]
                age = time.time() - created_time
                
                # 如果连接年龄超过最大生命周期（keep_alive_timeout * 2），则关闭
                if age > self.keep_alive_timeout * 2:
                    return False
            
            return True
            
        except Exception as e:
            # 任何异常都认为连接无效
            return False
    
    async def _close_connection(self, connection: 'aiohttp.TCPConnector'):
        """
        关闭连接并清理相关资源
        
        该方法安全地关闭连接，并清理所有相关的记录和元数据。
        
        Args:
            connection: 要关闭的连接对象
        """
        if connection is None:
            return
        
        try:
            connection_id = id(connection)
            
            # 关闭连接
            if hasattr(connection, 'closed') and not connection.closed:
                await connection.close()
            
            # 清理使用记录
            if connection_id in self._connection_usage:
                del self._connection_usage[connection_id]
            
            # 清理创建时间记录
            if connection_id in self._connection_created:
                del self._connection_created[connection_id]
            
            # 清理元数据
            if connection_id in self._connection_metadata:
                del self._connection_metadata[connection_id]
            
            # 更新统计
            if self.stats['total_connections'] > 0:
                self.stats['total_connections'] -= 1
                
        except Exception as e:
            # 记录错误但不抛出异常
            self.stats['failed_connections'] += 1
    
    async def cleanup_expired_connections(self) -> int:
        """
        清理所有过期的连接
        
        该方法遍历所有连接池，检查并关闭所有过期的连接。
        应该定期调用此方法以释放资源。
        
        Returns:
            清理的连接数量
        """
        async with self._lock:
            current_time = time.time()
            expired_connections: List[Tuple[str, 'aiohttp.TCPConnector']] = []
            
            # 遍历所有连接池
            for pool_key, connections in self._pools.items():
                # 使用切片创建副本进行遍历，避免修改迭代中的列表
                for connection in connections[:]:
                    connection_id = id(connection)
                    
                    # 检查是否超时
                    if connection_id in self._connection_usage:
                        last_used = self._connection_usage[connection_id]
                        idle_time = current_time - last_used
                        
                        if idle_time > self.keep_alive_timeout:
                            expired_connections.append((pool_key, connection))
                    else:
                        # 没有使用记录的连接也视为过期
                        expired_connections.append((pool_key, connection))
            
            # 关闭过期连接
            cleanup_count = 0
            for pool_key, connection in expired_connections:
                try:
                    await self._close_connection(connection)
                    
                    # 从连接池中移除
                    if pool_key in self._pools and connection in self._pools[pool_key]:
                        self._pools[pool_key].remove(connection)
                    
                    cleanup_count += 1
                except Exception as e:
                    # 忽略清理过程中的错误
                    pass
            
            # 更新统计
            if cleanup_count > 0:
                self.stats['timeout_cleanups'] += cleanup_count
            
            return cleanup_count
    
    async def health_check(self, host: str, port: int = 443) -> Dict[str, any]:
        """
        对指定主机的连接池进行健康检查
        
        该方法检查指定主机连接池的健康状况，包括连接数量、有效连接数等。
        
        Args:
            host: 目标主机名
            port: 目标端口，默认为 443
            
        Returns:
            健康检查结果字典，包含以下字段：
            - pool_key: 连接池键
            - total_connections: 总连接数
            - valid_connections: 有效连接数
            - invalid_connections: 无效连接数
            - is_healthy: 是否健康
        """
        async with self._lock:
            pool_key = self._get_pool_key(host, port)
            connections = self._pools.get(pool_key, [])
            
            valid_count = 0
            invalid_count = 0
            
            for connection in connections:
                if await self._is_connection_valid(connection):
                    valid_count += 1
                else:
                    invalid_count += 1
            
            return {
                'pool_key': pool_key,
                'total_connections': len(connections),
                'valid_connections': valid_count,
                'invalid_connections': invalid_count,
                'is_healthy': invalid_count == 0,
                'checked_at': datetime.now().isoformat()
            }
    
    async def get_stats(self) -> Dict[str, any]:
        """
        获取连接池统计信息
        
        该方法返回连接池的详细统计信息，包括总连接数、活跃连接数、
        复用次数、各主机连接池状态等。
        
        Returns:
            统计信息字典，包含以下字段：
            - total_connections: 总连接数
            - active_connections: 活跃连接数（正在使用中）
            - reuse_count: 连接复用次数
            - timeout_cleanups: 超时清理次数
            - failed_connections: 失败连接数
            - pools: 各主机连接池状态
            - pool_count: 连接池数量
        """
        async with self._lock:
            # 统计各连接池的连接数
            pool_stats = {}
            total_idle_connections = 0
            
            for pool_key, connections in self._pools.items():
                valid_count = 0
                for conn in connections:
                    if await self._is_connection_valid(conn):
                        valid_count += 1
                
                pool_stats[pool_key] = {
                    'total': len(connections),
                    'valid': valid_count,
                    'invalid': len(connections) - valid_count
                }
                total_idle_connections += len(connections)
            
            return {
                **self.stats,
                'idle_connections': total_idle_connections,
                'pools': pool_stats,
                'pool_count': len(self._pools),
                'max_connections_per_host': self.max_connections_per_host,
                'keep_alive_timeout': self.keep_alive_timeout
            }
    
    async def close_all(self):
        """
        关闭所有连接，用于优雅退出
        
        该方法关闭连接池中的所有连接，并清理所有相关资源。
        应该在程序退出前调用此方法以确保资源正确释放。
        """
        async with self._lock:
            # 关闭所有连接
            for pool_key, connections in self._pools.items():
                for connection in connections:
                    try:
                        await self._close_connection(connection)
                    except Exception as e:
                        # 忽略关闭过程中的错误
                        pass
            
            # 清空连接池
            self._pools.clear()
            self._connection_usage.clear()
            self._connection_created.clear()
            self._connection_metadata.clear()
            
            # 重置统计
            self.stats['total_connections'] = 0
            self.stats['active_connections'] = 0
    
    async def remove_pool(self, host: str, port: int = 443) -> bool:
        """
        移除指定主机的连接池
        
        该方法关闭并移除指定主机的所有连接。
        
        Args:
            host: 目标主机名
            port: 目标端口，默认为 443
            
        Returns:
            是否成功移除
        """
        async with self._lock:
            pool_key = self._get_pool_key(host, port)
            
            if pool_key not in self._pools:
                return False
            
            # 关闭该连接池中的所有连接
            connections = self._pools[pool_key]
            for connection in connections:
                try:
                    await self._close_connection(connection)
                except Exception as e:
                    pass
            
            # 移除连接池
            del self._pools[pool_key]
            
            return True
    
    async def get_pool_size(self, host: str, port: int = 443) -> int:
        """
        获取指定主机连接池的大小
        
        Args:
            host: 目标主机名
            port: 目标端口，默认为 443
            
        Returns:
            连接池中的连接数
        """
        async with self._lock:
            pool_key = self._get_pool_key(host, port)
            return len(self._pools.get(pool_key, []))
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口，自动关闭所有连接"""
        await self.close_all()
        return False
    
    def __repr__(self) -> str:
        """返回连接池的字符串表示"""
        return (
            f"ConnectionPool("
            f"max_per_host={self.max_connections_per_host}, "
            f"timeout={self.keep_alive_timeout}s, "
            f"pools={len(self._pools)}, "
            f"total={self.stats['total_connections']})"
        )


# 便捷函数
async def create_connection_pool(
    max_connections_per_host: int = 10,
    connection_timeout: int = 30,
    keep_alive_timeout: int = 60
) -> ConnectionPool:
    """
    创建连接池的便捷函数
    
    Args:
        max_connections_per_host: 每个目标主机的最大连接数
        connection_timeout: 连接超时时间（秒）
        keep_alive_timeout: Keep-Alive 超时时间（秒）
        
    Returns:
        ConnectionPool 实例
    """
    return ConnectionPool(
        max_connections_per_host=max_connections_per_host,
        connection_timeout=connection_timeout,
        keep_alive_timeout=keep_alive_timeout
    )
