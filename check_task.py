import mysql.connector

# Sizin konfigürasyonunuz (Şifreniz xxxxxxxx değilse buraya gerçek şifrenizi yazın)
MYSQL_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "ksu40600",  
    "database": "entegrator_db",
    "port": 3306,
    "charset": "utf8mb4",
    "use_pure": True,
    "autocommit": True
}

def check_n11_tasks():
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        cursor = conn.cursor(dictionary=True)

        print("🔌 'entegrator_db' veritabanına başarıyla bağlanıldı.\n")

        # PENDING durumundaki N11 görevlerini çek
        query = """
        SELECT id, product_id, task_id, status, created_at 
        FROM n11_tasks 
        WHERE status = 'PENDING'
        LIMIT 50;
        """
        cursor.execute(query)
        rows = cursor.fetchall()

        print(f"=== BEKLEYEN (PENDING) N11 GÖREVLERİ: {len(rows)} Adet ===\n")

        if not rows:
            print("PENDING durumunda hiç görev bulunamadı.")
            return

        print(f"{'ID':<8} | {'Product ID':<12} | {'Task ID (N11 Batch ID)':<30} | {'Status':<10}")
        print("-" * 75)

        null_count = 0
        for row in rows:
            t_id = row.get('task_id')
            if not t_id or str(t_id).strip() == "":
                t_disp = "❌ NULL / EKSİK"
                null_count += 1
            else:
                t_disp = str(t_id)

            print(f"{str(row['id']):<8} | {str(row['product_id']):<12} | {t_disp:<30} | {str(row['status']):<10}")

        print("-" * 75)
        if null_count > 0:
            print(f"\n⚠️ SORUN TESPİT EDİLDİ:")
            print(f"Toplam {null_count} adet görevin 'task_id' (N11 İşlem ID) değeri BOŞ (NULL).")
            print("👉 '0 adet görevin durumu güncellendi' mesajı bu yüzden çıkıyor.")
            print("👉 Ürünler N11'e ilk gönderildiğinde N11'in döndüğü Batch Request ID veritabanındaki 'task_id' sütununa yazılamıyor.")

        cursor.close()
        conn.close()

    except mysql.connector.Error as err:
        print(f"❌ MySQL Hatası: {err}")

if __name__ == "__main__":
    check_n11_tasks()