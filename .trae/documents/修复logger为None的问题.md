# 修改计划：修复 logger 为 None 时的问题

## 问题分析

之前的修改把 `self.logger = logger or logging.getLogger(__name__)` 改成了 `self.logger = logger`，这导致当 `logger` 参数为 `None` 时，`self.logger` 也是 `None`，调用 `info`、`warning` 等方法会报错。

## 正确的修改方式

需要保留后备机制，使用 loguru 的全局 logger 作为默认值：

```python
# 修改前
import logging
self.logger = logger or logging.getLogger(__name__)

# 修改后（正确方式）
from loguru import logger as loguru_logger
self.logger = logger or loguru_logger
```

## 需要修改的文件

### 1. 导入语句修改

| 文件 | 修改内容 |
|------|----------|
| `modules/stream/others.py` | `from loguru import logger` → `from loguru import logger as loguru_logger` |
| `modules/stream/sse.py` | 同上 |
| `modules/stream/media.py` | 同上 |
| `modules/stream/handle.py` | 同上 |
| `modules/sessions.py` | 同上 |
| `modules/scripts.py` | 同上 |
| `modules/websockets.py` | 同上 |
| `modules/controler.py` | 同上 |
| `modules/connectionpool.py` | 同上 |

### 2. logger 初始化修改

| 文件 | 行号 | 当前代码 | 修改后代码 |
|------|------|----------|------------|
| `modules/stream/others.py` | 75 | `self.logger = logger` | `self.logger = logger or loguru_logger` |
| `modules/stream/sse.py` | 94 | `self.logger = logger` | `self.logger = logger or loguru_logger` |
| `modules/stream/media.py` | 83 | `self.logger = logger` | `self.logger = logger or loguru_logger` |
| `modules/stream/handle.py` | 65 | `self.logger = logger` | `self.logger = logger or loguru_logger` |
| `modules/sessions.py` | 112 | `self._logger = logger` | `self._logger = logger or loguru_logger` |
| `modules/scripts.py` | 114 | `self._logger = logger` | `self._logger = logger or loguru_logger` |
| `modules/websockets.py` | 102 | `self.logger = logger` | `self.logger = logger or loguru_logger` |
| `modules/controler.py` | 83, 466 | `self.logger = logger` | `self.logger = logger or loguru_logger` |
| `modules/connectionpool.py` | 93 | `self._logger = logger` | `self._logger = logger or loguru_logger` |

### 3. exc_info 参数修改

| 文件 | 行号 | 当前代码 | 修改后代码 |
|------|------|----------|------------|
| `modules/stream/handle.py` | 329 | `self.logger.error(..., exc_info=True)` | `self.logger.opt(exception=True).error(...)` |
| `modules/proxy.py` | 1581 | `self.logger.error(..., exc_info=True)` | `self.logger.opt(exception=True).error(...)` |

## 执行步骤

1. 修改 9 个文件的导入语句
2. 修改 9 个文件的 logger 初始化（共 11 处）
3. 修改 2 个文件的 exc_info 参数
4. 验证修改结果
