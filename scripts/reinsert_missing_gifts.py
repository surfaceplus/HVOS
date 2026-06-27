"""Re-insert missing gift products (IDs 8150-8167)"""
import paramiko

VPS_HOST = "89.117.22.200"
VPS_USER = "root"
VPS_PASS = "QQ33945551"
MYSQL_USER = "sql_hiugift_com"
MYSQL_PASS = "d441c6b635d2e8"
MYSQL_DB   = "sql_hiugift_com"
PRE        = "wp_0dd69b_"
NOW        = "2026-06-27 19:00:00"

# Missing products: IDs 8150-8157 (Middle Age 33-40) and 8158-8167 (Seniors 41-50)
# Category IDs: Middle Age=76, Seniors=80
MISSING = [
    (8150, 76, "Hiugift Air Purifier for Bedroom — HEPA Filter, UV-C, Aromatherapy (60㎡ Coverage)", 99.99, "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322700.jpg", "0.8"),
    (8151, 76, "Hiugift Espresso Machine — 20 Bar Semi-Auto Espresso Maker with Milk Frother", 149.99, "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322900.jpg", "1.2"),
    (8158, 80, "Hiugift Heated Electric Blanket — Soft Flannel Electric Throw (50x60 inches, 10 Heat Settings)", 49.99, "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190323100.jpg", "0.6"),
    (8159, 80, "Hiugift Digital Blood Pressure Monitor — Upper Arm BP Machine with Large LCD & 2 Users×120 Records", 39.99, "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190321600.jpg", "0.3"),
    (8160, 80, "Hiugift Non-Slip Bath Mat — Memory Foam Bathroom Mat with Microfiber Cover (20x32 inches)", 24.99, "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190321700.jpg", "0.4"),
    (8161, 80, "Hiugift Large-Button TV Remote — Universal Remote Control for Elderly, Big Buttons, Backlit", 18.99, "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322100.jpg", "0.2"),
    (8162, 80, "Hiugift Pill Organizer with Alarm — 7-Day Large Capacity Medicine Dispenser", 22.99, "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322300.jpg", "0.3"),
    (8163, 80, "Hiugift Reading Magnifier Floor Lamp — Adjustable LED Magnifying Floor Lamp for Seniors", 64.99, "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322700.jpg", "1.5"),
    (8164, 80, "Hiugift Digital Bathroom Scale — Extra-Large Platform, High-Weight Capacity (400lbs)", 27.99, "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322900.jpg", "0.8"),
    (8165, 80, "Hiugift Aromatherapy Hand Cream Gift Set — 6-Piece Deep Moisturizing Hand Care Kit", 19.99, "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190323100.jpg", "0.3"),
    (8166, 80, "Hiugift Warm Compression Heating Pad — Auto Shut-Off Electric Heating Pad (12x24 inches)", 29.99, "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190321600.jpg", "0.5"),
    (8167, 80, "Hiugift Large Print Word Search Puzzle Books — 10-Puzzle Set, Easy-Read Font", 22.99, "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190321700.jpg", "0.6"),
]


def slugify(text):
    import re
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s]+', '-', text)
    return text[:80]


def full_desc(name, short, price, img):
    return (
        f"<p><strong>Product Name:</strong> {name}</p>"
        f"<p><strong>Short Description:</strong><br>{short}</p>"
        f"<hr><h3>Product Features</h3><p>{short}</p>"
        f"<hr><h3>Product Images</h3>"
        f'<p><img src="{img}" alt="{name}" style="max-width:100%;margin:8px 0;"></p>'
        f"<hr><p><strong>Price:</strong> ${price:.2f}</p>"
        f'<p><em>Buy now on <a href="https://hiugift.com">hiugift.com</a></em></p>'
    )


client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)

inserted = 0
for (pid, cat_id, name, price, img, weight) in MISSING:
    slug = slugify(name)
    guid = f"https://hiugift.com/?post_type=product&p={pid}"
    desc = full_desc(name, name.split(" — ")[1] if " — " in name else name, price, img)
    desc_esc = desc.replace("'", "''")
    name_esc = name.replace("'", "''")
    short_esc = name.split(" — ")[1].replace("'", "") if " — " in name else name
    short_esc = short_esc.replace("'", "''")

    post_sql = (
        f"INSERT INTO {PRE}posts "
        f"(ID, post_author, post_date, post_date_gmt, post_content, post_title, post_excerpt, "
        f"post_status, comment_status, ping_status, post_password, post_name, to_ping, pinged, "
        f"post_content_filtered, post_parent, guid, post_type, post_mime_type) "
        f"VALUES "
        f"({pid}, 1, '{NOW}', '{NOW}', '{desc_esc}', '{name_esc}', '{short_esc}', "
        f"'publish', 'open', 'open', '', '{slug}', '', '', '', 0, '{guid}', 'product', '');"
    )

    meta_sql = (
        f"INSERT INTO {PRE}postmeta (post_id, meta_key, meta_value) VALUES "
        f"({pid}, '_price', '{price}'),"
        f"({pid}, '_regular_price', '{price}'),"
        f"({pid}, '_stock_status', 'instock'),"
        f"({pid}, '_visibility', 'visible'),"
        f"({pid}, '_tax_status', 'taxable'),"
        f"({pid}, '_weight', '{weight}'),"
        f"({pid}, '_product_version', '10.8.1'),"
        f"({pid}, '_sku', 'HIU-{pid:05d}'),"
        f"({pid}, 'total_sales', '0');"
    )

    cat_sql = (
        f"INSERT INTO {PRE}term_relationships (object_id, term_taxonomy_id, term_order) "
        f"VALUES ({pid}, {cat_id}, 0);"
    )

    combined = post_sql + meta_sql + cat_sql

    stdin_c, stdout_c, stderr_c = client.exec_command(
        f"mysql -u {MYSQL_USER} -p'{MYSQL_PASS}' {MYSQL_DB} 2>&1"
    )
    stdin_c.write(combined.encode('utf-8'))
    stdin_c.channel.shutdown_write()
    out = stdout_c.read().decode('utf-8', errors='replace')
    err = stderr_c.read().decode('utf-8', errors='replace')

    if err and 'ERROR' in err.upper():
        print(f"  ❌ ID {pid}: {err[:100]}")
    else:
        print(f"  ✅ ID {pid}: {name[:50]}")
        inserted += 1

# Update category counts
upd_sql = (
    f"UPDATE {PRE}term_taxonomy tt "
    f"SET count = (SELECT COUNT(*) FROM {PRE}term_relationships WHERE term_taxonomy_id = tt.term_taxonomy_id) "
    f"WHERE EXISTS (SELECT 1 FROM {PRE}term_relationships WHERE term_taxonomy_id = tt.term_taxonomy_id);"
)
stdin_c, stdout_c, stderr_c = client.exec_command(
    f"mysql -u {MYSQL_USER} -p'{MYSQL_PASS}' {MYSQL_DB} 2>&1"
)
stdin_c.write(upd_sql.encode('utf-8'))
stdin_c.channel.shutdown_write()
stdout_c.read()
stderr_c.read()

client.close()
print(f"\nDone: {inserted}/{len(MISSING)} missing products re-inserted")
