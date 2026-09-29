# Dosya: product_frame.py
# İşlem Tarihi: 21 Eylül 2026 / MySQL Uyumlu Kararlı Sürüm

import tkinter as tk
from tkinter import messagebox, filedialog
import customtkinter as ctk
import pandas as pd
import re 
from mysql_database import MySQLDatabase as Database, MySQLDatabaseManager as DatabaseManager, get_mysql_db as get_db_connection
from ui.datatable import DataTable

class ProductManagementFrame(ctk.CTkFrame):
    """
    Tüm Pazaryerleri Tarafından Ortak Kullanılan
    Merkezi Mağaza Ürün ve Stok Yönetimi Ekranı (MySQL Uyumlu).
    """

    def __init__(self, parent, db: Database):
        super().__init__(parent)
        self.db = db

        self.current_page = 1
        self.items_per_page = 50
        self.filtered_products = []
        self.all_products = []

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_ui()
        self.load_products()

    def _build_ui(self):
        # 1. Üst Kontrol Paneli (Pazaryeri Seçimi, Arama, Excel Yükleme)
        top_frame = ctk.CTkFrame(self)
        top_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)


        # Mağaza Ürün ve Stok Listesi Başlığı
        lbl_title = ctk.CTkLabel(top_frame, text="Magaza Urun ve Stok Listesi", font=ctk.CTkFont(size=15, weight="bold"))
        lbl_title.pack(side="left", padx=(20, 10))

        # Arama Kutusu
        self.entry_search = ctk.CTkEntry(top_frame, placeholder_text="Kod, isim veya marka ile ara...", width=320)
        self.entry_search.pack(side="left", padx=10)
        self.entry_search.bind("<KeyRelease>", self.filter_products)

        # Excel / Stok Dosyası Yükle Butonu
        btn_upload = ctk.CTkButton(
            top_frame,
            text="Excel / Stok Dosyasi Yukle",
            fg_color="#1b5e20",
            hover_color="#2e7d32",
            command=self.upload_excel
        )
        btn_upload.pack(side="right", padx=10)

        # 2. Veri Tablosu (DataTable)
        self.columns = [
            #("ID", "ID", 80, "center"),
            ("STOK_KODU", "STOK KODU", 130, "center"),
            ("URUN_KODU", "ÜRÜN KODU", 130, "center"),
            ("BARKOD", "BARKOD", 140, "center"),
            ("KATEGORI", "KATEGORİ", 120, "w"),
            ("URUN_ADI", "ÜRÜN ADI", 280, "w"),
            ("RENK", "RENK", 90, "center"),
            ("BEDEN", "BEDEN", 90, "center"),
            ("STOK", "STOK", 80, "center"),
            ("KDV", "KDV", 80, "center"),
            ("KDV_HARIC_FIYAT", "KDV HARİÇ FİYAT", 120, "e"),
            ("KDV_DAHIL_FIYAT", "KDV DAHİL FİYAT", 120, "e"),
            ("MARKA", "MARKA", 130, "w"),
            ("FIYAT_1", "FİYAT 1", 110, "e"),
            ("FIYAT_2", "FİYAT 2", 110, "e"),
            ("GORSEL_1", "GÖRSEL 1", 120, "w"),
            ("GORSEL_2", "GÖRSEL 2", 120, "w"),
            ("GORSEL_3", "GÖRSEL 3", 120, "w"),
            ("GORSEL_4", "GÖRSEL 4", 120, "w"),
            ("KATEGORI_ID", "KATEGORİ ID", 100, "center"),
            ("ALT_KATEGORI", "ALT KATEGORİ", 150, "w"),
            ("CATEGORY_TREE", "categoryTree", 180, "w"),
            ("CATEGORY_LABEL", "productCategoryLabel", 180, "w"),
            ("PRODUCT_LINK", "productLink", 200, "w")
        ]
        self.table = DataTable(self, columns=self.columns)
        self.table.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)

        # 3. Alt Sayfalama (Pagination) Paneli
        bottom_frame = ctk.CTkFrame(self)
        bottom_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=10)

        self.btn_prev = ctk.CTkButton(bottom_frame, text="Önceki Sayfa", width=120, command=self.prev_page)
        self.btn_prev.pack(side="left", padx=10)

        self.lbl_page_info = ctk.CTkLabel(bottom_frame, text="Sayfa: 1 / 1 (Toplam: 0)", font=ctk.CTkFont(size=13, weight="bold"))
        self.lbl_page_info.pack(side="left", expand=True)

        self.btn_next = ctk.CTkButton(bottom_frame, text="Sonraki Sayfa", width=120, command=self.next_page)
        self.btn_next.pack(side="right", padx=10)

    def on_platform_changed(self, selected_platform):
        self.load_products()

    def load_products(self):
        """🛡️ [ARAYÜZ FİLTRE KALKANI]
        products tablosundan varyant satırlarını tamamen eler, ekranda SADECE ANA ÜRÜNLERİ listeler.
        """
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("""
                    SELECT 
                        code AS stock_code, 
                        COALESCE(main_code, code) AS main_code, 
                        COALESCE(title, '') AS title, 
                        COALESCE(brand, '') AS brand, 
                        COALESCE(barcode, '') AS barcode, 
                        COALESCE(price, 0.0) AS price, 
                        COALESCE(stock, 0) AS stock_quantity, 
                        COALESCE(tax, 18) AS tax,
                        COALESCE(mainCategory, '') AS mainCategory, 
                        COALESCE(category, '') AS category, 
                        COALESCE(subCategory, '') AS subCategory, 
                        COALESCE(images, '') AS images,
                        COALESCE(details, '') AS details, 
                        COALESCE(color, '') AS color, 
                        COALESCE(gender, '') AS gender, 
                        COALESCE(origin, '') AS origin, 
                        COALESCE(supplier, '') AS supplier, 
                        COALESCE(size, '') AS size, 
                        COALESCE(is_mapped, 0) AS is_mapped
                    FROM products
                    WHERE code = main_code OR main_code = '' OR main_code IS NULL
                    ORDER BY updated_at DESC
                """)
                self.all_products = list(cursor.fetchall())
            self.filter_products()
        except Exception as e:
            messagebox.showerror("Hata", f"Ürünler yüklenirken hata oluştu: {e}")

    def filter_products(self, event=None):
        query = self.entry_search.get().strip().lower()
        if query:
            self.filtered_products = []
            for p in self.all_products:
                stock_code = str(p.get("stock_code", "")).lower()
                barcode = str(p.get("barcode", "")).lower()
                title = str(p.get("title", "")).lower()
                brand = str(p.get("brand", "")).lower()
                category = str(p.get("mainCategory", "")).lower()
                product_code = str(p.get("product_code", "")).lower()

                if len(query) == 1:
                    matched = (
                        stock_code.startswith(query) or
                        barcode.startswith(query) or
                        any(word.startswith(query) for word in title.split()) or
                        any(word.startswith(query) for word in brand.split()) or
                        category.startswith(query)
                    )
                else:
                    matched = (
                        query in stock_code or
                        query in barcode or
                        query in title or
                        query in brand or
                        query in category or
                        query in product_code
                    )

                if matched:
                    self.filtered_products.append(p)
        else:
            self.filtered_products = list(self.all_products)

        self.current_page = 1
        self.render_table()

    def render_table(self):
        total_items = len(self.filtered_products)
        total_pages = max(1, (total_items + self.items_per_page - 1) // self.items_per_page)

        if self.current_page > total_pages:
            self.current_page = total_pages

        start_idx = (self.current_page - 1) * self.items_per_page
        end_idx = start_idx + self.items_per_page
        page_items = self.filtered_products[start_idx:end_idx]

        formatted_rows = []

        for item in page_items:
            m_code = item.get("code") or item.get("stock_code") or ""
            
            excl_val = float(item.get("price") or 0.0) 
            tax_rate = float(item.get("tax") or 20.0)
            
            price_val = excl_val * (1.0 + (tax_rate / 100.0)) if tax_rate > 0 else excl_val

            # Kategori hiyerarşisini oluşturan yardımcı yapı
            main_cat = str(item.get("mainCategory", "")).strip()
            mid_cat = str(item.get("category", "")).strip()
            sub_cat = str(item.get("subCategory", "")).strip()

            # mainCategory > category > subCategory şeklinde dinamik ağaç yapısı oluşturma
            category_parts = [p for p in [main_cat, mid_cat, sub_cat] if p and p != "nan"]
            category_tree_str = " > ".join(category_parts)

            # Görsel yollarını güvenli bir şekilde ayırma
            images_raw = str(item.get("images") or "")
            image_list = [img.strip() for img in images_raw.split(",") if img.strip()]

            formatted_rows.append({
                #"ID": "",
                "STOK_KODU": str(m_code),
                "URUN_KODU": str(item.get("main_code") or m_code),
                "BARKOD": str(item.get("barcode") or ""),
                "KATEGORI": mid_cat if mid_cat else main_cat, # Orta kategori veya ana kategori
                "URUN_ADI": str(item.get('title', '')), 
                "RENK": str(item.get("color") or "-"), 
                "BEDEN": str(item.get("size") or "-"), 
                "STOK": str(item.get("stock_quantity") or 0),
                "KDV": str(int(tax_rate)),
                "KDV_HARIC_FIYAT": f"{excl_val:.2f}",
                "KDV_DAHIL_FIYAT": f"{price_val:.2f}",
                "MARKA": str(item.get("brand") or ""),
                "FIYAT_1": f"{price_val:.2f}",
                "FIYAT_2": f"{price_val:.2f}",
                "KATEGORI_ID": str(item.get("category_id") or ""),
                "ALT_KATEGORI": sub_cat, # En alt kategori
                "CATEGORY_TREE": category_tree_str, # Örn: Çanta > Sırt Çantaları > ...
                "CATEGORY_LABEL": main_cat,
                "GORSEL_1": image_list[0] if len(image_list) > 0 else "",
                "GORSEL_2": image_list[1] if len(image_list) > 2 else "",
                "GORSEL_3": image_list[2] if len(image_list) > 3 else "",
                "GORSEL_4": image_list[3] if len(image_list) > 4 else "",
                "PRODUCT_LINK": ""
            })        
        self.table.set_data(formatted_rows)
        self.lbl_page_info.configure(text=f"Sayfa: {self.current_page} / {total_pages} (Toplam Ana Ürün: {total_items})")

    def prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.render_table()

    def next_page(self):
        total_items = len(self.filtered_products)
        total_pages = max(1, (total_items + self.items_per_page - 1) // self.items_per_page)
        if self.current_page < total_pages:
            self.current_page += 1
            self.render_table()

    def upload_excel(self):
        file_path = filedialog.askopenfilename(
            title="Excel / Stok Dosyası Seçin",
            filetypes=[("Excel Dosyaları", "*.xlsx *.xls *.csv"), ("Tüm Dosyalar", "*.*")]
        )
        if not file_path:
            return

        try:
            if file_path.endswith('.csv'):
                df = pd.read_csv(file_path, dtype=str)
            else:
                xls = pd.ExcelFile(file_path)
                df = pd.read_excel(file_path, sheet_name=xls.sheet_names[0], dtype=str)

            df.fillna("", inplace=True)

            def tr_upper(text):
                text = str(text)
                rep = {'i': 'İ', 'ı': 'I', 'ç': 'Ç', 'ğ': 'Ğ', 'ö': 'Ö', 'ş': 'Ş', 'ü': 'Ü'}
                for k, v in rep.items():
                    text = text.replace(k, v)
                return text.upper()

            col_map = {}
            rules = [
                ("color", ["variantValue1"]),
                ("size", ["variantValue2"]),
                ("images", ["picture1Path", "PICTURE1PATH", "picture1path"]),
                ("barcode", ["BARKOD", "BARCODE", "EAN", "GTIN"]),
                ("stock_code", ["STOCKCODE", "STOK KODU", "STOK KOD", "SKU", "stockCode"]),
                ("product_code", ["rootProductStockCode", "ÜRÜN KODU", "URUN KODU", "MODEL KODU"]),
                ("mainCategory", ["MAINCATEGORY", "ANA KATEGORİ", "mainCategory"]),
                ("category", ["CATEGORY", "KATEGORİ", "category"]),
                ("subCategory", ["SUBCATEGORY", "ALT KATEGORİ", "subCategory"]),
                ("title", ["LABEL", "URUN ADI", "ÜRÜN ADI", "label"]),
                ("brand", ["BRAND", "MARKA", "brand"]),
                ("variant_name1", ["variantName1"]),
                ("variant_value1", ["variantValue1"]),
                ("variant_name2", ["variantName2"]),
                ("variant_value2", ["variantValue2"]),
                ("picture2", ["picture2Path", "GÖRSEL 2"]),
                ("picture3", ["picture3Path", "GÖRSEL 3"]),
                ("picture4", ["picture4Path", "GÖRSEL 4"]),
                ("price", ["price2", "PRICEWITHTAX", "price1"]),
                ("tax", ["tax", "KDV", "KDV ORANI"]),
                ("stock", ["stockAmount", "STOCK", "QUANTITY"])
            ]

            for field, keywords in rules:
                for col in df.columns:
                    if col in col_map.values():
                        continue
                    
                    c_clean = tr_upper(col).strip()
                    
                    if field in ["mainCategory", "category", "subCategory"]:
                        if "DISTCODE" in c_clean or "KOD" in c_clean or "CODE" in c_clean:
                            continue

                    if any(tr_upper(kw) == c_clean or tr_upper(kw) in c_clean for kw in keywords):
                        col_map[field] = col
                        break

            # 🧠 [1. ETAP - ANA ÜRÜN İSİMLERİNİ ÖNBELLEĞE ALMA]
            excel_titles_cache = {}
            for _, row in df.iterrows():
                sc = str(row.get(col_map.get("stock_code"), "")).strip()
                rc = str(row.get(col_map.get("product_code"), "")).strip()
                lbl = str(row.get(col_map.get("title"), "")).strip()
                if lbl and (not rc or rc == "0" or rc == "" or rc == sc):
                    excel_titles_cache[sc] = lbl

            saved_products_count = 0
            
            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Eski hatalı/artık satırları temizleme
                cursor.execute("""
                    DELETE FROM products 
                    WHERE main_code != code 
                      AND main_code IS NOT NULL 
                      AND main_code != '' 
                      AND main_code != '0'
                """)

                # 🔄 [2. ETAP - VERİ AKTARIMI VE İSİM BİRLEŞTİRME]
                for _, row in df.iterrows():
                    stock_code = str(row.get(col_map.get("stock_code"), "")).strip()
                    if not stock_code:
                        continue
                    
                    product_code = str(row.get(col_map.get("product_code"), "")).strip()
                    if not product_code or product_code == "0":
                        product_code = stock_code
                        
                    raw_title = str(row.get(col_map.get("title"), "")).strip()
                    brand = str(row.get(col_map.get("brand"), "")).strip()
                    barcode = str(row.get(col_map.get("barcode"), "")).strip()
                    main_cat = str(row.get(col_map.get("mainCategory"), "")).strip()
                    mid_cat = str(row.get(col_map.get("category"), "")).strip()
                    sub_cat = str(row.get(col_map.get("subCategory"), "")).strip()
                    
                    v_val1 = str(row.get(col_map.get("variant_value1"), "")).strip()
                    v_val2 = str(row.get(col_map.get("variant_value2"), "")).strip()
                    
                    # Ana ürün başlığını bul
                    main_title = excel_titles_cache.get(product_code) or excel_titles_cache.get(stock_code) or raw_title
                    if not main_title:
                        main_title = brand or "Standart Ürün"
                        
                    is_main = (stock_code == product_code or not product_code or product_code == stock_code)

                    # Eğer varyant satırındaysak ve ayrı bir variantValue1 yoksa, raw_title'ı renk/varyant kabul edelim
                    if not is_main and not v_val1 and raw_title and raw_title != main_title:
                        v_val1 = raw_title

                    details_list = []
                    if v_val1 and v_val1.lower() not in ["none", "nan", "", "0", "standart"]:
                        details_list.append(v_val1)
                    if v_val2 and v_val2.lower() not in ["none", "nan", "", "0", "standart"]:
                        details_list.append(v_val2)
                        
                    if not details_list:
                        if raw_title and raw_title.lower() != "urun" and raw_title != main_title:
                            details_list.append(raw_title)
                        else:
                            details_list.append("Standart Seçenek")
                            
                    v_details = " / ".join(details_list)
                    
                    # 🎯 ANA ÜRÜN ADINI VARYANTLA BİRLEŞTİRME
                    if is_main:
                        final_title = main_title
                        main_code_val = stock_code
                    else:
                        if main_title.lower() in raw_title.lower():
                            final_title = raw_title
                        else:
                            final_title = f"{main_title} - {v_details}"
                        main_code_val = product_code
                        
                    images = str(row.get(col_map.get("images"), "")).strip()
                    
                    try:
                        price = float(row.get(col_map.get("price"), 0.0) or 0.0)
                    except ValueError:
                        price = 0.0
                        
                    try:
                        stock = int(float(row.get(col_map.get("stock"), 0) or 0))
                    except ValueError:
                        stock = 0
                        
                    try:
                        tax_str = str(row.get(col_map.get("tax"), "20")).replace("%", "").strip()
                        tax = float(tax_str) if tax_str else 20.0
                    except ValueError:
                        tax = 20.0

                    cursor.execute("""
                        INSERT INTO products 
                        (code, main_code, title, brand, barcode, price, stock, tax, mainCategory, category, subCategory, images, details, color, size, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON DUPLICATE KEY UPDATE
                            main_code = VALUES(main_code),
                            title = VALUES(title),
                            brand = VALUES(brand),
                            barcode = VALUES(barcode),
                            price = VALUES(price),
                            stock = VALUES(stock),
                            tax = VALUES(tax),
                            mainCategory = VALUES(mainCategory),
                            category = VALUES(category),
                            subCategory = VALUES(subCategory),
                            images = VALUES(images),
                            details = VALUES(details),
                            color = VALUES(color),
                            size = VALUES(size),
                            updated_at = CURRENT_TIMESTAMP
                    """, (
                        stock_code, main_code_val, final_title, brand, barcode, price, stock, tax,
                        main_cat, mid_cat, sub_cat, images, v_details, v_val1, v_val2  # <--- mid_cat düzeltmesi yapıldı
                    ))
                    saved_products_count += 1

                # 🧹 [3. ETAP - VERİTABANINDAKİ MEVCUT EKSİK İSİMLERİ DÜZELTME]
                cursor.execute("""
                    SELECT code, main_code, title, details FROM products 
                    WHERE main_code != code AND main_code IS NOT NULL AND main_code != ''
                """)
                variants = cursor.fetchall()
                for v in variants:
                    if isinstance(v, dict):
                        v_code = v.get("code")
                        m_code = v.get("main_code")
                        curr_title = v.get("title", "")
                        details = v.get("details", "")
                    else:
                        v_code = v[0]
                        m_code = v[1]
                        curr_title = v[2] if len(v) > 2 else ""
                        details = v[3] if len(v) > 3 else ""
                    
                    cursor.execute("SELECT title FROM products WHERE code = %s", (m_code,))
                    main_row = cursor.fetchone()
                    if main_row:
                        m_title = main_row.get("title") if isinstance(main_row, dict) else main_row[0]
                        if m_title and not curr_title.startswith(m_title):
                            if details and details != "Standart Seçenek":
                                new_title = f"{m_title} - {details}"
                            else:
                                new_title = f"{m_title} - {curr_title}"
                            cursor.execute("UPDATE products SET title = %s WHERE code = %s", (new_title, v_code))

                conn.commit()
                
            messagebox.showinfo("Başarılı", f"Toplam {saved_products_count} ürün yüklendi ve mevcut varyant isimleri ana ürün adıyla güncellendi.")
            self.load_products()
            
        except Exception as e:
            messagebox.showerror("Hata", f"İşlem sırasında hata oluştu:\n{e}")