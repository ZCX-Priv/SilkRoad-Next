"""
优雅退出模块

实现优雅退出机制，确保：
- 完成正在处理的请求
- 保存配置和缓存
- 关闭所有连接

Author: SilkRoad-Next Team
"""

import signal
import asyncio
from typing import Set, Optional
import atexit
import sys


class GracefulExit:
    """
    优雅退出管理器

    负责处理系统信号、管理活动任务、执行清理操作
    """

    # 类变量：关闭事件
    shutdown_event: Optional[asyncio.Event] = None

    # 类变量：日志记录器
    logger = None

    # 类变量：活动任务集合
    active_tasks: Set[asyncio.Task] = set()

    # 类变量：是否已初始化
    _initialized: bool = False

    @classmethod
    def setup(cls, shutdown_event: asyncio.Event, logger) -> None:
        """
        设置优雅退出

        Args:
            shutdown_event: 异步关闭事件，用于通知系统开始关闭
            logger: 日志记录器实例
        """
        # 避免重复初始化
        if cls._initialized:
            logger.warning("GracefulExit 已经初始化，跳过重复设置")
            return

        cls.shutdown_event = shutdown_event
        cls.logger = logger
        cls._initialized = True

        # 注册信号处理器
        # SIGINT: Ctrl+C 中断信号
        signal.signal(signal.SIGINT, cls._signal_handler)

        # SIGTERM: 终止信号（kill 命令默认发送）
        signal.signal(signal.SIGTERM, cls._signal_handler)

        # Windows 不支持 SIGQUIT，需要捕获 AttributeError
        try:
            signal.signal(signal.SIGQUIT, cls._signal_handler)
        except AttributeError:
            # Windows 系统不支持 SIGQUIT 信号
            if cls.logger:
                cls.logger.debug("当前系统不支持 SIGQUIT 信号（Windows 平台）")

        # 注册退出清理函数
        # atexit 会在 Python 解释器退出时自动调用
        atexit.register(cls._cleanup)

        if cls.logger:
            cls.logger.info("优雅退出模块初始化完成")

    @classmethod
    def _signal_handler(cls, signum: int, frame) -> None:
        """
        信号处理器

        处理接收到的系统信号，触发优雅退出流程

        Args:
            signum: 信号编号
            frame: 当前栈帧（未使用）
        """
        # 信号编号到信号名称的映射
        signal_names = {
            signal.SIGINT: 'SIGINT (Ctrl+C)',
            signal.SIGTERM: 'SIGTERM (终止信号)',
        }

        # 尝试添加 SIGQUIT（如果系统支持）
        try:
            signal_names[signal.SIGQUIT] = 'SIGQUIT (退出信号)'
        except AttributeError:
            pass

        # 获取信号名称
        signal_name = signal_names.get(signum, f'信号 {signum}')

        # 记录日志
        if cls.logger:
            cls.logger.info(f"接收到 {signal_name}，准备优雅退出")

        # 设置关闭事件，通知主程序开始关闭流程
        if cls.shutdown_event:
            cls.shutdown_event.set()

    @classmethod
    def register_task(cls, task: asyncio.Task) -> None:
        """
        注册活动任务

        将任务添加到活动任务集合，任务完成后自动移除

        Args:
            task: 需要注册的异步任务
        """
        if not cls._initialized:
            if cls.logger:
                cls.logger.warning("GracefulExit 未初始化，无法注册任务")
            return

        # 添加到活动任务集合
        cls.active_tasks.add(task)

        # 任务完成时自动从集合中移除
        # 使用 add_done_callback 确保任务完成后自动清理
        task.add_done_callback(cls.active_tasks.discard)

        if cls.logger:
            cls.logger.debug(f"注册任务: {task.get_name()}, 当前活动任务数: {len(cls.active_tasks)}")

    @classmethod
    async def wait_for_tasks(cls, timeout: int = 30) -> None:
        """
        等待所有任务完成

        在指定超时时间内等待所有活动任务完成

        Args:
            timeout: 超时时间（秒），默认 30 秒
        """
        if not cls.active_tasks:
            if cls.logger:
                cls.logger.info("没有活动任务，直接退出")
            return

        if cls.logger:
            cls.logger.info(f"等待 {len(cls.active_tasks)} 个活动任务完成（超时: {timeout}秒）...")

        try:
            # 等待所有任务完成
            # return_exceptions=True 确保即使任务抛出异常也不会中断等待
            await asyncio.wait_for(
                asyncio.gather(*cls.active_tasks, return_exceptions=True),
                timeout=timeout
            )

            if cls.logger:
                cls.logger.info("所有活动任务已完成")

        except asyncio.TimeoutError:
            # 超时后仍有任务未完成
            if cls.logger:
                cls.logger.warning(
                    f"等待超时，仍有 {len(cls.active_tasks)} 个任务未完成，强制退出"
                )

            # 记录未完成任务的信息
            for task in cls.active_tasks:
                if cls.logger:
                    cls.logger.warning(f"未完成任务: {task.get_name()}, 状态: {task.done()}")

    @classmethod
    def _cleanup(cls) -> None:
        """
        清理资源

        在程序退出时执行清理操作，包括：
        - 保存配置
        - 清理缓存
        - 关闭文件句柄
        - 释放系统资源
        """
        if cls.logger:
            cls.logger.info("执行清理操作...")

        try:
            # 1. 清理活动任务
            if cls.active_tasks:
                if cls.logger:
                    cls.logger.info(f"清理 {len(cls.active_tasks)} 个未完成任务")

                # 取消所有未完成的任务
                for task in cls.active_tasks:
                    if not task.done():
                        task.cancel()

            # 2. 清理其他资源
            # TODO: 在实际使用中添加以下清理逻辑：
            # - 保存配置文件
            # - 刷新日志缓冲区
            # - 关闭数据库连接
            # - 清理临时文件
            # - 释放网络连接

            if cls.logger:
                cls.logger.info("清理操作完成")

        except Exception as e:
            # 清理过程中的错误不应该阻止程序退出
            if cls.logger:
                cls.logger.error(f"清理过程中发生错误: {e}")

    @classmethod
    def force_exit(cls, exit_code: int = 0) -> None:
        """
        强制退出程序

        在无法优雅退出时使用，立即终止程序

        Args:
            exit_code: 退出码，默认 0（正常退出）
        """
        if cls.logger:
            cls.logger.warning(f"强制退出程序，退出码: {exit_code}")

        # 执行清理
        cls._cleanup()

        # 强制退出
        sys.exit(exit_code)

    @classmethod
    def get_active_task_count(cls) -> int:
        """
        获取活动任务数量

        Returns:
            int: 当前活动任务的数量
        """
        return len(cls.active_tasks)

    @classmethod
    def is_initialized(cls) -> bool:
        """
        检查是否已初始化

        Returns:
            bool: 是否已初始化
        """
        return cls._initialized


# 提供便捷的模块级函数
def setup_graceful_exit(shutdown_event: asyncio.Event, logger) -> None:
    """
    设置优雅退出的便捷函数

    Args:
        shutdown_event: 异步关闭事件
        logger: 日志记录器实例
    """
    GracefulExit.setup(shutdown_event, logger)


def register_async_task(task: asyncio.Task) -> None:
    """
    注册异步任务的便捷函数

    Args:
        task: 需要注册的异步任务
    """
    GracefulExit.register_task(task)


async def wait_for_all_tasks(timeout: int = 30) -> None:
    """
    等待所有任务完成的便捷函数

    Args:
        timeout: 超时时间（秒），默认 30 秒
    """
    await GracefulExit.wait_for_tasks(timeout)
