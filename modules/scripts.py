"""
脚本注入模块

提供前端 JS 脚本注入功能，支持在代理的网页中注入自定义脚本，
实现浮动面板、进度条、缩放等增强功能。

功能特性：
1. 脚本加载与管理
2. 条件注入（基于 URL 模式和内容类型）
3. 注入位置控制（head_start/head_end/body_start/body_end）
4. 脚本优先级管理
5. 脚本配置热重载
6. 注入统计信息查询
7. 动态添加和移除脚本

作者: SilkRoad-Next Team
版本: V2.0
"""

import asyncio
import json
import re
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from datetime import datetime
import time

from loguru import logger


class ScriptInjector:
    """
    脚本注入管理器

    管理前端 JS 脚本的加载、条件匹配和注入功能。

    Attributes:
        config_file (str): 脚本配置文件路径
        scripts_dir (Path): 脚本文件目录
        _scripts (Dict[str, dict]): 脚本配置字典
        _script_cache (Dict[str, str]): 脚本内容缓存
        stats (dict): 统计信息

    Example:
        >>> injector = ScriptInjector('databases/scripts.json')
        >>> html = '<html><head></head><body></body></html>'
        >>> injected = await injector.inject_scripts(html, 'https://example.com')
    """

    def __init__(self, config_file: str = 'databases/scripts.json'):
        """
        初始化脚本注入管理器

        Args:
            config_file: 脚本配置文件路径，默认为 'databases/scripts.json'
        """
        self.config_file = config_file
        self.scripts_dir = Path('Scripts')

        # 脚本配置：{script_name: config}
        self._scripts: Dict[str, dict] = {}

        # 脚本内容缓存：{script_name: content}
        self._script_cache: Dict[str, str] = {}

        # 锁机制，确保线程安全
        self._lock = asyncio.Lock()

        # 统计信息
        self.stats = {
            'total_injections': 0,
            'scripts_loaded': 0,
            'injection_errors': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }

        # 加载配置（在事件循环中异步执行）
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.load_config())
            else:
                loop.run_until_complete(self.load_config())
        except RuntimeError:
            # 如果没有事件循环，延迟加载
            pass

    async def load_config(self) -> None:
        """
        加载脚本配置

        从配置文件加载脚本配置，并预加载脚本内容到缓存。

        Raises:
            FileNotFoundError: 配置文件不存在时创建默认配置
            json.JSONDecodeError: 配置文件格式错误
        """
        async with self._lock:
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                self._scripts = config.get('scripts', {})

                # 预加载脚本内容
                await self._preload_scripts()

                self.stats['scripts_loaded'] = len(self._scripts)

                logger.info(f"Loaded {len(self._scripts)} script configurations from {self.config_file}")

            except FileNotFoundError:
                logger.warning(f"Script config file not found: {self.config_file}, creating default config")
                await self._create_default_config()

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in script config file: {e}")
                self.stats['injection_errors'] += 1
                raise

            except Exception as e:
                logger.error(f"Failed to load script config: {e}")
                self.stats['injection_errors'] += 1
                raise

    async def _create_default_config(self) -> None:
        """
        创建默认脚本配置

        当配置文件不存在时，创建包含示例脚本的默认配置。
        """
        default_config = {
            "scripts": {
                "dock": {
                    "file": "dock.js",
                    "enabled": True,
                    "position": "body_end",
                    "priority": 100,
                    "conditions": {
                        "url_patterns": [".*"],
                        "content_types": ["text/html"]
                    },
                    "description": "浮动面板脚本 - 在页面右下角显示控制面板"
                },
                "progress": {
                    "file": "progress.js",
                    "enabled": True,
                    "position": "head_end",
                    "priority": 90,
                    "conditions": {
                        "url_patterns": [".*"],
                        "content_types": ["text/html"]
                    },
                    "description": "进度条脚本 - 显示页面加载进度"
                },
                "zoom": {
                    "file": "zoom.js",
                    "enabled": False,
                    "position": "body_end",
                    "priority": 80,
                    "conditions": {
                        "url_patterns": [".*\\.jpg", ".*\\.png", ".*\\.gif"],
                        "content_types": ["text/html"]
                    },
                    "description": "图片缩放脚本 - 点击图片放大查看"
                },
                "target": {
                    "file": "target.js",
                    "enabled": True,
                    "position": "body_end",
                    "priority": 70,
                    "conditions": {
                        "url_patterns": [".*"],
                        "content_types": ["text/html"]
                    },
                    "description": "目标定位脚本 - 高亮显示当前访问的目标"
                }
            }
        }

        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, ensure_ascii=False, indent=2)

            self._scripts = default_config['scripts']
            await self._preload_scripts()

            logger.info(f"Created default script config at {self.config_file}")

        except Exception as e:
            logger.error(f"Failed to create default script config: {e}")
            raise

    async def _preload_scripts(self) -> None:
        """
        预加载所有脚本内容到缓存

        遍历所有配置的脚本，读取脚本文件内容并缓存。
        """
        loaded_count = 0

        for script_name, script_config in self._scripts.items():
            script_file = script_config.get('file')

            if not script_file:
                logger.warning(f"Script '{script_name}' has no file specified")
                continue

            script_path = self.scripts_dir / script_file

            try:
                with open(script_path, 'r', encoding='utf-8') as f:
                    self._script_cache[script_name] = f.read()
                    loaded_count += 1
                    logger.debug(f"Loaded script: {script_name} from {script_path}")

            except FileNotFoundError:
                logger.error(f"Script file not found: {script_path}")
                self.stats['injection_errors'] += 1

            except PermissionError:
                logger.error(f"Permission denied reading script: {script_path}")
                self.stats['injection_errors'] += 1

            except Exception as e:
                logger.error(f"Failed to load script {script_name}: {e}")
                self.stats['injection_errors'] += 1

        logger.info(f"Preloaded {loaded_count}/{len(self._scripts)} scripts")

    async def reload_config(self) -> None:
        """
        热重载脚本配置

        清空缓存并重新加载配置文件和脚本内容。
        """
        async with self._lock:
            # 清空缓存
            self._script_cache.clear()
            self._scripts.clear()

            logger.info("Reloading script configuration...")

        # 重新加载
        await self.load_config()

        logger.info("Script configuration reloaded successfully")

    async def get_scripts_for_url(self,
                                   url: str,
                                   content_type: str = 'text/html') -> List[dict]:
        """
        获取适用于指定 URL 的脚本列表

        根据配置的条件（URL 模式和内容类型）筛选适用的脚本，
        并按优先级排序。

        Args:
            url: 请求 URL
            content_type: 内容类型，默认为 'text/html'

        Returns:
            脚本配置列表，每个元素包含 name、config 和 content，
            按优先级从高到低排序

        Example:
            >>> scripts = await injector.get_scripts_for_url(
            ...     'https://example.com/page.html',
            ...     'text/html'
            ... )
            >>> print(len(scripts))
            3
        """
        async with self._lock:
            applicable_scripts = []

            for script_name, script_config in self._scripts.items():
                # 检查是否启用
                if not script_config.get('enabled', False):
                    continue

                # 检查条件
                conditions = script_config.get('conditions', {})

                # 检查 URL 模式
                url_patterns = conditions.get('url_patterns', [])
                url_match = False

                for pattern in url_patterns:
                    try:
                        if re.search(pattern, url):
                            url_match = True
                            break
                    except re.error as e:
                        logger.error(f"Invalid URL pattern '{pattern}': {e}")
                        continue

                if not url_match:
                    continue

                # 检查内容类型
                content_types = conditions.get('content_types', [])
                content_match = content_type in content_types

                if not content_match:
                    continue

                # 获取脚本内容
                content = self._script_cache.get(script_name, '')

                if not content:
                    logger.warning(f"Script '{script_name}' content is empty or not loaded")
                    continue

                # 添加到适用列表
                applicable_scripts.append({
                    'name': script_name,
                    'config': script_config,
                    'content': content
                })

            # 按优先级排序（高优先级在前）
            applicable_scripts.sort(
                key=lambda x: x['config'].get('priority', 0),
                reverse=True
            )

            return applicable_scripts

    async def inject_scripts(self,
                            html: str,
                            url: str,
                            content_type: str = 'text/html') -> str:
        """
        在 HTML 中注入脚本

        根据配置的条件和位置，将适用的脚本注入到 HTML 中。

        Args:
            html: HTML 内容
            url: 请求 URL
            content_type: 内容类型，默认为 'text/html'

        Returns:
            注入脚本后的 HTML 内容

        Example:
            >>> html = '<html><head></head><body></body></html>'
            >>> injected = await injector.inject_scripts(
            ...     html,
            ...     'https://example.com'
            ... )
            >>> '<script' in injected
            True
        """
        # 获取适用的脚本
        scripts = await self.get_scripts_for_url(url, content_type)

        if not scripts:
            return html

        # 分类脚本（按位置）
        head_start_scripts = []
        head_end_scripts = []
        body_start_scripts = []
        body_end_scripts = []

        for script in scripts:
            position = script['config'].get('position', 'body_end')

            if position == 'head_start':
                head_start_scripts.append(script)
            elif position == 'head_end':
                head_end_scripts.append(script)
            elif position == 'body_start':
                body_start_scripts.append(script)
            else:  # body_end
                body_end_scripts.append(script)

        # 注入到 head_start
        if head_start_scripts:
            html = await self._inject_to_position(html, head_start_scripts, 'head_start')

        # 注入到 head_end
        if head_end_scripts:
            html = await self._inject_to_position(html, head_end_scripts, 'head_end')

        # 注入到 body_start
        if body_start_scripts:
            html = await self._inject_to_position(html, body_start_scripts, 'body_start')

        # 注入到 body_end
        if body_end_scripts:
            html = await self._inject_to_position(html, body_end_scripts, 'body_end')

        # 更新统计
        self.stats['total_injections'] += len(scripts)

        logger.debug(f"Injected {len(scripts)} scripts into {url}")

        return html

    async def _inject_to_position(self, html: str, scripts: List[dict], position: str) -> str:
        """
        将脚本注入到指定位置

        Args:
            html: HTML 内容
            scripts: 脚本列表
            position: 注入位置 (head_start/head_end/body_start/body_end)

        Returns:
            注入后的 HTML
        """
        # 生成脚本标签
        script_tags = []

        for script in scripts:
            content = script['content']
            name = script['name']

            # 生成带标记的 script 标签
            tag = (
                f'<!-- SilkRoad Script: {name} -->\n'
                f'<script type="text/javascript">\n'
                f'{content}\n'
                f'</script>\n'
                f'<!-- End SilkRoad Script: {name} -->'
            )
            script_tags.append(tag)

        # 合并所有脚本标签
        scripts_html = '\n'.join(script_tags)

        # 根据位置注入
        if position == 'head_start':
            # 注入到 head 开始
            pattern = r'(<head[^>]*>)'
            replacement = r'\1\n' + scripts_html
            html = re.sub(pattern, replacement, html, flags=re.IGNORECASE)

        elif position == 'head_end':
            # 注入到 head 结束
            pattern = r'(</head>)'
            replacement = scripts_html + '\n\\1'
            html = re.sub(pattern, replacement, html, flags=re.IGNORECASE)

        elif position == 'body_start':
            # 注入到 body 开始
            pattern = r'(<body[^>]*>)'
            replacement = r'\1\n' + scripts_html
            html = re.sub(pattern, replacement, html, flags=re.IGNORECASE)

        else:  # body_end
            # 注入到 body 结束
            pattern = r'(</body>)'
            replacement = scripts_html + '\n\\1'
            html = re.sub(pattern, replacement, html, flags=re.IGNORECASE)

        return html

    async def add_script(self,
                        name: str,
                        file: str,
                        enabled: bool = True,
                        position: str = 'body_end',
                        priority: int = 50,
                        conditions: Optional[dict] = None,
                        description: str = '') -> bool:
        """
        添加新脚本

        动态添加新的脚本配置并保存到配置文件。

        Args:
            name: 脚本名称（唯一标识）
            file: 脚本文件名（相对于 Scripts/ 目录）
            enabled: 是否启用，默认为 True
            position: 注入位置，默认为 'body_end'
            priority: 优先级（1-100），默认为 50
            conditions: 注入条件，默认为匹配所有 text/html
            description: 脚本描述

        Returns:
            是否添加成功

        Example:
            >>> success = await injector.add_script(
            ...     name='custom-script',
            ...     file='custom.js',
            ...     priority=60,
            ...     description='自定义脚本'
            ... )
            >>> print(success)
            True
        """
        async with self._lock:
            # 检查脚本是否已存在
            if name in self._scripts:
                logger.warning(f"Script '{name}' already exists")
                return False

            # 设置默认条件
            if conditions is None:
                conditions = {
                    'url_patterns': ['.*'],
                    'content_types': ['text/html']
                }

            # 创建脚本配置
            self._scripts[name] = {
                'file': file,
                'enabled': enabled,
                'position': position,
                'priority': priority,
                'conditions': conditions,
                'description': description
            }

            # 尝试加载脚本内容
            script_path = self.scripts_dir / file

            try:
                with open(script_path, 'r', encoding='utf-8') as f:
                    self._script_cache[name] = f.read()

                # 保存配置
                await self._save_config()

                logger.info(f"Added script '{name}' successfully")
                return True

            except FileNotFoundError:
                logger.error(f"Script file not found: {script_path}")
                # 回滚
                del self._scripts[name]
                return False

            except Exception as e:
                logger.error(f"Failed to add script '{name}': {e}")
                # 回滚
                if name in self._scripts:
                    del self._scripts[name]
                return False

    async def remove_script(self, name: str) -> bool:
        """
        移除脚本

        从配置中移除指定脚本并保存配置文件。

        Args:
            name: 脚本名称

        Returns:
            是否移除成功

        Example:
            >>> success = await injector.remove_script('custom-script')
            >>> print(success)
            True
        """
        async with self._lock:
            if name not in self._scripts:
                logger.warning(f"Script '{name}' not found")
                return False

            # 删除脚本配置
            del self._scripts[name]

            # 清除缓存
            if name in self._script_cache:
                del self._script_cache[name]

            # 保存配置
            await self._save_config()

            logger.info(f"Removed script '{name}' successfully")
            return True

    async def enable_script(self, name: str) -> bool:
        """
        启用脚本

        Args:
            name: 脚本名称

        Returns:
            是否启用成功
        """
        async with self._lock:
            if name not in self._scripts:
                logger.warning(f"Script '{name}' not found")
                return False

            self._scripts[name]['enabled'] = True
            await self._save_config()

            logger.info(f"Enabled script '{name}'")
            return True

    async def disable_script(self, name: str) -> bool:
        """
        禁用脚本

        Args:
            name: 脚本名称

        Returns:
            是否禁用成功
        """
        async with self._lock:
            if name not in self._scripts:
                logger.warning(f"Script '{name}' not found")
                return False

            self._scripts[name]['enabled'] = False
            await self._save_config()

            logger.info(f"Disabled script '{name}'")
            return True

    async def update_script(self,
                           name: str,
                           **kwargs) -> bool:
        """
        更新脚本配置

        Args:
            name: 脚本名称
            **kwargs: 要更新的配置项

        Returns:
            是否更新成功

        Example:
            >>> success = await injector.update_script(
            ...     'dock',
            ...     priority=110,
            ...     enabled=True
            ... )
        """
        async with self._lock:
            if name not in self._scripts:
                logger.warning(f"Script '{name}' not found")
                return False

            # 更新配置
            for key, value in kwargs.items():
                if key in self._scripts[name]:
                    self._scripts[name][key] = value

            # 如果更新了文件，重新加载内容
            if 'file' in kwargs:
                script_file = kwargs['file']
                script_path = self.scripts_dir / script_file

                try:
                    with open(script_path, 'r', encoding='utf-8') as f:
                        self._script_cache[name] = f.read()

                except Exception as e:
                    logger.error(f"Failed to reload script '{name}': {e}")
                    return False

            # 保存配置
            await self._save_config()

            logger.info(f"Updated script '{name}'")
            return True

    async def _save_config(self) -> None:
        """
        保存脚本配置到文件

        将当前脚本配置保存到配置文件。
        """
        config = {
            "scripts": self._scripts
        }

        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

            logger.debug(f"Saved script config to {self.config_file}")

        except Exception as e:
            logger.error(f"Failed to save script config: {e}")
            raise

    def get_script_info(self, name: str) -> Optional[dict]:
        """
        获取脚本详细信息

        Args:
            name: 脚本名称

        Returns:
            脚本信息字典，如果不存在则返回 None
        """
        if name not in self._scripts:
            return None

        info = {
            'name': name,
            'config': self._scripts[name],
            'loaded': name in self._script_cache,
            'content_length': len(self._script_cache.get(name, ''))
        }

        return info

    def list_scripts(self, enabled_only: bool = False) -> List[dict]:
        """
        列出所有脚本

        Args:
            enabled_only: 是否只列出启用的脚本

        Returns:
            脚本信息列表
        """
        scripts = []

        for name, config in self._scripts.items():
            if enabled_only and not config.get('enabled', False):
                continue

            scripts.append({
                'name': name,
                'enabled': config.get('enabled', False),
                'position': config.get('position', 'body_end'),
                'priority': config.get('priority', 0),
                'description': config.get('description', ''),
                'loaded': name in self._script_cache
            })

        # 按优先级排序
        scripts.sort(key=lambda x: x['priority'], reverse=True)

        return scripts

    def get_stats(self) -> dict:
        """
        获取脚本注入统计信息

        Returns:
            统计信息字典，包含注入次数、加载脚本数、错误数等

        Example:
            >>> stats = injector.get_stats()
            >>> print(stats['total_injections'])
            150
        """
        return {
            **self.stats,
            'total_scripts': len(self._scripts),
            'enabled_scripts': sum(
                1 for s in self._scripts.values() if s.get('enabled', False)
            ),
            'cached_scripts': len(self._script_cache),
            'cache_hit_rate': (
                self.stats['cache_hits'] /
                (self.stats['cache_hits'] + self.stats['cache_misses']) * 100
                if (self.stats['cache_hits'] + self.stats['cache_misses']) > 0
                else 0
            )
        }

    async def clear_cache(self) -> None:
        """
        清空脚本缓存

        清空所有已缓存的脚本内容，下次使用时重新加载。
        """
        async with self._lock:
            self._script_cache.clear()
            logger.info("Script cache cleared")

    async def reload_script(self, name: str) -> bool:
        """
        重新加载指定脚本

        Args:
            name: 脚本名称

        Returns:
            是否重新加载成功
        """
        async with self._lock:
            if name not in self._scripts:
                logger.warning(f"Script '{name}' not found")
                return False

            script_file = self._scripts[name].get('file')
            if not script_file:
                logger.error(f"Script '{name}' has no file specified")
                return False

            script_path = self.scripts_dir / script_file

            try:
                with open(script_path, 'r', encoding='utf-8') as f:
                    self._script_cache[name] = f.read()

                logger.info(f"Reloaded script '{name}'")
                return True

            except Exception as e:
                logger.error(f"Failed to reload script '{name}': {e}")
                return False

    def validate_config(self) -> Tuple[bool, List[str]]:
        """
        验证脚本配置

        检查所有脚本配置的有效性。

        Returns:
            (是否全部有效, 错误消息列表)
        """
        errors = []

        for name, config in self._scripts.items():
            # 检查必需字段
            if 'file' not in config:
                errors.append(f"Script '{name}': missing 'file' field")

            # 检查文件是否存在
            script_file = config.get('file')
            if script_file:
                script_path = self.scripts_dir / script_file
                if not script_path.exists():
                    errors.append(f"Script '{name}': file '{script_file}' not found")

            # 检查 position 值
            position = config.get('position', 'body_end')
            valid_positions = ['head_start', 'head_end', 'body_start', 'body_end']
            if position not in valid_positions:
                errors.append(
                    f"Script '{name}': invalid position '{position}', "
                    f"must be one of {valid_positions}"
                )

            # 检查 priority 范围
            priority = config.get('priority', 50)
            if not isinstance(priority, (int, float)) or priority < 0 or priority > 100:
                errors.append(
                    f"Script '{name}': invalid priority '{priority}', "
                    f"must be a number between 0 and 100"
                )

            # 检查 conditions
            conditions = config.get('conditions', {})
            if 'url_patterns' in conditions:
                for pattern in conditions['url_patterns']:
                    try:
                        re.compile(pattern)
                    except re.error as e:
                        errors.append(
                            f"Script '{name}': invalid URL pattern '{pattern}': {e}"
                        )

        return len(errors) == 0, errors


# 便捷函数
async def create_injector(config_file: str = 'databases/scripts.json') -> ScriptInjector:
    """
    创建并初始化脚本注入器

    Args:
        config_file: 配置文件路径

    Returns:
        初始化完成的 ScriptInjector 实例
    """
    injector = ScriptInjector(config_file)
    await injector.load_config()
    return injector
