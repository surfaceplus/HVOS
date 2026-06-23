#!/usr/bin/env python3
"""WooCommerce Payment Fixer — 用 pymysql 直连 MySQL"""
import pymysql, re

def main():
    print("=== 连接 MySQL ===")
    conn = pymysql.connect(
        host='localhost',
        user='sql_hiugift_com',
        password='d441c6b635d2e8',
        database='sql_hiugift_com',
        cursorclass=pymysql.cursors.DictCursor
    )
    cur = conn.cursor()

    # 1. PayPal
    print("\n[1/3] PayPal 设置...")
    cur.execute("SELECT option_value FROM wp_0dd69b_options WHERE option_name='woocommerce_paypal_settings'")
    row = cur.fetchone()
    if not row:
        print("  PayPal: 选项不存在")
    else:
        val = row['option_value']
        m = re.search(r's:7:"enabled";s:(\d+):"([^"]+)"', val)
        current = m.group(2) if m else '?'
        print(f"  当前: enabled={current}")
        if val == 'test_enabled_yes' or current == 'no':
            PAYPAL = r'''a:25:{s:7:"enabled";s:3:"yes";s:5:"title";s:6:"PayPal";s:11:"description";s:85:"Pay via PayPal; you can pay with your credit card if you don't have a PayPal account.";s:5:"email";s:17:"admin@hiugift.com";s:8:"advanced";s:0:"";s:8:"testmode";s:2:"no";s:13:"paymentaction";s:4:"sale";s:14:"paypal_buttons";s:3:"yes";s:14:"invoice_prefix";s:3:"WC-";s:13:"send_shipping";s:3:"yes";s:16:"address_override";s:2:"no";s:5:"debug";s:2:"no";s:9:"image_url";s:0:"";s:16:"ipn_notification";s:3:"yes";s:14:"receiver_email";s:17:"admin@hiugift.com";s:14:"identity_token";s:0:"";s:11:"api_details";s:0:"";s:12:"api_username";s:0:"";s:12:"api_password";s:0:"";s:13:"api_signature";s:0:"";s:20:"sandbox_api_username";s:0:"";s:20:"sandbox_api_password";s:0:"";s:21:"sandbox_api_signature";s:0:"";s:28:"transact_onboarding_complete";s:2:"no";s:12:"_should_load";s:2:"no";}'''
            cur.execute("UPDATE wp_0dd69b_options SET option_value=%s WHERE option_name='woocommerce_paypal_settings'", (PAYPAL,))
            conn.commit()
            print(f"  ✅ PayPal 已修复 (受影响的行: {cur.rowcount})")
        else:
            print(f"  ✅ PayPal 已启用，无需修改")

    # 2. COD
    print("\n[2/3] COD 设置...")
    cur.execute("SELECT option_value FROM wp_0dd69b_options WHERE option_name='woocommerce_cod_settings'")
    cod = cur.fetchone()
    if cod:
        m = re.search(r's:7:"enabled";s:(\d+):"([^"]+)"', cod['option_value'])
        print(f"  COD enabled={m.group(2) if m else '?'}")
    else:
        print("  COD: 未配置（需在 WooCommerce 设置中启用）")

    # 3. BACS
    print("\n[3/3] BACS 设置...")
    cur.execute("SELECT option_value FROM wp_0dd69b_options WHERE option_name='woocommerce_bacs_settings'")
    bacs = cur.fetchone()
    if bacs:
        m = re.search(r's:7:"enabled";s:(\d+):"([^"]+)"', bacs['option_value'])
        print(f"  BACS enabled={m.group(2) if m else '?'}")
    else:
        print("  BACS: 未配置")

    conn.close()
    print("\n✅ 全部完成")

if __name__ == '__main__':
    main()
