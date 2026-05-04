import asyncio
import aiohttp
from typing import Dict, Optional, Any, TYPE_CHECKING
from datetime import datetime
import time
from loguru import logger as loguru_logger

if TYPE_CHECKING:
    from modules.logging import Logger


class ConnectionPool:

    def __init__(self,
                 max_connections_per_host: int = 100,
                 connection_timeout: int = 30,
                 keep_alive_timeout: int = 60,
                 total_connection_limit: int = 500,
                 logger: Optional['Logger'] = None):
        self.max_connections_per_host = max_connections_per_host
        self.connection_timeout = connection_timeout
        self.keep_alive_timeout = keep_alive_timeout
        self.total_connection_limit = total_connection_limit

        self._sessions: Dict[str, aiohttp.ClientSession] = {}
        self._session_created: Dict[str, float] = {}
        self._session_last_used: Dict[str, float] = {}
        self._session_active_count: Dict[str, int] = {}
        self._session_locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

        self.session_manager: Any = None

        self._logger = logger or loguru_logger

        self.stats = {
            'total_sessions': 0,
            'active_requests': 0,
            'reuse_count': 0,
            'timeout_cleanups': 0,
            'failed_connections': 0,
            'created_sessions': 0
        }

        self._logger.info(
            f"ConnectionPool 初始化完成: "
            f"max_per_host={max_connections_per_host}, "
            f"total_limit={total_connection_limit}, "
            f"timeout={connection_timeout}s, "
            f"keepalive={keep_alive_timeout}s"
        )

    def _make_key(self, host: str, port: int, is_https: bool) -> str:
        scheme = 'https' if is_https else 'http'
        return f"{scheme}://{host}:{port}"

    async def _get_lock(self, pool_key: str) -> asyncio.Lock:
        async with self._global_lock:
            if pool_key not in self._session_locks:
                self._session_locks[pool_key] = asyncio.Lock()
            return self._session_locks[pool_key]

    async def get_session(self,
                          host: str,
                          port: int = 443,
                          is_https: bool = True,
                          _session_id: Optional[str] = None) -> aiohttp.ClientSession:
        pool_key = self._make_key(host, port, is_https)
        lock = await self._get_lock(pool_key)

        async with lock:
            session = self._sessions.get(pool_key)

            if session is not None and not session.closed:
                self._session_last_used[pool_key] = time.time()
                self._session_active_count[pool_key] = self._session_active_count.get(pool_key, 0) + 1
                self.stats['reuse_count'] += 1
                self.stats['active_requests'] += 1
                self._logger.debug(f"Session 复用: {pool_key}")
                return session

            session = await self._create_session(pool_key, host, port, is_https)
            self._sessions[pool_key] = session
            self._session_created[pool_key] = time.time()
            self._session_last_used[pool_key] = time.time()
            self._session_active_count[pool_key] = 1
            self.stats['created_sessions'] += 1
            self.stats['total_sessions'] += 1
            self.stats['active_requests'] += 1
            self._logger.debug(f"新 Session 创建: {pool_key}")
            return session

    async def _create_session(self, _pool_key: str, _host: str, _port: int,
                               _is_https: bool) -> aiohttp.ClientSession:
        timeout = aiohttp.ClientTimeout(
            total=self.connection_timeout * 2,
            connect=self.connection_timeout
        )
        connector = aiohttp.TCPConnector(
            limit=self.max_connections_per_host,
            limit_per_host=self.max_connections_per_host,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
            force_close=False
        )
        return aiohttp.ClientSession(
            timeout=timeout,
            connector=connector
        )

    async def release_session(self, host: str, port: int, is_https: bool = True) -> None:
        pool_key = self._make_key(host, port, is_https)
        count = self._session_active_count.get(pool_key, 0)
        if count > 0:
            self._session_active_count[pool_key] = count - 1
        if self.stats['active_requests'] > 0:
            self.stats['active_requests'] -= 1

    def register_connection(self, _host: str, _port: int,
                             _connection: aiohttp.BaseConnector) -> None:
        pass

    async def return_connection(self, _host: str, _port: int,
                                 _connection: aiohttp.BaseConnector) -> bool:
        return True

    async def get_connection(self, host: str, port: int = 443,
                              is_https: bool = True,
                              _session_id: Optional[str] = None) -> Optional[aiohttp.BaseConnector]:
        pool_key = self._make_key(host, port, is_https)
        session = self._sessions.get(pool_key)
        if session is not None and not session.closed and session.connector is not None:
            return session.connector
        return None

    def get_session_cookies(self) -> Dict[str, str]:
        return {}

    def clear_session_cookies(self) -> None:
        pass

    async def cleanup_expired_connections(self) -> int:
        cleaned_count = 0
        current_time = time.time()
        keys_to_remove = []

        for pool_key, last_used in list(self._session_last_used.items()):
            active = self._session_active_count.get(pool_key, 0)
            if active == 0 and current_time - last_used > self.keep_alive_timeout:
                keys_to_remove.append(pool_key)

        for pool_key in keys_to_remove:
            lock = await self._get_lock(pool_key)
            async with lock:
                session = self._sessions.pop(pool_key, None)
                if session is not None and not session.closed:
                    await session.close()
                self._session_created.pop(pool_key, None)
                self._session_last_used.pop(pool_key, None)
                self._session_active_count.pop(pool_key, None)
                if self.stats['total_sessions'] > 0:
                    self.stats['total_sessions'] -= 1
                self.stats['timeout_cleanups'] += 1
                cleaned_count += 1

        if cleaned_count > 0:
            self._logger.info(f"清理过期 Session 完成: 清理了 {cleaned_count} 个")

        return cleaned_count

    async def get_stats(self) -> dict:
        pool_stats = {}
        for pool_key, session in self._sessions.items():
            connector = session.connector if not session.closed else None
            pool_stats[pool_key] = {
                'active': self._session_active_count.get(pool_key, 0),
                'alive': not session.closed if session else False,
                'created_at': self._session_created.get(pool_key),
                'last_used': self._session_last_used.get(pool_key),
                'connector_stats': {
                    'opened': len(connector._conns) if connector and hasattr(connector, '_conns') else 0
                } if connector else {}
            }

        return {
            **self.stats,
            'pools': pool_stats,
            'total_pools': len(self._sessions),
            'config': {
                'max_connections_per_host': self.max_connections_per_host,
                'total_connection_limit': self.total_connection_limit,
                'connection_timeout': self.connection_timeout,
                'keep_alive_timeout': self.keep_alive_timeout
            }
        }

    async def close_all(self) -> int:
        closed_count = 0
        for _, session in list(self._sessions.items()):
            if not session.closed:
                await session.close()
                closed_count += 1

        self._sessions.clear()
        self._session_created.clear()
        self._session_last_used.clear()
        self._session_active_count.clear()
        self._session_locks.clear()

        self.stats['total_sessions'] = 0
        self.stats['active_requests'] = 0

        self._logger.info(f"所有 Session 已关闭: 共关闭 {closed_count} 个")
        return closed_count

    async def get_pool_status(self, host: str, port: int) -> dict:
        pool_key_https = self._make_key(host, port, True)
        pool_key_http = self._make_key(host, port, False)

        result = {}
        for pool_key in [pool_key_https, pool_key_http]:
            if pool_key in self._sessions:
                session = self._sessions[pool_key]
                result[pool_key] = {
                    'exists': True,
                    'active': self._session_active_count.get(pool_key, 0),
                    'alive': not session.closed,
                    'created_at': datetime.fromtimestamp(self._session_created[pool_key]).isoformat() if pool_key in self._session_created else None,
                    'last_used': datetime.fromtimestamp(self._session_last_used[pool_key]).isoformat() if pool_key in self._session_last_used else None,
                }
            else:
                result[pool_key] = {
                    'exists': False,
                    'active': 0,
                    'max': self.max_connections_per_host
                }

        return result

    async def health_check(self) -> dict:
        total_sessions = len(self._sessions)
        alive_count = 0
        expired_count = 0
        current_time = time.time()

        for pool_key, session in self._sessions.items():
            if session.closed:
                expired_count += 1
            elif current_time - self._session_last_used.get(pool_key, current_time) > self.keep_alive_timeout:
                if self._session_active_count.get(pool_key, 0) == 0:
                    expired_count += 1
                else:
                    alive_count += 1
            else:
                alive_count += 1

        return {
            'healthy': expired_count == 0,
            'total_sessions': total_sessions,
            'alive_sessions': alive_count,
            'expired_sessions': expired_count,
            'active_requests': self.stats['active_requests'],
            'reuse_rate': (
                self.stats['reuse_count'] / self.stats['created_sessions'] * 100
                if self.stats['created_sessions'] > 0 else 0
            ),
            'pools_count': total_sessions
        }

    def __repr__(self) -> str:
        return (
            f"ConnectionPool("
            f"sessions={len(self._sessions)}, "
            f"active={self.stats['active_requests']}, "
            f"reuse={self.stats['reuse_count']})"
        )


async def create_connection_pool(
    max_connections_per_host: int = 100,
    connection_timeout: int = 30,
    keep_alive_timeout: int = 60,
    logger: Optional['Logger'] = None
) -> ConnectionPool:
    return ConnectionPool(
        max_connections_per_host=max_connections_per_host,
        connection_timeout=connection_timeout,
        keep_alive_timeout=keep_alive_timeout,
        logger=logger
    )
