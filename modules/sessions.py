"""
会话管理模块

该模块实现了客户端会话管理器，用于管理客户端会话状态，支持会话持久化、
会话超时清理、会话数据共享等功能。

主要功能：
1. 会话创建与销毁
2. 会话数据存储（最大 1MB）
3. 会话超时自动清理（默认 30 分钟）
4. 会话持久化到文件
5. 按 IP 地址查找会话
6. 会话统计信息查询
7. 启动定期清理任务

作者: SilkRoad-Next Team
版本: V2.0
"""

import asyncio
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class SessionError(Exception):
    """会话相关错误的基类"""
    pass


class SessionNotFoundError(SessionError):
    """会话不存在错误"""
    pass


class SessionExpiredError(SessionError):
    """会话已过期错误"""
    pass


class SessionDataSizeError(SessionError):
    """会话数据大小超限错误"""
    pass


class SessionManager:
    """
    客户端会话管理器

    该类负责管理客户端会话状态，支持会话创建、销毁、数据存储、超时清理、
    持久化等功能。使用异步锁确保线程安全，适用于高并发场景。

    Attributes:
        session_timeout (int): 会话超时时间（秒），默认 30 分钟
        cleanup_interval (int): 清理间隔（秒），默认 60 秒
        max_data_size (int): 会话数据最大大小（字节），默认 1MB
        stats (dict): 会话统计信息

    Example:
        >>> manager = SessionManager(session_timeout=1800)
        >>> session_id = await manager.create_session('192.168.1.100')
        >>> session = await manager.get_session(session_id)
        >>> await manager.delete_session(session_id)
    """

    # 会话数据最大大小（1MB）
    MAX_DATA_SIZE = 1024 * 1024

    def __init__(self,
                 session_timeout: int = 1800,
                 cleanup_interval: int = 60,
                 max_data_size: int = MAX_DATA_SIZE):
        """
        初始化会话管理器

        Args:
            session_timeout: 会话超时时间（秒），默认为 1800 秒（30 分钟）
            cleanup_interval: 清理间隔（秒），默认为 60 秒
            max_data_size: 会话数据最大大小（字节），默认为 1MB

        Raises:
            ValueError: 如果参数值无效
        """
        # 参数验证
        if session_timeout <= 0:
            raise ValueError("session_timeout must be positive")
        if cleanup_interval <= 0:
            raise ValueError("cleanup_interval must be positive")
        if max_data_size <= 0:
            raise ValueError("max_data_size must be positive")

        self.session_timeout = session_timeout
        self.cleanup_interval = cleanup_interval
        self.max_data_size = max_data_size

        # 会话存储：{session_id: session_data}
        self._sessions: Dict[str, dict] = {}

        # 会话最后访问时间：{session_id: last_access_time}
        self._last_access: Dict[str, float] = {}

        # IP 地址索引：{client_ip: [session_id1, session_id2, ...]}
        self._ip_index: Dict[str, List[str]] = {}

        # 锁机制
        self._lock = asyncio.Lock()

        # 清理任务
        self._cleanup_task: Optional[asyncio.Task] = None
        self._is_running = False

        # 统计信息
        self.stats = {
            'total_sessions': 0,
            'active_sessions': 0,
            'expired_sessions': 0,
            'total_data_size': 0,
            'created_sessions': 0,
            'deleted_sessions': 0
        }

    def _generate_session_id(self) -> str:
        """
        生成唯一会话 ID

        Returns:
            会话 ID 字符串
        """
        return str(uuid.uuid4())

    def _is_session_expired(self, session_id: str) -> bool:
        """
        检查会话是否过期

        Args:
            session_id: 会话 ID

        Returns:
            会话是否过期
        """
        if session_id not in self._last_access:
            return True

        last_access = self._last_access[session_id]
        return time.time() - last_access > self.session_timeout

    def _calculate_data_size(self, data: dict) -> int:
        """
        计算会话数据大小

        Args:
            data: 会话数据字典

        Returns:
            数据大小（字节）
        """
        try:
            return len(json.dumps(data, ensure_ascii=False).encode('utf-8'))
        except Exception:
            return 0

    async def create_session(self,
                            client_ip: str,
                            user_agent: str = '',
                            initial_data: Optional[dict] = None) -> str:
        """
        创建新会话

        该方法创建一个新的会话，并返回会话 ID。会话数据大小不能超过 max_data_size。

        Args:
            client_ip: 客户端 IP 地址
            user_agent: 客户端 User-Agent，默认为空字符串
            initial_data: 初始会话数据，默认为 None

        Returns:
            会话 ID

        Raises:
            SessionDataSizeError: 如果初始数据大小超过限制

        Example:
            >>> session_id = await manager.create_session(
            ...     client_ip='192.168.1.100',
            ...     user_agent='Mozilla/5.0',
            ...     initial_data={'username': 'test'}
            ... )
        """
        async with self._lock:
            # 检查初始数据大小
            if initial_data:
                data_size = self._calculate_data_size(initial_data)
                if data_size > self.max_data_size:
                    raise SessionDataSizeError(
                        f"Initial data size ({data_size} bytes) exceeds "
                        f"maximum allowed size ({self.max_data_size} bytes)"
                    )

            # 生成唯一会话 ID
            session_id = self._generate_session_id()

            # 创建会话数据
            session_data = {
                'session_id': session_id,
                'client_ip': client_ip,
                'user_agent': user_agent,
                'created_at': datetime.now().isoformat(),
                'data': initial_data or {}
            }

            # 存储会话
            self._sessions[session_id] = session_data
            self._last_access[session_id] = time.time()

            # 更新 IP 索引
            if client_ip not in self._ip_index:
                self._ip_index[client_ip] = []
            self._ip_index[client_ip].append(session_id)

            # 更新统计
            self.stats['total_sessions'] += 1
            self.stats['active_sessions'] += 1
            self.stats['created_sessions'] += 1

            if initial_data:
                self.stats['total_data_size'] += self._calculate_data_size(initial_data)

            return session_id

    async def get_session(self, session_id: str) -> Optional[dict]:
        """
        获取会话数据

        该方法根据会话 ID 获取会话数据。如果会话不存在或已过期，则返回 None。

        Args:
            session_id: 会话 ID

        Returns:
            会话数据字典，如果会话不存在或已过期则返回 None

        Example:
            >>> session = await manager.get_session(session_id)
            >>> if session:
            ...     print(f"Client IP: {session['client_ip']}")
        """
        async with self._lock:
            # 检查会话是否存在
            if session_id not in self._sessions:
                return None

            # 检查会话是否过期
            if self._is_session_expired(session_id):
                await self._delete_session_internal(session_id)
                return None

            # 更新最后访问时间
            self._last_access[session_id] = time.time()

            return self._sessions[session_id]

    async def update_session(self,
                            session_id: str,
                            data: Dict[str, Any]) -> bool:
        """
        更新会话数据

        该方法更新指定会话的数据。如果会话不存在或已过期，则返回 False。
        更新后的数据大小不能超过 max_data_size。

        Args:
            session_id: 会话 ID
            data: 要更新的数据字典

        Returns:
            更新是否成功

        Raises:
            SessionDataSizeError: 如果更新后数据大小超过限制

        Example:
            >>> success = await manager.update_session(
            ...     session_id,
            ...     {'last_page': '/home', 'preferences': {'theme': 'dark'}}
            ... )
        """
        async with self._lock:
            # 检查会话是否存在
            if session_id not in self._sessions:
                return False

            # 检查会话是否过期
            if self._is_session_expired(session_id):
                await self._delete_session_internal(session_id)
                return False

            # 计算新数据大小
            current_data = self._sessions[session_id]['data'].copy()
            current_data.update(data)
            new_size = self._calculate_data_size(current_data)

            if new_size > self.max_data_size:
                raise SessionDataSizeError(
                    f"Updated data size ({new_size} bytes) exceeds "
                    f"maximum allowed size ({self.max_data_size} bytes)"
                )

            # 更新数据
            old_size = self._calculate_data_size(self._sessions[session_id]['data'])
            self._sessions[session_id]['data'].update(data)
            self._last_access[session_id] = time.time()

            # 更新统计
            self.stats['total_data_size'] += (new_size - old_size)

            return True

    async def delete_session(self, session_id: str) -> bool:
        """
        删除会话

        该方法删除指定的会话。如果会话不存在，则返回 False。

        Args:
            session_id: 会话 ID

        Returns:
            删除是否成功

        Example:
            >>> success = await manager.delete_session(session_id)
        """
        async with self._lock:
            return await self._delete_session_internal(session_id)

    async def _delete_session_internal(self, session_id: str) -> bool:
        """
        内部删除会话方法（不加锁）

        Args:
            session_id: 会话 ID

        Returns:
            删除是否成功
        """
        if session_id not in self._sessions:
            return False

        # 获取会话信息
        session_data = self._sessions[session_id]
        client_ip = session_data['client_ip']
        data_size = self._calculate_data_size(session_data['data'])

        # 删除会话
        del self._sessions[session_id]
        del self._last_access[session_id]

        # 更新 IP 索引
        if client_ip in self._ip_index:
            if session_id in self._ip_index[client_ip]:
                self._ip_index[client_ip].remove(session_id)
            if not self._ip_index[client_ip]:
                del self._ip_index[client_ip]

        # 更新统计
        self.stats['active_sessions'] -= 1
        self.stats['deleted_sessions'] += 1
        self.stats['total_data_size'] -= data_size

        return True

    async def get_session_by_ip(self, client_ip: str) -> Optional[dict]:
        """
        根据 IP 地址获取会话

        该方法根据客户端 IP 地址查找并返回第一个有效的会话。
        如果没有找到有效会话，则返回 None。

        Args:
            client_ip: 客户端 IP 地址

        Returns:
            会话数据字典，如果没有找到则返回 None

        Example:
            >>> session = await manager.get_session_by_ip('192.168.1.100')
            >>> if session:
            ...     print(f"Session ID: {session['session_id']}")
        """
        async with self._lock:
            # 检查 IP 索引
            if client_ip not in self._ip_index:
                return None

            # 遍历该 IP 的所有会话
            for session_id in self._ip_index[client_ip][:]:  # 使用切片创建副本
                if session_id in self._sessions:
                    # 检查是否过期
                    if not self._is_session_expired(session_id):
                        # 更新访问时间
                        self._last_access[session_id] = time.time()
                        return self._sessions[session_id]
                    else:
                        # 删除过期会话
                        await self._delete_session_internal(session_id)

            return None

    async def get_all_sessions_by_ip(self, client_ip: str) -> List[dict]:
        """
        根据 IP 地址获取所有会话

        该方法根据客户端 IP 地址查找并返回所有有效的会话。

        Args:
            client_ip: 客户端 IP 地址

        Returns:
            会话数据列表

        Example:
            >>> sessions = await manager.get_all_sessions_by_ip('192.168.1.100')
            >>> for session in sessions:
            ...     print(f"Session ID: {session['session_id']}")
        """
        async with self._lock:
            # 检查 IP 索引
            if client_ip not in self._ip_index:
                return []

            valid_sessions = []

            # 遍历该 IP 的所有会话
            for session_id in self._ip_index[client_ip][:]:
                if session_id in self._sessions:
                    # 检查是否过期
                    if not self._is_session_expired(session_id):
                        # 更新访问时间
                        self._last_access[session_id] = time.time()
                        valid_sessions.append(self._sessions[session_id])
                    else:
                        # 删除过期会话
                        await self._delete_session_internal(session_id)

            return valid_sessions

    async def cleanup_expired_sessions(self) -> int:
        """
        清理过期会话

        该方法遍历所有会话，检查并删除所有过期的会话。
        应该定期调用此方法以释放资源。

        Returns:
            清理的会话数量

        Example:
            >>> cleanup_count = await manager.cleanup_expired_sessions()
            >>> print(f"Cleaned up {cleanup_count} expired sessions")
        """
        async with self._lock:
            expired_sessions = []

            # 找出所有过期会话
            for session_id in list(self._sessions.keys()):
                if self._is_session_expired(session_id):
                    expired_sessions.append(session_id)

            # 删除过期会话
            for session_id in expired_sessions:
                await self._delete_session_internal(session_id)
                self.stats['expired_sessions'] += 1

            return len(expired_sessions)

    async def start_cleanup_task(self) -> None:
        """
        启动定期清理任务

        该方法启动一个后台任务，定期清理过期的会话。
        清理间隔由 cleanup_interval 参数指定。

        Example:
            >>> await manager.start_cleanup_task()
            >>> # 清理任务将在后台运行
        """
        if self._is_running:
            return

        self._is_running = True

        async def _cleanup_loop():
            """清理循环"""
            while self._is_running:
                try:
                    await asyncio.sleep(self.cleanup_interval)
                    await self.cleanup_expired_sessions()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    # 记录错误但继续运行
                    print(f"Error in cleanup task: {e}")

        self._cleanup_task = asyncio.create_task(_cleanup_loop())

    async def stop_cleanup_task(self) -> None:
        """
        停止定期清理任务

        该方法停止后台清理任务。

        Example:
            >>> await manager.stop_cleanup_task()
        """
        if not self._is_running:
            return

        self._is_running = False

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

    async def save_to_file(self, file_path: str) -> None:
        """
        将会话数据保存到文件

        该方法将所有会话数据保存到指定的 JSON 文件中。
        包括会话数据、最后访问时间和统计信息。

        Args:
            file_path: 文件路径

        Raises:
            IOError: 如果文件写入失败

        Example:
            >>> await manager.save_to_file('sessions_backup.json')
        """
        async with self._lock:
            try:
                # 准备保存的数据
                data = {
                    'sessions': self._sessions,
                    'last_access': self._last_access,
                    'stats': self.stats,
                    'metadata': {
                        'saved_at': datetime.now().isoformat(),
                        'session_timeout': self.session_timeout,
                        'max_data_size': self.max_data_size
                    }
                }

                # 确保目录存在
                path = Path(file_path)
                path.parent.mkdir(parents=True, exist_ok=True)

                # 写入文件
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

            except Exception as e:
                raise IOError(f"Failed to save sessions to file: {e}")

    async def load_from_file(self, file_path: str) -> int:
        """
        从文件加载会话数据

        该方法从指定的 JSON 文件中加载会话数据。
        注意：加载前会清空当前的所有会话数据。

        Args:
            file_path: 文件路径

        Returns:
            加载的会话数量

        Raises:
            IOError: 如果文件读取失败
            ValueError: 如果文件格式无效

        Example:
            >>> count = await manager.load_from_file('sessions_backup.json')
            >>> print(f"Loaded {count} sessions")
        """
        async with self._lock:
            try:
                # 检查文件是否存在
                path = Path(file_path)
                if not path.exists():
                    return 0

                # 读取文件
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # 验证数据格式
                if not isinstance(data, dict):
                    raise ValueError("Invalid session file format")

                # 清空当前数据
                self._sessions.clear()
                self._last_access.clear()
                self._ip_index.clear()

                # 加载会话数据
                self._sessions = data.get('sessions', {})
                self._last_access = data.get('last_access', {})

                # 重建 IP 索引
                for session_id, session_data in self._sessions.items():
                    client_ip = session_data.get('client_ip')
                    if client_ip:
                        if client_ip not in self._ip_index:
                            self._ip_index[client_ip] = []
                        self._ip_index[client_ip].append(session_id)

                # 更新统计信息
                self.stats = data.get('stats', self.stats)
                self.stats['active_sessions'] = len(self._sessions)

                # 清理过期会话
                await self.cleanup_expired_sessions()

                return len(self._sessions)

            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON format: {e}")
            except Exception as e:
                raise IOError(f"Failed to load sessions from file: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """
        获取会话统计信息

        该方法返回会话管理器的详细统计信息，包括总会话数、活跃会话数、
        过期会话数、数据大小等。

        Returns:
            统计信息字典，包含以下字段：
            - total_sessions: 总会话数
            - active_sessions: 活跃会话数
            - expired_sessions: 过期会话数
            - total_data_size: 总数据大小（字节）
            - created_sessions: 创建的会话数
            - deleted_sessions: 删除的会话数
            - session_timeout: 会话超时时间（秒）
            - max_data_size: 最大数据大小（字节）
            - unique_ips: 唯一 IP 地址数

        Example:
            >>> stats = manager.get_stats()
            >>> print(f"Active sessions: {stats['active_sessions']}")
        """
        return {
            **self.stats,
            'session_timeout': self.session_timeout,
            'max_data_size': self.max_data_size,
            'unique_ips': len(self._ip_index),
            'average_data_size': (
                self.stats['total_data_size'] / self.stats['active_sessions']
                if self.stats['active_sessions'] > 0 else 0
            )
        }

    async def get_session_count(self) -> int:
        """
        获取当前活跃会话数

        Returns:
            活跃会话数
        """
        async with self._lock:
            return len(self._sessions)

    async def get_all_session_ids(self) -> List[str]:
        """
        获取所有会话 ID

        Returns:
            会话 ID 列表
        """
        async with self._lock:
            return list(self._sessions.keys())

    async def clear_all_sessions(self) -> int:
        """
        清空所有会话

        该方法删除所有会话，并返回删除的会话数。

        Returns:
            删除的会话数

        Example:
            >>> count = await manager.clear_all_sessions()
            >>> print(f"Cleared {count} sessions")
        """
        async with self._lock:
            count = len(self._sessions)

            # 清空所有数据
            self._sessions.clear()
            self._last_access.clear()
            self._ip_index.clear()

            # 更新统计
            self.stats['active_sessions'] = 0
            self.stats['total_data_size'] = 0
            self.stats['deleted_sessions'] += count

            return count

    async def __aenter__(self) -> 'SessionManager':
        """
        异步上下文管理器入口

        Returns:
            会话管理器实例
        """
        await self.start_cleanup_task()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        异步上下文管理器出口

        自动停止清理任务
        """
        await self.stop_cleanup_task()

    def __repr__(self) -> str:
        """返回会话管理器的字符串表示"""
        return (
            f"SessionManager("
            f"timeout={self.session_timeout}s, "
            f"active={len(self._sessions)}, "
            f"unique_ips={len(self._ip_index)})"
        )


# 便捷函数
async def create_session_manager(
    session_timeout: int = 1800,
    cleanup_interval: int = 60,
    max_data_size: int = SessionManager.MAX_DATA_SIZE,
    auto_start_cleanup: bool = True
) -> SessionManager:
    """
    创建会话管理器的便捷函数

    Args:
        session_timeout: 会话超时时间（秒）
        cleanup_interval: 清理间隔（秒）
        max_data_size: 会话数据最大大小（字节）
        auto_start_cleanup: 是否自动启动清理任务

    Returns:
        SessionManager 实例

    Example:
        >>> manager = await create_session_manager(
        ...     session_timeout=3600,
        ...     cleanup_interval=120
        ... )
    """
    manager = SessionManager(
        session_timeout=session_timeout,
        cleanup_interval=cleanup_interval,
        max_data_size=max_data_size
    )

    if auto_start_cleanup:
        await manager.start_cleanup_task()

    return manager
