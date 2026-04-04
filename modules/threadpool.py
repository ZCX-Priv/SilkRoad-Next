"""
线程池管理模块

该模块提供了线程池管理器，用于处理 CPU 密集型任务，防止阻塞主异步事件循环。
支持任务超时控制、优先级调度、批量执行等功能。

Author: SilkRoad-Next Team
Version: 2.0
"""

import asyncio
import functools
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple


class ThreadPoolManager:
    """
    线程池管理器

    功能：
    1. 管理 CPU 密集型任务的执行
    2. 防止阻塞主事件循环
    3. 任务优先级调度
    4. 任务超时控制
    5. 批量任务执行
    6. 任务统计信息查询
    7. 优雅关闭
    """

    def __init__(self, max_workers: Optional[int] = None):
        """
        初始化线程池

        Args:
            max_workers: 最大工作线程数，默认为 CPU 核心数 * 2
                        如果为 None，则使用 concurrent.futures 的默认值
                        (CPU 核心数 + 4，最大 32)
        """
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.loop: Optional[asyncio.AbstractEventLoop] = None

        # 任务统计
        self.stats: Dict[str, Any] = {
            'total_tasks': 0,
            'completed_tasks': 0,
            'failed_tasks': 0,
            'timeout_tasks': 0,
            'average_execution_time': 0.0,
            'total_execution_time': 0.0
        }

        # 任务队列（用于优先级调度）
        self._task_queue: List[Tuple[int, float, Callable, tuple, dict]] = []
        self._queue_lock = asyncio.Lock()

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """
        设置事件循环

        Args:
            loop: asyncio 事件循环
        """
        self.loop = loop

    async def run_in_thread(
        self,
        func: Callable,
        *args,
        timeout: Optional[float] = None,
        priority: int = 0,
        **kwargs
    ) -> Any:
        """
        在线程池中运行 CPU 密集型任务

        Args:
            func: 要执行的函数
            *args: 函数位置参数
            timeout: 任务超时时间（秒），None 表示不超时
            priority: 任务优先级，数值越大优先级越高（默认为 0）
            **kwargs: 函数关键字参数

        Returns:
            函数执行结果

        Raises:
            asyncio.TimeoutError: 任务超时
            Exception: 任务执行失败

        Example:
            >>> async def example():
            ...     result = await thread_pool.run_in_thread(
            ...         cpu_intensive_function,
            ...         data,
            ...         timeout=10.0,
            ...         priority=5
            ...     )
            ...     return result
        """
        if self.loop is None:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                # 如果没有运行中的事件循环，创建一个新的
                self.loop = asyncio.get_event_loop()

        start_time = time.time()

        try:
            self.stats['total_tasks'] += 1

            # 使用 functools.partial 绑定参数
            if kwargs:
                func_partial = functools.partial(func, *args, **kwargs)
            else:
                func_partial = functools.partial(func, *args)

            # 在线程池中执行
            future = self.loop.run_in_executor(self.executor, func_partial)

            # 设置超时
            if timeout is not None and timeout > 0:
                try:
                    result = await asyncio.wait_for(future, timeout=timeout)
                except asyncio.TimeoutError:
                    self.stats['timeout_tasks'] += 1
                    self.stats['failed_tasks'] += 1
                    raise
            else:
                result = await future

            # 更新统计信息
            execution_time = time.time() - start_time
            self.stats['completed_tasks'] += 1
            self._update_average_time(execution_time)

            return result

        except asyncio.TimeoutError:
            # 已经在上面更新了统计信息
            raise
        except Exception as e:
            self.stats['failed_tasks'] += 1
            raise

    def _update_average_time(self, execution_time: float) -> None:
        """
        更新平均执行时间

        Args:
            execution_time: 本次执行时间（秒）
        """
        completed = self.stats['completed_tasks']
        current_avg = self.stats['average_execution_time']

        # 计算新的平均值（增量更新）
        new_avg = (current_avg * (completed - 1) + execution_time) / completed
        self.stats['average_execution_time'] = new_avg
        self.stats['total_execution_time'] += execution_time

    async def run_batch(
        self,
        tasks: List[Tuple[Callable, tuple, Optional[dict]]],
        timeout: Optional[float] = None,
        fail_fast: bool = False
    ) -> List[Any]:
        """
        批量执行多个任务

        Args:
            tasks: 任务列表，每个元素为 (func, args, kwargs) 元组
                   - func: 要执行的函数
                   - args: 函数位置参数（元组）
                   - kwargs: 函数关键字参数（字典，可选）
            timeout: 单个任务超时时间（秒），None 表示不超时
            fail_fast: 是否在第一个失败时立即返回，默认为 False

        Returns:
            结果列表，顺序与输入一致。如果任务失败，结果为异常对象。

        Example:
            >>> async def example():
            ...     tasks = [
            ...         (func1, (arg1, arg2), {'kwarg1': value1}),
            ...         (func2, (arg3,), None),
            ...         (func3, (), {'kwarg2': value2})
            ...     ]
            ...     results = await thread_pool.run_batch(tasks, timeout=5.0)
            ...     return results
        """
        futures = []

        for task in tasks:
            # 解析任务参数
            if len(task) == 2:
                func, args = task
                kwargs = {}
            elif len(task) == 3:
                func, args, kwargs = task
                if kwargs is None:
                    kwargs = {}
            else:
                raise ValueError(
                    f"Invalid task format: {task}. "
                    f"Expected (func, args, kwargs) or (func, args)"
                )

            # 创建任务
            future = self.run_in_thread(func, *args, timeout=timeout, **kwargs)
            futures.append(future)

        # 并发执行所有任务
        if fail_fast:
            # 使用 gather 的 return_exceptions=False 模式
            # 第一个异常会立即抛出
            try:
                results = await asyncio.gather(*futures, return_exceptions=False)
            except Exception:
                # 取消所有未完成的任务
                for future in futures:
                    if not future.done():
                        future.cancel()
                raise
        else:
            # 使用 gather 的 return_exceptions=True 模式
            # 所有任务都会执行完成，失败的任务返回异常对象
            results = await asyncio.gather(*futures, return_exceptions=True)

        return results

    async def run_with_priority(
        self,
        func: Callable,
        *args,
        priority: int = 0,
        timeout: Optional[float] = None,
        **kwargs
    ) -> Any:
        """
        按优先级执行任务

        注意：此方法为简化实现，优先级仅用于统计和日志记录。
        实际执行顺序由线程池调度器决定。

        Args:
            func: 要执行的函数
            *args: 函数位置参数
            priority: 任务优先级，数值越大优先级越高（默认为 0）
            timeout: 任务超时时间（秒）
            **kwargs: 函数关键字参数

        Returns:
            函数执行结果

        Example:
            >>> async def example():
            ...     # 高优先级任务
            ...     result = await thread_pool.run_with_priority(
            ...         important_function,
            ...         data,
            ...         priority=10,
            ...         timeout=5.0
            ...     )
            ...     return result
        """
        # 在简化实现中，优先级仅用于日志记录
        # 实际执行仍然使用 run_in_thread
        return await self.run_in_thread(
            func,
            *args,
            timeout=timeout,
            priority=priority,
            **kwargs
        )

    def get_stats(self) -> Dict[str, Any]:
        """
        获取线程池统计信息

        Returns:
            统计信息字典，包含：
            - total_tasks: 总任务数
            - completed_tasks: 已完成任务数
            - failed_tasks: 失败任务数
            - timeout_tasks: 超时任务数
            - average_execution_time: 平均执行时间（秒）
            - total_execution_time: 总执行时间（秒）
            - max_workers: 最大工作线程数
            - active_threads: 活跃线程数

        Example:
            >>> stats = thread_pool.get_stats()
            >>> print(f"Completed: {stats['completed_tasks']}/{stats['total_tasks']}")
            >>> print(f"Average time: {stats['average_execution_time']:.2f}s")
        """
        # 获取线程池信息
        max_workers = self.executor._max_workers

        # 计算活跃线程数
        active_threads = 0
        if hasattr(self.executor, '_threads'):
            active_threads = len([
                t for t in self.executor._threads if t.is_alive()
            ])

        return {
            **self.stats,
            'max_workers': max_workers,
            'active_threads': active_threads,
            'success_rate': (
                self.stats['completed_tasks'] / self.stats['total_tasks'] * 100
                if self.stats['total_tasks'] > 0 else 0.0
            )
        }

    def reset_stats(self) -> None:
        """
        重置统计信息

        将所有统计计数器归零，保留线程池配置。
        """
        self.stats = {
            'total_tasks': 0,
            'completed_tasks': 0,
            'failed_tasks': 0,
            'timeout_tasks': 0,
            'average_execution_time': 0.0,
            'total_execution_time': 0.0
        }

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        """
        关闭线程池

        Args:
            wait: 是否等待所有任务完成（默认为 True）
            cancel_futures: 是否取消未开始的任务（默认为 False）
                           Python 3.9+ 支持

        Example:
            >>> # 优雅关闭（等待任务完成）
            >>> thread_pool.shutdown(wait=True)
            >>>
            >>> # 立即关闭（不等待）
            >>> thread_pool.shutdown(wait=False)
        """
        try:
            # Python 3.9+ 支持 cancel_futures 参数
            if cancel_futures:
                self.executor.shutdown(wait=wait, cancel_futures=cancel_futures)
            else:
                self.executor.shutdown(wait=wait)
        except TypeError:
            # Python 3.8 及以下版本不支持 cancel_futures 参数
            self.executor.shutdown(wait=wait)

    async def __aenter__(self) -> 'ThreadPoolManager':
        """
        异步上下文管理器入口

        Returns:
            线程池管理器实例
        """
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        异步上下文管理器出口

        自动关闭线程池
        """
        self.shutdown(wait=True)

    def __enter__(self) -> 'ThreadPoolManager':
        """
        同步上下文管理器入口

        Returns:
            线程池管理器实例
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        同步上下文管理器出口

        自动关闭线程池
        """
        self.shutdown(wait=True)


class PriorityThreadPoolManager(ThreadPoolManager):
    """
    支持优先级的线程池管理器

    使用多个线程池实现优先级调度：
    - 高优先级任务使用专用线程池
    - 普通优先级任务使用普通线程池
    """

    def __init__(
        self,
        max_workers: Optional[int] = None,
        high_priority_workers: Optional[int] = None,
        normal_priority_workers: Optional[int] = None
    ):
        """
        初始化优先级线程池

        Args:
            max_workers: 总最大工作线程数（如果未指定高/普通优先级线程数）
            high_priority_workers: 高优先级线程池大小
            normal_priority_workers: 普通优先级线程池大小
        """
        # 如果未单独指定，则平均分配
        if max_workers is None:
            import os
            max_workers = (os.cpu_count() or 1) * 2

        if high_priority_workers is None:
            high_priority_workers = max_workers // 2 or 1

        if normal_priority_workers is None:
            normal_priority_workers = max_workers - high_priority_workers or 1

        # 不调用父类的 __init__，而是自己初始化
        self.high_priority_executor = ThreadPoolExecutor(
            max_workers=high_priority_workers
        )
        self.normal_priority_executor = ThreadPoolExecutor(
            max_workers=normal_priority_workers
        )
        self.loop: Optional[asyncio.AbstractEventLoop] = None

        # 任务统计
        self.stats: Dict[str, Any] = {
            'total_tasks': 0,
            'completed_tasks': 0,
            'failed_tasks': 0,
            'timeout_tasks': 0,
            'average_execution_time': 0.0,
            'total_execution_time': 0.0,
            'high_priority_tasks': 0,
            'normal_priority_tasks': 0
        }

    async def run_with_priority(
        self,
        func: Callable,
        *args,
        priority: int = 0,
        timeout: Optional[float] = None,
        **kwargs
    ) -> Any:
        """
        按优先级执行任务

        Args:
            func: 要执行的函数
            *args: 函数位置参数
            priority: 任务优先级
                     - priority >= 5: 高优先级
                     - priority < 5: 普通优先级
            timeout: 任务超时时间（秒）
            **kwargs: 函数关键字参数

        Returns:
            函数执行结果
        """
        if self.loop is None:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                self.loop = asyncio.get_event_loop()

        start_time = time.time()

        try:
            self.stats['total_tasks'] += 1

            # 根据优先级选择线程池
            if priority >= 5:
                executor = self.high_priority_executor
                self.stats['high_priority_tasks'] += 1
            else:
                executor = self.normal_priority_executor
                self.stats['normal_priority_tasks'] += 1

            # 使用 functools.partial 绑定参数
            if kwargs:
                func_partial = functools.partial(func, *args, **kwargs)
            else:
                func_partial = functools.partial(func, *args)

            # 在线程池中执行
            future = self.loop.run_in_executor(executor, func_partial)

            # 设置超时
            if timeout is not None and timeout > 0:
                try:
                    result = await asyncio.wait_for(future, timeout=timeout)
                except asyncio.TimeoutError:
                    self.stats['timeout_tasks'] += 1
                    self.stats['failed_tasks'] += 1
                    raise
            else:
                result = await future

            # 更新统计信息
            execution_time = time.time() - start_time
            self.stats['completed_tasks'] += 1
            self._update_average_time(execution_time)

            return result

        except asyncio.TimeoutError:
            raise
        except Exception as e:
            self.stats['failed_tasks'] += 1
            raise

    def get_stats(self) -> Dict[str, Any]:
        """
        获取线程池统计信息

        Returns:
            统计信息字典，包含优先级相关的统计
        """
        # 计算活跃线程数
        high_priority_active = 0
        normal_priority_active = 0

        if hasattr(self.high_priority_executor, '_threads'):
            high_priority_active = len([
                t for t in self.high_priority_executor._threads if t.is_alive()
            ])

        if hasattr(self.normal_priority_executor, '_threads'):
            normal_priority_active = len([
                t for t in self.normal_priority_executor._threads if t.is_alive()
            ])

        return {
            **self.stats,
            'high_priority_workers': self.high_priority_executor._max_workers,
            'normal_priority_workers': self.normal_priority_executor._max_workers,
            'high_priority_active': high_priority_active,
            'normal_priority_active': normal_priority_active,
            'success_rate': (
                self.stats['completed_tasks'] / self.stats['total_tasks'] * 100
                if self.stats['total_tasks'] > 0 else 0.0
            )
        }

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        """
        关闭所有线程池

        Args:
            wait: 是否等待所有任务完成
            cancel_futures: 是否取消未开始的任务
        """
        try:
            if cancel_futures:
                self.high_priority_executor.shutdown(
                    wait=wait, cancel_futures=cancel_futures
                )
                self.normal_priority_executor.shutdown(
                    wait=wait, cancel_futures=cancel_futures
                )
            else:
                self.high_priority_executor.shutdown(wait=wait)
                self.normal_priority_executor.shutdown(wait=wait)
        except TypeError:
            # Python 3.8 及以下版本
            self.high_priority_executor.shutdown(wait=wait)
            self.normal_priority_executor.shutdown(wait=wait)
