import mysql.connector

MYSQL_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "ksu40600",  # Kendi MySQL şifreniz
    "database": "entegrator_db",
    "port": 3306,
    "charset": "utf8mb4",
    "use_pure": True,
    "autocommit": True
}

def inspect_n11_tasks():
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        cursor = conn.cursor(dictionary=True)

        print("🔌 'entegrator_db' veritabanına bağlanıldı.\n")

        # 1. Tablo yapısını incele
        cursor.execute("DESCRIBE n11_tasks;")
        columns = [col['Field'] for col in cursor.fetchall()]
        
        print("📋 'n11_tasks' Tablosundaki Sütunlar:")
        print("   " + ", ".join(columns))
        print("=" * 60)

        # 2. Tüm sütunları çekerek veriyi listele
        query = "SELECT * FROM n11_tasks WHERE status = 'PENDING' LIMIT 50;"
        cursor.execute(query)
        rows = cursor.fetchall()

        print(f"\n=== BEKLEYEN (PENDING) GÖREVLER: {len(rows)} Adet ===\n")

        if not rows:
            print("PENDING durumunda görev bulunamadı.")
        else:
            for idx, row in enumerate(rows, 1):
                print(f"📌 Kayıt #{idx}")
                for key, val in row.items():
                    # Null veya boş kontrolü vurgula
                    if key in ['task_id', 'batch_id', 'request_id', 'n11_task_id'] and (val is None or str(val).strip() == ""):
                        print(f"   ⚠️ {key}: ❌ NULL / EKSİK (Sorgulamayı engelleyen alan!)")
                    else:
                        print(f"   • {key}: {val}")
                print("-" * 40)

        cursor.close()
        conn.close()

    except mysql.connector.Error as err:
        print(f"❌ MySQL Hatası: {err}")

if __name__ == "__main__":
    inspect_n11_tasks()