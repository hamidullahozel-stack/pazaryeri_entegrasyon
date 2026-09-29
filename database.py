# Dosya Yolu: 1database.py
# İşlem Tarihi: 21 Eylül 2026
# Açıklama: Geriye Dönük Uyumluluk Sarmalayıcısı (MySQL Yönlendirici)

from mysql_database import (
    MySQLDatabase as Database,
    MySQLDatabaseManager as DatabaseManager,
    get_mysql_db as get_db,
    get_mysql_db as get_db_connection,
    init_db_mysql as init_db
)

__all__ = ["Database", "DatabaseManager", "get_db", "get_db_connection", "init_db"]