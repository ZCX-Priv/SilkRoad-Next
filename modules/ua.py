"""
User-Agent 随机化模块

管理 User-Agent 池，提供随机 UA 选择功能，支持按类别选择。
用于避免被目标服务器识别为爬虫或代理。

Author: SilkRoad-Next Team
Version: 1.0
"""

import json
import random
from pathlib import Path
from typing import Dict, List, Optional


class UAHandler:
    """
    User-Agent 处理器

    负责管理 User-Agent 池，提供随机 UA 选择功能。
    支持按浏览器类型和设备类型分类选择 UA。

    Attributes:
        ua_file (Path): UA 配置文件路径
        user_agents (List[str]): 所有 UA 列表（向后兼容）
        categories (Dict[str, List[str]]): 分类 UA 字典

    Example:
        >>> handler = UAHandler()
        >>> ua = handler.get_random_ua()  # 随机获取 UA
        >>> mobile_ua = handler.get_mobile_ua()  # 获取移动端 UA
        >>> chrome_ua = handler.get_random_ua('chrome')  # 获取 Chrome UA
    """

    def __init__(self, ua_file: str = "databases/ua.json"):
        """
        初始化 UA 处理器

        Args:
            ua_file (str): UA 配置文件路径，默认为 "databases/ua.json"

        Note:
            如果配置文件不存在，将使用默认 UA 列表
        """
        self.ua_file = Path(ua_file)
        self.user_agents: List[str] = []  # 所有 UA 列表（向后兼容）
        self.categories: Dict[str, List[str]] = {}  # 分类 UA 字典

        # 加载 UA 池
        self._load_user_agents()

    def _load_user_agents(self) -> None:
        """
        从 JSON 文件加载 UA 池

        从配置文件中加载 User-Agent 列表，支持两种格式：
        1. 新格式：直接按类别组织（chrome/firefox/safari/mobile）
        2. 旧格式：包含 userAgents 和 categories 字段

        如果文件不存在或加载失败，使用默认 UA 列表。

        Raises:
            无异常抛出，错误时使用默认 UA
        """
        # 默认 UA 列表（作为后备方案）
        default_user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
            "Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.2 Safari/605.1.15"
        ]

        default_categories = {
            "chrome": [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ],
            "firefox": [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
                "Gecko/20100101 Firefox/121.0"
            ],
            "safari": [
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
                "(KHTML, like Gecko) Version/17.2 Safari/605.1.15"
            ],
            "mobile": [
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 "
                "Mobile/15E148 Safari/604.1"
            ]
        }

        # 检查文件是否存在
        if not self.ua_file.exists():
            # 文件不存在，使用默认值
            self.user_agents = default_user_agents
            self.categories = default_categories
            return

        try:
            # 读取 JSON 文件
            with open(self.ua_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 判断数据格式
            if isinstance(data, dict):
                # 检查是否为旧格式（包含 userAgents 字段）
                if 'userAgents' in data:
                    # 旧格式：包含 userAgents 和 categories
                    self.user_agents = data.get('userAgents', default_user_agents)
                    self.categories = data.get('categories', default_categories)
                else:
                    # 新格式：直接按类别组织
                    self.categories = data
                    # 合并所有类别到 user_agents 列表
                    self.user_agents = []
                    for category_uas in self.categories.values():
                        if isinstance(category_uas, list):
                            self.user_agents.extend(category_uas)

                    # 如果合并后为空，使用默认值
                    if not self.user_agents:
                        self.user_agents = default_user_agents
                        self.categories = default_categories
            else:
                # 数据格式错误，使用默认值
                self.user_agents = default_user_agents
                self.categories = default_categories

        except json.JSONDecodeError as e:
            # JSON 解析错误，使用默认值
            print(f"[UAHandler] UA 文件格式错误: {e}，使用默认 UA")
            self.user_agents = default_user_agents
            self.categories = default_categories

        except Exception as e:
            # 其他错误，使用默认值
            print(f"[UAHandler] 加载 UA 文件失败: {e}，使用默认 UA")
            self.user_agents = default_user_agents
            self.categories = default_categories

    def get_random_ua(self, category: Optional[str] = None) -> str:
        """
        获取随机 User-Agent

        从 UA 池中随机选择一个 User-Agent，支持按类别选择。

        Args:
            category (str, optional): UA 类别，可选值：
                - 'chrome': Chrome 浏览器 UA
                - 'firefox': Firefox 浏览器 UA
                - 'safari': Safari 浏览器 UA
                - 'mobile': 移动端 UA
                - None: 从所有 UA 中随机选择（默认）

        Returns:
            str: 随机选择的 User-Agent 字符串

        Raises:
            无异常抛出，如果类别不存在则从所有 UA 中随机选择

        Example:
            >>> handler = UAHandler()
            >>> ua = handler.get_random_ua()  # 随机 UA
            >>> chrome_ua = handler.get_random_ua('chrome')  # Chrome UA
        """
        # 如果指定了类别且类别存在
        if category and category in self.categories:
            category_uas = self.categories[category]
            if category_uas:
                return random.choice(category_uas)

        # 类别不存在或未指定类别，从所有 UA 中随机选择
        if self.user_agents:
            return random.choice(self.user_agents)

        # 如果所有列表都为空，返回默认 UA（理论上不会执行到这里）
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

    def get_mobile_ua(self) -> str:
        """
        获取移动端 User-Agent

        从移动端 UA 池中随机选择一个 User-Agent。

        Returns:
            str: 随机选择的移动端 User-Agent 字符串

        Example:
            >>> handler = UAHandler()
            >>> mobile_ua = handler.get_mobile_ua()
            >>> print(mobile_ua)
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X)...'
        """
        return self.get_random_ua('mobile')

    def get_desktop_ua(self) -> str:
        """
        获取桌面端 User-Agent

        从桌面端 UA 池（Chrome、Firefox、Safari）中随机选择一个 User-Agent。

        Returns:
            str: 随机选择的桌面端 User-Agent 字符串

        Example:
            >>> handler = UAHandler()
            >>> desktop_ua = handler.get_desktop_ua()
            >>> print(desktop_ua)
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64)...'
        """
        # 合并所有桌面端 UA 类别
        desktop_uas: List[str] = []

        # 按优先级添加桌面端 UA
        desktop_categories = ['chrome', 'firefox', 'safari']

        for category in desktop_categories:
            if category in self.categories:
                category_uas = self.categories[category]
                if isinstance(category_uas, list):
                    desktop_uas.extend(category_uas)

        # 如果有桌面端 UA，随机选择
        if desktop_uas:
            return random.choice(desktop_uas)

        # 如果没有桌面端 UA，从所有 UA 中选择
        return self.get_random_ua()

    def get_all_uas(self) -> List[str]:
        """
        获取所有 User-Agent 列表

        返回所有可用的 User-Agent 列表（去重后）。

        Returns:
            List[str]: 所有 User-Agent 列表

        Example:
            >>> handler = UAHandler()
            >>> all_uas = handler.get_all_uas()
            >>> print(len(all_uas))
            20
        """
        # 去重并返回
        return list(set(self.user_agents))

    def get_categories(self) -> List[str]:
        """
        获取所有可用的 UA 类别

        Returns:
            List[str]: UA 类别列表

        Example:
            >>> handler = UAHandler()
            >>> categories = handler.get_categories()
            >>> print(categories)
            ['chrome', 'firefox', 'safari', 'mobile']
        """
        return list(self.categories.keys())

    def get_category_count(self, category: str) -> int:
        """
        获取指定类别的 UA 数量

        Args:
            category (str): UA 类别

        Returns:
            int: 该类别的 UA 数量，如果类别不存在则返回 0

        Example:
            >>> handler = UAHandler()
            >>> count = handler.get_category_count('chrome')
            >>> print(count)
            6
        """
        if category in self.categories:
            return len(self.categories[category])
        return 0

    def reload(self) -> None:
        """
        重新加载 UA 配置文件

        从文件重新加载 User-Agent 池，用于热更新配置。

        Example:
            >>> handler = UAHandler()
            >>> handler.reload()  # 重新加载配置
        """
        self._load_user_agents()


# 模块测试代码
if __name__ == "__main__":
    # 创建 UA 处理器实例
    handler = UAHandler()

    print("=" * 60)
    print("UA Handler 测试")
    print("=" * 60)

    # 测试获取所有类别
    print("\n可用类别:")
    for category in handler.get_categories():
        count = handler.get_category_count(category)
        print(f"  - {category}: {count} 个 UA")

    # 测试随机 UA
    print("\n随机 UA 测试:")
    print(f"  随机 UA: {handler.get_random_ua()[:80]}...")

    # 测试按类别获取
    print("\n按类别获取 UA:")
    for category in ['chrome', 'firefox', 'safari', 'mobile']:
        ua = handler.get_random_ua(category)
        print(f"  {category}: {ua[:80]}...")

    # 测试移动端和桌面端
    print("\n移动端 UA:")
    print(f"  {handler.get_mobile_ua()[:80]}...")

    print("\n桌面端 UA:")
    print(f"  {handler.get_desktop_ua()[:80]}...")

    # 测试总数
    print(f"\n总 UA 数量: {len(handler.get_all_uas())}")

    print("=" * 60)
