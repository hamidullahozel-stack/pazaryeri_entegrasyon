# Dosya Yolu: utils\credentials_manager.py
# İşlem Tarihi: 21 Eylül 2026
# Açıklama: MySQL Tabanlı Güvenli API Kimlik Bilgileri Yöneticisi (Tam Düzeltilmiş)

import logging
import os
import sys

# Proje kök dizinini dinamik olarak sys.path'e ekleyerek modüllerin yüklenmesini garanti altına alıyoruz.
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Geriye dönük uyumluluk ve güvenli MySQL bağlantı yöneticisini dahil ediyoruz
from mysql_database import get_mysql_db as get_db_connection

log = logging.getLogger("credentials")


def save_credentials(db, platform, app_key, app_secret):
    """
    Seçilen pazar yerinin API bilgilerini merkezi MySQL tablosuna mühürler.
    Dışarıdan db nesnesi gelse de thread-safe bağlantı yöneticisiyle izole çalışır.
    """
    clean_key = str(app_key or "").strip()
    clean_secret = str(app_secret or "").strip()
    plat_str = str(platform.value if hasattr(platform, "value") else platform).strip().upper()

    if not clean_key or not clean_secret:
        return False, "❌ App Key ve App Secret boş bırakılamaz."

    try:
        # 🛡️ NameError Çözümü: Tanımsız get_db() yerine context manager get_db_connection() çağrılıyor
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # API tablosunun MySQL standartlarında varlığını garanti altına alıyoruz
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    platform VARCHAR(50) PRIMARY KEY,
                    app_key TEXT,
                    app_secret TEXT,
                    seller_id VARCHAR(100),
                    extra_params TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            
            # MySQL 'ON DUPLICATE KEY UPDATE' sözdizimi kullanılarak kayıt mühürleniyor
            sql = """
                INSERT INTO api_keys (platform, app_key, app_secret)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    app_key = VALUES(app_key),
                    app_secret = VALUES(app_secret)
            """
            cursor.execute(sql, (plat_str, clean_key, clean_secret))
            conn.commit()
            
        return True, f"✅ {plat_str} API bilgileri başarıyla MySQL veritabanına kaydedildi."
    except Exception as e:
        log.exception("save_credentials beklenmeyen hata")
        return False, f"❌ Veritabanı Hatası: {str(e)}"


def get_credentials(db, platform):
    """
    Veritabanından ilgili platforma ait API anahtarlarını güvenle okur.
    """
    plat_str = str(platform.value if hasattr(platform, "value") else platform).strip().upper()
    try:
        # 🛡️ NameError Çözümü: Thread-safe bağımsız MySQL havuz bağlantısı açılıyor
        with get_db_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT app_key, app_secret FROM api_keys WHERE UPPER(platform) = %s LIMIT 1",
                (plat_str,)
            )
            row = cursor.fetchone()
            
            if not row:
                return None, None
                
            return row["app_key"], row["app_secret"]
    except Exception as e:
        log.exception("get_credentials hatası")
        return None, None
