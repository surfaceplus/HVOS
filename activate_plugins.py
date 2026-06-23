#!/usr/bin/env python3
"""激活 WooCommerce Stripe + Facebook Pixel 插件"""
import pymysql, re

def unserialize_array(serialized):
    """从序列化字符串提取 active_plugins"""
    m = re.search(r'a:(\d+):\{(.+?)\}', serialized)
    if not m: return []
    count, content = int(m.group(1)), m.group(2)
    plugins = re.findall(r'i:\d+;s:\d+:\"([^\"]+)\"', content)
    return plugins

def serialize_array(arr):
    items = []
    for i, p in enumerate(arr):
        items.append(f'i:{i};s:{len(p)}:"{p}"')
    return 'a:' + str(len(arr)) + ':{' + ';'.join(items) + '}'

def main():
    conn = pymysql.connect(
        host='localhost', user='sql_hiugift_com',
        password='d441c6b635d2e8', database='sql_hiugift_com',
        cursorclass=pymysql.cursors.DictCursor
    )
    cur = conn.cursor()

    # 读取 active_plugins
    cur.execute("SELECT option_value FROM wp_0dd69b_options WHERE option_name='active_plugins'")
    row = cur.fetchone()
    if not row:
        print("active_plugins 不存在，初始化")
        current = []
    else:
        current = unserialize_array(row['option_value'])

    NEW_PLUGINS = [
        'woocommerce-gateway-stripe/woocommerce-gateway-stripe.php',
        'facebook-for-woocommerce/facebook-for-woocommerce.php',
    ]

    added = [p for p in NEW_PLUGINS if p not in current]
    if added:
        new_list = current + added
        new_serialized = serialize_array(new_list)
        cur.execute(
            "UPDATE wp_0dd69b_options SET option_value=%s WHERE option_name='active_plugins'",
            (new_serialized,)
        )
        conn.commit()
        print(f"✅ 已添加插件: {added}")
        print(f"   当前激活: {new_list}")
    else:
        print(f"✅ 插件已存在: {current}")

    # 添加 Stripe 默认设置（空配置，用户需填入 API key）
    cur.execute("SELECT option_value FROM wp_0dd69b_options WHERE option_name='woocommerce_stripe_settings'")
    if not cur.fetchone():
        stripe_settings = 'a:5:{s:7:"enabled";s:2:"no";s:5:"title";s:6:"Stripe";s:11:"description";s:26:"通过信用卡付款";s:8:"testmode";s:2:"no";s:4:"keys";a:3:{s:5:"test";a:3:{s:4:"pk_k";s:0:"";s:4:"sk_k";s:0:"";s:5:"sk_s3";s:0:"";}s:3:"liv";a:3:{s:4:"pk_k";s:0:"";s:4:"sk_k";s:0:"";s:5:"sk_s3";s:0:"";}}}'
        cur.execute(
            "INSERT INTO wp_0dd69b_options (option_name, option_value, autoload) VALUES ('woocommerce_stripe_settings', %s, 'yes')",
            (stripe_settings,)
        )
        conn.commit()
        print("✅ Stripe 默认设置已创建（需在 WooCommerce 设置中填入 API Key）")
    else:
        print("✅ Stripe settings 已存在")

    # 添加 Facebook Pixel 默认设置
    cur.execute("SELECT option_value FROM wp_0dd69b_options WHERE option_name='woocommerce_facebook_pixel_settings'")
    if not cur.fetchone():
        fb_settings = 'a:3:{s:7:"enabled";s:2:"no";s:5:"pixel";s:0:"";s:10:"api_key_id";s:0:"";}'
        cur.execute(
            "INSERT INTO wp_0dd69b_options (option_name, option_value, autoload) VALUES ('woocommerce_facebook_pixel_settings', %s, 'yes')",
            (fb_settings,)
        )
        conn.commit()
        print("✅ Facebook Pixel 设置已创建（需在 WooCommerce 设置中填入 Pixel ID）")
    else:
        print("✅ Facebook Pixel settings 已存在")

    conn.close()
    print("\n🎉 插件安装完成！请在 WordPress 后台激活并配置")

if __name__ == '__main__':
    main()
