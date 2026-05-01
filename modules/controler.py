"""
流量控制器模块

功能：
1. 请求调度
2. 带宽管理
3. 流量整形
4. 优先级队列
5. 连接限制
6. 速率限制

Author: SilkRoad-Next Team
Version: 4.0.0
"""

import asyncio
import random
import time
from typing import Optional, Dict, Any, List, TYPE_CHECKING
from enum import Enum
from dataclasses import dataclass, field
from collections import deque
from loguru import logger as loguru_logger
import uuid

from modules.wafpasser import WAFPasser, RequestObfuscator

if TYPE_CHECKING:
    from modules.logging import Logger


class RequestPriority(Enum):
    """请求优先级"""
    CRITICAL = 10
    HIGH = 8
    NORMAL = 5
    LOW = 3
    BACKGROUND = 1


@dataclass
class RequestInfo:
    """请求信息"""
    request_id: str
    url: str
    method: str
    priority: RequestPriority
    content_type: str
    client_ip: str
    timestamp: float = field(default_factory=time.time)
    size: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BandwidthUsage:
    """带宽使用记录"""
    timestamp: float
    bytes_sent: int
    bytes_received: int


class TrafficController:
    """
    流量控制器
    
    功能：
    1. 请求调度
    2. 带宽管理
    3. 流量整形
    4. 优先级队列
    """
    
    def __init__(self, config, logger: Optional['Logger'] = None):
        """
        初始化流量控制器
        
        Args:
            config: 配置管理器
            logger: 日志记录器
        """
        self.config = config
        self.logger = logger or loguru_logger
        
        self.max_bandwidth = config.get('trafficControl.maxBandwidth', 104857600)
        self.max_connections = config.get('trafficControl.maxConnections', 5000)
        self.request_queue_enabled = config.get('trafficControl.requestQueue.enabled', True)
        self.queue_max_size = config.get('trafficControl.requestQueue.maxSize', 10000)
        self.queue_timeout = config.get('trafficControl.requestQueue.timeout', 30)
        self.rate_limit_enabled = config.get('trafficControl.rateLimit.enabled', True)
        self.requests_per_second = config.get('trafficControl.rateLimit.requestsPerSecond', 1000)
        self.burst_size = config.get('trafficControl.rateLimit.burstSize', 100)
        
        # 初始化 WAF 穿透模块
        self.waf_passer = WAFPasser()
        self.request_obfuscator = RequestObfuscator(self.waf_passer)
        
        self._request_queues: Dict[RequestPriority, deque] = {
            priority: deque() for priority in RequestPriority
        }
        
        self._active_connections: Dict[str, RequestInfo] = {}
        
        self._bandwidth_history: deque = deque(maxlen=60)
        
        self._tokens = self.burst_size
        self._last_token_update = time.time()
        
        self._lock = asyncio.Lock()
        self._queue_lock = asyncio.Lock()
        
        self.stats = {
            'total_requests': 0,
            'queued_requests': 0,
            'rejected_requests': 0,
            'active_connections': 0,
            'bytes_sent': 0,
            'bytes_received': 0,
            'rate_limited': 0,
            'queue_timeouts': 0
        }
        
        self.logger.info("TrafficController 初始化完成")
    
    async def acquire(self, request_info: RequestInfo) -> bool:
        """
        获取流量控制许可
        
        Args:
            request_info: 请求信息
            
        Returns:
            是否获取成功
        """
        async with self._lock:
            if len(self._active_connections) >= self.max_connections:
                self.logger.warning(f"连接数已达上限: {len(self._active_connections)}/{self.max_connections}")
                self.stats['rejected_requests'] += 1
                return False
            
            if self.rate_limit_enabled and not await self._check_rate_limit():
                self.logger.debug(f"速率限制: {request_info.url}")
                self.stats['rate_limited'] += 1
                
                if self.request_queue_enabled:
                    return await self._enqueue_request(request_info)
                else:
                    self.stats['rejected_requests'] += 1
                    return False
            
            if not await self._check_bandwidth():
                self.logger.debug(f"带宽限制: {request_info.url}")
                
                if self.request_queue_enabled:
                    return await self._enqueue_request(request_info)
                else:
                    self.stats['rejected_requests'] += 1
                    return False
            
            self._active_connections[request_info.request_id] = request_info
            self.stats['total_requests'] += 1
            self.stats['active_connections'] = len(self._active_connections)
            
            return True
    
    async def release(self, request_info: RequestInfo) -> None:
        """
        释放流量控制许可
        
        Args:
            request_info: 请求信息
        """
        async with self._lock:
            if request_info.request_id in self._active_connections:
                del self._active_connections[request_info.request_id]
                self.stats['active_connections'] = len(self._active_connections)
            
            if request_info.size > 0:
                self._bandwidth_history.append(BandwidthUsage(
                    timestamp=time.time(),
                    bytes_sent=request_info.size,
                    bytes_received=0
                ))
                self.stats['bytes_sent'] += request_info.size
    
    async def _check_rate_limit(self) -> bool:
        """
        检查速率限制（令牌桶算法）
        
        Returns:
            是否通过速率限制
        """
        current_time = time.time()
        elapsed = current_time - self._last_token_update
        
        self._tokens = min(
            self.burst_size,
            self._tokens + elapsed * self.requests_per_second
        )
        self._last_token_update = current_time
        
        if self._tokens >= 1:
            self._tokens -= 1
            return True
        
        return False
    
    async def _check_bandwidth(self) -> bool:
        """
        检查带宽限制
        
        Returns:
            是否通过带宽限制
        """
        if not self._bandwidth_history:
            return True
        
        current_time = time.time()
        recent_usage = [
            usage for usage in self._bandwidth_history
            if current_time - usage.timestamp <= 1.0
        ]
        
        total_bytes = sum(usage.bytes_sent + usage.bytes_received for usage in recent_usage)
        current_bandwidth = total_bytes
        
        return current_bandwidth < self.max_bandwidth
    
    async def _enqueue_request(self, request_info: RequestInfo) -> bool:
        """
        将请求加入队列
        
        Args:
            request_info: 请求信息
            
        Returns:
            是否成功加入队列
        """
        async with self._queue_lock:
            total_queued = sum(len(queue) for queue in self._request_queues.values())
            
            if total_queued >= self.queue_max_size:
                self.logger.warning(f"请求队列已满: {total_queued}/{self.queue_max_size}")
                self.stats['rejected_requests'] += 1
                return False
            
            self._request_queues[request_info.priority].append(request_info)
            self.stats['queued_requests'] += 1
            
            self.logger.debug(
                f"请求加入队列: {request_info.url} | "
                f"优先级={request_info.priority.name} | "
                f"队列长度={len(self._request_queues[request_info.priority])}"
            )
            
            return True
    
    async def get_next_request(self) -> Optional[RequestInfo]:
        """
        从队列获取下一个请求（优先级调度）
        
        Returns:
            下一个请求信息
        """
        async with self._queue_lock:
            for priority in sorted(RequestPriority, key=lambda p: p.value, reverse=True):
                if self._request_queues[priority]:
                    request_info = self._request_queues[priority].popleft()
                    
                    if time.time() - request_info.timestamp > self.queue_timeout:
                        self.stats['queue_timeouts'] += 1
                        continue
                    
                    return request_info
            
            return None
    
    def determine_priority(self, request_info: RequestInfo) -> RequestPriority:
        """
        确定请求优先级
        
        Args:
            request_info: 请求信息
            
        Returns:
            请求优先级
        """
        priority_map = self.config.get('trafficControl.scheduling.priorities', {})
        
        if 'websocket' in request_info.metadata.get('upgrade', '').lower():
            return RequestPriority.CRITICAL
        
        if any(media_type in request_info.content_type.lower() 
               for media_type in ['video/', 'audio/']):
            return RequestPriority.HIGH
        
        if 'text/event-stream' in request_info.content_type.lower():
            return RequestPriority.HIGH
        
        if 'text/html' in request_info.content_type.lower():
            return RequestPriority.NORMAL
        
        if any(static_type in request_info.content_type.lower()
               for static_type in ['image/', 'text/css', 'application/javascript']):
            return RequestPriority.LOW
        
        return RequestPriority.NORMAL
    
    async def get_stats(self) -> dict:
        """获取流量控制统计信息"""
        async with self._lock:
            queue_sizes = {
                priority.name: len(queue)
                for priority, queue in self._request_queues.items()
            }
            
            return {
                **self.stats,
                'queue_sizes': queue_sizes,
                'available_tokens': self._tokens,
                'bandwidth_usage': await self._get_current_bandwidth()
            }
    
    async def _get_current_bandwidth(self) -> int:
        """获取当前带宽使用"""
        if not self._bandwidth_history:
            return 0
        
        current_time = time.time()
        recent_usage = [
            usage for usage in self._bandwidth_history
            if current_time - usage.timestamp <= 1.0
        ]
        
        return sum(usage.bytes_sent + usage.bytes_received for usage in recent_usage)
    
    async def start_scheduler(self):
        """启动请求调度器"""
        while True:
            await asyncio.sleep(0.1)
            
            if len(self._active_connections) < self.max_connections:
                request_info = await self.get_next_request()
                
                if request_info:
                    if await self.acquire(request_info):
                        self.logger.debug(f"调度请求: {request_info.url}")
    
    async def schedule_request(self, request: Any, target_domain: str) -> bool:
        """
        调度请求 - 集成 WAF 绕过策略
        
        Args:
            request: 请求对象
            target_domain: 目标域名
            
        Returns:
            调度结果
        """
        waf_evasion_config = self.config.get('waf_evasion', {})
        
        # 检查配置是否启用请求速率控制
        if waf_evasion_config.get('request_pacing', {}).get('enabled', False):
            delay = self._calculate_adaptive_delay(target_domain)
            await asyncio.sleep(delay)
        
        # 检查配置是否启用 WAF 穿透
        if waf_evasion_config.get('enabled', False):
            request = self._apply_evasion_headers(request, target_domain)
        
        return await self._enqueue_request_for_schedule(request)
    
    def _calculate_adaptive_delay(self, domain: str) -> float:
        """
        计算自适应延迟
        
        根据历史成功率动态调整延迟时间
        
        Args:
            domain: 目标域名
            
        Returns:
            延迟时间（秒）
        """
        stats = self.waf_passer.success_stats.get(domain, {})
        
        total = stats.get('total', 1)
        success = stats.get('success', 0)
        success_rate = success / max(total, 1)
        
        if success_rate > 0.9:
            return random.uniform(0.5, 1.5)
        elif success_rate > 0.7:
            return random.uniform(1.0, 3.0)
        elif success_rate > 0.5:
            return random.uniform(2.0, 5.0)
        else:
            return random.uniform(5.0, 10.0)
    
    def _apply_evasion_headers(self, request: Any, domain: str) -> Any:
        """
        应用绕过请求头
        
        使用 request_obfuscator.obfuscate_headers 混淆请求头
        
        Args:
            request: 请求对象
            domain: 目标域名
            
        Returns:
            修改后的请求对象
        """
        # 获取原始请求头
        original_headers = dict(request.headers) if hasattr(request, 'headers') else {}
        
        # 获取目标 URL
        target_url = str(request.url) if hasattr(request, 'url') else f"https://{domain}"
        
        # 使用 request_obfuscator 混淆请求头
        obfuscated_headers = self.request_obfuscator.obfuscate_headers(
            original_headers,
            target_url
        )
        
        # 更新请求头
        if hasattr(request, 'headers'):
            for key, value in obfuscated_headers.items():
                request.headers[key] = value
        
        return request
    
    async def _enqueue_request_for_schedule(self, request: Any) -> bool:
        """
        将请求加入调度队列
        
        Args:
            request: 请求对象
            
        Returns:
            是否成功加入队列
        """
        # 简化实现：直接返回 True
        # 实际使用时可根据需要扩展
        return True


class BandwidthManager:
    """
    带宽管理器
    
    功能：
    1. 实时带宽监控
    2. 带宽分配
    3. 流量整形
    """
    
    def __init__(self, max_bandwidth: int, logger: Optional['Logger'] = None):
        """
        初始化带宽管理器
        
        Args:
            max_bandwidth: 最大带宽（bytes/s）
            logger: 日志记录器
        """
        self.max_bandwidth = max_bandwidth
        self.logger = logger or loguru_logger
        
        self._current_usage = 0
        self._last_update = time.time()
        
        self._allocations: Dict[str, int] = {}
        
        self._lock = asyncio.Lock()
    
    async def allocate(self, connection_id: str, requested_bandwidth: int) -> int:
        """
        分配带宽
        
        Args:
            connection_id: 连接 ID
            requested_bandwidth: 请求的带宽
            
        Returns:
            实际分配的带宽
        """
        async with self._lock:
            available = self.max_bandwidth - self._current_usage
            
            allocated = min(requested_bandwidth, available)
            
            if allocated > 0:
                self._allocations[connection_id] = allocated
                self._current_usage += allocated
            
            return allocated
    
    async def release(self, connection_id: str) -> None:
        """
        释放带宽
        
        Args:
            connection_id: 连接 ID
        """
        async with self._lock:
            if connection_id in self._allocations:
                self._current_usage -= self._allocations[connection_id]
                del self._allocations[connection_id]
    
    async def update_usage(self, connection_id: str, actual_usage: int) -> None:
        """
        更新带宽使用
        
        Args:
            connection_id: 连接 ID
            actual_usage: 实际使用量
        """
        async with self._lock:
            if connection_id in self._allocations:
                old_allocation = self._allocations[connection_id]
                self._current_usage -= old_allocation
                self._current_usage += actual_usage
                self._allocations[connection_id] = actual_usage
    
    def get_usage(self) -> dict:
        """获取带宽使用情况"""
        return {
            'max_bandwidth': self.max_bandwidth,
            'current_usage': self._current_usage,
            'available': self.max_bandwidth - self._current_usage,
            'utilization': (self._current_usage / self.max_bandwidth * 100) if self.max_bandwidth > 0 else 0,
            'allocations': dict(self._allocations)
        }


def create_request_info(url: str, method: str, content_type: str, 
                        client_ip: str, metadata: Optional[Dict[str, Any]] = None) -> RequestInfo:
    """
    创建请求信息对象的便捷函数
    
    Args:
        url: 请求 URL
        method: HTTP 方法
        content_type: 内容类型
        client_ip: 客户端 IP
        metadata: 元数据
        
    Returns:
        RequestInfo 对象
    """
    return RequestInfo(
        request_id=str(uuid.uuid4())[:8],
        url=url,
        method=method,
        priority=RequestPriority.NORMAL,
        content_type=content_type,
        client_ip=client_ip,
        metadata=metadata or {}
    )
