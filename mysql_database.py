# Dosya Yolu: mysql_database.py
# İşlem Tarihi: 21 Eylül 2026
# Açıklama: MySQL Tabanlı Merkezi Veritabanı ve Bağlantı Yöneticisi (Eksiksiz Sürüm)

import logging
import mysql.connector
from mysql.connector import Error
from contextlib import contextmanager
from constants import MYSQL_CONFIG as DB_CONFIG

logger = logging.getLogger(__name__)


def _ensure_column_mysql(cursor, table, column, col_type):
    """MySQL tablosunda ilgili sütunun varlığını kontrol eder, yoksa ekler."""
    try:
        cursor.execute(f"DESCRIBE {table}")
        cols = [row[0] for row in cursor.fetchall()]
        if column not in cols:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except Error as e:
        logger.error(f"Sütun kontrolü sırasında hata [{table}.{column}]: {e}")


def init_db_mysql():
    """Uygulama ilk açıldığında MySQL üzerinde tüm pazar yeri tablolarını hazırlar."""
    try:
        temp_config = DB_CONFIG.copy()
        db_name = temp_config.pop("database")
        
        conn_temp = mysql.connector.connect(**temp_config)
        cursor_temp = conn_temp.cursor()
        cursor_temp.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
        cursor_temp.close()
        conn_temp.close()

        with get_mysql_db() as conn:
            cursor = conn.cursor()

            # 1. API Anahtarları Tablosu
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

            # 2. Ayarlar Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    `key` VARCHAR(100) PRIMARY KEY,
                    `value` TEXT
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 3. Ortak Ürünler Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    code VARCHAR(100) PRIMARY KEY,
                    main_code VARCHAR(100),
                    title TEXT,
                    brand VARCHAR(150),
                    barcode VARCHAR(100),
                    price DECIMAL(10,2) DEFAULT 0.00,
                    stock INT DEFAULT 0,
                    tax INT DEFAULT 18,
                    mainCategory VARCHAR(150),
                    category VARCHAR(150),
                    subCategory VARCHAR(150),
                    images TEXT,
                    details TEXT,
                    color VARCHAR(50),
                    gender VARCHAR(50),
                    origin VARCHAR(100),
                    supplier VARCHAR(150),
                    size VARCHAR(50),
                    is_mapped INT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 4. Ürün Varyantları Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS product_variants (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    main_code VARCHAR(100),
                    code VARCHAR(100) UNIQUE,
                    barcode VARCHAR(100),
                    stock INT DEFAULT 0,
                    price DECIMAL(10,2) DEFAULT 0.00,
                    variant_name VARCHAR(100),
                    variant_value TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 5. N11 Uzak Ürünler Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS n11_remote_products (
                    n11_id VARCHAR(100) PRIMARY KEY,
                    n11_product_id VARCHAR(100),
                    id VARCHAR(100),
                    stock_code VARCHAR(100),
                    product_seller_code VARCHAR(100) UNIQUE,
                    title TEXT,
                    subtitle TEXT,
                    price DECIMAL(10,2) DEFAULT 0.00,
                    display_price DECIMAL(10,2) DEFAULT 0.00,
                    stock_items INT DEFAULT 0,
                    approval_status VARCHAR(50),
                    status VARCHAR(50),
                    sale_status VARCHAR(50),
                    category_id INT,
                    images TEXT,
                    remote_status VARCHAR(50),
                    last_checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 6. N11 Görevler Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS n11_tasks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    task_id VARCHAR(100) UNIQUE,
                    stock_code VARCHAR(100),
                    main_code VARCHAR(100),
                    batch_request_id VARCHAR(100),
                    status VARCHAR(50) DEFAULT 'PENDING',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            
            _ensure_column_mysql(cursor, "n11_tasks", "batch_request_id", "VARCHAR(100)")

            # 7. Trendyol Uzak Ürünler Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trendyol_remote_products (
                    item_id VARCHAR(100) PRIMARY KEY,
                    barcode VARCHAR(100),
                    title TEXT,
                    stock_code VARCHAR(100),
                    price DECIMAL(10,2) DEFAULT 0.00,
                    sale_price DECIMAL(10,2) DEFAULT 0.00,
                    quantity INT DEFAULT 0,
                    approved INT DEFAULT 0,
                    archived INT DEFAULT 0,
                    category_name VARCHAR(150),
                    images TEXT,
                    last_checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 8. Trendyol Görevler Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trendyol_tasks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    batch_request_id VARCHAR(100) UNIQUE,
                    stock_code VARCHAR(100),
                    main_code VARCHAR(100),
                    status VARCHAR(50) DEFAULT 'PENDING',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 9. Hepsiburada Uzak Ürünler Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS hepsiburada_remote_products (
                    hepsiburada_sku VARCHAR(100) PRIMARY KEY,
                    merchant_sku VARCHAR(100),
                    title TEXT,
                    price DECIMAL(10,2) DEFAULT 0.00,
                    stock INT DEFAULT 0,
                    is_salable INT DEFAULT 1,
                    last_checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 10. Hepsiburada Görevler Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS hepsiburada_tasks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    task_id VARCHAR(100) UNIQUE,
                    stock_code VARCHAR(100),
                    main_code VARCHAR(100),
                    status VARCHAR(50) DEFAULT 'PENDING',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 11. Pazarama Uzak Ürünler Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pazarama_remote_products (
                    pazarama_code VARCHAR(100) PRIMARY KEY,
                    stock_code VARCHAR(100),
                    title TEXT,
                    price DECIMAL(10,2) DEFAULT 0.00,
                    stock INT DEFAULT 0,
                    approval_status VARCHAR(50),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 12. Pazarama Görevler Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pazarama_tasks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    batch_request_id VARCHAR(100) UNIQUE,
                    stock_code VARCHAR(100),
                    status VARCHAR(50) DEFAULT 'PENDING',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 13. İdefix Uzak Ürünler Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS idefix_remote_products (
                    sku VARCHAR(100) PRIMARY KEY,
                    merchant_sku VARCHAR(100),
                    title TEXT,
                    price DECIMAL(10,2) DEFAULT 0.00,
                    stock INT DEFAULT 0,
                    status VARCHAR(50),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 14. İdefix Görevler Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS idefix_tasks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    task_id VARCHAR(100) UNIQUE,
                    stock_code VARCHAR(100),
                    status VARCHAR(50) DEFAULT 'PENDING',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 15. Hatalı Ürünler Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS n11_failed_products (
                    stock_code VARCHAR(100) PRIMARY KEY,
                    reason TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 16. Stok/Fiyat Fark Raporları Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stock_diff_reports (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    stock_code VARCHAR(100),
                    diff_type VARCHAR(50),
                    old_value TEXT,
                    new_value TEXT,
                    update_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 17. Şablonlar Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS templates (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(150) UNIQUE,
                    title TEXT,
                    template_name VARCHAR(150),
                    platform VARCHAR(50),
                    prep_time VARCHAR(50),
                    delivery_template VARCHAR(150),
                    price_field VARCHAR(50),
                    operator VARCHAR(20),
                    price_value DECIMAL(10,2),
                    discount_rate DECIMAL(5,2),
                    start_date VARCHAR(50),
                    end_date VARCHAR(50),
                    max_purchase INT DEFAULT 99,
                    shipment_template VARCHAR(150),
                    preparing_day INT,
                    delivery_fee_type VARCHAR(50),
                    status VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 18. Kategori Eşleştirme Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS n11_category_mappings (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    ideasoft_cat TEXT,
                    n11_cat TEXT,
                    template_name VARCHAR(150),
                    n11_cat_id VARCHAR(50),
                    parent_id VARCHAR(50),
                    local_category VARCHAR(255),
                    n11_category_id VARCHAR(50),
                    n11_category_name TEXT,
                    template_id INT,
                    platform VARCHAR(50) DEFAULT 'N11',
                    store_id VARCHAR(50) DEFAULT 'N11',
                    catalog_status VARCHAR(50) DEFAULT 'READY',
                    catalog_id VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY ux_n11_cat_key (platform, store_id, local_category)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 19. Ürün Özellikleri Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS product_attributes (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    product_code VARCHAR(100),
                    n11_attribute_id VARCHAR(50),
                    n11_attribute_name VARCHAR(150),
                    n11_value_id VARCHAR(50),
                    custom_value TEXT,
                    is_mandatory INT DEFAULT 0,
                    is_variant INT DEFAULT 0,
                    is_custom INT DEFAULT 0
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 20. Siparişler Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    order_number VARCHAR(100) UNIQUE,
                    status VARCHAR(50),
                    buyer_name VARCHAR(150),
                    total_amount DECIMAL(10,2),
                    create_date VARCHAR(50)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 21. Sipariş Kalemleri Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS order_items (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    order_number VARCHAR(100),
                    product_code VARCHAR(100),
                    quantity INT,
                    price DECIMAL(10,2),
                    FOREIGN KEY(order_number) REFERENCES orders(order_number) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 22. Ürün Varyant Özellikleri Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS product_variant_attributes (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    variant_code VARCHAR(100),
                    main_code VARCHAR(100),
                    n11_attribute_id VARCHAR(50),
                    n11_attribute_name VARCHAR(150),
                    n11_value_id VARCHAR(50),
                    custom_value TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY ux_var_attr (variant_code, n11_attribute_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 23. PttAVM Uzak Ürünler Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pttavm_remote_products (
                    pttavm_code VARCHAR(100) PRIMARY KEY,
                    stock_code VARCHAR(100),
                    title TEXT,
                    price DECIMAL(10,2) DEFAULT 0.00,
                    stock INT DEFAULT 0,
                    approval_status VARCHAR(50),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 24. PttAVM Görevler Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pttavm_tasks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    task_id VARCHAR(100) UNIQUE,
                    stock_code VARCHAR(100),
                    status VARCHAR(50) DEFAULT 'PENDING',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            conn.commit()
            logger.info("MySQL veritabanı şeması başarıyla oluşturuldu.")
    except Error as e:
        logger.error(f"MySQL Şema İlklendirme Hatası: {e}")
        

def translate_sql(query):
    """SQLite sorgu kalıplarını ve '?' parametrelerini MySQL %s formatına dönüştürür."""
    if not isinstance(query, str):
        return query
    q = query.replace("?", "%s")
    q = q.replace("INSERT OR REPLACE", "REPLACE")
    q = q.replace("INSERT OR IGNORE", "INSERT IGNORE")
    q = q.replace("AUTOINCREMENT", "AUTO_INCREMENT")
    
    if "PRAGMA table_info" in q:
        import re
        match = re.search(r'PRAGMA\s+table_info\s*\(\s*([a-zA-Z0-9_]+)\s*\)', q, re.IGNORECASE)
        if match:
            table_name = match.group(1)
            return f"DESCRIBE {table_name}"
    if "PRAGMA database_list" in q:
        return "SHOW DATABASES"
        
    return q


class MySQLDatabaseCursorWrapper:
    def __init__(self, connection, cursor):
        object.__setattr__(self, 'connection', connection)
        object.__setattr__(self, 'cursor', cursor)

    def execute(self, query, params=None):
        translated = translate_sql(query)
        if params is not None:
            return self.cursor.execute(translated, params)
        return self.cursor.execute(translated)

    def executemany(self, query, params_seq):
        translated = translate_sql(query)
        return self.cursor.executemany(translated, params_seq)

    def __getattr__(self, name):
        return getattr(self.cursor, name)

    def __setattr__(self, name, value):
        return setattr(self.cursor, name, value)


@contextmanager
def get_mysql_db():
    """Thread-safe MySQL bağlantı yöneticisi."""
    conn = mysql.connector.connect(**DB_CONFIG)
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        if conn.is_connected():
            conn.close()


class MySQLDatabase:
    def __init__(self, config=DB_CONFIG):
        self.config = config if isinstance(config, dict) else DB_CONFIG

    def __fspath__(self):
        return "entegrator_mysql_db"

    def __str__(self):
        return "MySQLDatabase"

    def init(self):
        init_db_mysql()

    def commit(self):
        with get_mysql_db() as conn:
            conn.commit()

    def rollback(self):
        with get_mysql_db() as conn:
            conn.rollback()

    @contextmanager
    def connect(self):
        with get_mysql_db() as conn:
            yield conn

    def cursor(self):
        # 🛡️ KRİTİK DÜZELTME: Bu metodun açtığı bağlantı, self.db.commit()'in açtığı bağlantıdan
        # FARKLIYDI. Yani "cursor = self.db.cursor(); cursor.execute(...); self.db.commit()" deseniyle
        # yapılan TÜM yazma işlemleri (örn. _record_failed_product, _clear_failed_product ve
        # buna benzer 20+ çağrı) hiçbir zaman gerçekten commit edilmiyordu; bağlantı kapanınca
        # (veya çöp toplanınca) sessizce rollback oluyordu. autocommit=True ile bu bağlantı
        # kendi yazdığını kendi commit eder, dışarıdaki self.db.commit() artık gereksiz ama zararsız.
        conn = mysql.connector.connect(**self.config)
        conn.autocommit = True
        raw_cursor = conn.cursor(dictionary=True)
        return MySQLDatabaseCursorWrapper(conn, raw_cursor)

    def query(self, sql, params=()):
        with get_mysql_db() as conn:
            cursor = conn.cursor(dictionary=True)
            translated_sql = translate_sql(sql)
            cursor.execute(translated_sql, params)
            return cursor.fetchall()

    def query_one(self, sql, params=()):
        with get_mysql_db() as conn:
            cursor = conn.cursor(dictionary=True)
            translated_sql = translate_sql(sql)
            cursor.execute(translated_sql, params)
            return cursor.fetchone()

    def scalar(self, sql, params=()):
        with get_mysql_db() as conn:
            cursor = conn.cursor()
            translated_sql = translate_sql(sql)
            cursor.execute(translated_sql, params)
            row = cursor.fetchone()
            return row[0] if row else None

    def execute(self, sql, params=()):
        with get_mysql_db() as conn:
            cursor = conn.cursor()
            translated_sql = translate_sql(sql)
            cursor.execute(translated_sql, params)
            conn.commit()
            return cursor.lastrowid

    def executemany(self, sql, params_seq):
        with get_mysql_db() as conn:
            cursor = conn.cursor()
            translated_sql = translate_sql(sql)
            cursor.executemany(translated_sql, params_seq)
            conn.commit()
            return cursor.rowcount

    def save_setting(self, key: str, value: str):
        sql = """
            INSERT INTO settings (`key`, `value`)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)
        """
        self.execute(sql, (key, value.strip()))

    def get_setting(self, key: str, default="") -> str:
        res = self.scalar("SELECT `value` FROM settings WHERE `key` = %s", (key,))
        return res if res is not None else default

    def save_api_keys(self, platform_name: str, app_key: str, app_secret: str, seller_id: str = "", extra_params: str = ""):
        plat = str(platform_name).strip().upper()
        sql = """
            INSERT INTO api_keys (platform, app_key, app_secret, seller_id, extra_params)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                app_key = VALUES(app_key),
                app_secret = VALUES(app_secret),
                seller_id = VALUES(seller_id),
                extra_params = VALUES(extra_params)
        """
        self.execute(sql, (plat, app_key, app_secret, seller_id, extra_params))

    def get_api_keys(self, platform_name: str) -> dict:
        plat = str(platform_name).strip().upper()
        row = self.query_one("SELECT app_key, app_secret, seller_id, extra_params FROM api_keys WHERE platform = %s", (plat,))
        if row:
            app_key = row["app_key"] or ""
            app_secret = row["app_secret"] or ""
            seller_id = row["seller_id"] or ""
            extra_params = row["extra_params"] or ""
            return {
                "app_key": app_key, "app_secret": app_secret,
                "api_key": app_key, "api_secret": app_secret,
                "seller_id": seller_id, "supplier_id": seller_id, "extra_params": extra_params
            }
        return {"app_key": "", "app_secret": "", "api_key": "", "api_secret": "", "seller_id": "", "supplier_id": "", "extra_params": ""}

    def save_product(self, code, title, brand="", barcode="", price=0.0, stock=0, tax=18.0, mainCategory="", category="", subCategory="", images="", details="", color="", gender="", origin="", supplier="", size="", main_code=""):
        try:
            junk = {"", "nan", "none", "genel", "null", "general"}
            parts = []
            
            # Excel'den gelen ham kategorileri tek tek inceliyoruz
            for f in (mainCategory, category, subCategory):
                s = str(f or "").strip()
                if not s or s.lower() in junk:
                    continue
                # 🛡️ KESİN FİLTRE: Eğer gelen metin şifreli kodsa veritabanına sokma, atla!
                if s.startswith("c_") or s.startswith("m_") or "_" in s or len(s) == 8:
                    continue
                parts.append(s)
                    
            clean = []
            for p in parts:
                if not clean or clean[-1].lower() != p.lower():
                    clean.append(p)
                    
            # 🎯 Hiyerarşiyi strictly 3 kolon düzenine kırıyoruz
            if len(clean) >= 3:
                m_brut = clean[0]
                c_brut = clean[1]
                sub_brut = " > ".join(clean[2:])
            elif len(clean) == 2:
                m_brut = clean[0]
                c_brut = clean[1]
                sub_brut = ""
            elif len(clean) == 1:
                m_brut = clean[0]
                c_brut = "Genel Kategori"
                sub_brut = ""
            else:
                # Eğer her şey şifreli kod çıkıp elendiyse Excel'deki ilk metne güven veya default ata
                m_brut = str(mainCategory or "Genel Mağaza").strip()
                c_brut = "Genel Kategori"
                sub_brut = ""

            # Eğer temizlenen değerlerde hala şifreli kod kalıntısı varsa son kez temizle
            if m_brut.startswith("c_") or m_brut.startswith("m_") or "_" in m_brut:
                m_brut = "Genel Mağaza"
            if c_brut.startswith("c_") or c_brut.startswith("m_") or "_" in c_brut:
                c_brut = "Genel Kategori"

            params = (
                str(code).strip(), str(main_code or code).strip(), str(title or "").strip(),
                str(brand or "").strip(), str(barcode or "").strip(), float(price or 0.0),
                int(stock or 0), float(tax or 18.0), str(m_brut).strip(), 
                str(c_brut).strip(), str(sub_brut).strip(), str(images or "").strip(), 
                str(details or "").strip(), str(color or "").strip(), str(gender or "").strip(), 
                str(origin or "").strip(), str(supplier or "").strip(), str(size or "").strip()
            )

            sql = """
                INSERT INTO products 
                (code, main_code, title, brand, barcode, price, stock, tax, mainCategory, category, subCategory, images, details, color, gender, origin, supplier, size)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    main_code = VALUES(main_code), title = VALUES(title), brand = VALUES(brand),
                    barcode = VALUES(barcode), price = VALUES(price), stock = VALUES(stock),
                    tax = VALUES(tax), mainCategory = VALUES(mainCategory), category = VALUES(category),
                    subCategory = VALUES(subCategory), images = VALUES(images), details = VALUES(details),
                    color = VALUES(color), gender = VALUES(gender), origin = VALUES(origin),
                    supplier = VALUES(supplier), size = VALUES(size)
            """
            self.execute(sql, params)
            return True
        except Exception as e:
            logger.error(f"MySQL ürün kaydetme hatası [{code}]: {e}")
            return False

        
    def get_all_products(self) -> list:
        try:
            sql = """
                SELECT 
                    code AS stock_code, COALESCE(main_code, code) AS main_code, 
                    COALESCE(title, '') AS title, COALESCE(brand, '') AS brand, 
                    COALESCE(barcode, '') AS barcode, COALESCE(price, 0.0) AS price, 
                    COALESCE(stock, 0) AS stock_quantity, COALESCE(tax, 18) AS tax,
                    COALESCE(mainCategory, '') AS mainCategory, COALESCE(category, '') AS category, 
                    COALESCE(subCategory, '') AS subCategory, COALESCE(images, '') AS images,
                    COALESCE(details, '') AS details, COALESCE(color, '') AS color, 
                    COALESCE(gender, '') AS gender, COALESCE(origin, '') AS origin, 
                    COALESCE(supplier, '') AS supplier, COALESCE(size, '') AS size, 
                    COALESCE(is_mapped, 0) AS is_mapped
                FROM products
                ORDER BY updated_at DESC
            """
            return self.query(sql)
        except Exception as e:
            logger.error(f"Ürünler çekilirken hata: {e}")
            return []

    def get_products(self) -> list:
        return self.get_all_products()

    def save_category_mapping(self, local_category, n11_category_id, template_name="", n11_category_name="", platform="N11", store_id="N11", template_id=None, catalog_id="", catalog_status="READY"):
        """[TAMİR EDİLDİ - %100 MYSQL UYUMLU] Kategori eşleştirmelerini NameError vermeden güvenle kaydeder."""
        try:
            l_cat = str(local_category or "").strip()
            n_cat_id = str(n11_category_id or "").strip()
            t_name = str(template_name or "").strip()
            n_cat_name = str(n11_category_name or "").strip()
            plat = str(platform or "N11").strip()
            s_id = str(store_id or "N11").strip()
            c_id = str(catalog_id or "").strip()
            c_status = str(catalog_status or "READY").strip()
            
            t_id = None
            if template_id is not None and str(template_id).strip() != "" and str(template_id).lower() != "none":
                try:
                    t_id = int(template_id)
                except ValueError:
                    t_id = None

            # 🛡️ SQLite 'with get_db()' kalkanı kaldırıldı, merkezi MySQL execute motoruna bağlandı
            sql = """
                INSERT INTO n11_category_mappings 
                (local_category, n11_category_id, template_name, n11_category_name, platform, store_id, template_id, catalog_id, catalog_status, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE
                    n11_category_id = VALUES(n11_category_id),
                    template_name = VALUES(template_name),
                    n11_category_name = VALUES(n11_category_name),
                    template_id = VALUES(template_id),
                    catalog_id = VALUES(catalog_id),
                    catalog_status = VALUES(catalog_status),
                    updated_at = CURRENT_TIMESTAMP
            """
            self.execute(sql, (l_cat, n_cat_id, t_name, n_cat_name, plat, s_id, t_id, c_id, c_status))
            return True
        except Exception as e:
            print(f"❌ Kategori eşleştirme kaydetme hatası: {e}")
            return False

    def save_product_attribute(self, product_code=None, attr_id=None, attr_name=None, val_id=None, custom_val="", is_mandatory=0, is_variant=0, is_custom=0, **kwargs):
        """[TAMİR EDİLDİ - %100 MYSQL UYUMLU] Ürün genel üst niteliklerini NameError fırlatmadan mühürler."""
        try:
            p_code = str(product_code or kwargs.get("product_code", "")).strip()
            a_id = str(attr_id or kwargs.get("attribute_id") or kwargs.get("n11_attribute_id", "")).strip()
            a_name = str(attr_name or kwargs.get("attribute_name") or kwargs.get("n11_attribute_name", "")).strip()
            v_id = str(val_id or kwargs.get("value_id") or kwargs.get("n11_value_id", "")).strip()
            c_val = str(custom_val or kwargs.get("custom_value", "")).strip()
            
            try:
                mandatory = int(is_mandatory or kwargs.get("is_mandatory", 0))
            except (ValueError, TypeError):
                mandatory = 0

            try:
                variant = int(is_variant or kwargs.get("is_variant", 0))
            except (ValueError, TypeError):
                variant = 0

            try:
                custom = int(is_custom or kwargs.get("is_custom", 0))
            except (ValueError, TypeError):
                custom = 0

            # 🛡️ SQLite bağlantı bağımlılığı temizlendi, thread-safe MySQL havuzuna yönlendirildi
            sql = """
                INSERT INTO product_attributes 
                (product_code, n11_attribute_id, n11_attribute_name, n11_value_id, custom_value, is_mandatory, is_variant, is_custom)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            self.execute(sql, (p_code, a_id, a_name, v_id, c_val, mandatory, variant, custom))
            return True
        except Exception as e:
            print(f"❌ Ürün özelliği kaydetme hatası: {e}")
            return False


    def save_n11_task(self, task_id, stock_code, main_code=""):
        """[MÜHÜRLENDİ] NameError vermeden N11 görevlerini MySQL tablosuna hatasız mühürler."""
        try:
            sql = """
                INSERT INTO n11_tasks (task_id, stock_code, main_code, status)
                VALUES (%s, %s, %s, 'PENDING')
                ON DUPLICATE KEY UPDATE status = 'PENDING'
            """
            # Sınıfın kendi içindeki thread-safe execute metodunu çağırıyoruz
            self.execute(sql, (str(task_id), str(stock_code), str(main_code or stock_code)))
            
            # Eğer ürün önceden hatalı masasındaysa onu oradan temizle
            self.execute("DELETE FROM n11_failed_products WHERE stock_code = %s", (str(main_code or stock_code),))
            return True
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"❌ [N11 Task Kayıt Hatası] {task_id}: {e}")
            print(f"❌ [N11 Task Kayıt Hatası] {task_id}: {e}")
            return False

    def check_and_add_columns(self):
        """Eksik kolonları veritabanına dinamik olarak ekler (Migration)."""
        cursor = self.connection.cursor()
        try:
            cursor.execute("SHOW COLUMNS FROM n11_tasks LIKE 'batch_request_id'")
            result = cursor.fetchone()

            if not result:
                cursor.execute(
                    "ALTER TABLE n11_tasks ADD COLUMN batch_request_id VARCHAR(255) NULL;"
                )
            self.connection.commit()
            print("✅ 'batch_request_id' sütunu n11_tasks tablosuna eklendi.")
        except Exception as e:
            print(f"⚠️ Sütun kontrolü sırasında bir hata oluştu: {e}")
        finally:
            cursor.close()

    # --- PTTAVM İDEASOFT TABLO VE KAYIT METOTLARI ---
    def create_pttavm_ideasoft_table(self):
        """PttAVM IdeaSoft Excel ürünleri için tablo oluşturur."""
        try:
            sql = """
                CREATE TABLE IF NOT EXISTS pttavm_ideasoft_products (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    product_code VARCHAR(100),
                    barcode VARCHAR(100),
                    name VARCHAR(255),
                    price DECIMAL(10, 2) DEFAULT 0.00,
                    stock INT DEFAULT 0,
                    category VARCHAR(150),
                    brand VARCHAR(100),
                    description TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
            self.execute(sql)
            return True
        except Exception as e:
            logger.error(f"PttAVM IdeaSoft tablo oluşturma hatası: {e}")
            return False

    def save_pttavm_products_batch(self, products_list):
        print(">>> TEST: save_pttavm_products_batch metodunun içine girildi!") # <--- Bunu ekle
        """Ürünleri veritabanına toplu ve güvenli bir şekilde (parçalar halinde) kaydeder."""
        try:
            if not products_list:
                return True
                
            sql = """
                INSERT INTO pttavm_ideasoft_products 
                (product_code, barcode, name, price, stock, category, brand, description) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                barcode=VALUES(barcode),
                name=VALUES(name),
                price=VALUES(price),
                stock=VALUES(stock),
                category=VALUES(category),
                brand=VALUES(brand),
                description=VALUES(description)
            """
            
            # Verileri 100'erli paketler halinde (chunk) gönderiyoruz ki MySQL şişmesin
            batch_size = 100
            total = len(products_list)
            
            with get_mysql_db() as conn:
                cursor = conn.cursor()
                for i in range(0, total, batch_size):
                    batch = products_list[i:i + batch_size]
                    values = []
                    for p in batch:
                        values.append((
                            p.get("product_code"),
                            p.get("barcode"),
                            p.get("name"),
                            p.get("price", 0.0),
                            p.get("stock", 0),
                            p.get("category"),
                            p.get("brand"),
                            p.get("description")
                        ))
                    cursor.executemany(sql, values)
                    conn.commit()
                    print(f"[MySQL] PttAVM ürünleri aktarılıyor... {min(i + batch_size, total)} / {total}")
                cursor.close()
                
            print("[MySQL] Tüm PttAVM ürünleri başarıyla veritabanına kaydedildi.")
            return True
        except Exception as e:
            logger.error(f"MySQL Kayıt Hatası: {e}")
            print(f"[MySQL Kayıt Hatası]: {e}")
            return False
    
        
MySQLDatabaseManager = MySQLDatabase
get_mysql_connection = get_mysql_db