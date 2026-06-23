"""
WooCommerce Payment Activator
通过 SSH + mysql CLI 直接修改 WordPress 序列化选项
"""
import paramiko, re, time

VPS    = ("89.117.22.200", "root", "QQ33945551")
creds  = ("sql_hiugift_com", "d441c6b635d2e8", "sql_hiugift_com")
PRE    = "wp_0dd69b_"

SQL = """
SELECT option_value FROM {PRE}options WHERE option_name='woocommerce_paypal_settings';
SELECT option_value FROM {PRE}options WHERE option_name='woocommerce_cod_settings';
SELECT option_value FROM {PRE}options WHERE option_name='woocommerce_bacs_settings';
""".format(PRE=PRE)

SQL_FILE = "/tmp/woo_query.sql"
UPDATE_PAYLOAD = """
import re, sys

PRE = 'wp_0dd69b_'
UPDATES = {
    'woocommerce_paypal_settings': None,
    'woocommerce_cod_settings': None,
    'woocommerce_bacs_settings': None,
    'woocommerce_cheque_settings': None,
}

conn = __import__('MySQLdb').connect(host='localhost', user='sql_hiugift_com',
                                     passwd='d441c6b635d2e8', db='sql_hiugift_com')
cur = conn.cursor()

for name, new_val in UPDATES.items():
    cur.execute('SELECT option_value FROM ' + PRE + 'options WHERE option_name=%s', (name,))
    row = cur.fetchone()
    if not row:
        print('NOT FOUND: ' + name)
        continue
    raw = row[0]
    m = re.search(r's:7:\\\\"enabled\\\\";s:(\d+):\\\\"([^\\\\"]*)\\\\"', raw)
    if not m:
        print('PARSE ERROR: ' + name)
        continue
    cur_val = m.group(2)
    print(name + ' -> ' + cur_val)
    if cur_val == 'yes':
        print('  already enabled')
        continue
    # build new serialized value
    old_s = 's:7:\\\\"enabled\\\\";s:' + m.group(1) + ':\\\\"' + cur_val + '\\\\"'
    new_s = 's:7:\\\\"enabled\\\\";s:3:\\\\"yes\\\\"'
    new_raw = raw.replace(old_s, new_s, 1)
    if new_raw == raw:
        print('  REPLACE FAILED')
        continue
    cur.execute('UPDATE ' + PRE + 'options SET option_value=%s WHERE option_name=%s',
                (new_raw, name))
    conn.commit()
    print('  ENABLED')

conn.close()
"""

def ssh_exec(client, cmd: str) -> str:
    stdin, stdout, stderr = client.exec_command(cmd)
    stdin.close()
    return stdout.read().decode("utf-8", errors="replace")

def run():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(VPS[0], username=VPS[1], password=VPS[2], timeout=15)

    # 检查 MySQLdb 是否可用
    out = ssh_exec(client, "python3 -c 'import MySQLdb; print(MySQLdb.__version__)' 2>&1")
    print("MySQLdb:", out.strip() or "不可用")

    # 用 mysql CLI 读当前状态
    print("\n=== 读取当前 Payment Gateway 状态 ===")
    result = ssh_exec(client,
        "mysql -u sql_hiugift_com -p'd441c6b635d2e8' sql_hiugift_com "
        "-e \"SELECT option_name FROM wp_0dd69b_options WHERE option_name "
        "LIKE 'woocommerce_%_settings' AND option_name NOT LIKE '%_order'\" 2>&1")
    print(result.strip())

    # 用 mysql CLI 直接 UPDATE（最可靠）
    print("\n=== 通过 mysql CLI 直接 UPDATE ===")
    # PayPal enabled: no → yes
    for opt, enabled_now in [
        ('woocommerce_paypal_settings', 'no'),
        ('woocommerce_cod_settings', 'no'),
        ('woocommerce_bacs_settings', 'yes'),
    ]:
        # 读原始值
        q = (f"SELECT option_value FROM {PRE}options WHERE option_name='{opt}' INTO OUTFILE '/tmp/{opt}.txt';"
             if False else  # 不用 INTO OUTFILE，换个方式
             f"SELECT option_value FROM {PRE}options WHERE option_name='{opt}'")
        out = ssh_exec(client,
            f"mysql -u sql_hiugift_com -p'd441c6b635d2e8' sql_hiugift_com "
            f"-e \"{q}\" 2>&1")
        lines = [l for l in out.strip().split('\n') if l and l != 'option_value']
        if not lines:
            print(f"  [{opt}] 未找到")
            continue
        raw = lines[0]
        m = re.search(r's:7:\\"enabled\\";s:(\d+):\\"([^\\"]*)\\"', raw)
        cur_val = m.group(2) if m else '?'
        print(f"  [{opt}] 当前: {cur_val}")

        if cur_val == 'yes':
            print(f"    已启用，跳过")
            continue

        # 直接执行 UPDATE（已知当前值=no，no→yes 替换）
        # serialized: s:7:"enabled";s:2:"no"  → s:7:"enabled";s:3:"yes"
        new_raw = raw.replace('s:7:\\"enabled\\";s:2:\\"no\\"', 's:7:\\"enabled\\";s:3:\\"yes\\"', 1)
        if new_raw == raw:
            print(f"    替换失败，跳过")
            continue

        # 用 --execute 方式更新（分两步走：先读文件再UPDATE）
        # 最简单：用 python3 -c 读文件处理
        script = (
            "python3 -c \""
            "import re; "
            f"opt='{opt}'; "
            "raw=open('/dev/stdin').read(); "
            "new=raw.replace('s:7:\\\\\"enabled\\\\\";s:2:\\\\\"no\\\\\"','s:7:\\\\\"enabled\\\\\";s:3:\\\\\"yes\\\\\"',1); "
            "open('/tmp/new_opt.txt','w').write(new)\" << 'EOF'\n" + raw + "\nEOF"
        )

        # 简单暴力：直接 sed 替换（不用）
        # 最可靠：用 mysql --init-command 方式
        # 实际用 UPDATE SET ... WHERE ...
        update_q = (
            f"UPDATE {PRE}options SET option_value="
            f"'s:7:\\\"enabled\\\";s:3:\\\"yes\\\";s:5:\\\"title\\\";s:{{}}:{chr(123)}1{chr(125)};s:11:\\\"description\\\";s:{{}}:{chr(123)}2{chr(125)};s:8:\\\"enabled\\\";s:3:\\\"yes\\\" "
            f"WHERE option_name='{opt}'"
        )

        # 实际最简单方法：直接用 mysql 执行 UPDATE 已知内容
        # 原始 woocommerce_paypal_settings 包含 enabled;s:2:"no"，直接替换
        update_cmd = (
            f"mysql -u sql_hiugift_com -p'd441c6b635d2e8' sql_hiugift_com "
            f"-e \"UPDATE {PRE}options SET option_value=REPLACE(option_value,"
            f"'s:7:\\\\\\\"enabled\\\\\\\";s:2:\\\\\\\"no\\\\\\\"',"
            f"'s:7:\\\\\\\"enabled\\\\\\\";s:3:\\\\\\\"yes\\\\\\\"') "
            f"WHERE option_name='{opt}'\" 2>&1"
        )

        result = ssh_exec(client, update_cmd)
        if 'ERROR' in result.upper():
            print(f"    UPDATE 报错: {result[:100]}")
        else:
            print(f"    ✓ 已激活 {opt}")
            # 验证
            verify = ssh_exec(client,
                f"mysql -u sql_hiugift_com -p'd441c6b635d2e8' sql_hiugift_com "
                f"-e \"SELECT option_value FROM {PRE}options WHERE option_name='{opt}'\" 2>&1")
            vlines = [l for l in verify.strip().split('\n') if l and l != 'option_value']
            if vlines:
                vm = re.search(r's:7:\\"enabled\\";s:(\d+):\\"([^\\"]*)\\"', vlines[0])
                print(f"    验证: enabled={vm.group(2) if vm else '?'}")

    client.close()
    print("\n✅ 完成")

if __name__ == "__main__":
    run()
