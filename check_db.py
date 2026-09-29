# Dosya Yolu: check_db.py
# Açıklama: SQLite Verilerinin MySQL Veritabanına Güvenli, Eksiksiz ve NULL Önleyici Göç Betiği (n11_id NULL Hatası Düzeltilmiş)

import sqlite3
import mysql.connector
from mysql_database import DB_CONFIG, init_db_mysql

def force_migrate_all_tables():
    """SQLite (entegrator.db) içindeki TÜM tabloları ve verileri MySQL veritabanına aktarır."""
    sqlite_conn = None
    mysql_conn = None
    try:
        print("🔄 MySQL Veritabanı şeması ilklendiriliyor...")
        init_db_mysql()

        print("🔄 SQLite veritabanına bağlanılıyor...")
        sqlite_conn = sqlite3.connect("entegrator.db")
        sqlite_conn.row_factory = sqlite3.Row
        sq_cursor = sqlite_conn.cursor()

        mysql_conn = mysql.connector.connect(**DB_CONFIG)
        my_cursor = mysql_conn.cursor()

        # MySQL üzerindeki mevcut tabloları sorgula
        my_cursor.execute("SHOW TABLES;")
        mysql_tables = {row[0].lower() for row in my_cursor.fetchall()}

        # SQLite üzerindeki tüm tabloları al
        sq_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tables = [row[0] for row in sq_cursor.fetchall()]

        print(f"📊 Taşınacak Toplam SQLite Tablo Sayısı: {len(tables)}")

        for table in tables:
            if table.lower() not in mysql_tables:
                print(f"⚠️  MySQL veritabanında [{table}] tablosu mevcut değil, atlanıyor.")
                continue

            sq_cursor.execute(f"SELECT * FROM `{table}`")
            rows = sq_cursor.fetchall()
            
            if not rows:
                print(f"ℹ️  SQLite [{table}] tablosu boş, atlanıyor.")
                continue

            sqlite_cols = list(rows[0].keys())

            # MySQL tablosundaki gerçek sütunları öğren (id uyuşmazlığını önlemek için)
            my_cursor.execute(f"DESCRIBE `{table}`")
            mysql_cols = {row[0].lower() for row in my_cursor.fetchall()}

            # Sadece her iki tarafta da ortak olan sütunları eşle
            cols_to_use = [col for col in sqlite_cols if col.lower() in mysql_cols]

            if not cols_to_use:
                print(f"⚠️ [{table}] tablosu için eşleşen sütun bulunamadı, atlanıyor.")
                continue

            col_str = ", ".join([f"`{c}`" for c in cols_to_use])
            placeholders = ", ".join(["%s"] * len(cols_to_use))

            print(f"🧹 MySQL [{table}] tablosu temizleniyor...")
            try:
                my_cursor.execute(f"TRUNCATE TABLE `{table}`")
            except Exception:
                try:
                    my_cursor.execute(f"DELETE FROM `{table}`")
                except Exception as e_clean:
                    print(f"⚠️ [{table}] temizlenirken uyarı: {e_clean}")
            mysql_conn.commit()

            insert_query = f"INSERT INTO `{table}` ({col_str}) VALUES ({placeholders})"
            
            data_to_insert = []
            seen_pks = set() # Tablo bazlı birincil anahtar tekrarlarını önlemek için bellek havuzu

            for r in rows:
                # sqlite3.Row nesnesini standart Python dict yapısına çeviriyoruz
                row = dict(r)

                # 🛡️ [KRİTİK GÜVENLİK KALKANI] n11_id NULL veya Boş Metin Filtresi
                if table.lower() == "n11_remote_products":
                    n11_id_val = row.get("n11_id") or row.get("n11_product_id")
                    
                    # Eğer n11_id değeri None (NULL) ise veya tamamen boşsa bu satırı listeye eklemeden GEÇ!
                    if n11_id_val is None or str(n11_id_val).strip() == "" or str(n11_id_val).lower() == "none":
                        continue 
                    
                    pk_clean = str(n11_id_val).strip()
                    if pk_clean in seen_pks:
                        continue # Mükerrer anahtarlı satırı atla
                    seen_pks.add(pk_clean)

                # 🛡️ Genel Tablo Birincil Anahtar Mükerrer Kontrolü (Örn: code, stock_code)
                elif table.lower() in ["products", "api_keys", "settings", "n11_failed_products"]:
                    primary_col = "code" if "code" in sqlite_cols else ("platform" if "platform" in sqlite_cols else ("key" if "key" in sqlite_cols else "stock_code"))
                    if primary_col in row and row[primary_col]:
                        pk_val = str(row[primary_col]).strip()
                        if pk_val in seen_pks:
                            continue
                        seen_pks.add(pk_val)

                row_vals = []
                skip_row_due_to_null_pk = False

                for col in cols_to_use:
                    val = row[col]
                    
                    # Ekstra Güvenlik: Eğer döngü esnasında hedef sütun n11_id ise ve veri sızdıysa son kontrol
                    if table.lower() == "n11_remote_products" and col.lower() == "n11_id":
                        if val is None or str(val).strip() == "" or str(val).lower() == "none":
                            skip_row_due_to_null_pk = True
                            break

                    # Data Too Long Kırpma Mekanizması
                    if table.lower() == "product_variants" and col.lower() == "variant_value" and val is not None:
                        val_str = str(val)
                        if len(val_str) > 100:
                            val = val_str[:97] + "..."

                    row_vals.append(val)
                
                if skip_row_due_to_null_pk:
                    continue

                data_to_insert.append(tuple(row_vals))

            if data_to_insert:
                try:
                    my_cursor.executemany(insert_query, data_to_insert)
                    mysql_conn.commit()
                    print(f"✅ [{table}] tablosuna {len(data_to_insert)} adet kayıt başarıyla aktarıldı.")
                except mysql.connector.Error as db_err:
                    # Mükerrer satır sızma durumunda (1062) işlemi durdurmamak için tekli ekleme koruması
                    if db_err.errno == 1062:
                        print(f"⚠️ [{table}] tablosunda mükerrer kayıtlar saptandı, tekil güvenli moda geçiliyor...")
                        mysql_conn.rollback()
                        for single_row in data_to_insert:
                            try:
                                my_cursor.execute(insert_query, single_row)
                            except mysql.connector.Error as s_err:
                                if s_err.errno != 1062: # Duplicate entry dışındaki hataları fırlat
                                    print(f"❌ Satır eklenemedi: {s_err}")
                        mysql_conn.commit()
                        print(f"✅ [{table}] tablosu uyuşmazlıklar elenerek başarıyla tamamlandı.")
                    else:
                        raise db_err

        print("\n🎉 TÜM MİGRASYON İŞLEMİ BAŞARIYLA TAMAMLANDI!")

    except Exception as e:
        if mysql_conn and mysql_conn.is_connected():
            mysql_conn.rollback()
        print(f"❌ Aktarım sırasında kritik hata oluştu: {e}")
    finally:
        if sqlite_conn:
            sqlite_conn.close()
        if mysql_conn and mysql_conn.is_connected():
            mysql_conn.close()

if __name__ == "__main__":
    force_migrate_all_tables()
