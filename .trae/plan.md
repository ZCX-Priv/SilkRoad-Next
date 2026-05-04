# SilkRoad 代理服务器 403 和跨域问题修复计划

## 问题分析

### 1. 403 Forbidden 错误原因

通过分析代码和测试日志，发现以下问题：

#### 1.1 请求头处理不完整
- **位置**: `modules/proxy.py` 第 599-653 行 `_build_forward_headers` 方法
- **问题**: 
  - 硬编码了要跳过的请求头，没有使用配置文件中的 `forwardHeaders` 列表
  - 缺少关键的请求头字段，如：
    - `Accept` - 指定客户端能够接收的内容类型
    - `Accept-Language` - 指定首选语言
    - `Origin` - 跨域请求的关键字段
    - `X-Forwarded-For` - 代理服务器的标准头
  - 某些网站（如虎扑）会检查请求头的完整性，缺少这些字段会返回 403

#### 1.2 配置文件未被正确使用
- **配置文件**: `databases/config.json` 第 19-44 行
- **问题**: 
  - 配置中定义了 `forwardHeaders` 和 `dropHeaders`，但代码中未使用
  - 导致配置文件形同虚设

### 2. 跨域问题原因

#### 2.1 响应头缺少 CORS 字段
- **位置**: `modules/flow/normal.py` 第 306-336 行 `_send_response` 方法
- **问题**:
  - 只移除了 `Content-Security-Policy`，但没有添加 CORS 相关头
  - 缺少以下关键响应头：
    - `Access-Control-Allow-Origin` - 允许的源
    - `Access-Control-Allow-Methods` - 允许的方法
    - `Access-Control-Allow-Headers` - 允许的头
    - `Access-Control-Allow-Credentials` - 是否允许携带凭证
    - `Access-Control-Max-Age` - 预检请求缓存时间

#### 2.2 OPTIONS 预检请求未处理
- **问题**: 
  - 浏览器在发送跨域请求前会先发送 OPTIONS 预检请求
  - 当前代码没有特殊处理 OPTIONS 请求
  - 导致预检请求失败，后续的实际请求无法发送

## 解决方案

### 方案 1: 修复请求头处理（优先级：高）

**文件**: `modules/proxy.py`

**修改点 1**: `_build_forward_headers` 方法（第 599-653 行）

**修改内容**:
```python
def _build_forward_headers(self, original_headers: Dict[str, str],
                            target_url: str) -> Dict[str, str]:
    """
    构建转发请求头
    
    根据配置文件的 forwardHeaders 和 dropHeaders 处理请求头
    """
    forward_headers = {}
    
    # 从配置文件读取要转发的头列表
    forward_list = self.config.get('proxy.forwardHeaders', [])
    drop_list = set(self.config.get('proxy.dropHeaders', []))
    
    # 添加配置中指定的要转发的头
    for header in forward_list:
        if header in original_headers:
            forward_headers[header] = original_headers[header]
    
    # 添加其他未被丢弃的头
    for key, value in original_headers.items():
        if key in drop_list:
            continue
        if key not in forward_headers:  # 避免重复
            forward_headers[key] = value
    
    # 设置必要的头
    parsed = urlsplit(target_url)
    forward_headers['Host'] = parsed.netloc
    forward_headers['Connection'] = 'keep-alive'
    
    # 确保 Accept 头存在
    if 'Accept' not in forward_headers:
        forward_headers['Accept'] = '*/*'
    
    # 确保 Accept-Language 头存在
    if 'Accept-Language' not in forward_headers:
        forward_headers['Accept-Language'] = 'zh-CN,zh;q=0.9,en;q=0.8'
    
    # 确保 Accept-Encoding 头存在
    if 'Accept-Encoding' not in forward_headers:
        forward_headers['Accept-Encoding'] = 'gzip, deflate, br'
    
    # 确保 User-Agent 头存在
    if 'User-Agent' not in forward_headers:
        forward_headers['User-Agent'] = self.config.get(
            'proxy.defaultUserAgent',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
    
    # 处理 Origin 头（跨域请求的关键）
    if 'Origin' in original_headers:
        # 重写 Origin 为目标域名
        forward_headers['Origin'] = f"{parsed.scheme}://{parsed.netloc}"
    
    # 重写 Referer 头
    if 'Referer' in forward_headers:
        forward_headers['Referer'] = self._rewrite_referer(
            forward_headers['Referer'], target_url
        )
    
    return forward_headers
```

**预期效果**:
- ✅ 所有必要的请求头都会被正确转发
- ✅ 符合配置文件的设置
- ✅ 解决因缺少请求头导致的 403 错误

### 方案 2: 添加 CORS 响应头（优先级：高）

**文件**: `modules/flow/normal.py`

**修改点 1**: `_send_response` 方法（第 252-360 行）

**修改内容**: 在响应头处理部分添加 CORS 头

```python
# 在第 336 行之后添加以下代码

# 添加 CORS 响应头
resp_headers['Access-Control-Allow-Origin'] = '*'
resp_headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS'
resp_headers['Access-Control-Allow-Headers'] = '*'
resp_headers['Access-Control-Allow-Credentials'] = 'true'
resp_headers['Access-Control-Max-Age'] = '86400'  # 24小时
```

**修改点 2**: 添加 OPTIONS 请求处理方法

**新增方法**:
```python
async def _handle_options_request(self, writer: asyncio.StreamWriter,
                                   request_headers: Dict[str, str]) -> None:
    """
    处理 OPTIONS 预检请求
    
    Args:
        writer: 流写入器
        request_headers: 请求头
    """
    try:
        # 构建响应头
        headers = {
            'Allow': 'GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS',
            'Access-Control-Allow-Headers': '*',
            'Access-Control-Allow-Credentials': 'true',
            'Access-Control-Max-Age': '86400',
            'Content-Length': '0',
            'Connection': 'keep-alive'
        }
        
        # 发送响应
        response_line = 'HTTP/1.1 204 No Content\r\n'
        header_lines = ''.join(f'{k}: {v}\r\n' for k, v in headers.items())
        
        writer.write(response_line.encode())
        writer.write(header_lines.encode())
        writer.write(b'\r\n')
        await writer.drain()
        
    except Exception as e:
        self.logger.error(f"处理 OPTIONS 请求失败: {e}")
```

**修改点 3**: 在 `handle` 方法中添加 OPTIONS 请求判断

```python
async def handle(self, writer, method, target_url, headers, body, session_id=None):
    # 处理 OPTIONS 预检请求
    if method == 'OPTIONS':
        await self._handle_options_request(writer, headers)
        return
    
    # 原有的处理逻辑
    if self.connection_pool:
        await self._forward_with_pool(writer, method, target_url, headers, body, session_id)
    else:
        await self._forward_direct(writer, method, target_url, headers, body)
```

**预期效果**:
- ✅ 正确处理 OPTIONS 预检请求
- ✅ 添加必要的 CORS 响应头
- ✅ 解决跨域请求被浏览器拦截的问题

### 方案 3: 优化配置文件（优先级：中）

**文件**: `databases/config.json`

**修改内容**: 更新 `forwardHeaders` 列表，添加更多必要的头

```json
"forwardHeaders": [
  "Accept",
  "Accept-Language",
  "Accept-Datetime",
  "Accept-Encoding",
  "Cache-Control",
  "Content-Type",
  "If-Match",
  "If-Modified-Since",
  "If-None-Match",
  "If-Range",
  "If-Unmodified-Since",
  "Range",
  "X-Requested-With",
  "Origin",
  "X-Forwarded-For",
  "X-Real-IP",
  "X-Forwarded-Proto",
  "DNT",
  "Upgrade-Insecure-Requests"
]
```

**预期效果**:
- ✅ 配置文件更加完善
- ✅ 支持更多常见的请求头

## 实施步骤

### 步骤 1: 修改请求头处理逻辑
1. 打开 `modules/proxy.py`
2. 定位到 `_build_forward_headers` 方法（第 599 行）
3. 替换整个方法为新实现
4. 确保正确读取配置文件

### 步骤 2: 添加 CORS 支持
1. 打开 `modules/flow/normal.py`
2. 在 `_send_response` 方法中添加 CORS 响应头（第 336 行之后）
3. 添加 `_handle_options_request` 方法
4. 在 `handle` 方法开头添加 OPTIONS 请求判断

### 步骤 3: 更新配置文件
1. 打开 `databases/config.json`
2. 更新 `forwardHeaders` 列表
3. 保存配置文件

### 步骤 4: 测试验证
1. 重启 SilkRoad 服务器
2. 使用 Playwright 访问虎扑网站
3. 检查控制台是否还有 403 错误
4. 检查页面是否正常显示（无白屏）
5. 测试图片、视频等资源加载情况

## 预期结果

### 修复前
- ❌ 大量 403 Forbidden 错误
- ❌ 页面完全空白
- ❌ 跨域请求被拦截
- ❌ 资源加载失败

### 修复后
- ✅ 无 403 错误或大幅减少
- ✅ 页面正常显示
- ✅ 跨域请求正常工作
- ✅ 资源正常加载
- ✅ 符合验收标准：
  1. 网页内容正常加载，网页不白屏
  2. 网页内图片、视频等资源加载正常
  3. 网页可连续加载新内容
  4. 服务器性能良好

## 风险评估

### 低风险
- 修改请求头处理逻辑：只影响转发的请求头，不改变核心逻辑
- 添加 CORS 响应头：只是添加额外的头，不影响现有功能
- 更新配置文件：纯配置修改，风险极低

### 需要注意
- 确保修改后不影响其他网站的访问
- 测试时需要覆盖多种类型的网站
- 需要验证 HTTPS 和 HTTP 请求都能正常工作

## 回滚方案

如果修复后出现问题，可以：
1. 恢复原始代码（使用 git checkout）
2. 重启服务器
3. 清除浏览器缓存重新测试

## 时间估算

- 代码修改：15 分钟
- 测试验证：10 分钟
- 总计：25 分钟
