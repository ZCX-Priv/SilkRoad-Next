"""
SilkRoad-Next 程序主入口

作为整个系统的启动入口，负责：
- 初始化所有核心模块
- 启动代理服务器
- 注册信号处理器
- 协调各模块生命周期

V2 扩展功能：
- V2 模块状态显示
- V2 模块清理任务

Author: SilkRoad-Next Team
Version: 2.0.0
"""

import asyncio
import sys
from typing import Optional

from modules.cfg import ConfigManager, ConfigError
from modules.logging import Logger
from modules.proxy import ProxyServer
from modules.command import CommandHandler
from modules.exit import GracefulExit


class SilkRoad:
    """
    SilkRoad-Next 主应用类

    负责协调所有核心模块的初始化、启动和关闭。

    Attributes:
        config (ConfigManager): 配置管理器
        logger (Logger): 日志记录器
        proxy_server (Optional[ProxyServer]): 代理服务器实例
        command_handler (Optional[CommandHandler]): 命令处理器实例
        shutdown_event (asyncio.Event): 关闭事件，用于通知系统开始关闭
    """

    def __init__(self):
        """
        初始化 SilkRoad 应用

        创建所有核心模块的引用，但不执行初始化逻辑。
        """
        # 配置管理器
        self.config = ConfigManager()

        # 日志记录器（需要配置管理器）
        self.logger: Optional[Logger] = None

        # 代理服务器（需要配置和日志）
        self.proxy_server: Optional[ProxyServer] = None

        # 命令处理器（需要代理服务器、配置和日志）
        self.command_handler: Optional[CommandHandler] = None

        # 关闭事件，用于优雅退出
        self.shutdown_event = asyncio.Event()

    async def initialize(self) -> None:
        """
        初始化所有模块

        按照依赖顺序初始化所有核心模块：
        1. 加载配置文件
        2. 初始化日志系统
        3. 创建代理服务器
        4. 创建命令处理器
        5. 设置优雅退出

        Raises:
            ConfigError: 配置加载失败
            Exception: 其他初始化错误
        """
        try:
            print("=" * 60)
            print("  SilkRoad-Next v2.0.0 - 高性能反向代理服务器")
            print("=" * 60)
            print()
            print("[1/5] 加载配置文件...")

            await self.config.load()

            print("[2/5] 初始化日志系统...")

            self.logger = Logger(self.config)
            self.logger.info("配置加载完成")

            v2_enabled = self.config.get('v2.enabled', True)
            if v2_enabled:
                self.logger.info("V2 增强功能已启用")

            print("[3/5] 创建代理服务器...")

            proxy_host = self.config.get('server.proxy.host', '0.0.0.0')
            proxy_port = self.config.get('server.proxy.port', 8080)

            self.proxy_server = ProxyServer(
                host=proxy_host,
                port=proxy_port,
                config=self.config,
                logger=self.logger
            )

            self.logger.info(f"代理服务器配置: {proxy_host}:{proxy_port}")

            print("[4/5] 创建命令处理器...")

            self.command_handler = CommandHandler(
                proxy_server=self.proxy_server,
                config=self.config,
                logger=self.logger
            )

            self.proxy_server.command_handler = self.command_handler
            self.logger.info("命令处理器已绑定到代理服务器")

            # ========== 5. 设置优雅退出 ==========
            print("[5/5] 设置优雅退出...")

            GracefulExit.setup(self.shutdown_event, self.logger)

            # ========== 初始化完成 ==========
            print()
            print("=" * 60)
            print("  初始化完成！")
            print("=" * 60)
            print()

            self.logger.info("所有模块初始化完成")

        except ConfigError as e:
            print(f"[错误] 配置加载失败: {e}")
            raise

        except Exception as e:
            error_msg = f"初始化失败: {e}"
            if self.logger:
                self.logger.error(error_msg, exception=e)
            else:
                print(f"[错误] {error_msg}")
            raise

    async def run(self) -> None:
        """
        启动主服务

        执行完整的启动流程：
        1. 初始化所有模块
        2. 启动代理服务器
        3. 启动命令处理器
        4. 等待关闭信号

        Raises:
            Exception: 启动过程中的任何错误
        """
        try:
            await self.initialize()

            assert self.logger is not None
            assert self.proxy_server is not None

            self._display_startup_info()

            tasks = [
                asyncio.create_task(self.proxy_server.start()),
                asyncio.create_task(self.wait_for_shutdown())
            ]

            self.logger.info("所有服务已启动，开始处理请求...")

            await asyncio.gather(*tasks)

        except OSError as e:
            # 端口占用等系统错误
            if self.logger:
                self.logger.error(f"服务启动失败（系统错误）: {e}")
            else:
                print(f"[错误] 服务启动失败: {e}")
            raise

        except Exception as e:
            # 其他启动错误
            if self.logger:
                self.logger.error(f"服务启动失败: {e}", exception=e)
            else:
                print(f"[错误] 服务启动失败: {e}")
            raise

    async def wait_for_shutdown(self) -> None:
        """
        等待关闭信号

        阻塞等待关闭事件被触发，然后执行优雅关闭流程：
        1. 停止代理服务器（包含V2模块清理）
        2. 关闭日志系统
        """
        await self.shutdown_event.wait()

        if not self.logger:
            return

        self.logger.info("=" * 60)
        self.logger.info("开始优雅关闭...")
        self.logger.info("=" * 60)

        try:
            if self.proxy_server:
                self.logger.info("[1/2] 停止代理服务器和V2模块...")
                await self.proxy_server.stop()

            self.logger.info("[2/2] 关闭日志系统...")
            await self.logger.close()

            print()
            print("=" * 60)
            print("  SilkRoad-Next v2.0.0 已安全退出")
            print("=" * 60)

        except Exception as e:
            if self.logger:
                self.logger.error(f"关闭过程中发生错误: {e}")
            else:
                print(f"[错误] 关闭过程中发生错误: {e}")

    def _display_startup_info(self) -> None:
        """
        显示启动信息

        在控制台打印欢迎界面和服务信息。
        """
        proxy_host = self.config.get('server.proxy.host', '0.0.0.0')
        proxy_port = self.config.get('server.proxy.port', 8080)
        max_connections = self.config.get('server.proxy.maxConnections', 2000)
        log_level = self.config.get('logging.level', 'INFO')
        v2_enabled = self.config.get('v2.enabled', True)

        display_host = '127.0.0.1' if proxy_host == '0.0.0.0' else proxy_host

        v2_features = []
        if v2_enabled:
            if self.config.get('connectionPool.maxConnectionsPerHost', 10) > 0:
                v2_features.append("连接池")
            if self.config.get('threadPool.maxWorkers'):
                v2_features.append("线程池")
            if self.config.get('session.timeout', 1800) > 0:
                v2_features.append("会话管理")
            if self.config.get('cache.maxMemoryCacheSize', 104857600) > 0:
                v2_features.append("缓存管理")
            if self.config.get('blacklist.enabled', True):
                v2_features.append("黑名单拦截")
            if self.config.get('scripts.enabled', True):
                v2_features.append("脚本注入")

        print()
        print("┌" + "─" * 58 + "┐")
        print("│" + " " * 58 + "│")
        print("│" + "  SilkRoad-Next v2.0.0".ljust(58) + "│")
        print("│" + "  高性能反向代理服务器".ljust(58) + "│")
        print("│" + " " * 58 + "│")
        print("├" + "─" * 58 + "┤")
        print("│" + " " * 58 + "│")
        print("│  服务信息:".ljust(59) + "│")
        print(f"│    代理服务: http://{proxy_host}:{proxy_port}".ljust(59) + "│")
        print(f"│    管理接口: http://{display_host}:{proxy_port}/command/*".ljust(59) + "│")
        print("│" + " " * 58 + "│")
        print("│  配置信息:".ljust(59) + "│")
        print(f"│    最大并发连接: {max_connections}".ljust(59) + "│")
        print(f"│    日志级别: {log_level}".ljust(59) + "│")
        if v2_enabled and v2_features:
            print(f"│    V2 功能: {', '.join(v2_features)}".ljust(59) + "│")
        print("│" + " " * 58 + "│")
        print("├" + "─" * 58 + "┤")
        print("│" + " " * 58 + "│")
        print("│  可用命令:".ljust(59) + "│")
        print(f"│    查看状态: curl http://{display_host}:{proxy_port}/command/status".ljust(59) + "│")
        print(f"│    暂停服务: curl http://{display_host}:{proxy_port}/command/pause".ljust(59) + "│")
        print(f"│    恢复服务: curl http://{display_host}:{proxy_port}/command/resume".ljust(59) + "│")
        print(f"│    优雅退出: curl http://{display_host}:{proxy_port}/command/exit".ljust(59) + "│")
        print("│" + " " * 58 + "│")
        print("├" + "─" * 58 + "┤")
        print("│" + " " * 58 + "│")
        print("│  按 Ctrl+C 优雅退出".ljust(59) + "│")
        print("│" + " " * 58 + "│")
        print("└" + "─" * 58 + "┘")
        print()


def main() -> None:
    """
    主函数入口

    创建 SilkRoad 实例并启动服务。
    处理顶层异常并确保程序正确退出。
    """
    try:
        # 创建应用实例
        app = SilkRoad()

        # 运行应用（使用 asyncio.run 自动管理事件循环）
        asyncio.run(app.run())

    except KeyboardInterrupt:
        # Ctrl+C 中断（正常退出）
        print("\n[信息] 接收到中断信号，程序已退出")
        sys.exit(0)

    except ConfigError as e:
        # 配置错误
        print(f"\n[错误] 配置错误: {e}")
        sys.exit(1)

    except OSError as e:
        # 系统错误（如端口占用）
        print(f"\n[错误] 系统错误: {e}")
        sys.exit(1)

    except Exception as e:
        # 其他未捕获的异常
        print(f"\n[错误] 程序异常退出: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
