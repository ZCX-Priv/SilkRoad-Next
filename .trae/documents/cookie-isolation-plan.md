# Cookie 隔离方案实现计划

## 问题背景

当前代理服务器存在Cookie累积问题：
- 用户访问多个网站后，所有Cookie都存储在代理服务器域名下
- 后续请求会携带所有网站的Cookie，导致请求头过大
- 服务器返回 `400 Bad Request Request Header Or Cookie Too Large`

## 解决方案

实现**按目标域名隔离Cookie**的机制，核心思路：
1. **响应时**：重写 Set-Cookie 的 Path，添加目标域名前缀
2. **请求时**：过滤 Cookie，只保留当前目标网站的 Cookie

## 实现步骤

### 步骤1：创建 Cookie 处理模块

**文件**: `modules/url/cookie.py`

创建独立的Cookie处理器类 `CookieHandler`，包含以下方法：

```python
class CookieHandler:
    def rewrite_set_cookie(self, set_cookie: str, target_domain: str) -> str:
        """
        重写Set-Cookie响应头
        - 修改Path属性，添加目标域名前缀
        - 移除Domain属性（避免跨域问题）
        """
        
    def filter_request_cookies(self, cookie_header: str, target_domain: str) -> str:
        """
        过滤请求Cookie头
        - 只保留Path以目标域名开头的Cookie
        - 移除Path中的域名前缀后转发
        """
```

### 步骤2：修改代理服务器响应处理

**文件**: `modules/proxy.py`

修改 `_send_response` 方法（约第662行）：

1. 在发送响应头之前，拦截所有 `Set-Cookie` 头
2. 调用 `CookieHandler.rewrite_set_cookie` 重写每个 Set-Cookie
3. 将重写后的 Set-Cookie 头发送给客户端

关键修改位置：
- 第711行 `headers = dict(response.headers)` 之后
- 第732-736行发送响应头的循环中

### 步骤3：修改代理服务器请求头构建

**文件**: `modules/proxy.py`

修改 `_build_forward_headers` 方法（约第507行）：

1. 在第529-532行复制原始请求头的循环中
2. 特殊处理 `Cookie` 头
3. 调用 `CookieHandler.filter_request_cookies` 过滤Cookie

### 步骤4：集成 CookieHandler 到 ProxyServer

**文件**: `modules/proxy.py`

1. 在 `__init__` 方法中初始化 `CookieHandler` 实例
2. 导入新模块

## 技术细节

### Set-Cookie 重写规则

```
原始响应:
  Set-Cookie: session=abc123; Path=/; HttpOnly

重写后:
  Set-Cookie: session=abc123; Path=/example.com/; HttpOnly
```

### Cookie 过滤规则

```
浏览器发送:
  Cookie: session=abc123; other=xyz

过滤后（假设目标域名为 example.com）:
  Cookie: session=abc123
```

### 边界情况处理

1. **无Path属性的Cookie**: 默认添加 `Path=/domain/`
2. **已有Path的Cookie**: 在原Path前添加域名前缀
3. **多个Set-Cookie头**: 逐个处理
4. **Cookie属性保留**: 保留 HttpOnly, Secure, SameSite 等属性

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `modules/url/cookie.py` | 新建 | Cookie处理器 |
| `modules/url/__init__.py` | 修改 | 导出CookieHandler |
| `modules/proxy.py` | 修改 | 集成Cookie处理逻辑 |

## 测试验证

1. 访问多个不同网站，验证Cookie隔离
2. 检查请求头大小是否正常
3. 验证登录状态等Cookie功能正常
