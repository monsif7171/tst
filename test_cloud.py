# -*- coding: utf-8 -*-
"""Cloud Connection Tester for Teryaq Pharmacy System.
Tests PostgreSQL / Supabase connection, schema tables, and connectivity.
"""
import os
import sys

def get_database_url():
    """Read DATABASE_URL from .env file or environment variable."""
    # 1. Environment variable
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if db_url:
        return db_url

    # 2. .env file in the same directory
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DATABASE_URL=") and not line.startswith("#"):
                        val = line.split("DATABASE_URL=", 1)[1].strip()
                        # Strip outer quotes if any
                        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                            val = val[1:-1].strip()
                        return val
        except Exception:
            pass
    return ""


def test_cloud_connection():
    db_url = get_database_url()

    print("=" * 65)
    print("      Teryaq Cloud Database Connection Tester")
    print("=" * 65)

    if not db_url:
        print("\n[!] WARNING: DATABASE_URL is not configured in .env file.")
        print("    Current Mode: Local SQLite only.")
        print("    To enable Cloud: Open .env and add your Supabase / PostgreSQL URL.")
        print("\n" + "=" * 65)
        try:
            input("Press Enter to exit...")
        except (EOFError, KeyboardInterrupt):
            pass
        return

    # Normalize dialect prefix
    clean_url = db_url
    if clean_url.startswith("postgres://"):
        clean_url = "postgresql://" + clean_url[11:]

    # Mask password for secure console output
    masked_url = clean_url
    try:
        if "@" in clean_url and "://" in clean_url:
            proto, rest = clean_url.split("://", 1)
            creds, host_part = rest.split("@", 1)
            if ":" in creds:
                user = creds.split(":", 1)[0]
                masked_url = f"{proto}://{user}:******@{host_part}"
    except Exception:
        pass

    print(f"\n[+] Detected Database URL:")
    print(f"    {masked_url}")
    print(f"\n[+] Connecting to cloud server (timeout: 10s)...")

    try:
        import psycopg2
    except ImportError:
        print("\n[X] ERROR: 'psycopg2' library is not installed in current Python environment.")
        print("    Install it via: pip install psycopg2-binary")
        print("\n" + "=" * 65)
        try:
            input("Press Enter to exit...")
        except (EOFError, KeyboardInterrupt):
            pass
        return

    try:
        conn = psycopg2.connect(clean_url, connect_timeout=10)
        cur = conn.cursor()

        # 1. Test Server Version
        cur.execute("SELECT version();")
        ver = cur.fetchone()[0]
        print("\n[OK] Successfully connected to cloud database!")
        print(f"     Server Version: {ver.split(',')[0]}")

        # 2. Check Database Tables
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name;
        """)
        tables = [t[0] for t in cur.fetchall()]
        print(f"     Active Tables in Cloud: {len(tables)} tables")

        core_tables = {"users", "products", "sales", "sale_items", "customers", "suppliers", "branches", "settings"}
        missing_tables = core_tables - set(tables)

        if not missing_tables:
            print("     [OK] All core Teryaq tables are fully configured and ready!")

            # Check USD exchange rate setting
            try:
                cur.execute("SELECT value FROM settings WHERE key = 'usd_exchange_rate';")
                row = cur.fetchone()
                rate = row[0] if row else "Not Set"
                print(f"     [OK] Cloud USD Exchange Rate: {rate}")
            except Exception:
                pass

            # Count products
            try:
                cur.execute("SELECT COUNT(*) FROM products;")
                p_count = cur.fetchone()[0]
                print(f"     [OK] Total Products in Cloud: {p_count} items")
            except Exception:
                pass

        else:
            print(f"\n[!] WARNING: Missing required tables: {', '.join(missing_tables)}")
            print("    Please run 'schema_postgres.sql' in Supabase SQL Editor.")

        cur.close()
        conn.close()

        print("\n[SUCCESS] Cloud sync is operational and ready for use!")

    except Exception as e:
        err_msg = str(e).strip()
        print(f"\n[X] Cloud connection failed!")
        print(f"    Error Details: {err_msg}")
        print("\nTroubleshooting Tips:")
        if "password authentication failed" in err_msg.lower():
            print("  - Password incorrect. Reset your database password in Supabase.")
        elif "could not translate host name" in err_msg.lower() or "timeout" in err_msg.lower():
            print("  - Host unreachable. Check your internet connection and hostname.")
        elif "connection refused" in err_msg.lower():
            print("  - Connection refused. Ensure you are using Session pooling port (6543 or 5432).")
        else:
            print("  1. Ensure you copied the complete Connection URI from Supabase.")
            print("  2. Verify Session or Transaction pooling is enabled on port 6543 / 5432.")

    print("\n" + "=" * 65)
    try:
        input("Press Enter to exit...")
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    test_cloud_connection()
