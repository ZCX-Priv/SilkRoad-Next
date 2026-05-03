# 弃用 wafpasser 模块计划

## 概述

wafpasser 模块是 V5 版本新增的 WAF（Web Application Firewall）穿透模块，包含以下功能：
- WAF 类型识别与指纹检测
- 请求特征混淆
- 反爬虫机制绕过
- 智能请求调度
- 自适应策略调整

本计划将安全、完整地弃用该模块。

## 影响范围分析

### 1. 代码文件引用

| 文件 | 引用内容 | 操作 |
|------|----------|------|
| `modules/proxy.py` | 导入 `WAFPasser, WAFDetector, RequestObfuscator`，初始化三个组件属性 | 移除导入和属性初始化 |
| `SilkRoad.py` | 导入 `WAFPasser, WAFDetector`，条件初始化 WAF 模块 | 移除导入和初始化代码 |
| `modules/stream/handle.py` | 导入 `WAFDetector, WAFPasser`，初始化 `waf_detector` | 移除导入和属性初始化 |
| `modules/connectionpool.py` | 导入 `SessionPersistenceManager` | 移除导入 |

### 2. 配置文件引用

`databases/config.json` 中需要移除的配置项：
- `logging.waf_detection`
- `logging.evasion_attempts`
- `logging.success_rate_tracking`
- `waf_evasion` 整个配置块
- `session_persistence` 整个配置块

### 3. 相关文件

- `modules/wafpasser.py` - 主模块文件（删除）
- `databases/sessions/` - 会话存储目录（删除）
- `pages/error/waf_blocked.html` - WAF 拦截错误页面（删除）

## 实施步骤

### 步骤 1: 移除 modules/proxy.py 中的引用

1. 移除导入语句：
   ```python
   from modules.wafpasser import WAFPasser, WAFDetector, RequestObfuscator
   ```

2. 移除属性初始化（约第 110-112 行）：
   ```python
   self.waf_passer = WAFPasser()
   self.waf_detector = WAFDetector(self.waf_passer)
   self.request_obfuscator = RequestObfuscator(self.waf_passer)
   ```

### 步骤 2: 移除 SilkRoad.py 中的引用

1. 移除导入语句：
   ```python
   from modules.wafpasser import WAFPasser, WAFDetector
   ```

2. 移除初始化代码块（约第 283-289 行）：
   ```python
   # 11. 初始化 WAF 穿透模块
   print("[11/13] 初始化 WAF 穿透模块...")
   if self.config.get('waf_evasion.enabled', False):
       self.waf_passer = WAFPasser()
       self.waf_detector = WAFDetector(self.waf_passer)
       
       waf_types_count = len(self.waf_passer.waf_signatures)
       ...
   ```

### 步骤 3: 移除 modules/stream/handle.py 中的引用

1. 移除导入语句：
   ```python
   from modules.wafpasser import WAFDetector, WAFPasser
   ```

2. 移除属性初始化（约第 73 行）：
   ```python
   self.waf_detector = WAFDetector(WAFPasser())
   ```

### 步骤 4: 移除 modules/connectionpool.py 中的引用

1. 移除导入语句：
   ```python
   from modules.wafpasser import SessionPersistenceManager
   ```

### 步骤 5: 清理配置文件

编辑 `databases/config.json`：

1. 从 `logging` 配置块中移除：
   - `"waf_detection": true`
   - `"evasion_attempts": true`
   - `"success_rate_tracking": true`

2. 移除整个 `waf_evasion` 配置块（第 172-224 行）

3. 移除整个 `session_persistence` 配置块（第 225-230 行）

### 步骤 6: 删除模块文件

删除以下文件和目录：
- `modules/wafpasser.py`
- `databases/sessions/` 目录（如果存在）
- `pages/error/waf_blocked.html`（如果存在）

### 步骤 7: 更新文档（可选）

如果存在相关文档（如 V5.md、prd.md），需要更新以反映模块已弃用。

## 验证清单

- [ ] 所有 wafpasser 导入已移除
- [ ] 所有相关属性初始化已移除
- [ ] 配置文件已清理
- [ ] 模块文件已删除
- [ ] 项目可正常启动
- [ ] 代理功能正常工作
- [ ] 无残留引用错误

## 风险评估

- **低风险**: 该模块是独立的功能模块，弃用不会影响核心代理功能
- **注意事项**: 确保所有引用都已移除，避免运行时导入错误

## 回滚方案

如需回滚，可通过版本控制系统恢复以下内容：
- `modules/wafpasser.py`
- 各文件中的导入和初始化代码
- 配置文件中的相关配置项
