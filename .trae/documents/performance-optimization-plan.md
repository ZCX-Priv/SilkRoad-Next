# SilkRoad-Next 性能优化重构计划

## 目标

在 1核1G 环境下实现毫秒级响应，支撑 5000 并发连接。

## 现状分析

当前项目存在 **10 大性能瓶颈**，按严重程度排序：

| # | 瓶颈 | 严重程度 | 位置 |
|---|------|----------|------|
| 1 | 每个请求创建/销毁 ClientSession，连接池形同虚设 | **极高** | normal.py:151-173 |
| 2 | 异步方法中大量同步文件 I/O 阻塞事件循环 | **极高** | cachemanager/sessions/blacklist/scripts/cfg/pageserver |
| 3 | 全量读取响应到内存（包括大文件） | **高** | normal.py:199, normal.py:363 |
| 4 | ConnectionPool 单一全局锁 | **高** | connectionpool.py:91 |
| 5 | CPU 密集型操作（URL重写/脚本注入）未使用线程池 | **高** | normal.py:202-208 |
| 6 | aiohttp.TCPConnector limit 硬编码 100 | **中** | proxy.py:123 |
| 7 | BlacklistManager 每次请求重建 ipaddress 对象 | **中** | blacklist.py:254-258 |
| 8 | _is_valid_host 每次调用重建大型集合 | **中** | proxy.py:539-564 |
| 9 | SessionManager JSON序列化仅用于计算大小 | **中** | sessions.py:157 |
| 10 | 流式传输 chunk_size 过小 (8KB) | **中** | normal.py:467 |

---

## 优化方案（6 大模块）

### 模块一：连接池架构重构（最高优先级）

**问题**：`_forward_with_pool()` 每次请求都创建新的 `aiohttp.ClientSession` + `TCPConnector`，请求结束后立即关闭，完全无法复用 TCP 连接。

**方案**：改为 **Session 池** 模式 —— 按 `(host, port, scheme)` 维护持久化的 `aiohttp.ClientSession` 实例。

#### 步骤 1.1：重写 ConnectionPool 为 SessionPool

- 文件：`modules/connectionpool.py`
- 将存储结构从 `{host:port: [connector, ...]}` 改为 `{host:port:scheme: ClientSession}`
- 每个 `(host, port, scheme)` 维护一个持久化的 `ClientSession`，内含 `TCPConnector` 自动管理底层连接
- 移除手动管理 `TCPConnector` 的逻辑，让 `aiohttp` 内部管理连接生命周期
- 使用细粒度锁（per-pool-key）替代单一全局锁
- 添加会话 Cookie 的请求隔离（使用 `aiohttp.CookieJar` 而非实例属性）

#### 步骤 1.2：重构 NormalHandler._forward_with_pool()

- 文件：`modules/flow/normal.py`
- 不再每次创建/销毁 `ClientSession`
- 从 `SessionPool` 获取对应 host 的 `ClientSession`，直接复用
- 请求完成后不关闭 session，仅归还给池
- 会话 Cookie 通过 `aiohttp.CookieJar` 的 `clear()` + `update()` 实现请求隔离

#### 步骤 1.3：修复 ProxyServer 主 session 的连接池限制

- 文件：`modules/proxy.py`
- `TCPConnector(limit=100)` 改为使用配置值 `maxConnections`
- 添加 `force_close=False` 优化连接复用
- 添加 `limit_per_host` 配置项

#### 步骤 1.4：调整配置参数

- 文件：`databases/config.json`
- `performance.connectionPool.maxPoolSize` 从 100 提升到 500
- 添加 `limitPerHost` 配置项（默认 50）

---

### 模块二：异步 I/O 迁移（高优先级）

**问题**：所有文件 I/O（缓存读写、配置加载、会话持久化、脚本加载）都是同步操作，在 `async` 方法中直接阻塞事件循环。

**方案**：将所有文件 I/O 迁移到线程池执行，或使用 `aiofiles` / `asyncio.to_thread()`。

#### 步骤 2.1：CacheManager 异步化

- 文件：`modules/cachemanager.py`
- 所有 `open()` / `json.load()` / `json.dump()` 调用改为 `asyncio.to_thread()` 包装
- 磁盘缓存写入改为后台异步任务（不阻塞响应发送）
- 移除每次缓存读取时的 `last_access` 文件更新（改为内存中记录，定期批量刷盘）
- `_init_disk_cache_size()` 改为异步执行

#### 步骤 2.2：PageServer 异步化

- 文件：`modules/pageserver.py`
- 大文件流式传输改为 `asyncio.to_thread()` 读取 chunk
- 小文件读取改为异步
- Range 请求读取改为异步

#### 步骤 2.3：其他模块异步化

- `modules/sessions.py`：会话持久化改为异步
- `modules/blacklist.py`：配置加载/保存改为异步
- `modules/scripts.py`：脚本加载改为异步
- `modules/cfg.py`：配置加载/保存改为异步

---

### 模块三：流式响应与内存优化（高优先级）

**问题**：所有响应（包括大文件）全量读入内存后再处理和发送，1G 内存无法支撑 5000 并发。

**方案**：实现真正的流式代理，小响应全量处理，大响应流式透传。

#### 步骤 3.1：NormalHandler 流式响应重构

- 文件：`modules/flow/normal.py`
- `_forward_with_pool()` 改为流式处理：
  - 小于 `stream_threshold` 的响应：全量读取 → URL重写 → 脚本注入 → 发送
  - 大于 `stream_threshold` 的响应：流式透传（chunk-by-chunk），跳过 URL 重写和脚本注入
- `_forward_direct()` 同样优化
- chunk_size 从 8KB 提升到 64KB

#### 步骤 3.2：缓存响应保留 Content-Type

- 文件：`modules/flow/normal.py`
- `_send_cached_response()` 不再硬编码 `text/html`
- 缓存时同时存储原始 Content-Type，返回时使用

#### 步骤 3.3：错误页面预生成

- 文件：`modules/flow/normal.py` + `modules/proxy.py`
- 预生成常见错误码（400/403/404/408/500/502/504/508）的 HTML
- 存储为类属性，避免每次请求重新构建

---

### 模块四：CPU 密集型任务优化（中优先级）

**问题**：URL 重写（正则替换）、脚本注入（正则匹配）在事件循环中同步执行，阻塞所有请求。

**方案**：将 CPU 密集型任务卸载到线程池。

#### 步骤 4.1：URL 重写卸载到线程池

- 文件：`modules/url/handle.py` + `modules/flow/normal.py`
- `URLHandler.rewrite()` 改为接受线程池参数
- 正则替换操作通过 `thread_pool.run_in_thread()` 执行
- 对于小内容（< 1KB），直接在事件循环中执行（避免线程切换开销）

#### 步骤 4.2：脚本注入卸载到线程池

- 文件：`modules/scripts.py`
- `inject_scripts()` 的正则匹配部分卸载到线程池

#### 步骤 4.3：BlacklistManager 预编译优化

- 文件：`modules/blacklist.py`
- 配置加载时预编译 `ipaddress.ip_network()` 对象并缓存
- 请求时直接使用缓存的网络对象进行匹配

#### 步骤 4.4：ThreadPoolManager 统计锁优化

- 文件：`modules/threadpool.py`
- `asyncio.Lock` 改为 `threading.Lock`（统计更新在工作线程中执行）
- 统计更新改为同步操作，减少协程切换开销

---

### 模块五：数据结构与算法优化（中优先级）

**问题**：多处使用低效数据结构和算法。

#### 步骤 5.1：ConnectionPool 活跃连接计数优化

- 文件：`modules/connectionpool.py`
- 维护 `per-pool-key` 的活跃连接计数器，替代线性扫描

#### 步骤 5.2：CacheManager LRU 优化

- 文件：`modules/cachemanager.py`
- 使用 `collections.OrderedDict` 替代手动 LRU 管理
- 淘汰时 `popitem(last=False)` 即可，O(1) 复杂度

#### 步骤 5.3：ProxyServer._is_valid_host 常量提升

- 文件：`modules/proxy.py`
- `file_extensions` 和 `tlds` 集合提升为类常量

#### 步骤 5.4：PageServer 路由预排序

- 文件：`modules/pageserver.py`
- 路由在初始化时预排序，不再每次请求排序

#### 步骤 5.5：SessionManager 大小计算优化

- 文件：`modules/sessions.py`
- 用 `sys.getsizeof()` 或增量计数替代 `json.dumps()` 计算大小

---

### 模块六：1核1G 极限配置调优（中优先级）

**问题**：当前配置未针对低资源环境优化。

#### 步骤 6.1：内存预算分配

1G 内存分配方案：
- Python 进程基础：~50MB
- 事件循环 + 协程栈：~20MB
- 内存缓存：~200MB（从 100MB 适当增加，减少磁盘 I/O）
- 连接池缓冲：~100MB
- 响应缓冲（流式传输）：~100MB
- 系统保留：~530MB

#### 步骤 6.2：配置参数调整

```json
{
  "server": {
    "proxy": {
      "backlog": 4096,
      "maxConnections": 5000,
      "connectionTimeout": 15,
      "requestTimeout": 30
    }
  },
  "performance": {
    "connectionPool": {
      "maxPoolSize": 500,
      "maxKeepaliveConnections": 100,
      "keepaliveTimeout": 60
    },
    "threadPool": {
      "maxWorkers": 4,
      "queueSize": 2000
    }
  },
  "cache": {
    "maxSize": 209715200,
    "defaultTTL": 1800,
    "cleanupInterval": 120
  },
  "urlRewrite": {
    "streamThreshold": 524288
  },
  "stream": {
    "chunked": {
      "defaultChunkSize": 65536
    }
  }
}
```

关键调整说明：
- `connectionTimeout` 15s：快速释放空闲连接
- `requestTimeout` 30s：避免慢请求占满连接
- `threadPool.maxWorkers` 4：1核 CPU 不宜开太多线程
- `cache.maxSize` 200MB：内存缓存增大，减少磁盘 I/O
- `streamThreshold` 512KB：降低流式阈值，减少内存占用
- `defaultChunkSize` 64KB：提升流式传输效率

#### 步骤 6.3：TCP 内核参数优化（运行时提示）

在启动日志中输出系统级调优建议：
- `net.core.somaxconn` = 4096
- `net.ipv4.tcp_max_syn_backlog` = 4096
- `net.ipv4.tcp_tw_reuse` = 1
- `vm.swappiness` = 10
- `fs.file-max` = 65535

---

## 实施顺序

```
Phase 1（核心瓶颈，效果最大）:
  ├── 模块一：连接池架构重构
  └── 模块三：流式响应与内存优化

Phase 2（I/O 瓶颈）:
  └── 模块二：异步 I/O 迁移

Phase 3（CPU 与算法优化）:
  ├── 模块四：CPU 密集型任务优化
  └── 模块五：数据结构与算法优化

Phase 4（配置调优）:
  └── 模块六：1核1G 极限配置调优
```

## 预期效果

| 指标 | 优化前 | 优化后（预期） |
|------|--------|----------------|
| 单请求延迟 | 50-200ms | 1-10ms |
| 5000 并发 CPU 占用 | >90% | <60% |
| 5000 并发内存占用 | >2GB | <800MB |
| 连接复用率 | ~0% | >80% |
| 事件循环阻塞时间 | 频繁（磁盘I/O） | <1ms/次 |

## 验收标准

1. 网页内容正常加载，不白屏
2. 图片、视频等资源加载正常，无跨域/403 错误
3. 可连续加载新内容，不会请求 1 次后无法加载
4. 1核1G 环境下 5000 并发，CPU < 60%，内存 < 800MB
5. 缓存命中时响应延迟 < 5ms
6. 非缓存请求代理延迟增加 < 10ms（相比直连）
