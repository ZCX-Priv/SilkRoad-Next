# Dock URL 显示优化计划

## 需求分析

用户需要优化 dock 栏的 URL 显示功能：
1. **自动去掉代理链接前缀**：显示原始链接而非代理链接
2. **URL 可编辑**：用户可以修改 URL
3. **编辑时显示"前往"按钮**：点击可导航到编辑后的 URL

## 代理服务器 URL 格式分析

### 代理 URL 格式
- **浏览器地址栏显示**：`http://127.0.0.1:8080/www.zhidx.com/path`
- **应该显示的原格式**：`www.zhidx.com/path`

### 提取逻辑
从 `http://127.0.0.1:8080/www.zhidx.com/path` 提取：
- 去掉代理前缀：`http://127.0.0.1:8080/`
- 保留剩余部分：`www.zhidx.com/path`

### 导航逻辑
用户编辑后点击"前往"：
- 用户输入：`www.example.com/new-path`
- 构建代理 URL：`/www.example.com/new-path`
- 导航到：`http://127.0.0.1:8080/www.example.com/new-path`

## 当前实现分析

当前代码（[dock.js](file:///c:/Users/赵晨旭/Desktop/SilkRoad-Next/Scripts/dock.js)）中：
- URL 显示区域是 `div` 元素（第 275-302 行）
- 已有简单的代理 URL 提取逻辑（第 286-289 行），正则表达式不正确
- 点击 URL 只能复制，不能编辑

## 实现步骤

### 步骤 1：重写 URL 提取逻辑

```javascript
function extractOriginalUrl(proxyUrl) {
    try {
        const url = new URL(proxyUrl);
        // 获取路径部分，去掉开头的 /
        const originalPath = url.pathname.substring(1) + url.search + url.hash;
        return originalPath || '/';
    } catch (e) {
        return proxyUrl;
    }
}
```

### 步骤 2：将 URL 显示改为可编辑输入框

- 将 `div.silkroad-dock-url` 改为 `input` 元素
- 添加相应的 CSS 样式使输入框与原有设计一致
- 输入框宽度自适应，最大宽度保持 300px

### 步骤 3：添加"前往"按钮

- 在 URL 输入框右侧添加"前往"按钮
- 默认隐藏，当用户开始编辑（输入内容变化）时显示
- 按钮样式与现有 dock 按钮风格一致（圆形、透明背景、hover 效果）

### 步骤 4：实现交互逻辑

**编辑状态检测**：
- 监听 `input` 事件检测内容变化
- 内容变化时显示"前往"按钮
- 内容与原始 URL 相同时隐藏按钮

**导航逻辑**：
```javascript
function navigateToUrl(inputValue) {
    // 构建代理 URL 并导航
    const proxyPath = '/' + inputValue.replace(/^\//, '');
    window.location.href = proxyPath;
}
```

### 步骤 5：更新 CSS 样式

添加新样式：
- `.silkroad-dock-url-input`：输入框样式（无边框、透明背景、继承字体）
- `.silkroad-dock-go`：前往按钮样式（圆形、与现有按钮风格一致）
- `.silkroad-dock-url-wrapper`：URL 容器样式（flex 布局，包含输入框和按钮）

## 代码修改位置

文件：[Scripts/dock.js](file:///c:/Users/赵晨旭/Desktop/SilkRoad-Next/Scripts/dock.js)

主要修改：
1. **CSS 样式部分**（第 9-210 行）：添加输入框和前往按钮样式
2. **URL 提取逻辑**（第 279-299 行）：重写为简单的路径提取
3. **URL 显示区域**（第 274-302 行）：改为输入框 + 前往按钮
4. **事件监听**（第 442-533 行）：移除复制逻辑，添加编辑和导航功能

## 预期效果

1. Dock 栏显示原始 URL（如 `www.zhidx.com/path`）
2. 点击 URL 输入框可编辑内容
3. 编辑时右侧出现"前往"按钮
4. 点击"前往"按钮通过代理访问编辑后的 URL
5. 按 Enter 键也可触发导航

## 交互细节

| 状态 | URL 显示 | 前往按钮 |
|------|----------|----------|
| 初始加载 | `www.zhidx.com/path` | 隐藏 |
| 点击输入框 | 可编辑 | 隐藏 |
| 修改内容 | 编辑后的内容 | 显示 |
| 内容恢复原样 | 原始内容 | 隐藏 |
| 点击前往 | 导航到新 URL | - |
| 按 Enter | 导航到新 URL | - |
