"""
脚本注入模块 - ScriptInjector

功能：
1. 脚本加载与管理
2. 条件注入（基于 URL、域名等）
3. 脚本位置控制（head_start, head_end, body_start, body_end）
4. 脚本优先级管理
5. 热重载配置
6. 注入统计信息

作者: SilkRoad-Next Team
版本: 2.0.0
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from modules.logging import Logger


class ScriptInjector:
    """
    脚本注入管理器
    
    管理前端 JS 脚本注入功能，支持在代理的网页中注入自定义脚本，
    实现浮动面板、进度条、缩放等增强功能。
    
    功能：
    1. 脚本加载与管理
    2. 条件注入（基于 URL、域名等）
    3. 脚本位置控制（head、body）
    4. 脚本优先级管理
    5. 热重载配置
    
    使用示例:
        # 创建脚本注入器
        injector = ScriptInjector(
            config_file='databases/scripts.json',
            scripts_dir='Scripts'
        )
        
        # 加载配置
        await injector.load_config()
        
        # 注入脚本到 HTML
        html = '<html><head></head><body></body></html>'
        injected_html = await injector.inject_scripts(
            html, 
            'https://example.com/page',
            'text/html'
        )
        
        # 添加新脚本
        await injector.add_script(
            name='custom',
            file='custom.js',
            enabled=True,
            position='body_end',
            priority=50,
            conditions={
                'url_patterns': ['.*'],
                'content_types': ['text/html']
            },
            description='自定义脚本'
        )
        
        # 热重载配置
        await injector.reload_config()
        
        # 获取统计信息
        stats = injector.get_stats()
    """
    
    # 支持的注入位置
    VALID_POSITIONS = {'head_start', 'head_end', 'body_start', 'body_end'}
    
    def __init__(
        self,
        config_file: str = 'databases/scripts.json',
        scripts_dir: str = 'Scripts',
        logger: Optional['Logger'] = None
    ):
        """
        初始化脚本注入管理器
        
        Args:
            config_file: 脚本配置文件路径
            scripts_dir: 脚本文件目录
            logger: 日志记录器，如果为 None 则使用默认日志
        """
        self.config_file = config_file
        self.scripts_dir = Path(scripts_dir)
        
        # 脚本配置：{script_name: config}
        self._scripts: Dict[str, dict] = {}
        
        # 脚本内容缓存：{script_name: content}
        self._script_cache: Dict[str, str] = {}
        
        # 编译后的 URL 模式缓存：{script_name: [compiled_patterns]}
        self._pattern_cache: Dict[str, List[re.Pattern]] = {}
        
        # 锁机制，确保线程安全
        self._lock = asyncio.Lock()
        
        # 日志记录器
        self._logger = logger or logging.getLogger(__name__)
        
        # 配置加载状态
        self._config_loaded = False
        
        # 统计信息
        self._stats = {
            'total_injections': 0,
            'scripts_loaded': 0,
            'injection_errors': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'config_reloads': 0,
            'scripts_added': 0,
            'scripts_removed': 0,
        }
        
        self._logger.info(
            f"ScriptInjector 初始化完成: "
            f"config_file={config_file}, "
            f"scripts_dir={scripts_dir}"
        )
    
    async def load_config(self) -> bool:
        """
        加载脚本配置
        
        Returns:
            加载是否成功
        """
        async with self._lock:
            return await self._load_config_internal()
    
    async def _load_config_internal(self) -> bool:
        """
        内部加载脚本配置方法（不加锁，由调用者确保锁已获取）
        
        Returns:
            加载是否成功
        """
        try:
            # 检查配置文件是否存在
            config_path = Path(self.config_file)
            
            if not config_path.exists():
                self._logger.warning(
                    f"脚本配置文件不存在: {self.config_file}, 创建默认配置"
                )
                await self._create_default_config()
                return True
            
            # 读取配置文件
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 加载脚本配置
            self._scripts = config.get('scripts', {})
            
            # 预加载脚本内容
            await self._preload_scripts()
            
            # 编译 URL 模式
            self._compile_patterns()
            
            # 更新状态
            self._config_loaded = True
            self._stats['scripts_loaded'] = len(self._scripts)
            
            self._logger.info(
                f"脚本配置加载成功: 加载了 {len(self._scripts)} 个脚本配置"
            )
            
            return True
            
        except json.JSONDecodeError as e:
            self._logger.error(f"脚本配置文件格式错误: {e}")
            return False
        except Exception as e:
            self._logger.error(f"加载脚本配置失败: {e}")
            return False
    
    async def _create_default_config(self) -> None:
        """
        创建默认脚本配置
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
        
        # 确保目录存在
        config_path = Path(self.config_file)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 写入配置文件
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, ensure_ascii=False, indent=2)
        
        # 更新内部配置
        self._scripts = default_config['scripts']
        
        # 预加载脚本内容
        await self._preload_scripts()
        
        # 编译 URL 模式
        self._compile_patterns()
        
        self._logger.info(f"默认脚本配置已创建: {self.config_file}")
    
    async def _preload_scripts(self) -> None:
        """
        预加载所有脚本内容到缓存
        
        此方法假设调用者已持有锁。
        """
        loaded_count = 0
        error_count = 0
        
        for script_name, script_config in self._scripts.items():
            script_file = script_config.get('file')
            
            if not script_file:
                continue
            
            script_path = self.scripts_dir / script_file
            
            try:
                if script_path.exists():
                    with open(script_path, 'r', encoding='utf-8') as f:
                        self._script_cache[script_name] = f.read()
                    loaded_count += 1
                    self._stats['cache_hits'] += 1
                else:
                    self._logger.warning(
                        f"脚本文件不存在: {script_path}"
                    )
                    self._stats['cache_misses'] += 1
                    error_count += 1
                    
            except Exception as e:
                self._logger.error(
                    f"加载脚本文件失败: {script_path}, 错误: {e}"
                )
                self._stats['cache_misses'] += 1
                error_count += 1
        
        self._logger.info(
            f"脚本预加载完成: 成功={loaded_count}, 失败={error_count}"
        )
    
    def _compile_patterns(self) -> None:
        """
        编译所有 URL 模式为正则表达式
        
        此方法假设调用者已持有锁。
        """
        for script_name, script_config in self._scripts.items():
            conditions = script_config.get('conditions', {})
            url_patterns = conditions.get('url_patterns', [])
            
            compiled_patterns = []
            for pattern in url_patterns:
                try:
                    compiled_patterns.append(re.compile(pattern))
                except re.error as e:
                    self._logger.warning(
                        f"无效的 URL 模式: {pattern}, 错误: {e}"
                    )
            
            self._pattern_cache[script_name] = compiled_patterns
    
    async def reload_config(self) -> bool:
        """
        热重载脚本配置
        
        清空缓存并重新加载配置文件。
        
        Returns:
            重载是否成功
        """
        async with self._lock:
            self._logger.info("开始热重载脚本配置...")
            
            # 清空缓存
            self._script_cache.clear()
            self._pattern_cache.clear()
            
            # 重新加载（使用内部方法，避免死锁）
            result = await self._load_config_internal()
            
            if result:
                self._stats['config_reloads'] += 1
                self._logger.info("脚本配置热重载成功")
            else:
                self._logger.error("脚本配置热重载失败")
            
            return result
    
    async def get_scripts_for_url(
        self,
        url: str,
        content_type: str = 'text/html'
    ) -> List[dict]:
        """
        获取适用于指定 URL 的脚本列表
        
        Args:
            url: 请求 URL
            content_type: 内容类型
            
        Returns:
            脚本配置列表，按优先级排序（高优先级在前）
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
                if url_patterns:
                    # 使用编译后的模式
                    compiled_patterns = self._pattern_cache.get(script_name, [])
                    url_match = any(
                        pattern.search(url)
                        for pattern in compiled_patterns
                    )
                    
                    if not url_match:
                        continue
                
                # 检查内容类型
                content_types = conditions.get('content_types', [])
                if content_types:
                    # 支持通配符匹配，如 text/*
                    content_match = False
                    for allowed_type in content_types:
                        if allowed_type.endswith('*'):
                            # 通配符匹配
                            prefix = allowed_type[:-1]
                            if content_type.startswith(prefix):
                                content_match = True
                                break
                        elif content_type == allowed_type:
                            content_match = True
                            break
                    
                    if not content_match:
                        continue
                
                # 获取脚本内容
                content = self._script_cache.get(script_name, '')
                
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
    
    async def inject_scripts(
        self,
        html: str,
        url: str,
        content_type: str = 'text/html'
    ) -> str:
        """
        在 HTML 中注入脚本
        
        Args:
            html: HTML 内容
            url: 请求 URL
            content_type: 内容类型
            
        Returns:
            注入脚本后的 HTML
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
        
        result_html = html
        
        # 注入到 head_start
        if head_start_scripts:
            result_html = await self._inject_to_head_start(
                result_html, head_start_scripts
            )
        
        # 注入到 head_end
        if head_end_scripts:
            result_html = await self._inject_to_head_end(
                result_html, head_end_scripts
            )
        
        # 注入到 body_start
        if body_start_scripts:
            result_html = await self._inject_to_body_start(
                result_html, body_start_scripts
            )
        
        # 注入到 body_end
        if body_end_scripts:
            result_html = await self._inject_to_body_end(
                result_html, body_end_scripts
            )
        
        # 更新统计
        self._stats['total_injections'] += len(scripts)
        
        return result_html
    
    async def _inject_to_head_start(
        self,
        html: str,
        scripts: List[dict]
    ) -> str:
        """
        注入脚本到 head 标签开始位置
        
        Args:
            html: HTML 内容
            scripts: 脚本列表
            
        Returns:
            注入后的 HTML
        """
        # 生成脚本标签
        script_tags = self._generate_script_tags(scripts)
        
        if not script_tags:
            return html
        
        # 查找 <head> 标签
        pattern = r'(<head[^>]*>)'
        match = re.search(pattern, html, re.IGNORECASE)
        
        if match:
            # 在 <head> 标签后注入
            injection = '\n'.join(script_tags)
            replacement = match.group(1) + '\n' + injection
            html = re.sub(pattern, replacement, html, count=1, flags=re.IGNORECASE)
        else:
            # 没有 head 标签，记录警告
            self._logger.warning("HTML 中未找到 <head> 标签，无法注入 head_start 脚本")
        
        return html
    
    async def _inject_to_head_end(
        self,
        html: str,
        scripts: List[dict]
    ) -> str:
        """
        注入脚本到 head 标签结束位置
        
        Args:
            html: HTML 内容
            scripts: 脚本列表
            
        Returns:
            注入后的 HTML
        """
        # 生成脚本标签
        script_tags = self._generate_script_tags(scripts)
        
        if not script_tags:
            return html
        
        # 查找 </head> 标签
        pattern = r'(</head>)'
        match = re.search(pattern, html, re.IGNORECASE)
        
        if match:
            # 在 </head> 标签前注入
            injection = '\n'.join(script_tags)
            replacement = injection + '\n' + match.group(1)
            html = re.sub(pattern, replacement, html, count=1, flags=re.IGNORECASE)
        else:
            # 没有 head 结束标签，记录警告
            self._logger.warning("HTML 中未找到 </head> 标签，无法注入 head_end 脚本")
        
        return html
    
    async def _inject_to_body_start(
        self,
        html: str,
        scripts: List[dict]
    ) -> str:
        """
        注入脚本到 body 标签开始位置
        
        Args:
            html: HTML 内容
            scripts: 脚本列表
            
        Returns:
            注入后的 HTML
        """
        # 生成脚本标签
        script_tags = self._generate_script_tags(scripts)
        
        if not script_tags:
            return html
        
        # 查找 <body> 标签
        pattern = r'(<body[^>]*>)'
        match = re.search(pattern, html, re.IGNORECASE)
        
        if match:
            # 在 <body> 标签后注入
            injection = '\n'.join(script_tags)
            replacement = match.group(1) + '\n' + injection
            html = re.sub(pattern, replacement, html, count=1, flags=re.IGNORECASE)
        else:
            # 没有 body 标签，记录警告
            self._logger.warning("HTML 中未找到 <body> 标签，无法注入 body_start 脚本")
        
        return html
    
    async def _inject_to_body_end(
        self,
        html: str,
        scripts: List[dict]
    ) -> str:
        """
        注入脚本到 body 标签结束位置
        
        Args:
            html: HTML 内容
            scripts: 脚本列表
            
        Returns:
            注入后的 HTML
        """
        # 生成脚本标签
        script_tags = self._generate_script_tags(scripts)
        
        if not script_tags:
            return html
        
        # 查找 </body> 标签
        pattern = r'(</body>)'
        match = re.search(pattern, html, re.IGNORECASE)
        
        if match:
            # 在 </body> 标签前注入
            injection = '\n'.join(script_tags)
            replacement = injection + '\n' + match.group(1)
            html = re.sub(pattern, replacement, html, count=1, flags=re.IGNORECASE)
        else:
            # 没有 body 结束标签，尝试在 </html> 前注入
            pattern = r'(</html>)'
            match = re.search(pattern, html, re.IGNORECASE)
            
            if match:
                injection = '\n'.join(script_tags)
                replacement = injection + '\n' + match.group(1)
                html = re.sub(pattern, replacement, html, count=1, flags=re.IGNORECASE)
            else:
                # 没有 body 和 html 结束标签，追加到末尾
                self._logger.warning(
                    "HTML 中未找到 </body> 或 </html> 标签，追加脚本到末尾"
                )
                html += '\n' + '\n'.join(script_tags)
        
        return html
    
    def _generate_script_tags(self, scripts: List[dict]) -> List[str]:
        """
        生成 script 标签列表
        
        Args:
            scripts: 脚本列表
            
        Returns:
            script 标签字符串列表
        """
        tags = []
        
        for script in scripts:
            content = script.get('content', '')
            name = script.get('name', 'unknown')
            
            if not content:
                self._logger.debug(f"脚本内容为空，跳过: {name}")
                continue
            
            # 生成带注释的 script 标签
            tag = (
                f'<!-- SilkRoad Script: {name} -->\n'
                f'<script type="text/javascript">\n'
                f'{content}\n'
                f'</script>'
            )
            tags.append(tag)
        
        return tags
    
    async def add_script(
        self,
        name: str,
        file: str,
        enabled: bool = True,
        position: str = 'body_end',
        priority: int = 50,
        conditions: Optional[dict] = None,
        description: str = ''
    ) -> bool:
        """
        添加新脚本
        
        Args:
            name: 脚本名称（唯一标识）
            file: 脚本文件名
            enabled: 是否启用
            position: 注入位置（head_start, head_end, body_start, body_end）
            priority: 优先级（数值越大优先级越高）
            conditions: 注入条件
            description: 脚本描述
            
        Returns:
            添加是否成功
            
        Raises:
            ValueError: 如果位置参数无效
        """
        # 验证位置参数
        if position not in self.VALID_POSITIONS:
            raise ValueError(
                f"无效的注入位置: {position}, "
                f"有效位置: {self.VALID_POSITIONS}"
            )
        
        async with self._lock:
            try:
                # 创建脚本配置
                script_config = {
                    'file': file,
                    'enabled': enabled,
                    'position': position,
                    'priority': priority,
                    'conditions': conditions or {
                        'url_patterns': ['.*'],
                        'content_types': ['text/html']
                    },
                    'description': description
                }
                
                # 添加到配置
                self._scripts[name] = script_config
                
                # 加载脚本内容
                script_path = self.scripts_dir / file
                
                if script_path.exists():
                    with open(script_path, 'r', encoding='utf-8') as f:
                        self._script_cache[name] = f.read()
                    self._stats['cache_hits'] += 1
                else:
                    self._logger.warning(f"脚本文件不存在: {script_path}")
                    self._stats['cache_misses'] += 1
                
                # 编译 URL 模式
                url_patterns = script_config['conditions'].get('url_patterns', [])
                compiled_patterns = []
                for pattern in url_patterns:
                    try:
                        compiled_patterns.append(re.compile(pattern))
                    except re.error as e:
                        self._logger.warning(
                            f"无效的 URL 模式: {pattern}, 错误: {e}"
                        )
                self._pattern_cache[name] = compiled_patterns
                
                # 保存配置
                await self._save_config()
                
                # 更新统计
                self._stats['scripts_loaded'] = len(self._scripts)
                self._stats['scripts_added'] += 1
                
                self._logger.info(f"脚本添加成功: {name}")
                
                return True
                
            except Exception as e:
                self._logger.error(f"添加脚本失败: {name}, 错误: {e}")
                return False
    
    async def remove_script(self, name: str) -> bool:
        """
        移除脚本
        
        Args:
            name: 脚本名称
            
        Returns:
            移除是否成功
        """
        async with self._lock:
            if name not in self._scripts:
                self._logger.warning(f"脚本不存在，无法移除: {name}")
                return False
            
            try:
                # 从配置中移除
                del self._scripts[name]
                
                # 清除缓存
                if name in self._script_cache:
                    del self._script_cache[name]
                
                if name in self._pattern_cache:
                    del self._pattern_cache[name]
                
                # 保存配置
                await self._save_config()
                
                # 更新统计
                self._stats['scripts_loaded'] = len(self._scripts)
                self._stats['scripts_removed'] += 1
                
                self._logger.info(f"脚本移除成功: {name}")
                
                return True
                
            except Exception as e:
                self._logger.error(f"移除脚本失败: {name}, 错误: {e}")
                return False
    
    async def update_script(
        self,
        name: str,
        **kwargs
    ) -> bool:
        """
        更新脚本配置
        
        Args:
            name: 脚本名称
            **kwargs: 要更新的配置项
            
        Returns:
            更新是否成功
        """
        async with self._lock:
            if name not in self._scripts:
                self._logger.warning(f"脚本不存在，无法更新: {name}")
                return False
            
            try:
                script_config = self._scripts[name]
                
                # 验证位置参数
                if 'position' in kwargs:
                    if kwargs['position'] not in self.VALID_POSITIONS:
                        raise ValueError(
                            f"无效的注入位置: {kwargs['position']}, "
                            f"有效位置: {self.VALID_POSITIONS}"
                        )
                
                # 更新配置
                for key, value in kwargs.items():
                    if key in ['file', 'enabled', 'position', 'priority', 
                               'conditions', 'description']:
                        script_config[key] = value
                
                # 如果更新了文件，重新加载内容
                if 'file' in kwargs:
                    script_path = self.scripts_dir / kwargs['file']
                    if script_path.exists():
                        with open(script_path, 'r', encoding='utf-8') as f:
                            self._script_cache[name] = f.read()
                
                # 如果更新了条件，重新编译模式
                if 'conditions' in kwargs:
                    url_patterns = kwargs['conditions'].get('url_patterns', [])
                    compiled_patterns = []
                    for pattern in url_patterns:
                        try:
                            compiled_patterns.append(re.compile(pattern))
                        except re.error as e:
                            self._logger.warning(
                                f"无效的 URL 模式: {pattern}, 错误: {e}"
                            )
                    self._pattern_cache[name] = compiled_patterns
                
                # 保存配置
                await self._save_config()
                
                self._logger.info(f"脚本更新成功: {name}")
                
                return True
                
            except Exception as e:
                self._logger.error(f"更新脚本失败: {name}, 错误: {e}")
                return False
    
    async def enable_script(self, name: str) -> bool:
        """
        启用脚本
        
        Args:
            name: 脚本名称
            
        Returns:
            启用是否成功
        """
        return await self.update_script(name, enabled=True)
    
    async def disable_script(self, name: str) -> bool:
        """
        禁用脚本
        
        Args:
            name: 脚本名称
            
        Returns:
            禁用是否成功
        """
        return await self.update_script(name, enabled=False)
    
    async def _save_config(self) -> None:
        """
        保存脚本配置到文件
        
        此方法假设调用者已持有锁。
        """
        config = {
            "scripts": self._scripts
        }
        
        config_path = Path(self.config_file)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    
    def get_stats(self) -> dict:
        """
        获取脚本注入统计信息
        
        Returns:
            统计信息字典，包含以下字段：
            - total_injections: 总注入次数
            - scripts_loaded: 已加载脚本数
            - injection_errors: 注入错误次数
            - cache_hits: 缓存命中次数
            - cache_misses: 缓存未命中次数
            - config_reloads: 配置重载次数
            - scripts_added: 添加脚本次数
            - scripts_removed: 移除脚本次数
            - total_scripts: 总脚本数
            - enabled_scripts: 启用脚本数
            - cached_scripts: 缓存脚本数
        """
        return {
            **self._stats,
            'total_scripts': len(self._scripts),
            'enabled_scripts': sum(
                1 for s in self._scripts.values() if s.get('enabled', False)
            ),
            'disabled_scripts': sum(
                1 for s in self._scripts.values() if not s.get('enabled', False)
            ),
            'cached_scripts': len(self._script_cache),
            'config_loaded': self._config_loaded,
        }
    
    def get_script_names(self) -> List[str]:
        """
        获取所有脚本名称列表
        
        Returns:
            脚本名称列表
        """
        return list(self._scripts.keys())
    
    def get_script_config(self, name: str) -> Optional[dict]:
        """
        获取指定脚本的配置
        
        Args:
            name: 脚本名称
            
        Returns:
            脚本配置，如果不存在则返回 None
        """
        return self._scripts.get(name)
    
    def get_script_content(self, name: str) -> Optional[str]:
        """
        获取指定脚本的内容
        
        Args:
            name: 脚本名称
            
        Returns:
            脚本内容，如果不存在则返回 None
        """
        return self._script_cache.get(name)
    
    async def script_exists(self, name: str) -> bool:
        """
        检查脚本是否存在
        
        Args:
            name: 脚本名称
            
        Returns:
            脚本是否存在
        """
        async with self._lock:
            return name in self._scripts
    
    async def clear_cache(self) -> None:
        """
        清空脚本缓存
        """
        async with self._lock:
            self._script_cache.clear()
            self._pattern_cache.clear()
            self._logger.info("脚本缓存已清空")
    
    async def reload_script(self, name: str) -> bool:
        """
        重新加载指定脚本的内容
        
        Args:
            name: 脚本名称
            
        Returns:
            重载是否成功
        """
        async with self._lock:
            if name not in self._scripts:
                self._logger.warning(f"脚本不存在，无法重载: {name}")
                return False
            
            script_config = self._scripts[name]
            script_file = script_config.get('file')
            
            if not script_file:
                self._logger.warning(f"脚本未配置文件: {name}")
                return False
            
            script_path = self.scripts_dir / script_file
            
            try:
                if script_path.exists():
                    with open(script_path, 'r', encoding='utf-8') as f:
                        self._script_cache[name] = f.read()
                    self._logger.info(f"脚本重载成功: {name}")
                    return True
                else:
                    self._logger.warning(f"脚本文件不存在: {script_path}")
                    return False
                    
            except Exception as e:
                self._logger.error(f"重载脚本失败: {name}, 错误: {e}")
                return False
    
    def __repr__(self) -> str:
        """返回脚本注入器的字符串表示"""
        return (
            f"ScriptInjector("
            f"scripts={len(self._scripts)}, "
            f"enabled={sum(1 for s in self._scripts.values() if s.get('enabled', False))}, "
            f"cached={len(self._script_cache)})"
        )


# 便捷函数
def create_script_injector(
    config_file: str = 'databases/scripts.json',
    scripts_dir: str = 'Scripts',
    logger: Optional['Logger'] = None
) -> ScriptInjector:
    """
    创建脚本注入器的便捷函数
    
    Args:
        config_file: 脚本配置文件路径
        scripts_dir: 脚本文件目录
        logger: 日志记录器
        
    Returns:
        ScriptInjector 实例
        
    Example:
        injector = create_script_injector(
            config_file='databases/scripts.json',
            scripts_dir='Scripts'
        )
        
        # 加载配置
        await injector.load_config()
        
        # 注入脚本
        html = await injector.inject_scripts(html, url, content_type)
    """
    return ScriptInjector(
        config_file=config_file,
        scripts_dir=scripts_dir,
        logger=logger
    )
