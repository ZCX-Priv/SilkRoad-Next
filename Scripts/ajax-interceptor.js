(function() {
    const PROXY_ORIGIN = window.location.origin;
    
    function isProxyUrl(url) {
        if (!url) return false;
        if (url.startsWith('/') && !url.startsWith('//')) {
            const pathPart = url.split('?')[0].split('#')[0];
            const segments = pathPart.split('/').filter(Boolean);
            if (segments.length > 0) {
                const firstSegment = segments[0];
                if (firstSegment.includes('.') || 
                    firstSegment === 'localhost' ||
                    firstSegment.match(/^[\w.-]+:\d+$/)) {
                    return true;
                }
            }
        }
        return false;
    }
    
    function toProxyUrl(url) {
        if (!url) return url;
        
        url = url.trim();
        
        if (url.startsWith('data:') || 
            url.startsWith('blob:') || 
            url.startsWith('javascript:') ||
            url.startsWith('about:')) {
            return url;
        }
        
        if (isProxyUrl(url)) {
            return url;
        }
        
        if (url.startsWith('//')) {
            url = window.location.protocol + url;
        }
        
        if (url.startsWith('/')) {
            const currentPath = window.location.pathname;
            const segments = currentPath.split('/').filter(Boolean);
            if (segments.length > 0) {
                const domain = segments[0];
                return '/' + domain + url;
            }
            return url;
        }
        
        if (url.startsWith('http://') || url.startsWith('https://')) {
            try {
                const urlObj = new URL(url);
                let proxyUrl = '/' + urlObj.host + urlObj.pathname;
                if (urlObj.search) proxyUrl += urlObj.search;
                if (urlObj.hash) proxyUrl += urlObj.hash;
                return proxyUrl;
            } catch (e) {
                return url;
            }
        }
        
        return url;
    }
    
    const originalXhrOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(method, url, async, user, password) {
        const proxyUrl = toProxyUrl(url);
        return originalXhrOpen.call(this, method, proxyUrl, async !== false, user, password);
    };
    
    const originalFetch = window.fetch;
    if (originalFetch) {
        window.fetch = function(input, init) {
            let url;
            if (typeof input === 'string') {
                url = toProxyUrl(input);
                return originalFetch.call(this, url, init);
            } else if (input instanceof Request) {
                url = toProxyUrl(input.url);
                const newRequest = new Request(url, {
                    method: input.method,
                    headers: input.headers,
                    body: input.body,
                    mode: input.mode,
                    credentials: input.credentials,
                    cache: input.cache,
                    redirect: input.redirect,
                    referrer: input.referrer,
                    referrerPolicy: input.referrerPolicy,
                    integrity: input.integrity,
                    keepalive: input.keepalive,
                    signal: input.signal
                });
                return originalFetch.call(this, newRequest, init);
            } else if (input instanceof URL) {
                url = toProxyUrl(input.href);
                return originalFetch.call(this, url, init);
            }
            return originalFetch.call(this, input, init);
        };
    }
    
    if (window.jQuery) {
        const originalAjax = jQuery.ajax;
        jQuery.ajax = function(url, options) {
            if (typeof url === 'string') {
                url = toProxyUrl(url);
                return originalAjax.call(this, url, options);
            } else if (typeof url === 'object') {
                url.url = toProxyUrl(url.url);
                return originalAjax.call(this, url);
            }
            return originalAjax.apply(this, arguments);
        };
    }
    
    const originalOpen = window.open;
    if (originalOpen) {
        window.open = function(url, target, features) {
            url = toProxyUrl(url);
            return originalOpen.call(this, url, target, features);
        };
    }
    
    console.log('[SilkRoad] AJAX interceptor loaded');
})();
