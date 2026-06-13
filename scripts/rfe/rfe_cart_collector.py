from __future__ import annotations

import argparse
import json
import os
import re
import shlex
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import paramiko


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
DEFAULT_OUTPUT = DATA_DIR / "real_cart_events.json"

SSH_HOST = os.getenv("HVOS_RFE_SSH_HOST", "89.117.22.200")
SSH_USER = os.getenv("HVOS_RFE_SSH_USER") or os.getenv("HVOS_VPS_SSH_USER", "root")
SSH_PASSWORD = os.getenv("HVOS_RFE_SSH_PASSWORD") or os.getenv("HVOS_VPS_SSH_PASS")
SSH_KEY_PATH = os.getenv("HVOS_RFE_SSH_KEY_PATH")
SSH_PORT = int(os.getenv("HVOS_RFE_SSH_PORT", "22"))

DB_NAME = os.getenv("HVOS_RFE_DB_NAME") or os.getenv("HVOS_MYSQL_DB", "sql_hiugift_com")
DB_USER = os.getenv("HVOS_RFE_DB_USER") or os.getenv("HVOS_MYSQL_USER", "sql_hiugift_com")
DB_PASSWORD = os.getenv("HVOS_RFE_DB_PASSWORD") or os.getenv("HVOS_MYSQL_PASS")
TABLE_PREFIX = os.getenv("HVOS_RFE_TABLE_PREFIX") or os.getenv("HVOS_WC_TABLE_PREFIX", "wp_0dd69b_")

CART_ITEM_RE = re.compile(
    r's:10:"product_id";i:(?P<product_id>\d+);'
    r'.{0,4000}?s:8:"quantity";i:(?P<quantity>\d+);'
    r'.{0,4000}?s:13:"line_subtotal";(?:d|i):(?P<subtotal>[0-9.]+);',
    re.DOTALL,
)


def _require_config() -> None:
    missing = []
    if not SSH_USER:
        missing.append("HVOS_RFE_SSH_USER")
    if not SSH_PASSWORD and not SSH_KEY_PATH:
        missing.append("HVOS_RFE_SSH_PASSWORD or HVOS_RFE_SSH_KEY_PATH")
    if not DB_NAME:
        missing.append("HVOS_RFE_DB_NAME")
    if not DB_USER:
        missing.append("HVOS_RFE_DB_USER")
    if not DB_PASSWORD:
        missing.append("HVOS_RFE_DB_PASSWORD")
    if not re.fullmatch(r"[A-Za-z0-9_]+", TABLE_PREFIX):
        raise ValueError("HVOS_RFE_TABLE_PREFIX must contain only letters, numbers, and underscores.")
    if missing:
        raise RuntimeError("Missing RFE configuration: " + ", ".join(missing))


@dataclass
class CartEvent:
    session_key: str
    session_expiry: int
    product_id: str
    quantity: int
    line_subtotal: float


@dataclass
class ProductDemand:
    product_id: str
    product_name: str
    cart_add_count: int
    total_qty: int
    total_value: float
    session_count: int
    avg_line_value: float
    demand_intensity_score: float


def _connect_ssh() -> paramiko.SSHClient:
    _require_config()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connect_kwargs = {
        "hostname": SSH_HOST,
        "port": SSH_PORT,
        "username": SSH_USER,
        "timeout": 20,
        "banner_timeout": 20,
        "auth_timeout": 20,
    }
    if SSH_KEY_PATH:
        connect_kwargs["key_filename"] = SSH_KEY_PATH
    if SSH_PASSWORD:
        connect_kwargs["password"] = SSH_PASSWORD
    client.connect(**connect_kwargs)
    return client


def _remote_mysql(client: paramiko.SSHClient, sql: str) -> list[str]:
    _require_config()
    mysql_pwd = shlex.quote(str(DB_PASSWORD))
    db_user = shlex.quote(str(DB_USER))
    db_name = shlex.quote(str(DB_NAME))
    sql_arg = shlex.quote(sql)
    command = (
        f"MYSQL_PWD={mysql_pwd} mysql --batch --raw --skip-column-names "
        f"--default-character-set=utf8mb4 -u {db_user} -D {db_name} -e {sql_arg}"
    )
    stdin, stdout, stderr = client.exec_command(command, timeout=60)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    if exit_code != 0:
        raise RuntimeError(f"Remote MySQL command failed ({exit_code}): {err.strip()}")
    return [line for line in out.splitlines() if line.strip()]


def fetch_sessions() -> list[tuple[str, str, int]]:
    print(f"[RFE Collect] Connecting to VPS {SSH_HOST}:{SSH_PORT} with Paramiko over SSH...")
    sql = (
        "SELECT session_key, HEX(session_value), session_expiry "
        f"FROM {TABLE_PREFIX}woocommerce_sessions"
    )
    with _connect_ssh() as client:
        rows = _remote_mysql(client, sql)
    sessions: list[tuple[str, str, int]] = []
    for line in rows:
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        session_key, session_hex, expiry = parts
        try:
            session_value = bytes.fromhex(session_hex).decode("utf-8", errors="replace")
            sessions.append((session_key, session_value, int(expiry)))
        except ValueError:
            continue
    print(f"[RFE Collect] Fetched {len(sessions)} WooCommerce sessions.")
    return sessions


def fetch_product_names(product_ids: Iterable[str]) -> dict[str, str]:
    ids = sorted({str(pid) for pid in product_ids if str(pid).isdigit()})
    if not ids:
        return {}
    sql = (
        "SELECT ID, post_title FROM "
        f"{TABLE_PREFIX}posts WHERE ID IN ({','.join(ids)})"
    )
    names: dict[str, str] = {}
    try:
        with _connect_ssh() as client:
            rows = _remote_mysql(client, sql)
        for line in rows:
            parts = line.split("\t", 1)
            if len(parts) == 2:
                names[parts[0]] = parts[1]
    except Exception as exc:
        print(f"[RFE Collect] Product name lookup skipped: {exc}")
    return names


def _clean_product_name(name: str) -> str:
    replacements = {
        "鈥?": "-",
        "鈥�": "-",
        "â€“": "-",
        "â€”": "-",
        "\u2013": "-",
        "\u2014": "-",
    }
    cleaned = name
    for bad, good in replacements.items():
        cleaned = cleaned.replace(bad, good)
    return " ".join(cleaned.split())


def parse_cart_events(sessions: Iterable[tuple[str, str, int]]) -> list[CartEvent]:
    events: list[CartEvent] = []
    for session_key, session_value, session_expiry in sessions:
        for match in CART_ITEM_RE.finditer(session_value):
            events.append(
                CartEvent(
                    session_key=session_key,
                    session_expiry=session_expiry,
                    product_id=match.group("product_id"),
                    quantity=int(match.group("quantity")),
                    line_subtotal=float(match.group("subtotal")),
                )
            )
    return events


def aggregate_events(events: Iterable[CartEvent], names: dict[str, str] | None = None) -> list[ProductDemand]:
    names = names or {}
    grouped: dict[str, dict[str, object]] = defaultdict(
        lambda: {"count": 0, "qty": 0, "value": 0.0, "sessions": set()}
    )
    for event in events:
        row = grouped[event.product_id]
        row["count"] = int(row["count"]) + 1
        row["qty"] = int(row["qty"]) + event.quantity
        row["value"] = float(row["value"]) + event.line_subtotal
        row["sessions"].add(event.session_key)  # type: ignore[union-attr]

    products: list[ProductDemand] = []
    for product_id, row in grouped.items():
        count = int(row["count"])
        qty = int(row["qty"])
        value = round(float(row["value"]), 2)
        session_count = len(row["sessions"])  # type: ignore[arg-type]
        avg_line_value = round(value / count, 2) if count else 0.0
        demand_score = round((count * 10.0) + (qty * 2.0) + (value / 10.0) + (session_count * 3.0), 2)
        products.append(
            ProductDemand(
                product_id=product_id,
                product_name=_clean_product_name(names.get(product_id, "")),
                cart_add_count=count,
                total_qty=qty,
                total_value=value,
                session_count=session_count,
                avg_line_value=avg_line_value,
                demand_intensity_score=demand_score,
            )
        )
    return sorted(products, key=lambda item: (-item.cart_add_count, -item.total_value, item.product_id))


def collect_cart_demand(output_path: Path = DEFAULT_OUTPUT) -> dict[str, object]:
    sessions = fetch_sessions()
    events = parse_cart_events(sessions)
    product_names = fetch_product_names(event.product_id for event in events)
    products = aggregate_events(events, product_names)
    cart_sessions = {event.session_key for event in events}
    all_sessions = {session_key for session_key, _, _ in sessions}
    payload: dict[str, object] = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "source": f"{DB_NAME}.{TABLE_PREFIX}woocommerce_sessions",
        "window_days": 7,
        "session_count": len(all_sessions),
        "cart_session_count": len(cart_sessions),
        "browse_only_session_count": max(len(all_sessions) - len(cart_sessions), 0),
        "cart_event_count": len(events),
        "unique_product_count": len(products),
        "total_cart_value": round(sum(product.total_value for product in products), 2),
        "events": [asdict(event) for event in events],
        "products": [asdict(product) for product in products],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    print(
        "[RFE Collect] Parsed "
        f"{len(events)} cart events across {len(products)} products "
        f"(${payload['total_cart_value']} attempted cart value)."
    )
    print(f"[RFE Collect] Snapshot written: {output_path}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect WooCommerce cart-add demand over SSH.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    collect_cart_demand(args.output)


if __name__ == "__main__":
    main()
