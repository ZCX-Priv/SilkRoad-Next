"""
会话管理模块 - SessionManager

功能：
1. 会话创建与销毁
2. 会话数据存储
3. 会话超时清理
4. 会话持久化
5. 会话数据大小限制
6. 会话统计信息

作者: SilkRoad-Next Team
版本: 2.0.0
"""

import asyncio
import json
import time
import uuid
from loguru import logger as loguru_logger
from datetime import datetime
from typing import Any, Dict, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from modules.logging import Logger


class SessionManager:
    """
    客户端会话管理器
    
    管理客户端会话状态，支持会话持久化、会话超时清理、会话数据共享等功能。
    
    功能：
    1. 会话创建与销毁
    2. 会话数据存储
    3. 会话超时清理
    4. 会话持久化
    5. 会话数据大小限制
    6. 会话统计信息
    
    使用示例:
        # 创建会话管理器
        session_manager = SessionManager(
            session_timeout=1800,  # 30分钟
            cleanup_interval=60,   # 每60秒清理一次
            max_data_size=1048576  # 1MB 数据大小限制
        )
        
        # 启动清理任务
        asyncio.create_task(session_manager.start_cleanup_task())
        
        # 创建会话
        session_id = await session_manager.create_session(
            client_ip='192.168.1.100',
            user_agent='Mozilla/5.0...',
            initial_data={'username': 'test_user'}
        )
        
        # 获取会话
        session_data = await session_manager.get_session(session_id)
        
        # 更新会话
        await session_manager.update_session(
            session_id,
            {'last_page': '/home', 'preferences': {'theme': 'dark'}}
        )
        
        # 保存会话到文件
        await session_manager.save_to_file('sessions_backup.json')
        
        # 从文件加载会话
        await session_manager.load_from_file('sessions_backup.json')
        
        # 获取统计信息
        stats = session_manager.get_stats()
    """
    
    def __init__(
        self,
        session_timeout: int = 1800,
        cleanup_interval: int = 60,
        max_data_size: int = 1048576,
        logger: Optional['Logger'] = None
    ):
        """
        初始化会话管理器
        
        Args:
            session_timeout: 会话超时时间（秒），默认30分钟
            cleanup_interval: 清理间隔（秒），默认60秒
            max_data_size: 单个会话数据最大大小（字节），默认1MB
            logger: 日志记录器，如果为 None 则使用默认日志
        """
        self.session_timeout = session_timeout
        self.cleanup_interval = cleanup_interval
        self.max_data_size = max_data_size
        
        # 会话存储：{session_id: session_data}
        self._sessions: Dict[str, dict] = {}
        
        # 会话最后访问时间：{session_id: last_access_time}
        self._last_access: Dict[str, float] = {}
        
        # IP 到会话的映射：{client_ip: set(session_ids)}
        self._ip_session_map: Dict[str, Set[str]] = {}
        
        # 锁机制，确保线程安全
        self._lock = asyncio.Lock()
        
        # 日志记录器
        self._logger = logger or loguru_logger
        
        # 清理任务控制
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        
        # 统计信息
        self._stats = {
            'total_sessions': 0,
            'active_sessions': 0,
            'expired_sessions': 0,
            'total_creates': 0,
            'total_deletes': 0,
            'total_updates': 0,
            'total_gets': 0,
            'data_size_violations': 0,
        }
        
        self._logger.info(
            f"SessionManager 初始化完成: "
            f"timeout={session_timeout}s, "
            f"cleanup_interval={cleanup_interval}s, "
            f"max_data_size={max_data_size} bytes"
        )
    
    def _generate_session_id(self) -> str:
        """
        生成唯一会话 ID
        
        Returns:
            会话 ID 字符串
        """
        return str(uuid.uuid4())
    
    def _calculate_data_size(self, data: dict) -> int:
        """
        计算会话数据大小
        
        Args:
            data: 会话数据字典
            
        Returns:
            数据大小（字节）
        """
        try:
            return len(json.dumps(data, ensure_ascii=False))
        except (TypeError, ValueError):
            return 0
    
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
    
    async def create_session(
        self,
        client_ip: str,
        user_agent: str = '',
        initial_data: Optional[dict] = None
    ) -> str:
        """
        创建新会话
        
        Args:
            client_ip: 客户端 IP 地址
            user_agent: 客户端 User-Agent
            initial_data: 初始会话数据
            
        Returns:
            会话 ID
            
        Raises:
            ValueError: 如果初始数据超过大小限制
        """
        async with self._lock:
            # 检查初始数据大小
            if initial_data:
                data_size = self._calculate_data_size(initial_data)
                if data_size > self.max_data_size:
                    self._stats['data_size_violations'] += 1
                    raise ValueError(
                        f"Initial data size ({data_size} bytes) exceeds "
                        f"maximum allowed size ({self.max_data_size} bytes)"
                    )
            
            # 生成唯一会话 ID
            session_id = self._generate_session_id()
            
            # 创建会话数据
            current_time = datetime.now()
            session_data = {
                'session_id': session_id,
                'client_ip': client_ip,
                'user_agent': user_agent,
                'created_at': current_time.isoformat(),
                'updated_at': current_time.isoformat(),
                'data': initial_data or {}
            }
            
            # 存储会话
            self._sessions[session_id] = session_data
            self._last_access[session_id] = time.time()
            
            # 更新 IP 映射
            if client_ip not in self._ip_session_map:
                self._ip_session_map[client_ip] = set()
            self._ip_session_map[client_ip].add(session_id)
            
            # 更新统计
            self._stats['total_sessions'] += 1
            self._stats['active_sessions'] += 1
            self._stats['total_creates'] += 1
            
            self._logger.debug(
                f"会话创建成功: session_id={session_id}, "
                f"client_ip={client_ip}"
            )
            
            return session_id
    
    async def get_session(self, session_id: str) -> Optional[dict]:
        """
        获取会话数据
        
        Args:
            session_id: 会话 ID
            
        Returns:
            会话数据，如果会话不存在或已过期则返回 None
        """
        async with self._lock:
            self._stats['total_gets'] += 1
            
            # 检查会话是否存在
            if session_id not in self._sessions:
                self._logger.debug(f"会话不存在: session_id={session_id}")
                return None
            
            # 检查会话是否过期
            if self._is_session_expired(session_id):
                await self._delete_session_internal(session_id)
                self._logger.debug(f"会话已过期: session_id={session_id}")
                return None
            
            # 更新最后访问时间
            self._last_access[session_id] = time.time()
            
            # 返回会话数据的副本，防止外部修改
            return dict(self._sessions[session_id])
    
    async def update_session(
        self,
        session_id: str,
        data: Dict[str, Any],
        merge: bool = True
    ) -> bool:
        """
        更新会话数据
        
        Args:
            session_id: 会话 ID
            data: 要更新的数据
            merge: 是否合并数据（True）或替换数据（False）
            
        Returns:
            更新是否成功
            
        Raises:
            ValueError: 如果数据超过大小限制
        """
        async with self._lock:
            # 检查会话是否存在
            if session_id not in self._sessions:
                self._logger.debug(f"会话不存在，无法更新: session_id={session_id}")
                return False
            
            # 检查会话是否过期
            if self._is_session_expired(session_id):
                await self._delete_session_internal(session_id)
                self._logger.debug(f"会话已过期，无法更新: session_id={session_id}")
                return False
            
            # 计算新数据大小
            if merge:
                new_data = {**self._sessions[session_id]['data'], **data}
            else:
                new_data = data
            
            data_size = self._calculate_data_size(new_data)
            if data_size > self.max_data_size:
                self._stats['data_size_violations'] += 1
                raise ValueError(
                    f"Session data size ({data_size} bytes) exceeds "
                    f"maximum allowed size ({self.max_data_size} bytes)"
                )
            
            # 更新数据
            self._sessions[session_id]['data'] = new_data
            self._sessions[session_id]['updated_at'] = datetime.now().isoformat()
            self._last_access[session_id] = time.time()
            
            # 更新统计
            self._stats['total_updates'] += 1
            
            self._logger.debug(
                f"会话更新成功: session_id={session_id}, "
                f"data_size={data_size} bytes"
            )
            
            return True
    
    async def delete_session(self, session_id: str) -> bool:
        """
        删除会话
        
        Args:
            session_id: 会话 ID
            
        Returns:
            删除是否成功
        """
        async with self._lock:
            return await self._delete_session_internal(session_id)
    
    async def _delete_session_internal(self, session_id: str) -> bool:
        """
        内部删除会话方法（不加锁，由调用者确保锁已获取）
        
        Args:
            session_id: 会话 ID
            
        Returns:
            删除是否成功
        """
        if session_id not in self._sessions:
            return False
        
        # 获取客户端 IP 以更新映射
        client_ip = self._sessions[session_id].get('client_ip')
        
        # 删除会话数据
        del self._sessions[session_id]
        
        # 删除访问时间记录
        if session_id in self._last_access:
            del self._last_access[session_id]
        
        # 更新 IP 映射
        if client_ip and client_ip in self._ip_session_map:
            self._ip_session_map[client_ip].discard(session_id)
            if not self._ip_session_map[client_ip]:
                del self._ip_session_map[client_ip]
        
        # 更新统计
        self._stats['active_sessions'] -= 1
        self._stats['total_deletes'] += 1
        
        self._logger.debug(f"会话删除成功: session_id={session_id}")
        
        return True
    
    async def get_session_by_ip(self, client_ip: str) -> Optional[dict]:
        """
        根据 IP 地址获取最新会话
        
        Args:
            client_ip: 客户端 IP 地址
            
        Returns:
            最新的会话数据，如果没有有效会话则返回 None
        """
        async with self._lock:
            if client_ip not in self._ip_session_map:
                return None
            
            # 获取该 IP 的所有会话
            session_ids = self._ip_session_map[client_ip]
            
            if not session_ids:
                return None
            
            # 找到最新的有效会话
            latest_session: Optional[dict] = None
            latest_time: float = 0
            expired_sessions: list = []
            
            for session_id in session_ids:
                # 检查会话是否存在
                if session_id not in self._sessions:
                    expired_sessions.append(session_id)
                    continue
                
                # 检查是否过期
                if self._is_session_expired(session_id):
                    expired_sessions.append(session_id)
                    continue
                
                # 比较最后访问时间
                last_access = self._last_access.get(session_id, 0)
                if last_access > latest_time:
                    latest_time = last_access
                    latest_session = self._sessions[session_id]
            
            # 清理过期会话 ID
            for session_id in expired_sessions:
                session_ids.discard(session_id)
                if session_id in self._sessions:
                    await self._delete_session_internal(session_id)
                    self._stats['expired_sessions'] += 1
            
            # 清理空的 IP 映射
            if not session_ids:
                del self._ip_session_map[client_ip]
                return None
            
            if latest_session:
                # 更新访问时间
                self._last_access[latest_session['session_id']] = time.time()
                return dict(latest_session)
            
            return None
    
    async def get_all_sessions_by_ip(self, client_ip: str) -> list:
        """
        根据 IP 地址获取所有有效会话
        
        Args:
            client_ip: 客户端 IP 地址
            
        Returns:
            会话数据列表
        """
        async with self._lock:
            if client_ip not in self._ip_session_map:
                return []
            
            sessions = []
            expired_sessions = []
            
            for session_id in list(self._ip_session_map[client_ip]):
                if session_id not in self._sessions:
                    expired_sessions.append(session_id)
                    continue
                
                if self._is_session_expired(session_id):
                    expired_sessions.append(session_id)
                    continue
                
                sessions.append(dict(self._sessions[session_id]))
            
            # 清理过期会话
            for session_id in expired_sessions:
                self._ip_session_map[client_ip].discard(session_id)
                if session_id in self._sessions:
                    await self._delete_session_internal(session_id)
                    self._stats['expired_sessions'] += 1
            
            return sessions
    
    async def cleanup_expired_sessions(self) -> int:
        """
        清理过期会话
        
        Returns:
            清理的会话数量
        """
        async with self._lock:
            current_time = time.time()
            expired_sessions = []
            
            # 找出所有过期会话
            for session_id in list(self._sessions.keys()):
                if self._is_session_expired(session_id):
                    expired_sessions.append(session_id)
            
            # 删除过期会话
            for session_id in expired_sessions:
                await self._delete_session_internal(session_id)
                self._stats['expired_sessions'] += 1
            
            if expired_sessions:
                self._logger.info(
                    f"清理过期会话完成: 清理了 {len(expired_sessions)} 个会话"
                )
            
            return len(expired_sessions)
    
    async def start_cleanup_task(self) -> None:
        """
        启动定期清理任务
        
        此方法会无限循环运行，直到调用 stop_cleanup_task 或设置关闭事件。
        通常作为后台任务运行：
            asyncio.create_task(session_manager.start_cleanup_task())
        """
        self._logger.info(
            f"会话清理任务启动: 清理间隔={self.cleanup_interval}秒"
        )
        
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(self.cleanup_interval)
                
                if self._shutdown_event.is_set():
                    break
                
                cleaned_count = await self.cleanup_expired_sessions()
                
                if cleaned_count > 0:
                    self._logger.debug(
                        f"定期清理完成: 清理了 {cleaned_count} 个过期会话"
                    )
                    
            except asyncio.CancelledError:
                self._logger.info("会话清理任务被取消")
                break
            except Exception as e:
                self._logger.error(f"会话清理任务发生错误: {e}")
                await asyncio.sleep(1)  # 防止错误时快速循环
        
        self._logger.info("会话清理任务已停止")
    
    def stop_cleanup_task(self) -> None:
        """
        停止定期清理任务
        """
        self._shutdown_event.set()
        self._logger.info("请求停止会话清理任务")
    
    async def save_to_file(self, file_path: str) -> bool:
        """
        将会话数据保存到文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            保存是否成功
        """
        async with self._lock:
            try:
                # 准备保存的数据
                data = {
                    'version': '2.0.0',
                    'saved_at': datetime.now().isoformat(),
                    'config': {
                        'session_timeout': self.session_timeout,
                        'cleanup_interval': self.cleanup_interval,
                        'max_data_size': self.max_data_size
                    },
                    'sessions': self._sessions,
                    'last_access': self._last_access,
                    'stats': self._stats
                }
                
                # 写入文件
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                
                self._logger.info(
                    f"会话数据保存成功: {file_path}, "
                    f"会话数={len(self._sessions)}"
                )
                
                return True
                
            except Exception as e:
                self._logger.error(f"保存会话数据失败: {e}")
                return False
    
    async def load_from_file(self, file_path: str) -> bool:
        """
        从文件加载会话数据
        
        Args:
            file_path: 文件路径
            
        Returns:
            加载是否成功
        """
        async with self._lock:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 验证数据格式
                if 'sessions' not in data:
                    raise ValueError("Invalid session data format: missing 'sessions' key")
                
                # 加载会话数据
                loaded_sessions = data.get('sessions', {})
                loaded_last_access = data.get('last_access', {})
                
                # 过滤过期会话
                current_time = time.time()
                valid_sessions = {}
                valid_last_access = {}
                
                for session_id, session_data in loaded_sessions.items():
                    last_access = loaded_last_access.get(session_id, 0)
                    
                    # 检查是否过期
                    if current_time - last_access <= self.session_timeout:
                        valid_sessions[session_id] = session_data
                        valid_last_access[session_id] = last_access
                
                # 更新会话存储
                self._sessions = valid_sessions
                self._last_access = valid_last_access
                
                # 重建 IP 映射
                self._ip_session_map.clear()
                for session_id, session_data in self._sessions.items():
                    client_ip = session_data.get('client_ip')
                    if client_ip:
                        if client_ip not in self._ip_session_map:
                            self._ip_session_map[client_ip] = set()
                        self._ip_session_map[client_ip].add(session_id)
                
                # 更新统计
                self._stats['active_sessions'] = len(self._sessions)
                self._stats['total_sessions'] = len(self._sessions)
                
                # 合并统计信息
                if 'stats' in data:
                    for key in ['total_creates', 'total_deletes', 'total_updates', 
                               'total_gets', 'expired_sessions', 'data_size_violations']:
                        if key in data['stats']:
                            self._stats[key] = data['stats'][key]
                
                self._logger.info(
                    f"会话数据加载成功: {file_path}, "
                    f"有效会话数={len(self._sessions)}, "
                    f"过滤过期会话数={len(loaded_sessions) - len(self._sessions)}"
                )
                
                return True
                
            except FileNotFoundError:
                self._logger.warning(f"会话数据文件不存在: {file_path}")
                return False
            except json.JSONDecodeError as e:
                self._logger.error(f"会话数据文件格式错误: {e}")
                return False
            except Exception as e:
                self._logger.error(f"加载会话数据失败: {e}")
                return False
    
    def get_stats(self) -> dict:
        """
        获取会话统计信息
        
        Returns:
            统计信息字典，包含以下字段：
            - total_sessions: 历史总会话数
            - active_sessions: 当前活跃会话数
            - expired_sessions: 已过期会话数
            - total_creates: 总创建次数
            - total_deletes: 总删除次数
            - total_updates: 总更新次数
            - total_gets: 总获取次数
            - data_size_violations: 数据大小违规次数
            - unique_ips: 唯一 IP 数量
            - session_timeout: 会话超时时间
            - cleanup_interval: 清理间隔
            - max_data_size: 最大数据大小
        """
        # 计算总数据大小
        total_data_size = sum(
            self._calculate_data_size(s.get('data', {}))
            for s in self._sessions.values()
        )
        
        return {
            **self._stats,
            'unique_ips': len(self._ip_session_map),
            'total_data_size': total_data_size,
            'average_data_size': (
                total_data_size / len(self._sessions) 
                if self._sessions else 0
            ),
            'config': {
                'session_timeout': self.session_timeout,
                'cleanup_interval': self.cleanup_interval,
                'max_data_size': self.max_data_size
            }
        }
    
    async def clear_all(self) -> int:
        """
        清空所有会话
        
        Returns:
            清除的会话数量
        """
        async with self._lock:
            count = len(self._sessions)
            
            self._sessions.clear()
            self._last_access.clear()
            self._ip_session_map.clear()
            
            self._stats['active_sessions'] = 0
            
            self._logger.info(f"所有会话已清空: 清除了 {count} 个会话")
            
            return count
    
    async def get_session_count(self) -> int:
        """
        获取当前活跃会话数量
        
        Returns:
            活跃会话数量
        """
        async with self._lock:
            return len(self._sessions)
    
    async def get_session_ids(self) -> list:
        """
        获取所有会话 ID 列表
        
        Returns:
            会话 ID 列表
        """
        async with self._lock:
            return list(self._sessions.keys())
    
    async def session_exists(self, session_id: str) -> bool:
        """
        检查会话是否存在且有效
        
        Args:
            session_id: 会话 ID
            
        Returns:
            会话是否存在且有效
        """
        async with self._lock:
            if session_id not in self._sessions:
                return False
            
            if self._is_session_expired(session_id):
                await self._delete_session_internal(session_id)
                return False
            
            return True
    
    async def touch_session(self, session_id: str) -> bool:
        """
        更新会话的最后访问时间（延长会话有效期）
        
        Args:
            session_id: 会话 ID
            
        Returns:
            是否成功更新
        """
        async with self._lock:
            if session_id not in self._sessions:
                return False
            
            if self._is_session_expired(session_id):
                await self._delete_session_internal(session_id)
                return False
            
            self._last_access[session_id] = time.time()
            return True
    
    async def get_session_age(self, session_id: str) -> Optional[float]:
        """
        获取会话的存活时间
        
        Args:
            session_id: 会话 ID
            
        Returns:
            存活时间（秒），如果会话不存在则返回 None
        """
        async with self._lock:
            if session_id not in self._sessions:
                return None
            
            if session_id not in self._last_access:
                return None
            
            return time.time() - self._last_access[session_id]
    
    async def get_session_remaining_time(self, session_id: str) -> Optional[float]:
        """
        获取会话的剩余有效时间
        
        Args:
            session_id: 会话 ID
            
        Returns:
            剩余时间（秒），如果会话不存在或已过期则返回 None
        """
        async with self._lock:
            if session_id not in self._sessions:
                return None
            
            if session_id not in self._last_access:
                return None
            
            elapsed = time.time() - self._last_access[session_id]
            remaining = self.session_timeout - elapsed
            
            if remaining <= 0:
                await self._delete_session_internal(session_id)
                return None
            
            return remaining
    
    def __repr__(self) -> str:
        """返回会话管理器的字符串表示"""
        return (
            f"SessionManager("
            f"active={self._stats['active_sessions']}, "
            f"total={self._stats['total_sessions']}, "
            f"expired={self._stats['expired_sessions']}, "
            f"unique_ips={len(self._ip_session_map)})"
        )


# 便捷函数
def create_session_manager(
    session_timeout: int = 1800,
    cleanup_interval: int = 60,
    max_data_size: int = 1048576,
    logger: Optional['Logger'] = None
) -> SessionManager:
    """
    创建会话管理器的便捷函数
    
    Args:
        session_timeout: 会话超时时间（秒）
        cleanup_interval: 清理间隔（秒）
        max_data_size: 单个会话数据最大大小（字节）
        logger: 日志记录器
        
    Returns:
        SessionManager 实例
        
    Example:
        session_manager = create_session_manager(
            session_timeout=1800,
            cleanup_interval=60,
            max_data_size=1048576
        )
        
        # 启动清理任务
        asyncio.create_task(session_manager.start_cleanup_task())
    """
    return SessionManager(
        session_timeout=session_timeout,
        cleanup_interval=cleanup_interval,
        max_data_size=max_data_size,
        logger=logger
    )
