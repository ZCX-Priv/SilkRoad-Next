# 修复计划：URL 解析缺少斜杠时无法正确处理查询参数

## 问题描述

当用户访问 `http://127.0.0.1:8080/www.hao123.com?src=from_pc`（域名后没有斜杠）时，代理服务器返回 400 错误。

## 根本原因分析

在 `_parse_target_url` 函数中：

```
path = "/www.hao123.com?src=from_pc"
path.lstrip('/') = "www.hao123.com?src=from_pc"
path.split('/', 1) = ["www.hao123.com?src=from_pc"]  # 只有一个元素！
first_segment = "www.hao123.com?src=from_pc"
```

由于没有斜杠分隔，查询参数 `?src=from_pc` 被错误地包含在 `first_segment` 中，导致 `_is_valid_host()` 验证失败（因为包含 `?` 字符）。

## 修复方案

在 `_parse_target_url` 函数中，先分离查询参数，解析完域名和路径后再重新附加查询参数。

## 实现步骤

### 步骤 1：修改 `_parse_target_url` 函数

**文件：** `modules/proxy.py`

**修改位置：** 第 492-519 行

**修改内容：**

1. 在 `path.lstrip('/')` 之后，先分离查询参数
2. 解析域名和路径时不包含查询参数
3. 构建最终 URL 时重新附加查询参数

**修改前代码：**

```python
path = path.lstrip('/')

if not path:
    return None

parts = path.split('/', 1)
first_segment = parts[0]
target_path = '/' + parts[1] if len(parts) > 1 else '/'
```

**修改后代码：**

```python
path = path.lstrip('/')

if not path:
    return None

# 先分离查询参数，处理 "domain.com?query" 的情况
query_string = ''
if '?' in path:
    path, query_string = path.split('?', 1)
    query_string = '?' + query_string

parts = path.split('/', 1)
first_segment = parts[0]
target_path = '/' + parts[1] if len(parts) > 1 else '/'

# 将查询参数附加到路径后面
if query_string:
    target_path += query_string
```

## 测试验证

修复后，以下 URL 格式都应该正常工作：

* `http://127.0.0.1:8080/www.hao123.com?src=from_pc` ✅

* `http://127.0.0.1:8080/www.hao123.com/?src=from_pc` ✅

* `http://127.0.0.1:8080/www.hao123.com/path?query=value` ✅

* `http://127.0.0.1:8080/www.hao123.com/path/?query=value` ✅

## 影响范围

* 仅修改 `modules/proxy.py` 文件中的 `_parse_target_url` 方法

* 不影响其他功能

* 向后兼容，原有正常工作的 URL 格式不受影响

