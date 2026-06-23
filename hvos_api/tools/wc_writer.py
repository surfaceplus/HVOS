"""
WooCommerce Writer Tool
=======================
Writes/updates product listings in WooCommerce via direct MySQL connection.

Connects to WooCommerce MySQL database to create or update products.
"""

import os
import sys
from typing import Dict, Any, Optional, List
import json


class WCWriter:
    """
    WooCommerce Writer Tool.
    
    Writes or updates products in WooCommerce via MySQL.
    
    Usage:
        writer = WCWriter()
        result = writer.write(
            product_name="创意礼品盒",
            price=29.99,
            stock_quantity=100,
            categories=["Gift", "Home"]
        )
    """
    
    def __init__(
        self,
        db_host: str = None,
        db_port: int = 3306,
        db_user: str = None,
        db_password: str = None,
        db_name: str = None,
    ):
        """
        Initialize WooCommerce Writer.
        
        Args:
            db_host: MySQL host
            db_port: MySQL port
            db_user: MySQL user
            db_password: MySQL password
            db_name: WooCommerce database name
        """
        self.db_host = db_host or os.getenv("HVOS_RFE_SSH_HOST", os.getenv("WOOCOMMERCE_DB_HOST", "localhost"))
        self.db_port = db_port or int(os.getenv("HVOS_RFE_SSH_PORT", os.getenv("WOOCOMMERCE_DB_PORT", "3306")))
        self.db_user = db_user or os.getenv("HVOS_RFE_DB_USER", os.getenv("WOOCOMMERCE_DB_USER", "sql_hiugift_com"))
        self.db_password = db_password or os.getenv("HVOS_RFE_DB_PASSWORD", os.getenv("WOOCOMMERCE_DB_PASSWORD", ""))
        self.db_name = db_name or os.getenv("HVOS_RFE_DB_NAME", os.getenv("WOOCOMMERCE_DB_NAME", "sql_hiugift_com"))
        self._connection = None
    
    def _get_connection(self):
        """Get MySQL connection, optionally via SSH tunnel"""
        import socket
        import threading

        # Check if we should use SSH tunnel
        ssh_host = os.getenv("HVOS_RFE_SSH_HOST", "")
        ssh_user = os.getenv("HVOS_RFE_SSH_USER", "root")
        ssh_password = os.getenv("HVOS_RFE_SSH_PASSWORD", "")
        local_bind_address = ("127.0.0.1", 3307)  # Local port for tunnel

        if ssh_host and self.db_host in ("localhost", "127.0.0.1"):
            # Use SSH tunnel: connect to remote MySQL via SSH
            try:
                import paramiko
            except ImportError:
                raise RuntimeError("paramiko not installed. Install with: pip install paramiko")

            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(
                    ssh_host,
                    username=ssh_user,
                    password=ssh_password,
                    timeout=10,
                    look_for_keys=False,
                    allow_agent=False,
                )
                # Forward local port 3307 -> remote MySQL at localhost:3306
                transport = ssh.get_transport()
                channel = transport.open_channel(
                    "direct-tcpip",
                    dest_addr=("127.0.0.1", 3306),
                    src_addr=local_bind_address,
                )
                self._ssh_channel = channel  # Keep reference to prevent GC
                self._ssh_client = ssh

                import mysql.connector
                conn = mysql.connector.connect(
                    host="127.0.0.1",
                    port=3307,
                    user=self.db_user,
                    password=self.db_password,
                    database=self.db_name,
                    connection_timeout=15,
                )
                return conn
            except Exception as e:
                raise RuntimeError(f"SSH tunnel connection failed: {e}")

        # Direct MySQL connection (local development)
        try:
            import mysql.connector
            conn = mysql.connector.connect(
                host=self.db_host,
                port=self.db_port,
                user=self.db_user,
                password=self.db_password,
                database=self.db_name,
                connection_timeout=10,
            )
            return conn
        except ImportError:
            raise RuntimeError(
                "mysql-connector-python not installed. "
                "Install with: pip install mysql-connector-python"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to connect to MySQL: {e}")
    
    def write(
        self,
        product_name: str,
        price: float,
        stock_quantity: int = 0,
        product_status: str = "publish",
        categories: str = "",
        opportunity_id: str = None,
        metadata: dict = None,
    ) -> Dict[str, Any]:
        """
        Write or update a product in WooCommerce.
        
        Args:
            product_name: Product name/title
            price: Product price (USD)
            stock_quantity: Stock quantity (0 = out of stock)
            product_status: Status (publish, draft, private, pending)
            categories: Category names (comma-separated)
            opportunity_id: Linked HVOS opportunity ID
            metadata: Additional product metadata
            
        Returns:
            Result with product_id and details
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Check if product exists by name
            cursor.execute(
                "SELECT ID, post_title FROM wp_posts WHERE post_title = %s AND post_type = 'product' LIMIT 1",
                (product_name,)
            )
            existing = cursor.fetchone()
            
            product_id = None
            
            if existing:
                # Update existing product
                product_id = existing["ID"]
                cursor.execute(
                    """UPDATE wp_posts 
                       SET post_title = %s, post_status = %s, post_modified = NOW()
                       WHERE ID = %s""",
                    (product_name, product_status, product_id)
                )
                
                # Update price in postmeta
                cursor.execute(
                    """INSERT INTO wp_postmeta (post_id, meta_key, meta_value) 
                       VALUES (%s, '_price', %s)
                       ON DUPLICATE KEY UPDATE meta_value = %s""",
                    (product_id, str(price), str(price))
                )
                
                # Update stock
                cursor.execute(
                    """INSERT INTO wp_postmeta (post_id, meta_key, meta_value) 
                       VALUES (%s, '_stock', %s)
                       ON DUPLICATE KEY UPDATE meta_value = %s""",
                    (product_id, str(stock_quantity), str(stock_quantity))
                )
                
                action = "updated"
            else:
                # Create new product
                cursor.execute(
                    """INSERT INTO wp_posts 
                       (post_author, post_date, post_modified, post_type, post_status, post_title)
                       VALUES (1, NOW(), NOW(), 'product', %s, %s)""",
                    (product_status, product_name)
                )
                product_id = cursor.lastrowid
                action = "created"
                
                # Insert required postmeta
                postmeta_fields = [
                    ("_price", str(price)),
                    ("_regular_price", str(price)),
                    ("_stock", str(stock_quantity)),
                    ("_stock_status", "instock" if stock_quantity > 0 else "outofstock"),
                    ("_manage_stock", "yes"),
                    ("_visibility", "visible"),
                    ("_product_version", "8.0.0"),
                ]
                
                for meta_key, meta_value in postmeta_fields:
                    cursor.execute(
                        """INSERT INTO wp_postmeta (post_id, meta_key, meta_value) 
                           VALUES (%s, %s, %s)""",
                        (product_id, meta_key, meta_value)
                    )
            
            # Handle categories
            if categories:
                category_names = [c.strip() for c in categories.split(",")]
                for cat_name in category_names:
                    # Get or create category
                    cursor.execute(
                        "SELECT term_id FROM wp_terms WHERE name = %s LIMIT 1",
                        (cat_name,)
                    )
                    term = cursor.fetchone()
                    
                    if term:
                        term_id = term["term_id"]
                    else:
                        # Create category
                        cursor.execute(
                            "INSERT INTO wp_terms (name, slug) VALUES (%s, %s)",
                            (cat_name, cat_name.lower().replace(" ", "-"))
                        )
                        term_id = cursor.lastrowid
                        cursor.execute(
                            "INSERT INTO wp_term_taxonomy (term_id, taxonomy) VALUES (%s, 'product_cat')",
                            (term_id,)
                        )
                    
                    # Link product to category
                    cursor.execute(
                        """INSERT INTO wp_term_relationships (object_id, term_taxonomy_id)
                           VALUES (%s, (SELECT term_taxonomy_id FROM wp_term_taxonomy WHERE term_id = %s LIMIT 1))
                           ON DUPLICATE KEY UPDATE term_taxonomy_id=term_taxonomy_id""",
                        (product_id, term_id)
                    )
            
            # Handle opportunity_id metadata
            if opportunity_id:
                cursor.execute(
                    """INSERT INTO wp_postmeta (post_id, meta_key, meta_value) 
                       VALUES (%s, 'hvos_opportunity_id', %s)
                       ON DUPLICATE KEY UPDATE meta_value = %s""",
                    (product_id, opportunity_id, opportunity_id)
                )
            
            # Handle additional metadata
            if metadata:
                for key, value in metadata.items():
                    if isinstance(value, (dict, list)):
                        value = json.dumps(value)
                    cursor.execute(
                        """INSERT INTO wp_postmeta (post_id, meta_key, meta_value) 
                           VALUES (%s, %s, %s)
                           ON DUPLICATE KEY UPDATE meta_value = %s""",
                        (product_id, f"hvos_{key}", str(value), str(value))
                    )
            
            conn.commit()
            cursor.close()
            conn.close()
            
            return {
                "success": True,
                "tool": "wc_writer",
                "action": action,
                "product_id": product_id,
                "product_name": product_name,
                "price": price,
                "stock_quantity": stock_quantity,
                "status": product_status,
                "opportunity_id": opportunity_id,
                "categories": categories,
            }
            
        except Exception as e:
            return {
                "success": False,
                "tool": "wc_writer",
                "error": str(e),
                "error_type": type(e).__name__,
            }
    
    def delete(
        self,
        product_id: int,
    ) -> Dict[str, Any]:
        """
        Delete a product from WooCommerce.
        
        Args:
            product_id: WooCommerce product ID
            
        Returns:
            Result of deletion
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Delete postmeta first
            cursor.execute("DELETE FROM wp_postmeta WHERE post_id = %s", (product_id,))
            
            # Delete term relationships
            cursor.execute("DELETE FROM wp_term_relationships WHERE object_id = %s", (product_id,))
            
            # Delete post
            cursor.execute("DELETE FROM wp_posts WHERE ID = %s", (product_id,))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            return {
                "success": True,
                "tool": "wc_writer",
                "action": "deleted",
                "product_id": product_id,
            }
            
        except Exception as e:
            return {
                "success": False,
                "tool": "wc_writer",
                "error": str(e),
            }
    
    def get_product(
        self,
        product_id: int,
    ) -> Dict[str, Any]:
        """
        Get product details from WooCommerce.
        
        Args:
            product_id: WooCommerce product ID
            
        Returns:
            Product details
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Get post
            cursor.execute(
                "SELECT ID, post_title, post_status, post_date FROM wp_posts WHERE ID = %s AND post_type = 'product'",
                (product_id,)
            )
            product = cursor.fetchone()
            
            if not product:
                return {
                    "success": False,
                    "tool": "wc_writer",
                    "error": f"Product {product_id} not found",
                }
            
            # Get postmeta
            cursor.execute(
                "SELECT meta_key, meta_value FROM wp_postmeta WHERE post_id = %s",
                (product_id,)
            )
            meta = {row["meta_key"]: row["meta_value"] for row in cursor.fetchall()}
            
            cursor.close()
            conn.close()
            
            return {
                "success": True,
                "tool": "wc_writer",
                "product": {
                    "id": product["ID"],
                    "name": product["post_title"],
                    "status": product["post_status"],
                    "created_at": product["post_date"].isoformat() if product["post_date"] else None,
                    "price": meta.get("_price"),
                    "regular_price": meta.get("_regular_price"),
                    "stock": meta.get("_stock"),
                    "stock_status": meta.get("_stock_status"),
                    "opportunity_id": meta.get("hvos_opportunity_id"),
                }
            }
            
        except Exception as e:
            return {
                "success": False,
                "tool": "wc_writer",
                "error": str(e),
            }