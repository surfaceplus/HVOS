"""hiugift.com 产品成本调研"""
import paramiko, json

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('89.117.22.200', username='root', password='QQ33945551', timeout=20)

def ssh(cmd):
    stdin, stdout, stderr = client.exec_command(cmd)
    stdin.close()
    return stdout.read().decode('utf-8', errors='replace')

def mysql(q):
    return ssh(f"mysql -u sql_hiugift_com -p'd441c6b635d2e8' sql_hiugift_com -e \"{q}\" 2>&1")

# WooCommerce 产品成本/售价/利润率
print("=== hiugift.com 产品完整成本结构 ===")
q = (
    "SELECT p.ID, p.post_title AS product_name,"
    "pm1.meta_value AS price,"
    "pm2.meta_value AS cost,"
    "pm3.meta_value AS regular_price "
    "FROM wp_0dd69b_posts p "
    "LEFT JOIN wp_0dd69b_postmeta pm1 ON p.ID=pm1.post_id AND pm1.meta_key='_price' "
    "LEFT JOIN wp_0dd69b_postmeta pm2 ON p.ID=pm2.post_id AND pm2.meta_key='_wc_custom_concat_cebob' "  # 成本字段
    "LEFT JOIN wp_0dd69b_postmeta pm3 ON p.ID=pm3.post_id AND pm3.meta_key='_regular_price' "
    "WHERE p.post_type='product' AND p.post_status='publish' "
    "ORDER BY p.post_title"
)
r = mysql(q)
print(r[:3000])
client.close()
