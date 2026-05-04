/**
 * 同页面链接转换器
 * 将所有新标签页打开的链接改为在同一页面打开
 */

(function() {
    function normalizeProxyHref(href) {
        if (!href) return href;

        const trimmedHref = href.trim();
        if (!trimmedHref) return trimmedHref;

        if (
            trimmedHref.startsWith('javascript:') ||
            trimmedHref.startsWith('data:') ||
            trimmedHref.startsWith('blob:') ||
            trimmedHref.startsWith('mailto:') ||
            trimmedHref.startsWith('tel:') ||
            trimmedHref.startsWith('#')
        ) {
            return trimmedHref;
        }

        const embeddedAbsoluteUrlMatch = trimmedHref.match(/^\/[^/]+\/(https?:\/\/.+)$/i);
        if (embeddedAbsoluteUrlMatch) {
            return normalizeProxyHref(embeddedAbsoluteUrlMatch[1]);
        }

        const leadingSlashAbsoluteUrlMatch = trimmedHref.match(/^\/(https?:\/\/.+)$/i);
        if (leadingSlashAbsoluteUrlMatch) {
            return normalizeProxyHref(leadingSlashAbsoluteUrlMatch[1]);
        }

        let absoluteUrl = trimmedHref;
        if (trimmedHref.startsWith('//')) {
            absoluteUrl = window.location.protocol + trimmedHref;
        }

        if (absoluteUrl.startsWith('http://') || absoluteUrl.startsWith('https://')) {
            try {
                const parsedUrl = new URL(absoluteUrl);
                return `/${parsedUrl.host}${parsedUrl.pathname}${parsedUrl.search}${parsedUrl.hash}`;
            } catch (error) {
                return trimmedHref;
            }
        }

        return trimmedHref;
    }

    // 主函数：处理所有链接
    function convertAllLinks() {
        // 获取页面上所有链接
        const links = document.querySelectorAll('a[href]');
        let convertedCount = 0;
        let normalizedCount = 0;
        
        // 遍历所有链接并修改其target属性
        links.forEach(link => {
            const originalHref = link.getAttribute('href');
            const normalizedHref = normalizeProxyHref(originalHref);
            if (normalizedHref && normalizedHref !== originalHref) {
                link.setAttribute('href', normalizedHref);
                link.dataset.normalizedProxyLink = 'true';
                normalizedCount++;
            }

            if (link.getAttribute('target') === '_blank') {
                link.setAttribute('target', '_self');

                // 可选：添加视觉指示器，表明链接已被修改
                link.style.borderBottom = '1px dotted #0066cc';

                // 添加自定义数据属性，标记已处理过的链接
                link.dataset.convertedLink = 'true';
                convertedCount++;
            }
        });
        
        console.log(`已修正${normalizedCount}个异常链接，已将${convertedCount}个新标签页链接转换为同页面打开`);
    }
    
    // 初始转换现有链接
    convertAllLinks();
    
    // 监听DOM变化，处理动态加载的内容
    const observer = new MutationObserver(mutations => {
        let hasNewLinks = false;
        
        // 检查是否有新链接被添加
        mutations.forEach(mutation => {
            if (mutation.addedNodes.length) {
                hasNewLinks = true;
            }
        });
        
        // 如果有新链接，重新运行转换
        if (hasNewLinks) {
            convertAllLinks();
        }
    });
    
    // 配置观察器
    observer.observe(document.body, {
        childList: true,
        subtree: true
    });
    
    // 返回公共API
    return {
        convertLinks: convertAllLinks,
        stopObserving: () => observer.disconnect()
    };
})();