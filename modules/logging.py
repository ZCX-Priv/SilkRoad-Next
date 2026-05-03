"""
日志服务模块
基于 loguru 实现的日志系统，支持多级别日志、按天轮转、自动清理和彩色输出
"""

import sys
from pathlib import Path
from typing import Optional, Union
from loguru import logger

LoggerType = Union['Logger', object]


class LoggerOptWrapper:
    """
    Logger 选项包装器
    
    用于支持 opt() 方法的链式调用，如 logger.opt(exception=True).error(...)
    """
    
    def __init__(self, logger_instance, exception: bool = False):
        self._logger = logger_instance
        self._exception = exception
    
    def info(self, message: str):
        if self._exception:
            self._logger.opt(exception=True).info(message)
        else:
            self._logger.info(message)
    
    def debug(self, message: str):
        if self._exception:
            self._logger.opt(exception=True).debug(message)
        else:
            self._logger.debug(message)
    
    def warning(self, message: str):
        if self._exception:
            self._logger.opt(exception=True).warning(message)
        else:
            self._logger.warning(message)
    
    def error(self, message: str):
        if self._exception:
            self._logger.opt(exception=True).error(message)
        else:
            self._logger.error(message)


class Logger:
    """
    日志管理类
    
    功能特性：
    - 多级别日志支持（INFO/DEBUG/WARN/ERROR）
    - 控制台彩色输出
    - 文件按天轮转（格式：YYYY-MM-DD.log）
    - 错误日志单独文件（error_YYYY-MM-DD.log）
    - 自动清理过期日志
    - UTF-8 编码支持
    """
    
    def __init__(self, config):
        """
        初始化日志系统
        
        Args:
            config: 配置管理器对象，用于获取日志配置
        """
        self.config = config
        self.log_dir = Path('logs')
        
        # 创建日志目录
        self.log_dir.mkdir(exist_ok=True)
        
        # 配置 loguru
        self._setup_logger()
    
    def _setup_logger(self):
        """
        配置 loguru 日志系统
        
        配置三个输出目标：
        1. 控制台输出（带颜色）
        2. 普通日志文件（按天轮转）
        3. 错误日志文件（单独存储）
        """
        # 移除默认处理器，避免重复输出
        logger.remove()
        
        # 获取日志配置
        log_level = self.config.get('logging.level', 'INFO')
        retention = self._parse_retention(
            self.config.get('logging.retention', '30 days')
        )
        
        # 1. 控制台输出（带颜色）
        logger.add(
            sys.stdout,
            level=log_level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                   "<level>{level: <8}</level> | "
                   "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                   "<level>{message}</level>",
            colorize=True,
            enqueue=True  # 异步写入，提高性能
        )
        
        # 2. 文件输出（按天轮转）
        logger.add(
            self.log_dir / "{time:YYYY-MM-DD}.log",
            level=log_level,
            rotation="00:00",  # 每天午夜轮转
            retention=retention,
            encoding='utf-8',
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
            enqueue=True,  # 异步写入
            serialize=False  # 不序列化为JSON，保持可读性
        )
        
        # 3. 错误日志单独文件
        logger.add(
            self.log_dir / "error_{time:YYYY-MM-DD}.log",
            level="ERROR",
            rotation="00:00",
            retention=retention,
            encoding='utf-8',
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}\n{exception}",
            enqueue=True,
            serialize=False,
            backtrace=True,  # 显示完整回溯
            diagnose=True    # 显示变量值
        )
    
    def _parse_retention(self, retention_str: str) -> Optional[str]:
        """
        解析日志保留策略
        
        支持中文和英文两种格式：
        - 中文：7天、30天、6个月、1年、关闭
        - 英文：7 days、30 days、6 months、1 year、off
        
        Args:
            retention_str: 保留策略字符串
            
        Returns:
            loguru 支持的保留策略字符串，如果关闭则返回 None
        """
        # 中文映射表
        retention_map = {
            '7天': '7 days',
            '30天': '30 days',
            '6个月': '6 months',
            '1年': '1 year',
            '关闭': None,
            'off': None
        }
        
        # 查找映射表
        if retention_str in retention_map:
            return retention_map[retention_str]
        
        # 如果不在映射表中，直接返回原值（支持英文格式）
        return retention_str
    
    def info(self, message: str):
        """
        记录 INFO 级别日志
        
        Args:
            message: 日志消息
        """
        logger.info(message)
    
    def debug(self, message: str):
        """
        记录 DEBUG 级别日志
        
        Args:
            message: 日志消息
        """
        logger.debug(message)
    
    def warning(self, message: str):
        """
        记录 WARNING 级别日志
        
        Args:
            message: 日志消息
        """
        logger.warning(message)
    
    def error(self, message: str, exception: Optional[Exception] = None, exc_info: bool = False):
        """
        记录 ERROR 级别日志
        
        Args:
            message: 日志消息
            exception: 可选的异常对象，如果提供则会记录异常堆栈
            exc_info: 兼容标准库 logging 的参数，如果为 True 则记录异常堆栈
        """
        if exception or exc_info:
            logger.opt(exception=True).error(message)
        else:
            logger.error(message)
    
    def opt(self, exception: bool = False):
        """
        返回带有选项的 logger 包装器
        
        兼容 loguru 的 opt() 方法，用于控制日志行为
        
        Args:
            exception: 是否包含异常堆栈
            
        Returns:
            LoggerOptWrapper: 包装器对象，支持链式调用
        """
        return LoggerOptWrapper(logger, exception)
    
    async def close(self):
        """
        关闭日志系统
        
        确保所有日志都已写入文件，然后移除所有处理器
        """
        await logger.complete()
        logger.remove()
    
    def set_level(self, level: str):
        """
        动态设置日志级别
        
        重新配置日志系统以使用新的日志级别。
        这会移除现有的处理器并添加新的处理器。
        
        Args:
            level: 日志级别（DEBUG、INFO、WARNING、ERROR）
        """
        level = level.upper()
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR']
        if level not in valid_levels:
            raise ValueError(f"无效的日志级别: {level}，有效值为: {valid_levels}")
        
        retention = self._parse_retention(
            self.config.get('logging.retention', '30 days')
        )
        
        logger.remove()
        
        logger.add(
            sys.stdout,
            level=level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                   "<level>{level: <8}</level> | "
                   "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                   "<level>{message}</level>",
            colorize=True,
            enqueue=True
        )
        
        logger.add(
            self.log_dir / "{time:YYYY-MM-DD}.log",
            level=level,
            rotation="00:00",
            retention=retention,
            encoding='utf-8',
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
            enqueue=True,
            serialize=False
        )
        
        logger.add(
            self.log_dir / "error_{time:YYYY-MM-DD}.log",
            level="ERROR",
            rotation="00:00",
            retention=retention,
            encoding='utf-8',
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}\n{exception}",
            enqueue=True,
            serialize=False,
            backtrace=True,
            diagnose=True
        )
