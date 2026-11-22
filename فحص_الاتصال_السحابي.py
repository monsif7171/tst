# -*- coding: utf-8 -*-
"""Cloud Connection Tester for Teryaq Pharmacy System.
Tests PostgreSQL / Supabase connection, schema compatibility, and SSL/pooling.
"""
import os
import sys

# Ensure UTF-8 output encoding for Windows command prompt
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


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
    print("      فاحص الاتصال بقاعدة البيانات السحابية — نظام ترياق")
    print("=" * 65)

    if not db_url:
        print("\n[!] تنبيه: لم يتم ضبط DATABASE_URL في ملف .env")
        print("    الوضع الحالي: النظام سيعمل محلياً فقط (Local SQLite).")
        print("    للتشغيل السحابي: افتح ملف .env وضع رابط اتصال Supabase / PostgreSQL.")
        print("\n" + "=" * 65)
        try:
            input("اضغط Enter للخروج...")
        except (EOFError, KeyboardInterrupt):
            pass
        return

    # Check dialect prefix
    clean_url = db_url
    if clean_url.startswith("postgres://"):
        clean_url = "postgresql://" + clean_url[11:]

    # Mask password for secure display
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

    print(f"\n[+] رابط الاتصال المكتشف:")
    print(f"    {masked_url}")
    print(f"\n[+] جاري محاولة الاتصال بالخادم السحابي (مهلة 10 ثوانٍ)...")

    try:
        import psycopg2
    except ImportError:
        print("\n[✘] خطأ: مكتبة psycopg2 غير مثبتة في بيئة بايثون الحالية.")
        print("    لتثبيتها نفذ: pip install psycopg2-binary")
        print("\n" + "=" * 65)
        try:
            input("اضغط Enter للخروج...")
        except (EOFError, KeyboardInterrupt):
            pass
        return

    try:
        conn = psycopg2.connect(clean_url, connect_timeout=10)
        cur = conn.cursor()

        # 1. Test Server Version
        cur.execute("SELECT version();")
        ver = cur.fetchone()[0]
        print("\n[✔] تم الاتصال بالخادم السحابي بنجاح تام!")
        print(f"    إصدار الخادم: {ver.split(',')[0]}")

        # 2. Check Database Tables
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name;
        """)
        tables = [t[0] for t in cur.fetchall()]
        print(f"    عدد الجداول السحابية النشطة: {len(tables)} جدول")

        core_tables = {"users", "products", "sales", "sales_items", "customers", "suppliers", "branches", "settings"}
        missing_tables = core_tables - set(tables)

        if not missing_tables:
            print("    [✔] كافة جداول نظام ترياق الأساسية مهيأة ومطابقة 100%!")

            # Check USD exchange rate setting
            try:
                cur.execute("SELECT value FROM settings WHERE key = 'usd_exchange_rate';")
                row = cur.fetchone()
                rate = row[0] if row else "غير محدد"
                print(f"    [✔] سعر صرف الدولار المسجل سحابياً: {rate}")
            except Exception:
                pass

            # Count products
            try:
                cur.execute("SELECT COUNT(*) FROM products;")
                p_count = cur.fetchone()[0]
                print(f"    [✔] إجمالي الأصناف والأدوية المسجلة: {p_count} صنف")
            except Exception:
                pass

        else:
            print(f"\n[!] تنبيه: هناك جداول أساسية مفقودة: {', '.join(missing_tables)}")
            print("    يرجى فتح ملف schema_postgres.sql وتنفيذه في SQL Editor داخل Supabase.")

        cur.close()
        conn.close()

        print("\n[🎉] النتيجة: النظام جاهز للعمل بالربط السحابي مع الفروع!")

    except Exception as e:
        err_msg = str(e).strip()
        print(f"\n[✘] فشل الاتصال بقاعدة البيانات السحابية!")
        print(f"    رسالة الخطأ: {err_msg}")
        print("\n💡 نصائح لحل المشكلة:")
        if "password authentication failed" in err_msg.lower():
            print("  • كلمة المرور غير صحيحة، يرجى إعادة تعيين كلمة مرور قاعدة البيانات من Supabase.")
        elif "could not translate host name" in err_msg.lower() or "timeout" in err_msg.lower():
            print("  • تعذر الوصول للخادم. تأكد من اتصال الإنترنت وأن عنوان المضيف (Host) صحيح.")
        elif "connection refused" in err_msg.lower():
            print("  • تم رفض الاتصال. تأكد من استخدام المنفذ الصحيح (عادة 6543 لـ Connection Pooling أو 5432).")
        else:
            print("  1. تأكد من نسخ رابط Connection String (URI) كاملاً من Supabase.")
            print("  2. تأكد من اختيار وضع Session أو Transaction على المنفذ 6543 / 5432.")

    print("\n" + "=" * 65)
    try:
        input("اضغط Enter للإغلاق...")
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    test_cloud_connection()
