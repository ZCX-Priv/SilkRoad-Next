# 脚本注入重构计划

## 问题分析

### 当前问题
1. **注入时机错误**：当前脚本注入是在 URL 重写之后单独进行的（`normal.py` 第225-251行）
2. **标签查找失败**：脚本注入器使用正则表达式查找 `<head>`、`</head>`、`<body>`、`</body>` 等标签，但：
   - 某些网页可能没有标准的 HTML 结构
   - 某些网页可能使用 HTML5 简写格式
   - 在 URL 重写后 HTML 结构可能已变化
   - 正则表达式匹配不够健壮

### 当前流程
```
响应内容 → URL重写 → 脚本注入（独立解析HTML）→ 发送给客户端
```

### 改进后流程
```
响应内容 → URL重写 + 脚本注入（一次解析）→ 发送给客户端
```

## 改进方案

将脚本注入集成到 HTML 处理器中，在 URL 重写的同时进行脚本注入。

### 修改文件清单

#### 1. `modules/url/html.py` - HTMLHandler
**修改内容**：
- 添加 `script_injector` 属性
- 添加 `set_script_injector()` 方法
- 在 `rewrite()` 方法末尾调用脚本注入
- 在 `_inject_csp_meta()` 方法中同时注入脚本（利用已找到的 head 位置）

**具体改动**：
```python
# 新增属性
self.script_injector = None
self.current_url = None  # 用于脚本注入条件匹配

# 新增方法
def set_script_injector(self, script_injector):
    self.script_injector = script_injector

# 修改 rewrite() 方法
async def rewrite(self, html: str, base_url: str, config: Dict[str, Any]) -> str:
    # ... 现有的 URL 重写逻辑 ...
    
    # 在最后进行脚本注入
    if self.script_injector:
        html = await self.script_injector.inject_scripts(html, base_url, 'text/html')
    
    return html
```

#### 2. `modules/url/handle.py` - URLHandler
**修改内容**：
- 添加 `script_injector` 属性
- 添加 `set_script_injector()` 方法
- 在 `rewrite()` 方法中将 script_injector 传递给 HTMLHandler

**具体改动**：
```python
# 新增属性
self.script_injector = None

# 新增方法
def set_script_injector(self, script_injector):
    self.script_injector = script_injector
    # 传递给 HTMLHandler
    if 'text/html' in self.handlers:
        self.handlers['text/html'].set_script_injector(script_injector)
```

#### 3. `modules/flow/normal.py` - NormalHandler
**修改内容**：
- 移除独立的脚本注入逻辑（第225-251行）
- 将 `script_injector` 传递给 `url_handler`

**具体改动**：
```python
# 在初始化或设置方法中，将 script_injector 传递给 url_handler
if self.url_handler and self.script_injector:
    self.url_handler.set_script_injector(self.script_injector)

# 移除 _forward_with_pool 中的独立脚本注入代码块
```

#### 4. `modules/scripts.py` - ScriptInjector（可选优化）
**修改内容**：
- 优化注入方法，利用 HTMLHandler 已知的标签位置
- 添加更健壮的标签查找逻辑

**具体改动**：
```python
# 改进标签查找正则表达式，支持更多格式
# 例如：支持 <head >（带空格）、<head attr="value"> 等
```

## 实施步骤

### 步骤 1：修改 HTMLHandler
1. 添加 `script_injector` 和 `current_url` 属性
2. 添加 `set_script_injector()` 方法
3. 修改 `rewrite()` 方法，在末尾添加脚本注入调用

### 步骤 2：修改 URLHandler
1. 添加 `script_injector` 属性
2. 添加 `set_script_injector()` 方法
3. 在设置时传递给 HTMLHandler

### 步骤 3：修改 NormalHandler
1. 在 `_forward_with_pool` 方法中，在 URL 重写前设置 script_injector
2. 移除独立的脚本注入代码块
3. 同样修改 `_send_response` 方法（如果有类似逻辑）

### 步骤 4：测试验证
1. 测试正常 HTML 页面的脚本注入
2. 测试非标准 HTML 结构的页面
3. 测试无 head/body 标签的页面
4. 验证脚本注入统计信息正确

## 优势

1. **性能提升**：只需解析一次 HTML
2. **可靠性提升**：在完整的 HTML 结构上进行注入
3. **代码简化**：移除重复的 HTML 解析逻辑
4. **维护性提升**：脚本注入与 URL 重写统一管理

## 风险评估

- **低风险**：修改范围明确，不改变核心逻辑
- **向后兼容**：如果 script_injector 为 None，行为与之前一致
- **测试覆盖**：需要测试各种 HTML 格式
