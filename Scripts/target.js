/**
 * 目标定位脚本 - SilkRoad Target Locator
 * 
 * 功能：
 * 1. 在页面顶部显示当前访问的目标信息
 * 2. 高亮显示当前域名
 * 3. 显示代理状态指示器
 * 
 * 作者: SilkRoad-Next Team
 * 版本: 2.0.0
 */

(function() {
    'use strict';
    
    // 避免重复创建
    if (document.getElementById('silkroad-target-bar')) {
        return;
    }
    
    // 创建目标定位栏
    function createTargetBar() {
        const bar = document.createElement('div');
        bar.id = 'silkroad-target-bar';
        bar.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 28px;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: white;
            z-index: 999998;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
            font-size: 12px;
            display: flex;
            align-items: center;
            padding: 0 15px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.3);
        `;
        
        // 代理状态指示器
        const statusIndicator = document.createElement('div');
        statusIndicator.style.cssText = `
            width: 8px;
            height: 8px;
            background: #4CAF50;
            border-radius: 50%;
            margin-right: 10px;
            animation: pulse 2s infinite;
        `;
        
        // 添加动画样式
        const style = document.createElement('style');
        style.textContent = `
            @keyframes pulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.5; }
            }
            body { padding-top: 28px !important; }
        `;
        document.head.appendChild(style);
        
        // 代理标签
        const proxyLabel = document.createElement('span');
        proxyLabel.textContent = 'SilkRoad';
        proxyLabel.style.cssText = `
            color: #2196F3;
            font-weight: bold;
            margin-right: 10px;
        `;
        
        // 分隔符
        const separator = document.createElement('span');
        separator.textContent = '|';
        separator.style.cssText = `
            color: #555;
            margin-right: 10px;
        `;
        
        // 目标信息
        const targetInfo = document.createElement('span');
        targetInfo.style.cssText = `
            color: #aaa;
            display: flex;
            align-items: center;
            gap: 5px;
        `;
        
        // 协议图标
        const protocolIcon = document.createElement('span');
        protocolIcon.textContent = window.location.protocol === 'https:' ? '🔒' : '🔓';
        
        // 目标域名
        const targetDomain = document.createElement('span');
        targetDomain.textContent = window.location.hostname;
        targetDomain.style.cssText = `
            color: #4CAF50;
            font-weight: 500;
        `;
        
        // 目标路径
        const targetPath = document.createElement('span');
        targetPath.textContent = window.location.pathname;
        targetPath.style.cssText = `
            color: #888;
        `;
        
        targetInfo.appendChild(protocolIcon);
        targetInfo.appendChild(targetDomain);
        targetInfo.appendChild(targetPath);
        
        // 右侧信息
        const rightInfo = document.createElement('div');
        rightInfo.style.cssText = `
            margin-left: auto;
            display: flex;
            align-items: center;
            gap: 15px;
        `;
        
        // 时间显示
        const timeDisplay = document.createElement('span');
        timeDisplay.style.cssText = `
            color: #666;
        `;
        
        function updateTime() {
            const now = new Date();
            timeDisplay.textContent = now.toLocaleTimeString();
        }
        updateTime();
        setInterval(updateTime, 1000);
        
        // 切换按钮
        const toggleBtn = document.createElement('span');
        toggleBtn.textContent = '×';
        toggleBtn.style.cssText = `
            color: #666;
            cursor: pointer;
            font-size: 16px;
            padding: 0 5px;
            transition: color 0.2s;
        `;
        toggleBtn.addEventListener('mouseenter', function() {
            this.style.color = '#f44336';
        });
        toggleBtn.addEventListener('mouseleave', function() {
            this.style.color = '#666';
        });
        toggleBtn.addEventListener('click', function() {
            bar.style.transform = 'translateY(-100%)';
            document.body.style.paddingTop = '0';
            setTimeout(() => {
                bar.style.display = 'none';
            }, 300);
        });
        
        rightInfo.appendChild(timeDisplay);
        rightInfo.appendChild(toggleBtn);
        
        bar.appendChild(statusIndicator);
        bar.appendChild(proxyLabel);
        bar.appendChild(separator);
        bar.appendChild(targetInfo);
        bar.appendChild(rightInfo);
        
        document.body.appendChild(bar);
        
        // 监听 URL 变化（针对 SPA）
        let lastUrl = window.location.href;
        
        const urlObserver = new MutationObserver(function() {
            if (window.location.href !== lastUrl) {
                lastUrl = window.location.href;
                targetDomain.textContent = window.location.hostname;
                targetPath.textContent = window.location.pathname;
                protocolIcon.textContent = window.location.protocol === 'https:' ? '🔒' : '🔓';
            }
        });
        
        urlObserver.observe(document.body, {
            childList: true,
            subtree: true
        });
        
        // 监听 pushState 和 popstate
        const originalPushState = history.pushState;
        history.pushState = function() {
            originalPushState.apply(history, arguments);
            targetDomain.textContent = window.location.hostname;
            targetPath.textContent = window.location.pathname;
            protocolIcon.textContent = window.location.protocol === 'https:' ? '🔒' : '🔓';
        };
        
        window.addEventListener('popstate', function() {
            targetDomain.textContent = window.location.hostname;
            targetPath.textContent = window.location.pathname;
            protocolIcon.textContent = window.location.protocol === 'https:' ? '🔒' : '🔓';
        });
    }
    
    // 页面加载完成后创建目标栏
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', createTargetBar);
    } else {
        createTargetBar();
    }
})();
