// SilkRoad自定义脚本 - 底部Dock栏
(function() {
    console.log('底部浮动Dock栏');
    
    // 在页面加载完成后执行
    document.addEventListener('DOMContentLoaded', function() {
        // 创建样式
        const style = document.createElement('style');
        style.textContent = `
            .silkroad-dock {
                position: fixed !important;
                bottom: 20px !important;
                left: 50% !important;
                transform: translateX(-50%) !important;
                background-color: rgba(40, 44, 52, 0.95) !important;
                color: white !important;
                padding: 8px 16px !important;
                display: flex !important;
                justify-content: space-between !important;
                align-items: center !important;
                z-index: 9999 !important;
                transition: all 0.3s ease !important;
                box-shadow: 0 5px 25px rgba(0, 0, 0, 0.25) !important;
                font-family: 'Segoe UI', Arial, sans-serif !important;
                border-radius: 50px !important;
                max-width: 90% !important;
                width: auto !important;
            }
            .silkroad-dock.light-mode {
                background-color: rgba(240, 240, 240, 0.95) !important;
                color: #333 !important;
                box-shadow: 0 5px 25px rgba(0, 0, 0, 0.15) !important;
            }
            .silkroad-dock.light-mode .silkroad-dock-button svg,
            .silkroad-dock.light-mode .silkroad-dock-clear svg,
            .silkroad-dock.light-mode .silkroad-dock-theme svg,
            .silkroad-dock.light-mode .silkroad-dock-handle svg {
                fill: #333 !important;
            }
            .silkroad-dock-theme {
                background-color: transparent !important;
                border: none !important;
                color: white !important;
                width: 36px !important;
                height: 36px !important;
                border-radius: 50% !important;
                cursor: pointer !important;
                transition: all 0.2s !important;
                display: flex !important;
                justify-content: center !important;
                align-items: center !important;
                margin-left: 10px !important;
            }
            .silkroad-dock-theme:hover {
                background-color: rgba(255, 255, 255, 0.15) !important;
                transform: translateY(-3px) !important;
            }
            .silkroad-dock-theme svg {
                width: 18px !important;
                height: 18px !important;
                fill: white !important;
            }
            .silkroad-dock.collapsed {
                width: 50px !important;
                height: 50px !important;
                border-radius: 50% !important;
                padding: 0 !important;
                overflow: hidden !important;
                justify-content: center !important;
            }
            .silkroad-dock.collapsed .silkroad-dock-buttons,
            .silkroad-dock.collapsed .silkroad-dock-url,
            .silkroad-dock.collapsed .silkroad-dock-clear,
            .silkroad-dock.collapsed .silkroad-dock-theme {
                display: none !important;
            }
            .silkroad-dock-handle {
                width: 36px !important;
                height: 36px !important;
                border-radius: 50% !important;
                background-color: rgba(255, 255, 255, 0.1) !important;
                cursor: pointer !important;
                display: flex !important;
                justify-content: center !important;
                align-items: center !important;
                transition: all 0.3s ease !important;
                margin-left: 10px !important;
            }
            .silkroad-dock.collapsed .silkroad-dock-handle {
                margin: 0 !important;
                width: 26px !important;
                height: 26px !important;
            }
            .silkroad-dock-handle:hover {
                background-color: rgba(255, 255, 255, 0.2) !important;
            }
            .silkroad-dock-handle svg {
                width: 18px !important;
                height: 18px !important;
                fill: white !important;
                transition: transform 0.3s ease !important;
                transform: rotate(180deg) !important;
            }
            .silkroad-dock.collapsed .silkroad-dock-handle svg {
                transform: rotate(0deg) !important;
            }
            .silkroad-dock-buttons {
                display: flex !important;
                gap: 10px !important;
            }
            .silkroad-dock-button {
                background-color: transparent !important;
                border: none !important;
                color: white !important;
                width: 36px !important;
                height: 36px !important;
                border-radius: 50% !important;
                cursor: pointer !important;
                transition: all 0.2s !important;
                display: flex !important;
                justify-content: center !important;
                align-items: center !important;
            }
            .silkroad-dock-button:hover {
                background-color: rgba(255, 255, 255, 0.15) !important;
                transform: translateY(-3px) !important;
            }
            .silkroad-dock-button svg {
                width: 18px !important;
                height: 18px !important;
                fill: white !important;
            }
            .silkroad-dock-clear {
                background-color: transparent !important;
                border: none !important;
                color: white !important;
                width: 36px !important;
                height: 36px !important;
                border-radius: 50% !important;
                cursor: pointer !important;
                transition: all 0.2s !important;
                display: flex !important;
                justify-content: center !important;
                align-items: center !important;
                margin-left: 10px !important;
            }
            .silkroad-dock-clear:hover {
                background-color: rgba(255, 255, 255, 0.15) !important;
                transform: translateY(-3px) !important;
            }
            .silkroad-dock-clear svg {
                width: 18px !important;
                height: 18px !important;
                fill: white !important;
            }
            .silkroad-dock-url {
                flex-grow: 1 !important;
                margin: 0 0 0 15px !important;
                white-space: nowrap !important;
                overflow: hidden !important;
                text-overflow: ellipsis !important;
                font-size: 13px !important;
                opacity: 0.9 !important;
                background-color: rgba(255, 255, 255, 0.1) !important;
                padding: 6px 12px !important;
                border-radius: 20px !important;
                max-width: 300px !important;
                cursor: pointer !important;
                transition: all 0.2s !important;
                display: flex !important;
                align-items: center !important;
                gap: 8px !important;
            }
            .silkroad-dock-url:hover {
                background-color: rgba(255, 255, 255, 0.2) !important;
            }
            .silkroad-dock-url-input {
                flex-grow: 1 !important;
                background: transparent !important;
                border: none !important;
                outline: none !important;
                color: inherit !important;
                font-size: 13px !important;
                font-family: inherit !important;
                min-width: 0 !important;
                text-align: center !important;
            }
            .silkroad-dock-url-input.text-left {
                text-align: left !important;
            }
            .silkroad-dock-url-input::placeholder {
                color: rgba(255, 255, 255, 0.5) !important;
            }
            .silkroad-dock-go {
                background-color: transparent !important;
                border: none !important;
                color: white !important;
                width: 24px !important;
                height: 24px !important;
                border-radius: 50% !important;
                cursor: pointer !important;
                transition: all 0.2s !important;
                display: flex !important;
                justify-content: center !important;
                align-items: center !important;
                flex-shrink: 0 !important;
            }
            .silkroad-dock-go:hover {
                background-color: rgba(255, 255, 255, 0.15) !important;
                transform: translateY(-2px) !important;
            }
            .silkroad-dock-go svg {
                width: 14px !important;
                height: 14px !important;
                fill: white !important;
            }
            .silkroad-dock-go.loading svg {
                animation: spin 1s linear infinite !important;
            }
            @keyframes spin {
                from { transform: rotate(0deg); }
                to { transform: rotate(360deg); }
            }
            .silkroad-notification {
                position: fixed !important;
                top: 50% !important;
                left: 50% !important;
                transform: translate(-50%, -50%) !important;
                background-color: rgba(40, 44, 52, 0.95) !important;
                color: white !important;
                padding: 10px 20px !important;
                border-radius: 20px !important;
                font-size: 14px !important;
                box-shadow: 0 5px 25px rgba(0, 0, 0, 0.25) !important;
                z-index: 9998 !important;
                opacity: 0 !important;
                transition: all 0.3s ease !important;
                pointer-events: none !important;
                display: flex !important;
                align-items: center !important;
            }
            .silkroad-notification.show {
                opacity: 1 !important;
            }
            .silkroad-notification-icon {
                margin-right: 10px !important;
                width: 20px !important;
                height: 20px !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
            }
            .silkroad-notification-icon svg {
                width: 20px !important;
                height: 20px !important;
                fill: #4CAF50 !important;
            }
        `;
        document.head.appendChild(style);
        
        // 创建dock栏
        const dock = document.createElement('div');
        dock.className = 'silkroad-dock';
        
        // 检查并应用保存的主题设置
        try {
            const savedTheme = localStorage.getItem('silkroad-theme') || 'dark'; // 默认夜间模式
            if (savedTheme === 'light') {
                document.body.classList.add('light-mode');
            } else {
                document.body.classList.add('dark-mode'); // 默认夜间模式
            }
        } catch (e) {
            console.error('读取主题设置失败:', e);
            document.body.classList.add('dark-mode'); // 出错时默认使用夜间模式
        }
        
        // 创建通知元素
        const notification = document.createElement('div');
        notification.className = 'silkroad-notification';
        notification.innerHTML = `
            <span>链接已复制到剪贴板</span>
        `;
        
        // 创建按钮区域
        const buttons = document.createElement('div');
        buttons.className = 'silkroad-dock-buttons';

        // 返回首页按钮
        const homeBtn = document.createElement('button');
        homeBtn.className = 'silkroad-dock-button';
        homeBtn.title = '返回首页';
        homeBtn.innerHTML = `<svg viewBox="0 0 24 24"><path d="M10,20V14H14V20H19V12H22L12,3L2,12H5V20H10Z"/></svg>`;
        homeBtn.addEventListener('click', function() {
            window.stop();
            window.location.href = '/';
        });
        buttons.appendChild(homeBtn);
        
        // 返回上一页按钮
        const backBtn = document.createElement('button');
        backBtn.className = 'silkroad-dock-button';
        backBtn.title = '返回上一页';
        backBtn.innerHTML = `<svg viewBox="0 0 24 24"><path d="M20,11V13H8L13.5,18.5L12.08,19.92L4.16,12L12.08,4.08L13.5,5.5L8,11H20Z"/></svg>`;
        backBtn.addEventListener('click', function() {
            window.stop();
            window.history.back();
        });
        buttons.appendChild(backBtn);
        
        // 刷新按钮
        const refreshBtn = document.createElement('button');
        refreshBtn.className = 'silkroad-dock-button';
        refreshBtn.title = '刷新页面';
        
        const refreshIcon = `<svg viewBox="0 0 24 24"><path d="M17.65,6.35C16.2,4.9 14.21,4 12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20C15.73,20 18.84,17.45 19.73,14H17.65C16.83,16.33 14.61,18 12,18A6,6 0 0,1 6,12A6,6 0 0,1 12,6C13.66,6 15.14,6.69 16.22,7.78L13,11H20V4L17.65,6.35Z"/></svg>`;
        const stopIcon = `<svg viewBox="0 0 24 24"><path d="M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z"/></svg>`;
        
        let isLoading = false;
        
        function setLoadingState(loading) {
            isLoading = loading;
            if (loading) {
                refreshBtn.innerHTML = stopIcon;
                refreshBtn.title = '停止加载';
            } else {
                refreshBtn.innerHTML = refreshIcon;
                refreshBtn.title = '刷新页面';
            }
        }
        
        refreshBtn.innerHTML = refreshIcon;
        
        refreshBtn.addEventListener('click', function() {
            if (isLoading) {
                window.stop();
                setLoadingState(false);
            } else {
                setLoadingState(true);
                location.reload();
            }
        });
        buttons.appendChild(refreshBtn);
        
        dock.appendChild(buttons);
        
        // URL显示区域
        const urlDisplay = document.createElement('div');
        urlDisplay.className = 'silkroad-dock-url';
        
        // 创建输入框
        const urlInput = document.createElement('input');
        urlInput.className = 'silkroad-dock-url-input';
        urlInput.type = 'text';
        urlInput.title = '编辑URL后按Enter或点击前往按钮';
        
        // 创建前往按钮
        const goBtn = document.createElement('button');
        goBtn.className = 'silkroad-dock-go';
        goBtn.title = '前往';
        goBtn.innerHTML = `<svg viewBox="0 0 24 24"><path d="M4,10V14H13L9.5,17.5L11.92,19.92L19.84,12L11.92,4.08L9.5,6.5L13,10H4Z"/></svg>`;
        
        // 提取并显示实际访问的URL（去除代理前缀）
        let originalUrl = '';
        try {
            const proxyUrl = window.location.href || '';
            const url = new URL(proxyUrl);
            originalUrl = url.pathname.substring(1) + url.search + url.hash;
            if (!originalUrl) {
                originalUrl = '/';
            }
        } catch (e) {
            console.error('获取URL失败:', e);
            originalUrl = window.location.href || '/';
        }
        
        urlInput.value = originalUrl;
        urlDisplay.appendChild(urlInput);
        urlDisplay.appendChild(goBtn);
        dock.appendChild(urlDisplay);
        
        // 检测输入框内容长度，决定对齐方式
        function updateInputAlignment() {
            const inputWidth = urlInput.scrollWidth;
            const containerWidth = urlInput.clientWidth;
            if (inputWidth > containerWidth) {
                urlInput.classList.add('text-left');
            } else {
                urlInput.classList.remove('text-left');
            }
        }
        
        // 页面加载状态监听
        // 初始状态：如果页面正在加载则显示叉号，否则显示刷新图标
        setLoadingState(document.readyState !== 'complete');
        
        // 监听页面加载完成
        window.addEventListener('load', function() {
            setLoadingState(false);
        });
        
        document.addEventListener('readystatechange', function() {
            if (document.readyState === 'complete') {
                setLoadingState(false);
            } else {
                setLoadingState(true);
            }
        });
        
        // 白昼/夜间模式切换按钮 - 放在URL容器右侧，扫把按钮左侧
        const themeToggleBtn = document.createElement('button');
        themeToggleBtn.className = 'silkroad-dock-theme';
        themeToggleBtn.title = '切换白昼/夜间模式';
        // 默认显示月亮图标（表示当前是夜间模式，点击后切换到白昼模式）
        themeToggleBtn.innerHTML = `<svg viewBox="0 0 24 24"><path d="M17.75,4.09L15.22,6.03L16.13,9.09L13.5,7.28L10.87,9.09L11.78,6.03L9.25,4.09L12.44,4L13.5,1L14.56,4L17.75,4.09M21.25,11L19.61,12.25L20.2,14.23L18.5,13.06L16.8,14.23L17.39,12.25L15.75,11L17.81,10.95L18.5,9L19.19,10.95L21.25,11M18.97,15.95C19.8,15.87 20.69,17.05 20.16,17.8C19.84,18.25 19.5,18.67 19.08,19.07C15.17,23 8.84,23 4.94,19.07C1.03,15.17 1.03,8.83 4.94,4.93C5.34,4.53 5.76,4.17 6.21,3.85C6.96,3.32 8.14,4.21 8.06,5.04C7.79,7.9 8.75,10.87 10.95,13.06C13.14,15.26 16.1,16.22 18.97,15.95M17.33,17.97C14.5,17.81 11.7,16.64 9.53,14.5C7.36,12.31 6.2,9.5 6.04,6.68C3.23,9.82 3.34,14.64 6.35,17.66C9.37,20.67 14.19,20.78 17.33,17.97Z"></path></svg>`;
        
        // 设置默认为夜间模式（不添加类，因为默认就是夜间模式）
        
        // 添加点击事件
        themeToggleBtn.addEventListener('click', function() {
            // 切换dock栏的类名
            if (dock.classList.contains('light-mode')) {
                // 切换到夜间模式
                dock.classList.remove('light-mode');
                // 更改图标为月亮（表示当前是夜间模式，点击后切换到白昼模式）
                themeToggleBtn.innerHTML = `<svg viewBox="0 0 24 24"><path d="M17.75,4.09L15.22,6.03L16.13,9.09L13.5,7.28L10.87,9.09L11.78,6.03L9.25,4.09L12.44,4L13.5,1L14.56,4L17.75,4.09M21.25,11L19.61,12.25L20.2,14.23L18.5,13.06L16.8,14.23L17.39,12.25L15.75,11L17.81,10.95L18.5,9L19.19,10.95L21.25,11M18.97,15.95C19.8,15.87 20.69,17.05 20.16,17.8C19.84,18.25 19.5,18.67 19.08,19.07C15.17,23 8.84,23 4.94,19.07C1.03,15.17 1.03,8.83 4.94,4.93C5.34,4.53 5.76,4.17 6.21,3.85C6.96,3.32 8.14,4.21 8.06,5.04C7.79,7.9 8.75,10.87 10.95,13.06C13.14,15.26 16.1,16.22 18.97,15.95M17.33,17.97C14.5,17.81 11.7,16.64 9.53,14.5C7.36,12.31 6.2,9.5 6.04,6.68C3.23,9.82 3.34,14.64 6.35,17.66C9.37,20.67 14.19,20.78 17.33,17.97Z"></path></svg>`;
                
                // 显示通知
                const themeNotification = notification.cloneNode(true);
                themeNotification.innerHTML = `<span>已切换到夜间模式</span>`;
                document.body.appendChild(themeNotification);
                setTimeout(function() {
                    themeNotification.classList.add('show');
                    setTimeout(function() {
                        themeNotification.classList.remove('show');
                        setTimeout(function() {
                            if (themeNotification.parentNode) {
                                themeNotification.parentNode.removeChild(themeNotification);
                            }
                        }, 300);
                    }, 2000);
                }, 10);
            } else {
                // 切换到白昼模式
                dock.classList.add('light-mode');
                // 更改图标为太阳（表示当前是白昼模式，点击后切换到夜间模式）
                themeToggleBtn.innerHTML = `<svg viewBox="0 0 24 24"><path d="M12,7A5,5 0 0,1 17,12A5,5 0 0,1 12,17A5,5 0 0,1 7,12A5,5 0 0,1 12,7M12,9A3,3 0 0,0 9,12A3,3 0 0,0 12,15A3,3 0 0,0 15,12A3,3 0 0,0 12,9M12,2L14.39,5.42C13.65,5.15 12.84,5 12,5C11.16,5 10.35,5.15 9.61,5.42L12,2M3.34,7L7.5,6.65C6.9,7.16 6.36,7.78 5.94,8.5C5.5,9.24 5.25,10 5.11,10.79L3.34,7M3.36,17L5.12,13.23C5.26,14 5.53,14.78 5.95,15.5C6.37,16.24 6.91,16.86 7.5,17.37L3.36,17M20.65,7L18.88,10.79C18.74,10 18.47,9.23 18.05,8.5C17.63,7.78 17.1,7.15 16.5,6.64L20.65,7M20.64,17L16.5,17.36C17.09,16.85 17.62,16.22 18.04,15.5C18.46,14.77 18.73,14 18.87,13.21L20.64,17M12,22L9.59,18.56C10.33,18.83 11.14,19 12,19C12.82,19 13.63,18.83 14.37,18.56L12,22Z"></path></svg>`;
                
                // 显示通知
                const themeNotification = notification.cloneNode(true);
                themeNotification.innerHTML = `<span>已切换到白昼模式</span>`;
                document.body.appendChild(themeNotification);
                setTimeout(function() {
                    themeNotification.classList.add('show');
                    setTimeout(function() {
                        themeNotification.classList.remove('show');
                        setTimeout(function() {
                            if (themeNotification.parentNode) {
                                themeNotification.parentNode.removeChild(themeNotification);
                            }
                        }, 300);
                    }, 2000);
                }, 10);
            }
            
            // 保存用户偏好到localStorage
            try {
                localStorage.setItem('silkroad-dock-theme', dock.classList.contains('light-mode') ? 'light' : 'dark');
            } catch (e) {
                console.error('保存主题偏好失败:', e);
            }
        });
        
        dock.appendChild(themeToggleBtn);

        // 清除缓存按钮（扫把）- 放在URL容器右侧
        const clearCacheBtn = document.createElement('button'); // 修正拼写错误：buttom -> button
        clearCacheBtn.className = 'silkroad-dock-clear'; 
        clearCacheBtn.title = '清除该网站缓存';
        clearCacheBtn.innerHTML = `<svg viewBox="0 0 24 24"><path d="M19.36,2.72L20.78,4.14L15.06,9.85C16.13,11.39 16.28,13.24 15.38,14.44L9.06,8.12C10.26,7.22 12.11,7.37 13.65,8.44L19.36,2.72M5.93,17.57C3.92,15.56 2.69,13.16 2.35,10.92L7.23,8.83L14.67,16.27L12.58,21.15C10.34,20.81 7.94,19.58 5.93,17.57Z"/></svg>`;
        
        // 添加点击事件
        clearCacheBtn.addEventListener('click', function() {
            // 清除localStorage
            try {
                localStorage.clear();
            } catch (e) {
                console.error('清除localStorage失败:', e);
            }
            
            // 清除sessionStorage
            try {
                sessionStorage.clear();
            } catch (e) {
                console.error('清除sessionStorage失败:', e);
            }
            
            // 清除所有cookie
            try {
                const cookies = document.cookie.split(";");
                for (let i = 0; i < cookies.length; i++) {
                    const cookie = cookies[i];
                    const eqPos = cookie.indexOf("=");
                    const name = eqPos > -1 ? cookie.substr(0, eqPos).trim() : cookie.trim();
                    document.cookie = name + "=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/";
                    // 尝试为域名添加cookie
                    const domain = window.location.hostname;
                    document.cookie = name + "=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;domain=" + domain;
                }
            } catch (e) {
                console.error('清除cookie失败:', e);
            }
            
            // 清除缓存（通过重新加载并跳过缓存）
            // 创建通知元素的副本
            const cacheNotification = notification.cloneNode(true);
            cacheNotification.innerHTML = `<span>已清除该网站缓存</span>`;
            
            // 显示通知
            document.body.appendChild(cacheNotification);
            setTimeout(function() {
                cacheNotification.classList.add('show');
                
                // 2秒后隐藏通知并重新加载页面
                setTimeout(function() {
                    cacheNotification.classList.remove('show');
                    
                    // 动画完成后移除通知元素并刷新页面
                    setTimeout(function() {
                        if (cacheNotification.parentNode) {
                            cacheNotification.parentNode.removeChild(cacheNotification);
                        }
                        // 强制刷新页面（跳过缓存）
                        window.location.reload(true);
                    }, 300);
                }, 2000);
            }, 10);
        });
        
        dock.appendChild(clearCacheBtn);
        
        // 创建折叠把手
        const handle = document.createElement('div');
        handle.className = 'silkroad-dock-handle';
        handle.innerHTML = `<svg viewBox="0 0 24 24"><path d="M7.41,15.41L12,10.83L16.59,15.41L18,14L12,8L6,14L7.41,15.41Z"/></svg>`;
        dock.appendChild(handle);
        
        // 导航函数
        function navigateToUrl() {
            let inputValue = urlInput.value.trim();
            if (!inputValue) {
                return;
            }
            inputValue = inputValue.replace(/^\//, '');
            setLoadingState(true);
            window.location.href = '/' + inputValue;
        }
        
        // 输入框事件：更新对齐方式
        urlInput.addEventListener('input', function() {
            setTimeout(updateInputAlignment, 0);
        });
        
        // 输入框事件：按 Enter 键导航
        urlInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                navigateToUrl();
            }
        });
        
        // 前往按钮点击事件
        goBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            navigateToUrl();
        });
        
        // 添加到页面
        document.body.appendChild(dock);
        
        // 折叠/展开功能
        handle.addEventListener('click', function() {
            dock.classList.toggle('collapsed');
            // 保存状态到localStorage
            localStorage.setItem('silkroadDockCollapsed', dock.classList.contains('collapsed'));
        });
        
        // 恢复上次的折叠状态
        if (localStorage.getItem('silkroadDockCollapsed') === 'true') {
            dock.classList.add('collapsed');
        }
    });
})();
