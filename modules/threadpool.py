"""
线程池管理模块

功能：
1. 管理 CPU 密集型任务的执行
2. 防止阻塞主事件循环
3. 任务优先级调度
4. 任务超时控制
5. 批量任务执行
6. 任务统计信息

作者: SilkRoad-Next Team
版本: v2.0.0
"""

import asyncio
import functools
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple


class ThreadPoolManager:
    """
    线程池管理器
    
    将 CPU 密集型任务（如解压缩、大规模正则替换）交由独立线程池处理，
    防止阻塞主异步事件循环。
    
    功能：
    1. 管理 CPU 密集型任务的执行
    2. 防止阻塞主事件循环
    3. 任务优先级调度
    4. 任务超时控制
    5. 批量任务执行
    6. 任务统计信息
    
    使用示例：
        # 创建线程池
        thread_pool = ThreadPoolManager(max_workers=8)
        
        # 设置事件循环
        thread_pool.set_event_loop(asyncio.get_event_loop())
        
        # 在线程池中执行任务
        result = await thread_pool.run_in_thread(
            cpu_intensive_function,
            arg1, arg2,
            timeout=10.0,
            keyword_arg='value'
        )
        
        # 批量执行任务
        tasks = [
            (func1, (arg1,), {}),
            (func2, (arg1, arg2), {'kwarg': 'value'}),
        ]
        results = await thread_pool.run_batch(tasks, timeout=5.0)
        
        # 获取统计信息
        stats = thread_pool.get_stats()
        
        # 关闭线程池
        thread_pool.shutdown()
    """
    
    def __init__(self, max_workers: Optional[int] = None):
        """
        初始化线程池
        
        Args:
            max_workers: 最大工作线程数，默认为 CPU 核心数 * 2
                        如果不指定，ThreadPoolExecutor 会自动根据 CPU 核心数设置
        
        Raises:
            ValueError: 如果 max_workers 小于 1
        """
        if max_workers is not None and max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        
        self._max_workers = max_workers
        self._executor: Optional[ThreadPoolExecutor] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._initialized = False
        
        # 任务统计
        self._stats: Dict[str, Any] = {
            'total_tasks': 0,
            'completed_tasks': 0,
            'failed_tasks': 0,
            'timeout_tasks': 0,
            'average_execution_time': 0.0,
            'total_execution_time': 0.0,
            'min_execution_time': float('inf'),
            'max_execution_time': 0.0,
        }
        
        # 锁机制，确保统计信息的线程安全
        self._stats_lock = threading.Lock()
        
        # 初始化线程池
        self._init_executor()
    
    def _init_executor(self) -> None:
        """
        初始化线程池执行器
        """
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self._max_workers)
            self._initialized = True
    
    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """
        设置事件循环
        
        Args:
            loop: asyncio 事件循环
        
        Note:
            如果不调用此方法，run_in_thread 会自动获取当前事件循环
        """
        self._loop = loop
    
    def _get_event_loop(self) -> asyncio.AbstractEventLoop:
        """
        获取事件循环
        
        Returns:
            asyncio 事件循环
        
        Raises:
            RuntimeError: 如果无法获取事件循环
        """
        if self._loop is not None and not self._loop.is_closed():
            return self._loop
        
        try:
            loop = asyncio.get_running_loop()
            self._loop = loop
            return loop
        except RuntimeError:
            # 如果没有运行中的事件循环，尝试获取或创建
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                self._loop = loop
                return loop
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                return loop
    
    async def run_in_thread(
        self,
        func: Callable,
        *args,
        timeout: Optional[float] = None,
        **kwargs
    ) -> Any:
        """
        在线程池中运行 CPU 密集型任务
        
        Args:
            func: 要执行的函数（必须是可调用对象）
            *args: 函数位置参数
            timeout: 任务超时时间（秒），None 表示不限制超时
            **kwargs: 函数关键字参数
            
        Returns:
            函数执行结果
            
        Raises:
            asyncio.TimeoutError: 任务超时
            Exception: 任务执行失败时的原始异常
            
        Example:
            # 简单调用
            result = await thread_pool.run_in_thread(cpu_intensive_func, arg1, arg2)
            
            # 带超时调用
            result = await thread_pool.run_in_thread(
                cpu_intensive_func,
                arg1, arg2,
                timeout=10.0
            )
            
            # 带关键字参数调用
            result = await thread_pool.run_in_thread(
                cpu_intensive_func,
                arg1,
                timeout=5.0,
                keyword_arg='value'
            )
        """
        if not callable(func):
            raise TypeError(f"func must be callable, got {type(func)}")
        
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be positive")
        
        loop = self._get_event_loop()
        start_time = time.perf_counter()
        
        # 更新任务计数
        with self._stats_lock:
            self._stats['total_tasks'] += 1
        
        try:
            # 使用 functools.partial 绑定参数
            if kwargs:
                func_partial = functools.partial(func, *args, **kwargs)
            elif args:
                func_partial = functools.partial(func, *args)
            else:
                func_partial = func
            
            # 确保线程池已初始化
            if self._executor is None:
                self._init_executor()
            
            # 在线程池中执行
            future = loop.run_in_executor(self._executor, func_partial)
            
            # 设置超时
            if timeout is not None:
                result = await asyncio.wait_for(future, timeout=timeout)
            else:
                result = await future
            
            # 计算执行时间
            execution_time = time.perf_counter() - start_time
            
            self._update_stats_success(execution_time)
            
            return result
            
        except asyncio.TimeoutError:
            execution_time = time.perf_counter() - start_time
            self._update_stats_timeout(execution_time)
            raise
            
        except asyncio.CancelledError:
            execution_time = time.perf_counter() - start_time
            self._update_stats_failure(execution_time)
            raise
            
        except Exception:
            execution_time = time.perf_counter() - start_time
            self._update_stats_failure(execution_time)
            raise
    
    def _update_stats_success(self, execution_time: float) -> None:
        with self._stats_lock:
            self._stats['completed_tasks'] += 1
            self._stats['total_execution_time'] += execution_time

            if execution_time < self._stats['min_execution_time']:
                self._stats['min_execution_time'] = execution_time
            if execution_time > self._stats['max_execution_time']:
                self._stats['max_execution_time'] = execution_time

            completed = self._stats['completed_tasks']
            current_avg = self._stats['average_execution_time']
            new_avg = current_avg + (execution_time - current_avg) / completed
            self._stats['average_execution_time'] = new_avg

    def _update_stats_timeout(self, execution_time: float) -> None:
        with self._stats_lock:
            self._stats['failed_tasks'] += 1
            self._stats['timeout_tasks'] += 1
            self._stats['total_execution_time'] += execution_time

    def _update_stats_failure(self, execution_time: float) -> None:
        with self._stats_lock:
            self._stats['failed_tasks'] += 1
            self._stats['total_execution_time'] += execution_time
    
    def _update_average_time(self, execution_time: float) -> None:
        """
        更新平均执行时间（同步版本，用于内部调用）
        
        Args:
            execution_time: 本次执行时间
        
        Note:
            此方法已弃用，请使用 _update_stats_success 替代
        """
        completed = self._stats['completed_tasks']
        current_avg = self._stats['average_execution_time']
        
        # 计算新的平均值（增量计算，避免数值溢出）
        if completed > 0:
            new_avg = current_avg + (execution_time - current_avg) / completed
            self._stats['average_execution_time'] = new_avg
        else:
            self._stats['average_execution_time'] = execution_time
    
    async def run_batch(
        self,
        tasks: List[Tuple[Callable, tuple, dict]],
        timeout: Optional[float] = None,
        fail_fast: bool = False
    ) -> List[Any]:
        """
        批量执行多个任务
        
        Args:
            tasks: 任务列表，每个元素为 (func, args, kwargs) 元组
                   - func: 要执行的函数
                   - args: 位置参数元组
                   - kwargs: 关键字参数字典
            timeout: 单个任务超时时间（秒），None 表示不限制超时
            fail_fast: 是否在第一个失败时立即返回，默认为 False
                       如果为 True，遇到异常会立即停止并抛出异常
                       如果为 False，会继续执行所有任务，异常会作为结果返回
            
        Returns:
            结果列表，顺序与输入一致
            如果 fail_fast=False，异常会作为结果返回
            
        Raises:
            Exception: 如果 fail_fast=True 且某个任务失败
            
        Example:
            # 准备批量任务
            tasks = [
                (func1, (arg1,), {}),
                (func2, (arg1, arg2), {'kwarg': 'value'}),
                (func3, (), {'kwarg1': 'v1', 'kwarg2': 'v2'}),
            ]
            
            # 执行批量任务
            results = await thread_pool.run_batch(tasks, timeout=5.0)
            
            # 处理结果
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    print(f"Task {i} failed: {result}")
                else:
                    print(f"Task {i} result: {result}")
        """
        if not tasks:
            return []
        
        # 验证任务格式
        for i, task in enumerate(tasks):
            if not isinstance(task, (tuple, list)):
                raise TypeError(f"Task {i} must be a tuple or list, got {type(task)}")
            if len(task) < 2:
                raise ValueError(f"Task {i} must have at least 2 elements (func, args)")
            if not callable(task[0]):
                raise TypeError(f"Task {i} first element must be callable")
        
        futures: List[Any] = []

        for task in tasks:
            func = task[0]
            if len(task) == 2:
                args = task[1]
                kwargs: Dict[str, Any] = {}
            elif len(task) == 3:
                args = task[1]
                kwargs = task[2]
            else:
                raise ValueError(f"Task must have 2 or 3 elements, got {len(task)}")

            if not isinstance(args, tuple):
                args = (args,)

            future = self.run_in_thread(func, *args, timeout=timeout, **kwargs)
            futures.append(future)
        
        # 并发执行所有任务
        if fail_fast:
            # 使用 gather 的默认行为，遇到异常立即停止
            results = await asyncio.gather(*futures)
        else:
            # 使用 return_exceptions=True，异常作为结果返回
            results = await asyncio.gather(*futures, return_exceptions=True)
        
        return results
    
    async def run_batch_with_callback(
        self,
        tasks: List[Tuple[Callable, tuple, dict]],
        callback: Optional[Callable[[int, Any, Optional[Exception]], None]] = None,
        timeout: Optional[float] = None
    ) -> List[Any]:
        """
        带回调的批量执行任务
        
        Args:
            tasks: 任务列表，每个元素为 (func, args, kwargs) 元组
            callback: 回调函数，签名为 callback(index, result, exception)
                      - index: 任务索引
                      - result: 任务结果（成功时）
                      - exception: 异常（失败时）
            timeout: 单个任务超时时间（秒）
            
        Returns:
            结果列表，顺序与输入一致
            
        Example:
            def on_complete(index, result, exception):
                if exception:
                    print(f"Task {index} failed: {exception}")
                else:
                    print(f"Task {index} completed: {result}")
            
            results = await thread_pool.run_batch_with_callback(
                tasks,
                callback=on_complete,
                timeout=5.0
            )
        """
        results = await self.run_batch(tasks, timeout=timeout, fail_fast=False)
        
        if callback is not None:
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    callback(i, None, result)
                else:
                    callback(i, result, None)
        
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取线程池统计信息
        
        Returns:
            统计信息字典，包含以下字段：
            - total_tasks: 总任务数
            - completed_tasks: 已完成任务数
            - failed_tasks: 失败任务数
            - timeout_tasks: 超时任务数
            - average_execution_time: 平均执行时间（秒）
            - total_execution_time: 总执行时间（秒）
            - min_execution_time: 最小执行时间（秒）
            - max_execution_time: 最大执行时间（秒）
            - max_workers: 最大工作线程数
            - active_threads: 活跃线程数
            - success_rate: 成功率（百分比）
            
        Example:
            stats = thread_pool.get_stats()
            print(f"Success rate: {stats['success_rate']:.2f}%")
            print(f"Average time: {stats['average_execution_time']:.4f}s")
        """
        # 计算成功率
        total = self._stats['total_tasks']
        completed = self._stats['completed_tasks']
        success_rate = (completed / total * 100) if total > 0 else 0.0
        
        # 获取活跃线程数
        active_threads = 0
        if self._executor is not None:
            try:
                active_threads = len([
                    t for t in self._executor._threads 
                    if t.is_alive()
                ])
            except (AttributeError, TypeError):
                # 某些 Python 版本可能没有 _threads 属性
                active_threads = 0
        
        # 获取最大工作线程数
        max_workers = self._max_workers
        if self._executor is not None:
            try:
                max_workers = self._executor._max_workers
            except AttributeError:
                pass
        
        return {
            **self._stats,
            'max_workers': max_workers,
            'active_threads': active_threads,
            'success_rate': success_rate,
        }
    
    def reset_stats(self) -> None:
        """
        重置统计信息
        """
        self._stats = {
            'total_tasks': 0,
            'completed_tasks': 0,
            'failed_tasks': 0,
            'timeout_tasks': 0,
            'average_execution_time': 0.0,
            'total_execution_time': 0.0,
            'min_execution_time': float('inf'),
            'max_execution_time': 0.0,
        }
    
    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        """
        关闭线程池
        
        Args:
            wait: 是否等待所有任务完成
                  - True: 等待所有已提交的任务完成
                  - False: 立即关闭，不等待任务完成
            cancel_futures: 是否取消待执行的任务（Python 3.9+）
                           - True: 取消所有尚未开始的任务
                           - False: 保留待执行的任务
        
        Note:
            关闭后不能再提交新任务，否则会抛出 RuntimeError
            
        Example:
            # 等待所有任务完成后关闭
            thread_pool.shutdown(wait=True)
            
            # 立即关闭（不推荐，可能导致数据丢失）
            thread_pool.shutdown(wait=False)
        """
        if self._executor is not None:
            try:
                # Python 3.9+ 支持 cancel_futures 参数
                import sys
                if sys.version_info >= (3, 9):
                    self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)
                else:
                    self._executor.shutdown(wait=wait)
            except Exception:
                # 确保关闭
                try:
                    self._executor.shutdown(wait=wait)
                except Exception:
                    pass
            
            self._executor = None
            self._initialized = False
    
    async def __aenter__(self) -> 'ThreadPoolManager':
        """
        异步上下文管理器入口
        """
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        异步上下文管理器出口
        """
        self.shutdown(wait=True)
    
    def __enter__(self) -> 'ThreadPoolManager':
        """
        同步上下文管理器入口
        """
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        同步上下文管理器出口
        """
        self.shutdown(wait=True)
    
    def __repr__(self) -> str:
        """
        返回对象的字符串表示
        """
        stats = self.get_stats()
        return (
            f"ThreadPoolManager("
            f"max_workers={stats['max_workers']}, "
            f"active_threads={stats['active_threads']}, "
            f"total_tasks={stats['total_tasks']}, "
            f"completed={stats['completed_tasks']}, "
            f"failed={stats['failed_tasks']}, "
            f"success_rate={stats['success_rate']:.1f}%)"
        )
    
    def __del__(self) -> None:
        """
        析构函数，确保线程池被正确关闭
        """
        if self._executor is not None:
            try:
                self._executor.shutdown(wait=False)
            except Exception:
                pass


# 便捷函数
def create_thread_pool(max_workers: Optional[int] = None) -> ThreadPoolManager:
    """
    创建线程池管理器的便捷函数
    
    Args:
        max_workers: 最大工作线程数
        
    Returns:
        ThreadPoolManager 实例
        
    Example:
        thread_pool = create_thread_pool(max_workers=8)
        result = await thread_pool.run_in_thread(cpu_intensive_func, arg1, arg2)
    """
    return ThreadPoolManager(max_workers=max_workers)
