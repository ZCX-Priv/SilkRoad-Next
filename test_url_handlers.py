"""
URL修正引擎测试脚本
"""
import asyncio
from modules.url import HTMLHandler, CSSHandler, JSHandler, LocationHandler


async def test_html_handler():
    """测试HTML处理器"""
    print("=" * 50)
    print("测试 HTML 处理器")
    print("=" * 50)

    handler = HTMLHandler()

    # 测试1: 绝对URL
    html = '<a href="https://example.com/page">Link</a>'
    result = await handler.rewrite(html, 'https://test.com', {})
    print(f"测试1 - 绝对URL:")
    print(f"  输入: {html}")
    print(f"  输出: {result}")
    print()

    # 测试2: 相对URL
    html = '<img src="/images/logo.png">'
    result = await handler.rewrite(html, 'https://example.com', {})
    print(f"测试2 - 相对URL:")
    print(f"  输入: {html}")
    print(f"  输出: {result}")
    print()

    # 测试3: srcset属性
    html = '<img srcset="img.jpg 1x, img@2x.jpg 2x">'
    result = await handler.rewrite(html, 'https://example.com', {})
    print(f"测试3 - srcset属性:")
    print(f"  输入: {html}")
    print(f"  输出: {result}")
    print()

    # 测试4: 内联样式
    html = '<div style="background: url(https://example.com/bg.jpg);"></div>'
    result = await handler.rewrite(html, 'https://test.com', {})
    print(f"测试4 - 内联样式:")
    print(f"  输入: {html}")
    print(f"  输出: {result}")
    print()

    # 测试5: 特殊协议（不应修改）
    html = '<a href="javascript:void(0)">Click</a>'
    result = await handler.rewrite(html, 'https://example.com', {})
    print(f"测试5 - 特殊协议:")
    print(f"  输入: {html}")
    print(f"  输出: {result}")
    print()


async def test_css_handler():
    """测试CSS处理器"""
    print("=" * 50)
    print("测试 CSS 处理器")
    print("=" * 50)

    handler = CSSHandler()

    # 测试1: url()函数
    css = 'body { background: url("https://example.com/bg.jpg"); }'
    result = await handler.rewrite(css, 'https://test.com', {})
    print(f"测试1 - url()函数:")
    print(f"  输入: {css}")
    print(f"  输出: {result}")
    print()

    # 测试2: @import语句
    css = '@import "https://example.com/styles.css";'
    result = await handler.rewrite(css, 'https://test.com', {})
    print(f"测试2 - @import语句:")
    print(f"  输入: {css}")
    print(f"  输出: {result}")
    print()


async def test_js_handler():
    """测试JavaScript处理器"""
    print("=" * 50)
    print("测试 JavaScript 处理器")
    print("=" * 50)

    handler = JSHandler()

    # 测试1: 字符串中的URL
    js = 'var url = "https://example.com/api/data";'
    result = await handler.rewrite(js, 'https://test.com', {})
    print(f"测试1 - 字符串中的URL:")
    print(f"  输入: {js}")
    print(f"  输出: {result}")
    print()


async def test_location_handler():
    """测试Location处理器"""
    print("=" * 50)
    print("测试 Location 处理器")
    print("=" * 50)

    handler = LocationHandler()

    # 测试1: 绝对URL
    location = 'https://example.com/redirect'
    result = handler.rewrite(location, 'https://test.com')
    print(f"测试1 - 绝对URL:")
    print(f"  输入: {location}")
    print(f"  输出: {result}")
    print()

    # 测试2: 相对URL
    location = '/login'
    result = handler.rewrite(location, 'https://example.com/page')
    print(f"测试2 - 相对URL:")
    print(f"  输入: {location}")
    print(f"  输出: {result}")
    print()


async def main():
    """主测试函数"""
    print("\n" + "=" * 50)
    print("URL修正引擎功能测试")
    print("=" * 50 + "\n")

    await test_html_handler()
    await test_css_handler()
    await test_js_handler()
    await test_location_handler()

    print("=" * 50)
    print("所有测试完成！")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
