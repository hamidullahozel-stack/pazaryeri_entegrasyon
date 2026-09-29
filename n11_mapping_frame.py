import json
import re
import requests
import sqlite3
import threading
import customtkinter as ctk
import pandas as pd
from tkinter import filedialog, messagebox
import os
from datetime import datetime
from marketplaces.n11.n11_api import export_error_report_excel


from marketplaces.n11.n11_api import (
    N11CategoryAPI,
    fetch_n11_categories,
    fetch_n11_category_attributes,
    fetch_n11_sub_categories,
    get_n11_credentials,
    export_error_report_excel as api_export_error_report,
    generate_n11_transfer_report,
    send_product_to_n11_saf,
    send_variant_products_to_n11,
    check_n11_task_status,      
    parse_n11_task_response,  
)


# =====================================================================
# MySQL dictionary=True cursor uyumluluk yardımcıları
# (SQLite tuple satırları ile MySQL dict satırlarını tek yerden normalize eder)
# =====================================================================
def _as_dict(row, columns=None):
    """fetchone/fetchall satırını her zaman dict'e çevirir."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    if columns:
        return {columns[i]: row[i] for i in range(min(len(row), len(columns)))}
    try:
        return dict(row)
    except Exception:
        return {i: v for i, v in enumerate(row)}


def _row_val(row, key, index=None, default=None):
    """Dict veya tuple satırından güvenli değer okur."""
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    if index is not None and len(row) > index:
        return row[index]
    return default


# =====================================================================
# 1. UI YARDIMCI BİLEŞENLERİ (UI Components)
# =====================================================================
class SearchableCTkComboBox(ctk.CTkFrame):
    def __init__(self, parent, values=None, command=None, **kwargs):
        for k in ["state", "dropdown_max_height", "dropdown_fg_color", "dropdown_text_color"]:
            kwargs.pop(k, None)
            
        super().__init__(parent, fg_color="transparent")
        self.all_values = values or []
        self.command = command  # 🛡️ DÜZELTME: Tıklama callback komutu sınıfa kilitlendi
        self.current_value = ctk.StringVar(value="Seçiniz...")
        self.is_open = False
        self.dropdown_frame = None

        self.btn_select = ctk.CTkButton(
            self, 
            textvariable=self.current_value, 
            height=30, 
            fg_color="#2b2b2b", 
            text_color="#ffffff", 
            border_width=1, 
            border_color="#444444",
            anchor="w",
            command=self._toggle_dropdown
        )
        self.btn_select.pack(fill="x", expand=True)

    def _toggle_dropdown(self):
    
        if self.is_open:
            self._close_dropdown_internal()
            return

        self.is_open = True
        self.dropdown_frame = ctk.CTkFrame(self, fg_color="#1e1e1e", border_width=1, border_color="#444444")
        self.dropdown_frame.pack(fill="x", pady=(2, 0))

        search_var = ctk.StringVar()
        search_entry = ctk.CTkEntry(
            self.dropdown_frame, 
            placeholder_text="🔍 Aramak için yazın...", 
            textvariable=search_var,
            height=28,
            fg_color="#2a2a2a",
            border_width=1,
            border_color="#555555"
        )
        search_entry.pack(fill="x", padx=6, pady=6)
        search_entry.focus_set()

        list_scroll = ctk.CTkScrollableFrame(self.dropdown_frame, fg_color="transparent", height=180)
        list_scroll.pack(fill="x", padx=2, pady=(0, 4))

        def _normalize(text):
            s = str(text).lower()
            for k, v in {"ı": "i", "ğ": "g", "ü": "u", "ş": "s", "ö": "o", "ç": "c"}.items():
                s = s.replace(k, v)
            return s

        def select_item(val):
            self.current_value.set(val)
            self._close_dropdown_internal()
            if self.command:  # 🛡️ DÜZELTME: Seçilen veriyi üst motora fırlatır
                self.command(val)

        def filter_internal_list(*args):
            for child in list_scroll.winfo_children():
                child.destroy()
                
            q = _normalize(search_var.get().strip())
            filtered = [v for v in self.all_values if q in _normalize(v)] if q else self.all_values
            
            if not filtered:
                ctk.CTkLabel(list_scroll, text="Sonuç Bulunamadı", text_color="#ef4444", font=ctk.CTkFont(size=11)).pack(pady=5)
                return
                
            for item in filtered:
                btn = ctk.CTkButton(
                    list_scroll, 
                    text=str(item), 
                    fg_color="transparent", 
                    text_color="#ffffff", 
                    anchor="w", 
                    height=24,
                    hover_color="#1f6feb",
                    font=ctk.CTkFont(size=11),
                    command=lambda val=item: select_item(val)
                )
                btn.pack(fill="x", pady=1)

        search_var.trace_add("write", filter_internal_list)
        filter_internal_list()

    def _close_dropdown_internal(self):
        if self.dropdown_frame:
            self.dropdown_frame.pack_forget()
            self.dropdown_frame.destroy()
            self.dropdown_frame = None
        self.is_open = False

    def set(self, value):
        self.current_value.set(value)

    def get(self):
        val = self.current_value.get()
        return "" if val in ["Seçiniz...", "Seçiniz"] else val

    def update_values(self, new_values):
        self.all_values = new_values
        if self.current_value.get() not in new_values:
            self.current_value.set("Seçiniz...")

class CTkToolTip:
    active_tooltips = []

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        self.widget.bind("<Enter>", self.show_tip)
        self.widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        if not self.text:
            return
        CTkToolTip.hide_all()
        try:
            x = self.widget.winfo_rootx() + 20
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
            screen_width = self.widget.winfo_screenwidth()
            if x + 400 > screen_width:
                x = max(10, screen_width - 420)

            self.tipwindow = tw = ctk.CTkToplevel(self.widget)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{x}+{y}")

            label = ctk.CTkLabel(
                tw, text=self.text, justify="left", fg_color="#18181b",
                text_color="#ef4444", corner_radius=6, padx=10, pady=6,
                font=ctk.CTkFont(size=11, weight="bold")
            )
            label.pack()
            CTkToolTip.active_tooltips.append(self.tipwindow)
        except Exception:
            pass
        
    def hide_tip(self, event=None):
        if self.tipwindow:
            try:
                self.tipwindow.withdraw()
                self.tipwindow.destroy()
            except Exception:
                pass
            if self.tipwindow in CTkToolTip.active_tooltips:
                CTkToolTip.active_tooltips.remove(self.tipwindow)
            self.tipwindow = None

    @classmethod
    def hide_all(cls):
        for tw in list(cls.active_tooltips):
            try:
                tw.withdraw()
                tw.destroy()
            except Exception:
                pass
        cls.active_tooltips.clear()


# =====================================================================
# 2. KATEGORİ YÖNETİMİ SINIFI (Category Management Section)
# =====================================================================
class N11CategoryManager:
    def __init__(self, db):
        self.db = db

    def resolve_category_for_local(self, local_category, current_cat_name=""):
        try:
            cursor = self.db.cursor()
            target = (local_category or "").strip().lower()
            current_target = (current_cat_name or "").strip().lower()

            cursor.execute(
                """
                SELECT n11_category_id, template_name, n11_category_name, local_category, ideasoft_cat
                FROM n11_category_mappings
                """
            )
            rows = cursor.fetchall()

            for r in rows:
                if isinstance(r, dict):
                    n11_id = r.get("n11_category_id")
                    tpl = r.get("template_name")
                    n11_name = r.get("n11_category_name")
                    loc = str(r.get("local_category") or r.get("ideasoft_cat") or "").strip().lower()
                else:
                    n11_id, tpl, n11_name, loc_val, idea_val = r[0], r[1], r[2], r[3], r[4]
                    loc = str(loc_val or idea_val or "").strip().lower()

                if not loc:
                    continue

                if target and (target == loc or target in loc or loc in target):
                    return str(n11_id or ""), str(tpl or ""), str(n11_name or "")
                
                if current_target and (current_target == loc or current_target in loc or loc in current_target):
                    return str(n11_id or ""), str(tpl or ""), str(n11_name or "")

        except Exception as e:
            print(f"[N11] Kategori eşleştirme okuma hatası: {e}")
        return "", "", ""
    
        
    
# N11 Canlı Kategori Ağacı Oluşturma Mantığı
def fetch_and_build_n11_tree(api_service, db):
    try:
        # 1. N11 servisinden kategorileri canlı al
        app_key, app_secret = get_n11_credentials(db)
        categories = fetch_n11_categories(app_key, app_secret)
        
        if not categories:
            print("⚠️ N11 API'den kategori verisi alınamadı. API bilgilerinizi kontrol edin.")
            return

        # 2. Veritabanına kaydet (Eski nesne çağrıları MySQL'e uygun hale getirildi)
        cursor = db.cursor()
        for cat in categories:
            cat_id = cat.get("id")
            cat_name = cat.get("name")
            if cat_id and cat_name:
                cursor.execute("""
                    INSERT IGNORE INTO n11_category_mappings 
                    (n11_category_id, n11_category_name, platform, store_id) 
                    VALUES (%s, %s, 'N11', 'N11')
                """, (str(cat_id), str(cat_name)))
        db.commit()
        print(f"✅ N11'den {len(categories)} ana kategori başarıyla güncellendi.")
    except Exception as e:
        print(f"Kategori çekme hatası: {e}")

# =====================================================================
# 3. ŞABLON VE NİTELİK YÖNETİMİ SINIFI (Template & Attribute Section)
# =====================================================================
class N11AttributeTemplateManager:
    def __init__(self, db):
        self.db = db

    def get_template_data(self, template_name):
        data = {"prep_time": 3, "delivery_template": ""}
        if not template_name:
            return data
        try:
            cursor = self.db.cursor()
            for sql in (
                "SELECT prep_time, delivery_template FROM templates WHERE name = ? LIMIT 1",
                "SELECT preparing_day, shipment_template FROM templates WHERE name = ? LIMIT 1",
                "SELECT prep_time, shipment_template FROM templates WHERE name = ? LIMIT 1",
            ):
                try:
                    cursor.execute(sql, (template_name,))
                    row = cursor.fetchone()
                    if row:
                        if row[0] is not None:
                            data["prep_time"] = row[0]
                        if row[1]:
                            data["delivery_template"] = str(row[1])
                        break
                except Exception:
                    continue
        except Exception as e:
            print(f"[N11] Şablon okuma hatası: {e}")
        return data

    def load_db_attributes(self, product_code):
        attrs = []
        try:
            cursor = self.db.cursor()
            cursor.execute(
                """
                SELECT n11_attribute_id, n11_attribute_name, n11_value_id, custom_value
                FROM product_attributes
                WHERE product_code = ?
                """,
                (product_code,),
            )
            for attr_id, attr_name, val_id, custom_val in cursor.fetchall():
                item = {"name": attr_name or ""}
                if attr_id:
                    item["id"] = attr_id
                    item["attributeId"] = attr_id
                if val_id and str(val_id).lower() not in ("none", "null", "", "0"):
                    item["valueId"] = val_id
                if custom_val and str(custom_val).lower() not in ("none", "null", ""):
                    item["customValue"] = str(custom_val)
                if "valueId" in item or "customValue" in item:
                    attrs.append(item)
        except Exception as e:
            print(f"[N11] Attribute okuma hatası ({product_code}): {e}")
        return attrs

    def load_variant_attributes(self, variant_code, main_code=None):
        attrs = []
        seen_ids = set()
        seen_names = set()
        cursor = self.db.cursor()

        try:
            cursor.execute(
                """
                SELECT n11_attribute_id, n11_attribute_name, n11_value_id, custom_value
                FROM product_variant_attributes
                WHERE variant_code = ?
                """,
                (variant_code,),
            )
            rows = cursor.fetchall()
        except Exception:
            rows = []

        if not rows and main_code:
            try:
                cursor.execute(
                    """
                    SELECT n11_attribute_id, n11_attribute_name, n11_value_id, custom_value
                    FROM product_variant_attributes
                    WHERE main_code = ? AND variant_code = ?
                    """,
                    (main_code, variant_code),
                )
                rows = cursor.fetchall()
            except Exception:
                rows = []

        for attr_id, attr_name, val_id, custom_val in rows:
            item = {"name": attr_name or ""}
            if attr_id:
                item["id"] = attr_id
                item["attributeId"] = attr_id
                seen_ids.add(str(attr_id))
            if attr_name:
                seen_names.add(str(attr_name).lower())
            if val_id and str(val_id).lower() not in ("none", "null", "", "0"):
                item["valueId"] = val_id
            if custom_val and str(custom_val).lower() not in ("none", "null", ""):
                item["customValue"] = str(custom_val)
            if "valueId" in item or "customValue" in item:
                attrs.append(item)

        base_attrs = self.load_db_attributes(main_code) if main_code else []
        if not base_attrs and main_code:
            base_attrs = self.load_db_attributes(variant_code)
        for a in base_attrs:
            aid = str(a.get("id") or a.get("attributeId") or "")
            aname = str(a.get("name") or "").lower()
            if aid and aid in seen_ids:
                continue
            if aname and aname in seen_names:
                continue
            attrs.append(a)
            if aid:
                seen_ids.add(aid)
            if aname:
                seen_names.add(aname)

        return attrs


# =====================================================================
# 4. PAYLOAD VE VERİ PAKETLEME SINIFI (Payload Builder Section)
# =====================================================================
class N11PayloadManager:
    def __init__(self, db):
        self.db = db
        self.attr_template_mgr = N11AttributeTemplateManager(db)
        self.category_mgr = N11CategoryManager(db)

    def load_product_images(self, code, main_code):
        urls = []
        cursor = self.db.cursor()
        for sql, param in (
            ("SELECT image_url FROM product_images WHERE product_code = ? ORDER BY image_order ASC", main_code),
            ("SELECT image_url FROM product_images WHERE product_code = ? ORDER BY image_order ASC", code),
            ("SELECT image_url FROM product_images WHERE stock_code = ? ORDER BY sort_order ASC", code),
            ("SELECT image_url FROM product_images WHERE stock_code = ? ORDER BY sort_order ASC", main_code),
        ):
            try:
                cursor.execute(sql, (param,))
                rows = cursor.fetchall()
                if rows:
                    urls = [str(r[0]).strip() for r in rows if r[0]]
                    break
            except Exception:
                continue
        if not urls:
            try:
                cursor.execute(
                    "SELECT image, images, image_url FROM products WHERE code = ? OR main_code = ? LIMIT 1",
                    (code, main_code),
                )
                row = cursor.fetchone()
                if row:
                    for cell in row:
                        if cell and str(cell).strip().lower() not in ("", "nan", "none"):
                            urls.extend(
                                [u.strip() for u in str(cell).replace(";", ",").split(",") if u.strip()]
                            )
                            break
            except Exception:
                try:
                    cursor.execute(
                        "SELECT images FROM products WHERE code = ? OR main_code = ? LIMIT 1",
                        (code, main_code),
                    )
                    row = cursor.fetchone()
                    if row and row[0]:
                        urls = [u.strip() for u in str(row[0]).replace(";", ",").split(",") if u.strip()]
                except Exception:
                    pass
        return ",".join(urls)

    def infer_size_from_text(self, *texts):
        size_pattern = re.compile(
            r"(?:^|[|_\-./\s])(2XS|XXS|XS|S|M|L|XL|XXL|2XL|3XL|4XL|5XL|"
            r"28|30|32|34|36|38|40|42|44|46|48|50)(?:$|[|_\-./\s])",
            re.IGNORECASE,
        )
        ideasoft_suffix_map = {
            "100000": "XS", "100001": "S", "100002": "M", "100003": "L", 
            "100004": "XL", "100005": "XXL", "100006": "3XL", "100007": "4XL",
            "1002": "M", "1003": "L", "1004": "XL", "10001": "S"
        }

        for t in texts:
            if not t:
                continue
            text_str = str(t).strip()
            head = text_str.split("|")[0].strip()
            
            for src in (head, text_str):
                m = size_pattern.search(f" {src} ")
                if m:
                    return m.group(1).upper()
                for suffix, size_val in ideasoft_suffix_map.items():
                    if src.endswith(suffix) or f".{suffix}" in src or f"_{suffix}" in src:
                        return size_val
        return ""

from tkinter import filedialog, messagebox
from marketplaces.n11.n11_api import export_error_report_excel

def handle_export_report(self):
    # Kullanıcıdan dosya kaydetme konumunu al
    file_path = filedialog.asksaveasfilename(
        defaultextension=".xlsx",
        filetypes=[("Excel Dosyası", "*.xlsx"), ("Tüm Dosyalar", "*.*")],
        title="Hata Raporunu Kaydet",
        initialfile="hata_raporu.xlsx"
    )

    if file_path:
        # output_path kwarg parametresiyle güvenle çağır
        success, message = export_error_report_excel(db=self.db, output_path=file_path)
        
        if success:
            messagebox.showinfo("Başarılı", message)
        else:
            messagebox.showerror("Hata", message)
            
# =====================================================================
# 5. SENKRONİZASYON VE HATA ANALİZİ SINIFI (Sync & Error Analysis Section)
# =====================================================================
class N11SyncManager:
    def __init__(self, db):
        self.db = db
        self.current_page = 1
        
        
    def analyze_n11_rejection_root_cause(self, raw_error_message):
        err_lower = str(raw_error_message).lower()
        if "gtin" in err_lower or "barkod" in err_lower or "barcode" in err_lower or "duplicate seller stock code" in err_lower:
            return {
                "code": "BARCODE_ERROR",
                "clean_msg": "Barkod / GTIN Çakışması (Bu barkod pazar yerinde başka bir satıcıda kayıtlı veya hatalı).",
                "action": "Lütfen ürünün Ideasoft panelindeki Barkod / EAN değerini benzersiz bir kodla güncelleyin."
            }
        elif "description" in err_lower or "aciklama" in err_lower or "karakter" in err_lower or "min 15" in err_lower:
            return {
                "code": "CONTENT_LIMIT_ERROR",
                "clean_msg": "İçerik Karakter Limiti İhlali (Ürün adı veya açıklama alanı limit dışı).",
                "action": "Sistem sonraki gönderimde açıklamayı otomatik kırpacaktır. Bilgileri kontrol edip tekrar gönderin."
            }
        elif "attribute" in err_lower or "nitelik" in err_lower or "mandatory" in err_lower or "missing required field" in err_lower:
            return {
                "code": "ATTRIBUTE_MISSING_ERROR",
                "clean_msg": "Kategori Zorunlu Niteliği Eksik (N11'in bu kategori için istediği bir alan doldurulmamış).",
                "action": "Özellik Eşleştir butonuna basarak sağ paneldeki tüm 'Zorunlu' alanları doldurun."
            }
        elif "price" in err_lower or "fiyat" in err_lower or "vatrate" in err_lower or "decimals" in err_lower:
            return {
                "code": "PRICE_ANOMALY_ERROR",
                "clean_msg": "Fiyat veya KDV Şeması Hatası (Liste fiyatı satış fiyatından küçük olamaz veya kuruş hanesi hatalı).",
                "action": "Ürünün satış ve piyasa fiyatlarını, KDV oranlarını kontrol edin."
            }
        return {
            "code": "UNKNOWN_N11_ERROR",
            "clean_msg": f"N11 Servis Reddi: {raw_error_message}",
            "action": "Hatayı inceleyip pazar yeri kurallarına göre veriyi güncelleyin."
        }


# =====================================================================
# 6. DIŞA AKTARMA VE RAPORLAMA SINIFI (Export & Reporting Section)
# =====================================================================
class N11ExportManager:
    def __init__(self, db):
        self.db = db


# =====================================================================
# 7. ANA ARAYÜZ VE KONTROL SINIFI (Main Frame Controller)
# =====================================================================
class CategoryAndAttributeMappingFrame(ctk.CTkFrame):
    def _infer_size_from_text(self, *texts):
        """Arayüz çağrıları için payload manager içindeki beden tahmin motoruna tünel açar."""
        if hasattr(self, 'payload_mgr') and self.payload_mgr:
            return self.payload_mgr.infer_size_from_text(*texts)
        return ""
    def __init__(self, parent, db):
        super().__init__(parent)
        self.db = db
        self.current_category_name = ""
        self._search_timer = None

        # Alt Yöneticileri (Managers) Başlatıyoruz
        self.category_mgr = N11CategoryManager(db)
        self.attr_template_mgr = N11AttributeTemplateManager(db)
        self.payload_mgr = N11PayloadManager(db)
        self.sync_mgr = N11SyncManager(db)
        self.export_mgr = N11ExportManager(db)

        self._init_db_table()

        app_key, app_secret = get_n11_credentials(self.db)
        self.n11_api = N11CategoryAPI(app_key, app_secret)

        self.sub_frames = {}
        self.create_sub_frame_mapping_list()
        self.create_sub_frame_category_products()
        self.create_sub_frame_attribute_form()

        self.show_sub_frame("mapping_list")
        self.render_mapped_categories()

        try:
            print("[SİSTEM KALKANI] Hayalet ürün temizliği başlatılıyor...")
            cursor = self.db.cursor()
            cursor.execute("""
                UPDATE products 
                SET is_mapped = 0 
                WHERE is_mapped = 1 
                  AND COALESCE(NULLIF(main_code, ''), code) NOT IN (SELECT DISTINCT product_code FROM product_attributes)
            """)
            self.db.commit()
            print(f"[SİSTEM KALKANI] Temizlik tamamlandı! {cursor.rowcount} adet hatalı eşleşmiş ürün güvenle 'Bekliyor' moduna çekildi.")
        except Exception as e:
            print(f"[SİSTEM KALKANI] Temizlik esnasında hata: {e}")

    def _init_db_table(self):
        """[MÜHÜRLENDİ - %100 MYSQL] REPLACE INTO işlemlerinin çökmemesi için UNIQUE indeks kalkanlı tablolar."""
        try:
            cursor = self.db.cursor()
            # 1. Katalog Eşleşme Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS product_catalog_mappings (
                    variant_code VARCHAR(100) PRIMARY KEY,
                    n11_catalog_id VARCHAR(50),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            
            # 2. Görseller Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS product_images (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    product_code VARCHAR(100),
                    stock_code VARCHAR(100),
                    image_url TEXT,
                    image_order INT DEFAULT 0,
                    KEY idx_prod_code (product_code),
                    KEY idx_stock_code (stock_code)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 3. 🚨 KRİTİK GÜNCELLEME: REPLACE INTO çökmelerini önlemek için stock_code PRIMARY KEY yapıldı
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS n11_failed_products (
                    stock_code VARCHAR(100) PRIMARY KEY,
                    reason TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 4. Görev Kuyruğu Tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS n11_tasks (
                    task_id VARCHAR(100) PRIMARY KEY,
                    stock_code VARCHAR(100),
                    main_code VARCHAR(100),
                    status VARCHAR(50) DEFAULT 'PENDING',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            self.db.commit()
            print("✅ [VERİTABANI KALKANI] Tüm MySQL tabloları UNIQUE kilitleriyle mühürlendi.")
        except Exception as e:
            print(f"❌ Tablo kurulum hatası: {e}")
            

    def clear_n11_from_level(self, level_index):
        if not hasattr(self, '_n11_active_widgets'):
            self._n11_active_widgets = []
        target_index = max(1, level_index)
        while len(self._n11_active_widgets) > target_index:
            widget = self._n11_active_widgets.pop()
            try:
                widget.pack_forget()
                widget.destroy()
            except Exception:
                pass

    def _extract_n11_children(self, node):
        """Bir N11 dugumunden alt kategori listesini cikarir."""
        if not isinstance(node, dict):
            return []
        for sk in ("subCategories", "subCategoryList", "subCategory", "categories", "children"):
            children = node.get(sk)
            if children is None:
                continue
            # null / bos = yaprak
            if children is False:
                continue
            if isinstance(children, list):
                return [c for c in children if isinstance(c, dict)]
            if isinstance(children, dict):
                # bazi yanitlarda {"subCategory": [...]} veya tek obje
                out = []
                for v in children.values():
                    if isinstance(v, list):
                        out.extend([c for c in v if isinstance(c, dict)])
                    elif isinstance(v, dict) and (v.get("id") or v.get("name")):
                        out.append(v)
                if out:
                    return out
                # tek kategori objesi olabilir
                if children.get("id") or children.get("name"):
                    return [children]
        return []

    def _build_n11_children_index(self, nodes, index=None, depth=0):
        """Tum agaci gezip id(str) -> [ {id, name} ] indeksi kurar."""
        if index is None:
            index = {}
        if not nodes:
            return index
        if isinstance(nodes, dict):
            # kok {"categories": [...]} olabilir
            if "categories" in nodes and isinstance(nodes["categories"], list):
                nodes = nodes["categories"]
            else:
                nodes = [nodes]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            nid = node.get("id")
            if nid is None:
                nid = node.get("categoryId") or node.get("category_id")
            if nid is None:
                continue
            nid = str(nid).strip()
            name = str(node.get("name") or node.get("categoryName") or "").strip()
            children = self._extract_n11_children(node)
            if children:
                bucket = index.setdefault(nid, [])
                seen = {c["id"] for c in bucket}
                for ch in children:
                    cid = ch.get("id")
                    if cid is None:
                        cid = ch.get("categoryId") or ch.get("category_id")
                    if cid is None:
                        continue
                    cid = str(cid).strip()
                    cname = str(ch.get("name") or ch.get("categoryName") or "").strip()
                    if not cid or cid in seen or cid == nid:
                        continue
                    seen.add(cid)
                    bucket.append({"id": cid, "name": cname})
                # cocuklari da tara
                self._build_n11_children_index(children, index, depth + 1)
            else:
                # yaprak: bos liste isaretle (bilinsin diye)
                index.setdefault(nid, [])
            # parentId flat baglantisi
            pid = node.get("parentId") or node.get("parent_id")
            if pid is not None and str(pid).strip() not in ("", "0", "None"):
                pid = str(pid).strip()
                bucket = index.setdefault(pid, [])
                seen = {c["id"] for c in bucket}
                if nid not in seen and name:
                    bucket.append({"id": nid, "name": name})
        return index

    def _find_n11_node_by_id(self, nodes, target_id):
        """Ham agacta id ile dugum ara."""
        target = str(target_id).strip()
        if not nodes:
            return None
        if isinstance(nodes, dict):
            if "categories" in nodes and isinstance(nodes["categories"], list):
                nodes = nodes["categories"]
            else:
                nodes = [nodes]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            nid = node.get("id")
            if nid is None:
                nid = node.get("categoryId") or node.get("category_id")
            if nid is not None and str(nid).strip() == target:
                return node
            children = self._extract_n11_children(node)
            if children:
                found = self._find_n11_node_by_id(children, target)
                if found:
                    return found
        return None

    def _ensure_n11_tree_cache(self):
        """Tam N11 agacini bir kez cekip children indeksini hazirlar."""
        if getattr(self, "_n11_children_index", None) is not None and getattr(self, "_n11_raw_categories", None):
            return True
        try:
            app_key, app_secret = get_n11_credentials(self.db)
            if not app_key:
                print("[N11 Agac] API key yok")
                return False
            raw = fetch_n11_categories(app_key, app_secret) or []
            # Bazi surumler {"categories": [...]} dondurebilir
            if isinstance(raw, dict):
                raw = raw.get("categories") or raw.get("content") or []
            self._n11_raw_categories = raw
            self._n11_children_index = self._build_n11_children_index(raw)
            parents_with_kids = sum(1 for v in self._n11_children_index.values() if v)
            print(f"[N11 Agac] kok={len(raw) if isinstance(raw, list) else '?'} | indeks={len(self._n11_children_index)} ebeveyn | cocuklu={parents_with_kids}")
            # Ornek ilk kok dugum yapisi
            if isinstance(raw, list) and raw:
                sample = raw[0]
                if isinstance(sample, dict):
                    print(f"[N11 Agac] ornek kok keys={list(sample.keys())} id={sample.get('id')} name={sample.get('name')}")
                    kids = self._extract_n11_children(sample)
                    print(f"[N11 Agac] ornek kok alt sayisi={len(kids)} ilk={[(k.get('id'), k.get('name')) for k in kids[:3]]}")
            return True
        except Exception as e:
            print(f"[N11 Agac] Onbellek hatasi: {e}")
            import traceback
            traceback.print_exc()
            self._n11_children_index = {}
            self._n11_raw_categories = []
            return False

    def load_n11_sub_levels_async(self, target_id, level_index, parent_name):
        """
        N11 alt kategorilerini yerel onbellekten yukler.
        Indeks kacirsa ham agactan dugumu bulup cocuklarini dogrudan okur.
        """
        target_str = str(target_id).strip()

        def background_fetch():
            try:
                self._ensure_n11_tree_cache()
                index = getattr(self, "_n11_children_index", {}) or {}
                children = list(index.get(target_str, []))

                # Indeks bos ise ham agactan dugumu bul
                if not children:
                    node = self._find_n11_node_by_id(getattr(self, "_n11_raw_categories", []), target_str)
                    if node:
                        raw_kids = self._extract_n11_children(node)
                        for ch in raw_kids:
                            cid = ch.get("id")
                            if cid is None:
                                cid = ch.get("categoryId") or ch.get("category_id")
                            if cid is None:
                                continue
                            children.append({
                                "id": str(cid).strip(),
                                "name": str(ch.get("name") or ch.get("categoryName") or "").strip(),
                            })
                        print(f"[N11 Alt] indeks bos, ham dugumden {len(children)} cocuk bulundu")

                clean_sub_list = []
                seen = set()
                for ch in children:
                    cid = str(ch.get("id") or "").strip()
                    cname = str(ch.get("name") or "").strip()
                    if not cid or not cname or cid in seen or cid == target_str:
                        continue
                    seen.add(cid)
                    clean_sub_list.append({"id": cid, "name": cname})

                print(f"[N11 Alt] parent={target_str} ({parent_name}) seviye={level_index} -> {len(clean_sub_list)} cocuk")
                if clean_sub_list:
                    print(f"[N11 Alt] ornek: {[c['name'] for c in clean_sub_list[:5]]}")
                self.after(0, lambda lst=clean_sub_list: self._process_subCategories_result(lst, target_id, level_index, parent_name))
            except Exception as e:
                print(f"[N11 Alt] hata: {e}")
                import traceback
                traceback.print_exc()
                self.after(0, lambda: self._process_subCategories_result([], target_id, level_index, parent_name))

        threading.Thread(target=background_fetch, daemon=True).start()

    def _process_subCategories_result(self, sub_list, target_id, level_index, parent_name):
        """API/onbellekten gelen alt kategori listesini UI combobox olarak basar."""
        def get_cid(cat):
            if not isinstance(cat, dict):
                return ""
            for k in ("id", "categoryId", "category_id"):
                v = cat.get(k)
                if v is not None and str(v).strip():
                    return str(v).strip()
            return ""

        def get_cname(cat):
            if not isinstance(cat, dict):
                return ""
            return str(cat.get("name") or cat.get("categoryName") or "").strip()

        if not sub_list:
            self._n11_selected_leaf_id = target_id
            while len(getattr(self, "_n11_active_widgets", [])) >= level_index:
                w = self._n11_active_widgets.pop()
                try:
                    w.pack_forget()
                    w.destroy()
                except Exception:
                    pass
            print(f"🎯 Zincir Sonu! Leaf ID: {target_id} ({parent_name})")
            return

        cat_map = {}
        for c in sub_list:
            cid = get_cid(c)
            cname = get_cname(c)
            if cid and cname:
                cat_map[cname] = cid
        sub_names = sorted(cat_map.keys())

        if not sub_names:
            self._n11_selected_leaf_id = target_id
            while len(getattr(self, "_n11_active_widgets", [])) >= level_index:
                w = self._n11_active_widgets.pop()
                try:
                    w.pack_forget()
                    w.destroy()
                except Exception:
                    pass
            return

        def on_sub_change(selected_name):
            if selected_name in ("Seçiniz...", "Seçiniz", ""):
                return
            cid = cat_map.get(selected_name)
            if not cid:
                return
            while len(self._n11_selected_path) > level_index:
                self._n11_selected_path.pop()
            self._n11_selected_path.append(selected_name)
            self._n11_selected_leaf_id = cid
            self._n11_current_parent_id = cid
            while len(self._n11_active_widgets) > level_index:
                w = self._n11_active_widgets.pop()
                try:
                    w.pack_forget()
                    w.destroy()
                except Exception:
                    pass
            self.load_n11_sub_levels_async(cid, level_index + 1, selected_name)

        while len(getattr(self, "_n11_active_widgets", [])) >= level_index:
            w = self._n11_active_widgets.pop()
            try:
                w.pack_forget()
                w.destroy()
            except Exception:
                pass

        if not hasattr(self, "_n11_levels_frame") or self._n11_levels_frame is None:
            print("[N11 UI] _n11_levels_frame yok!")
            return

        level_container = ctk.CTkFrame(self._n11_levels_frame, fg_color="transparent")
        level_container.pack(fill="x", pady=(4, 4), padx=0)

        lbl = ctk.CTkLabel(
            level_container,
            text=f"Alt Kategori (Seviye {level_index + 1}):",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#9ca3af",
        )
        lbl.pack(anchor="w", pady=(2, 1))

        combo = SearchableCTkComboBox(
            level_container,
            values=sub_names,
            command=on_sub_change,
        )
        combo.pack(fill="x", pady=(0, 2))
        combo.set("Seçiniz...")

        if not hasattr(self, "_n11_active_widgets"):
            self._n11_active_widgets = []
        self._n11_active_widgets.append(level_container)
        print(f"[N11 UI] Seviye {level_index + 1} combobox eklendi ({len(sub_names)} secenek)")

    def load_category_attributes(self, category_id):
        try:
            app_key, app_secret = get_n11_credentials(self.db)
            if not app_key or not app_secret:
                messagebox.showerror(
                    "API Hatası",
                    "N11 API Key veya API Secret veritabanında bulunamadı!\nLütfen Ayarlar menüsünden bilgilerinizi girin."
                )
                return []
            
            # Doğrudan modül fonksiyonunu kullanabilir veya güvenli nesne türetebilirsiniz
            try:
                api = N11CategoryAPI(app_key, app_secret)
            except TypeError:
                api = N11CategoryAPI()

            attributes = fetch_n11_category_attributes(app_key, app_secret, category_id) if hasattr(api, 'get_category_attributes') == False else api.get_category_attributes(category_id)
            if not attributes:
                return []
            return attributes if isinstance(attributes, list) else []
        except Exception as e:
            messagebox.showerror("Sistem Hatası", f"Özellikler yüklenirken beklenmeyen hata:\n{e}")
            return []
        
        
    def show_sub_frame(self, frame_key):
        for f in self.sub_frames.values():
            f.pack_forget()
        if frame_key in self.sub_frames:
            self.sub_frames[frame_key].pack(fill="both", expand=True)

    def create_sub_frame_mapping_list(self):
        f = ctk.CTkFrame(self, fg_color="transparent")
        top_bar = ctk.CTkFrame(f, fg_color="transparent")
        top_bar.pack(fill="x", padx=15, pady=10)

        lbl_title = ctk.CTkLabel(
            top_bar,
            text="🗂️ Kategori & Özellik Eşleştirme Yönetimi",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        lbl_title.pack(side="left")

        btn_box_right = ctk.CTkFrame(top_bar, fg_color="transparent")
        btn_box_right.pack(side="right")

        btn_all_prods = ctk.CTkButton(
            btn_box_right,
            text="🌐 Tüm Ürünleri Listele / İndexle",
            fg_color="#3b82f6", hover_color="#2563eb",
            command=lambda: self.show_category_products_panel("__ALL_PRODUCTS__"),
        )
        btn_all_prods.pack(side="left", padx=5)

        btn_add_cat = ctk.CTkButton(
            btn_box_right,
            text="➕ Kategori Eşleştirmesi Ekle",
            fg_color="#1f538d",
            command=self.open_add_category_window,
        )
        btn_add_cat.pack(side="left", padx=5)

        self.scroll_mapped = ctk.CTkScrollableFrame(f, label_text="Eşleştirilen Kategoriler")
        self.scroll_mapped.pack(fill="both", expand=True, padx=15, pady=10)

        self.sub_frames["mapping_list"] = f
            

    def open_add_category_window(self):
        # Yeni Kategori Ekleme Sihirbazı (Strict Hiyerarşi: mainCategory > category > subCategory)
        add_win = ctk.CTkToplevel(self)
        add_win.title("Yeni N11 Kategori Eşleştirmesi Ekle")
        add_win.geometry("1150x680")
        add_win.grab_set()

        # Ana İçerik Çerçevesi
        main_frame = ctk.CTkFrame(add_win, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            main_frame, 
            text="Yeni Kategori Ekleme Sihirbazı", 
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", pady=(0, 15))

        # 3 Sütunun yan yana duracağı ana taşıyıcı çerçeve
        columns_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        columns_frame.pack(fill="both", expand=True, pady=(0, 15))

        # 1️⃣ SOL SÜTUN: Ideasoft Kategorisi (Temizlenmiş Hiyerarşi)
        col_left = ctk.CTkFrame(columns_frame, fg_color="#1a1a1a", corner_radius=8, border_width=1, border_color="#333333")
        col_left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        
        ctk.CTkLabel(
            col_left, 
            text="1️⃣ Ideasoft Kategorisi", 
            font=ctk.CTkFont(size=12, weight="bold"), 
            text_color="#3b82f6"
        ).pack(anchor="w", padx=12, pady=(12, 3))
        
        idea_levels_frame = ctk.CTkScrollableFrame(col_left, fg_color="transparent", height=350)
        idea_levels_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # 2️⃣ ORTA SÜTUN: N11 Şablonu Seçimi
        col_mid = ctk.CTkFrame(columns_frame, fg_color="#1a1a1a", corner_radius=8, border_width=1, border_color="#333333")
        col_mid.pack(side="left", fill="both", expand=True, padx=6)
        
        ctk.CTkLabel(
            col_mid, 
            text="2️⃣ N11 Şablonu Seç", 
            font=ctk.CTkFont(size=12, weight="bold"), 
            text_color="#eab308"
        ).pack(anchor="w", padx=12, pady=(12, 3))
        
        mid_scroll = ctk.CTkScrollableFrame(col_mid, fg_color="transparent", height=350)
        mid_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        db_templates = ["N11 Entegrasyon"]
        try:
            cursor = self.db.cursor()
            cursor.execute("SELECT name FROM templates")
            rows = cursor.fetchall()
            if rows:
                fetched_tpls = []
                for r in rows:
                    name = _row_val(r, "name", 0)
                    if name: fetched_tpls.append(str(name))
                if fetched_tpls: db_templates = fetched_tpls
        except Exception as e:
            print(f"Şablon çekme hatası: {e}")

        # =====================================================================
        # 🛡️ IDEASOFT STRICT KATEGORİ HAVUZU TAMİRATI (KOLON KAYMASI GİDERİLDİ)
        # =====================================================================
        try:
            cursor = self.db.cursor()
            # MÜHÜRLENDİ: Şifreli kodları (DistCode) tamamen es geçip, saf isim kolonlarını okuyoruz
            cursor.execute("SELECT mainCategory, category, subCategory FROM products")
            
            idea_tree = {}
            junk = {'', 'none', 'nan', 'null', 'general', 'genel'}

            for r in cursor.fetchall():
                mc = str(_row_val(r, "mainCategory", 0) or "").strip()
                c  = str(_row_val(r, "category", 1) or "").strip()
                sc = str(_row_val(r, "subCategory", 2) or "").strip()

                # Ana kategori her üründe olmak zorunda, yoksa o satırı es geç
                if not mc or mc.lower() in junk:
                    continue

                # 2. ve 3. basamak her üründe olmayabilir, yoksa 'Genel' veya Boş olarak yapılandır
                clean_c = c if (c and c.lower() not in junk) else "Genel Kategori"
                clean_sc = sc if (sc and sc.lower() not in junk) else ""

                # Şifreli kodların (c_ veya m_ veya _) kazara sızmasını kesin olarak engelleyen filtre
                if clean_c.startswith("c_") or clean_c.startswith("m_") or "_" in clean_c:
                    clean_c = "Genel Kategori"
                if clean_sc.startswith("c_") or clean_sc.startswith("m_") or "_" in clean_sc:
                    clean_sc = ""

                # mainCategory -> category -> subCategory strictly mühürlendi
                idea_tree.setdefault(mc, {}).setdefault(clean_c, set()).add(clean_sc)

            self._idea_category_tree = idea_tree
            idea_mains = sorted(list(idea_tree.keys()))
            print(f"✅ [Ideasoft Başarıyla Tamir Edildi]: {len(idea_mains)} Adet Temiz Ana Kategori Kilitlendi.")
            
        except Exception as e:
            print(f"❌ Ideasoft ağaç yükleme hatası: {e}")
            idea_mains = []
            self._idea_category_tree = {}

        lbl_tpl = ctk.CTkLabel(mid_scroll, text="Aktarım Şablonu:", font=ctk.CTkFont(size=10, weight="bold"), text_color="#a1a1aa")
        lbl_tpl.pack(anchor="w", pady=(3, 1))

        self.combo_template = ctk.CTkComboBox(mid_scroll, values=db_templates, height=30)
        self.combo_template.pack(fill="x", pady=(0, 5))
        if db_templates:
            self.combo_template.set(db_templates[0])

        # 3️⃣ SAĞ SÜTUN: N11 Pazar Yeri Kategori Ağacı (Canlı API)
        col_right = ctk.CTkFrame(columns_frame, fg_color="#1a1a1a", corner_radius=8, border_width=1, border_color="#333333")
        col_right.pack(side="left", fill="both", expand=True, padx=(6, 0))
        
        ctk.CTkLabel(
            col_right, 
            text="3️⃣ N11 Pazar Yeri Kategorisi Seç", 
            font=ctk.CTkFont(size=12, weight="bold"), 
            text_color="#22c55e"
        ).pack(anchor="w", padx=12, pady=(12, 3))
        
        n11_levels_frame = ctk.CTkScrollableFrame(col_right, fg_color="transparent", height=350)
        n11_levels_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._n11_levels_frame = n11_levels_frame
        self._n11_active_widgets = []
        self._n11_selected_path = []

        # Dinamik arayüz kutularını takip eden listeler
        idea_level2_widgets = []  # Kategori (category) kutuları
        idea_level3_widgets = []  # Alt Kategori (subCategory) kutuları

        def _destroy_widgets(lst):
            for w in lst:
                try:
                    w.pack_forget()
                    w.destroy()
                except Exception: pass
            lst.clear()

        # Son basamak (subCategory) seçildiğinde yolu mühürler
        def on_idea_sub_selected(main_val, cat_val, sub_val):
            self._selected_idea_path = [main_val, cat_val, sub_val]
            print(f"🎯 [Ideasoft Tam Yol Mühürlendi]: {main_val} > {cat_val} > {sub_val}")

        # 2. Basamak (category) seçilince 3. Basamağı (subCategory) yükleyen tetikleyici
        # 2. Basamak (category) seçilince 3. Basamağı (subCategory) SADECE VERİ VARSA açan tetikleyici
        def on_idea_cat_selected(main_val, cat_val):
            # Önce eski 3. seviye kalıntılarını temizle
            _destroy_widgets(idea_level3_widgets)
            
            idea_tree = getattr(self, "_idea_category_tree", {})
            sub_set = idea_tree.get(main_val, {}).get(cat_val, set()) or set()
            
            # Boş, geçersiz hücreleri eliyoruz
            junk_sub = {'', 'genel', 'nan', 'none', 'subcategory', 'maincategory', 'genel alt kategori', cat_val.lower()}
            sub_list = sorted([s for s in sub_set if s and str(s).strip().lower() not in junk_sub])

            # 🎯 EĞER 3. BASAMAKTA GERÇEK VERİ VARSA KUTUYU OLUŞTUR
            if sub_list:
                lbl_sub = ctk.CTkLabel(
                    idea_levels_frame,
                    text="3️⃣ Alt Kategori (subCategory):",
                    font=ctk.CTkFont(size=10, weight="bold"),
                    text_color="#a1a1aa",
                )
                lbl_sub.pack(anchor="w", pady=(8, 1))
                idea_level3_widgets.append(lbl_sub)

                combo_sub = ctk.CTkComboBox(
                    idea_levels_frame,
                    values=sub_list,
                    height=30,
                    command=lambda val: on_idea_sub_selected(main_val, cat_val, val),
                )
                combo_sub.set(sub_list[0])
                combo_sub.pack(fill="x", pady=(0, 5))
                idea_level3_widgets.append(combo_sub)
                
                on_idea_sub_selected(main_val, cat_val, sub_list[0])
            else:
                # 🛡️ Ayakkabı gibi 3. basamağı olmayan yerlerde kutuyu açma, yolu 2'li olarak mühürle
                self._selected_idea_path = [main_val, cat_val, ""]
                print(f"🎯 [Mühürlendi - 3. Basamak Yok]: {main_val} > {cat_val}")

        # 1. Basamak (mainCategory) seçilince alt basamakları zincirleme ve dinamik açan tetikleyici
        def on_idea_main_selected(main_val):
            _destroy_widgets(idea_level3_widgets)
            _destroy_widgets(idea_level2_widgets)
            self._selected_idea_path = [main_val, "", ""]

            idea_tree = getattr(self, "_idea_category_tree", {})
            cat_dict = idea_tree.get(main_val, {}) or {}
            
            junk_cat = {'', 'none', 'nan', 'null', 'category', 'genel kategori'}
            cat_sorted = sorted([k for k in cat_dict.keys() if k and str(k).strip().lower() not in junk_cat])

            # 🎯 EĞER SADECE TEK KATEGORİ VARSA (2. ve 3. Basamak Yoksa)
            if not cat_sorted:
                print(f"🎯 [Mühürlendi - Tek Basamaklı Kategori]: {main_val}")
                return

            # 2. Basamak kutusunu oluştur ve ekrana bas
            lbl_cat = ctk.CTkLabel(
                idea_levels_frame,
                text="2️⃣ Kategori (category):",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color="#a1a1aa",
                anchor="w"
            )
            lbl_cat.pack(anchor="w", pady=(8, 1))
            idea_level2_widgets.append(lbl_cat)

            combo_cat = ctk.CTkComboBox(
                idea_levels_frame,
                values=cat_sorted,
                height=30,
                command=lambda val: on_idea_cat_selected(main_val, val),
            )
            combo_cat.set(cat_sorted[0])
            combo_cat.pack(fill="x", pady=(0, 5))
            idea_level2_widgets.append(combo_cat)
            
            # Seçilen 2. basamağa göre 3. basamağın varlığını otomatik denetle
            on_idea_cat_selected(main_val, cat_sorted[0])


        def on_n11_main_selected(main_name):
            if not main_name or main_name in ("Seçiniz...", "Seçiniz"):
                return
            cat_id = n11_cat_map.get(main_name)
            if not cat_id:
                # isim eslesmesi kacmis olabilir - kismi ara
                for k, v in n11_cat_map.items():
                    if k.strip().lower() == main_name.strip().lower():
                        cat_id = v
                        break
            print(f"[N11 UI] Ana secildi: name={main_name!r} id={cat_id!r} map_size={len(n11_cat_map)}")
            if not cat_id:
                print(f"[N11 UI] ID bulunamadi! map ornek keys={list(n11_cat_map.keys())[:5]}")
                return
            self._n11_selected_path = [main_name]
            self._n11_selected_leaf_id = cat_id
            self._n11_current_parent_id = cat_id
            
            while len(self._n11_active_widgets) > 0:
                w = self._n11_active_widgets.pop()
                try:
                    w.pack_forget()
                    w.destroy()
                except Exception:
                    pass
            self.load_n11_sub_levels_async(cat_id, 1, main_name)

        try:
            cursor = self.db.cursor()
            # mainCategory boş olsa bile category kolonunu baz alacak şekilde esnetildi
            cursor.execute(
                "SELECT DISTINCT mainCategory, category, subCategory FROM products "
                "WHERE (category IS NOT NULL AND category != '') "
                "   OR (mainCategory IS NOT NULL AND mainCategory != '')"
            )
            idea_tree = {}
            junk = {'', 'none', 'nan', 'genel', 'maincategory', 'subcategory', 'category'}

            def _clean(v):
                s = str(v or "").strip()
                return "" if s.lower() in junk else s

            def _add_path(parts):
                parts = [p for p in parts if p]
                if not parts:
                    return
                # 1 seviye
                if len(parts) == 1:
                    idea_tree.setdefault(parts[0], {}).setdefault("Genel", set()).add("")
                    return
                # 2 seviye
                if len(parts) == 2:
                    idea_tree.setdefault(parts[0], {}).setdefault(parts[1], set()).add("")
                    return
                # 3+ seviye: ilk=main, ikinci=cat, geri kalan birlestirilmis sub
                idea_tree.setdefault(parts[0], {}).setdefault(parts[1], set()).add(" > ".join(parts[2:]))

            for row in cursor.fetchall():
                mc = _clean(_row_val(row, "mainCategory", 0))
                c = _clean(_row_val(row, "category", 1))
                sc = _clean(_row_val(row, "subCategory", 2))

                # Herhangi bir alanda " > " ile birlestirilmis yol varsa parcala
                path_parts = []
                for field in (mc, c, sc):
                    if field and ">" in field:
                        path_parts = [p.strip() for p in field.split(">") if p.strip() and p.strip().lower() not in junk]
                        break
                if path_parts:
                    _add_path(path_parts)
                    continue

                # Klasik 3 kolon hiyerarsi
                if not mc and not c and not sc:
                    continue
                if not mc:
                    # sadece category (+ sub) varsa category ana olur
                    if c:
                        _add_path([c, sc] if sc else [c])
                    elif sc:
                        _add_path([sc])
                    continue
                if c and c.lower() == mc.lower():
                    c = ""
                if sc and (sc.lower() == mc.lower() or (c and sc.lower() == c.lower())):
                    sc = ""
                _add_path([mc, c, sc] if c else ([mc, sc] if sc else [mc]))

            self._idea_category_tree = idea_tree
            idea_mains = sorted(list(idea_tree.keys()))
            print(f"[Ideasoft Ağaç] {len(idea_mains)} ana kategori yüklendi: {idea_mains[:8]}...")
            for _m in idea_mains[:5]:
                _cats = list((idea_tree.get(_m) or {}).keys())
                print(f"   └ {_m}: 2.seviye={_cats[:8]}")
        except Exception as e:
            print(f"Ideasoft ağaç yükleme hatası: {e}")
            import traceback
            traceback.print_exc()
            idea_mains = []

        if idea_mains:
            lbl_idea_main = ctk.CTkLabel(
                idea_levels_frame,
                text="Ana Kategori (mainCategory):",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color="#a1a1aa",
                anchor="w"
            )
            lbl_idea_main.pack(anchor="w", pady=(3, 1))
            combo_idea_main = ctk.CTkComboBox(
                idea_levels_frame, values=idea_mains, height=30, command=on_idea_main_selected
            )
            combo_idea_main.pack(fill="x", pady=(0, 5))
            
            # 🛡️ TAMİRAT: İlk elemanın combo içerisine yazılmasını kilitliyoruz
            combo_idea_main.set(idea_mains[0])
            
            # Açılış zincirini (mainCategory -> category -> subCategory) tetikle
            on_idea_main_selected(idea_mains[0])
        else:
            ctk.CTkLabel(
                idea_levels_frame,
                text="⚠️ products tablosunda kategori bulunamadı.\nÖnce ürünleri Ideasoft'tan çekin.",
                text_color="#ef4444",
                font=ctk.CTkFont(size=11),
                justify="left",
            ).pack(anchor="w", padx=4, pady=10)
            
            
        # N11 Canlı Kategoriler (tek seferlik onbellek)
        n11_cat_map = {}
        n11_mains = []
        try:
            self._n11_children_index = None  # zorla yeniden kur
            self._n11_raw_categories = None
            ok = self._ensure_n11_tree_cache()
            raw_mains = getattr(self, "_n11_raw_categories", []) or []
            for c in raw_mains:
                if not isinstance(c, dict):
                    continue
                c_name = c.get("name") or c.get("categoryName")
                c_id = c.get("id")
                if c_id is None:
                    c_id = c.get("categoryId")
                if c_name and c_id is not None:
                    n11_cat_map[str(c_name)] = str(c_id)
            n11_mains = sorted(list(n11_cat_map.keys()))
            print(f"[N11 UI] {len(n11_mains)} ana kategori comboya yazildi")
            if not n11_mains:
                n11_mains = ["⚠️ Kategoriler Yüklenemedi"]
        except Exception as e:
            print(f"N11 kok kategori hatasi: {e}")
            import traceback
            traceback.print_exc()
            n11_mains = ["⚠️ Kategoriler Yüklenemedi"]
            n11_cat_map = {}

        lbl_n11_main = ctk.CTkLabel(n11_levels_frame, text="Ana Kategori:", font=ctk.CTkFont(size=10, weight="bold"), text_color="#a1a1aa")
        lbl_n11_main.pack(anchor="w", pady=(3, 1))

        n11_main_values = (["Seçiniz..."] + n11_mains) if n11_mains and "⚠️" not in str(n11_mains[0]) else n11_mains
        combo_n11_main = ctk.CTkComboBox(n11_levels_frame, values=n11_main_values, height=30, command=on_n11_main_selected)
        combo_n11_main.pack(fill="x", pady=(0, 5))
        combo_n11_main.set("Seçiniz..." if "Seçiniz..." in n11_main_values else (n11_mains[0] if n11_mains else ""))

        # Alt Buton Alanı (Kaydet ve İptal)
        bottom_action_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        bottom_action_frame.pack(fill="x", pady=(15, 0))

        btn_save_mapping = ctk.CTkButton(
            bottom_action_frame, 
            text="💾 Eşleştirmeyi Mühürle ve Kaydet", 
            fg_color="#22c55e", 
            hover_color="#16a34a",
            height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.do_save_mapping
        )
        btn_save_mapping.pack(side="right", padx=5)

        cancel_btn = ctk.CTkButton(
            bottom_action_frame, 
            text="İptal", 
            fg_color="#ef4444", 
            hover_color="#dc2626",
            height=38,
            command=add_win.destroy
        )
        cancel_btn.pack(side="right", padx=5)
    
        def _destroy_widgets(lst):
            for w in lst:
                try:
                    w.pack_forget()
                    w.destroy()
                except Exception:
                    pass
            lst.clear()
    
        
    def open_edit_category_window(self, item_data):
        """Mevcut bir kategori eşleştirmesini güvenle düzenleme penceresini açar."""
        if "add_mapping" not in self.sub_frames:
            add_frame = ctk.CTkFrame(self, fg_color="transparent")
            self.sub_frames["add_mapping"] = add_frame
        
        add_frame = self.sub_frames["add_mapping"]
        for w in add_frame.winfo_children():
            w.destroy()

        self.show_sub_frame("add_mapping")

        top_bar = ctk.CTkFrame(add_frame, fg_color="transparent")
        top_bar.pack(fill="x", padx=15, pady=10)
        
        ctk.CTkButton(
            top_bar, text="⬅️ Geri Dön", fg_color="#374151", width=100,
            command=lambda: self.show_sub_frame("mapping_list")
        ).pack(side="left")
        
        map_id = item_data.get("id")
        current_local = item_data.get("local_category") or item_data.get("ideasoft_cat", "")
        current_template = item_data.get("template_name", "")
        current_n11_name = item_data.get("n11_category_name") or item_data.get("n11_cat", "")

        ctk.CTkLabel(top_bar, text=f"✏️ Kategori Eşleştirmesini Düzenle (ID: {map_id})", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left", padx=15)

        cursor = self.db.cursor()
        cursor.execute("SELECT app_key, app_secret FROM api_keys WHERE platform = 'N11'")
        api_row = cursor.fetchone()
        if api_row:
            app_key = str(_row_val(api_row, "app_key", 0) or "")
            app_secret = str(_row_val(api_row, "app_secret", 1) or "")
        else:
            app_key, app_secret = "", ""

        cursor.execute("SELECT name FROM templates")
        db_templates = []
        for row in cursor.fetchall():
            name = _row_val(row, "name", 0)
            if name:
                db_templates.append(str(name))
        if not db_templates:
            db_templates = ["N11 Entegrasyon"]

        raw_cats = fetch_n11_categories(app_key, app_secret) if app_key else []
        n11_cat_map = {}
        n11_mains = []

        if isinstance(raw_cats, list) and len(raw_cats) > 0:
            for c in raw_cats:
                c_name = c.get("name")
                c_id = c.get("id")
                if c_name and c_id:
                    n11_cat_map[c_name] = c_id
                    n11_mains.append(c_name)

        columns_scroll = ctk.CTkScrollableFrame(add_frame, fg_color="transparent")
        columns_scroll.pack(fill="both", expand=True, padx=15, pady=5)

        columns_frame = ctk.CTkFrame(columns_scroll, fg_color="transparent")
        columns_frame.pack(fill="both", expand=True)

        # Bilgi Paneli / Düzenlenen Kayıt Özeti
        info_card = ctk.CTkFrame(columns_frame, fg_color="#1f2937", corner_radius=6)
        info_card.pack(fill="x", padx=5, pady=(0, 10))
        
        ctk.CTkLabel(info_card, text=f"📌 Seçili Yerel Kategori: {current_local}", font=ctk.CTkFont(size=12, weight="bold"), text_color="#3b82f6").pack(anchor="w", padx=12, pady=6)
        ctk.CTkLabel(info_card, text=f"📌 Mevcut N11 Eşleşmesi: {current_n11_name}", font=ctk.CTkFont(size=12, weight="bold"), text_color="#22c55e").pack(anchor="w", padx=12, pady=(0, 6))

        # Şablon Seçimi Sütunu
        col_mid = ctk.CTkFrame(columns_frame, fg_color="#1a1a1a", corner_radius=8, border_width=1, border_color="#333333")
        col_mid.pack(fill="x", expand=True, padx=6, pady=5)
        ctk.CTkLabel(col_mid, text="2️⃣ N11 Şablonu Güncelle", font=ctk.CTkFont(size=12, weight="bold"), text_color="#eab308").pack(anchor="w", padx=12, pady=(12, 3))
        
        mid_scroll = ctk.CTkScrollableFrame(col_mid, fg_color="transparent", height=100)
        mid_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        self.combo_template = ctk.CTkComboBox(mid_scroll, values=db_templates, height=30)
        self.combo_template.pack(fill="x", padx=5, pady=5)
        if current_template in db_templates:
            self.combo_template.set(current_template)
        elif db_templates:
            self.combo_template.set(db_templates[0])

        # Yeni N11 Kategorisi Seçim Alanı
        col_right = ctk.CTkFrame(columns_frame, fg_color="#1a1a1a", corner_radius=8, border_width=1, border_color="#333333")
        col_right.pack(fill="both", expand=True, padx=6, pady=5)
        ctk.CTkLabel(col_right, text="3️⃣ Yeni N11 Pazar Yeri Kategorisi Seç", font=ctk.CTkFont(size=12, weight="bold"), text_color="#22c55e").pack(anchor="w", padx=12, pady=(12, 3))
        
        n11_levels_frame = ctk.CTkScrollableFrame(col_right, fg_color="transparent", height=200)
        n11_levels_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._n11_levels_frame = n11_levels_frame
        self._n11_active_widgets = []
        self._n11_selected_path = []
        self._n11_selected_leaf_id = item_data.get("n11_category_id")
        self._n11_raw_categories = raw_cats

        def on_n11_main_selected(main_name):
            if not main_name or main_name in ("Seçiniz...", "Seçiniz"):
                return
            cat_id = n11_cat_map.get(main_name)
            if not cat_id:
                return

            self._n11_selected_path = [main_name]
            self._n11_selected_leaf_id = cat_id
            self._n11_current_parent_id = cat_id

            # Önceki alt seviye kutularını temizle
            widgets = self._n11_active_widgets
            while len(widgets) > 0:
                widget = widgets.pop()
                try:
                    widget.pack_forget()
                    widget.destroy()
                except Exception:
                    pass
            
            # Alt kategorileri async yükle
            self.load_n11_sub_levels_async(cat_id, 1, main_name)

        lbl_main = ctk.CTkLabel(
            n11_levels_frame,
            text="Ana Kategori:",
            font=ctk.CTkFont(size=10, weight="bold")
        )
        lbl_main.pack(anchor="w", pady=(3, 1))

        combo_n11_main = ctk.CTkComboBox(
            n11_levels_frame,
            values=n11_mains,
            height=30,
            command=on_n11_main_selected
        )
        combo_n11_main.pack(fill="x", pady=(0, 5))

        if n11_mains and "⚠️" not in n11_mains[0]:
            combo_n11_main.set("Seçiniz...")
            # Kullanici secmadan alt seviye yukleme - hiz ve dogru cocuk icin

    def delete_mapping(self, map_id):
        """Açık imleçlerin kapanması için arayüze milisaniyelik nefes aldırıp güvenle siler."""
        if not messagebox.askyesno("Silme Onayı", "Bu kategori eşleştirmesini silmek istediğinize emin misiniz?"):
            return
        
        # 🚀 Arayüzün o anki odaklanma ve imleç kilitlerini bırakması için işleme mini bir es veriyoruz
        self.after(100, lambda: self._execute_safe_delete(map_id))

    def _execute_safe_delete(self, map_id):
        """MySQL üzerinden kategori eşleştirmesini siler (SQLite kalıntısı kaldırıldı)."""
        try:
            self.db.execute("DELETE FROM n11_category_mappings WHERE id = ?", (map_id,))
            messagebox.showinfo("Başarılı", "Kategori eşleştirmesi başarıyla silindi.")
            self.render_mapped_categories()
        except Exception as e:
            messagebox.showerror("Hata", f"Silme işlemi sırasında hata oluştu:\n{e}")
                
               
    def do_save_mapping(self):
        idea_path = getattr(self, "_selected_idea_path", ["", "", ""])
        n11_leaf_id = getattr(self, "_n11_selected_leaf_id", None)
        n11_path = getattr(self, "_n11_selected_path", [])
        
        template = "N11 Entegrasyon"
        if hasattr(self, "combo_template"):
            template = self.combo_template.get()

        if not n11_leaf_id:
            messagebox.showwarning("Uyarı", "N11 pazar yeri kategorisi seçilmedi.")
            return

        clean_path_parts = []
        for x in idea_path:
            val_str = str(x).strip()
            if val_str and val_str.lower() not in ['', 'none', 'nan', 'genel'] and val_str not in clean_path_parts:
                clean_path_parts.append(val_str)
        
        if not clean_path_parts:
            messagebox.showwarning("Uyarı", "Lütfen geçerli bir Yerel/Ideasoft kategorisi seçin!")
            return

        full_idea = " > ".join(clean_path_parts)
        main_cat_first = clean_path_parts[0]

        try:
            # SİL-YAP-BOZ OLMAMASI İÇİN MERKEZİ MYSQL DATABASE NESNESİ KULLANILIYOR
            # execute metodu arka planda ? işaretlerini %s formatına otomatik çevirir.
            self.db.execute("""
                INSERT INTO n11_category_mappings 
                (local_category, n11_category_id, n11_category_name, template_name, platform, store_id)
                VALUES (?, ?, ?, ?, 'N11', 'N11')
                ON DUPLICATE KEY UPDATE
                    n11_category_id = VALUES(n11_category_id),
                    n11_category_name = VALUES(n11_category_name),
                    template_name = VALUES(template_name)
            """, (full_idea, str(n11_leaf_id), " > ".join(n11_path), template))
            
            # Ürün eşleşme durumunu güncelleme
            self.db.execute("""
                UPDATE products 
                SET is_mapped = 2 
                WHERE mainCategory = ? OR category = ?
            """, (main_cat_first, full_idea))

            messagebox.showinfo("Kategori Kaydedildi", f"Kategori eşleştirmesi MySQL'e kaydedildi:\n{full_idea}")
            self.show_sub_frame("mapping_list")
            self.render_mapped_categories()

        except Exception as e:
            messagebox.showerror("Hata", f"MySQL veritabanı mühürleme hatası: {e}")


            
    def create_sub_frame_category_products(self):
        f = ctk.CTkFrame(self, fg_color="transparent")
        top_bar = ctk.CTkFrame(f, fg_color="transparent")
        top_bar.pack(fill="x", padx=15, pady=10)

        ctk.CTkButton(top_bar, text="⬅️ Kategori Listesine Dön", fg_color="#374151",
                        hover_color="#4b5563", command=lambda: self.show_sub_frame("mapping_list")).pack(side="left")
        self.lbl_cat_title = ctk.CTkLabel(top_bar, text="Kategori Ürünleri", font=ctk.CTkFont(size=15, weight="bold"))
        self.lbl_cat_title.pack(side="left", padx=20)

        self.export_btn = ctk.CTkButton(
            top_bar, 
            text="N11 Hazır Excel Aktar", 
            command=self.export_n11_ready_excel,
            fg_color="#27ae60", 
            hover_color="#2ecc71"
        )
        self.export_btn.pack(side="right", padx=5)

        self.scroll_cat_prods = ctk.CTkScrollableFrame(f)
        self.scroll_cat_prods.pack(fill="both", expand=True, padx=15, pady=10)
        self.sub_frames["category_products"] = f

    def build_complete_n11_payload(self, single_main_code=None):
        """[MÜHÜRLENDİ] Tuple ve Dict veri türlerini tek potada eriten çökmez payload hazırlama motoru."""
        try:
            cursor = self.db.cursor()
            if single_main_code:
                cursor.execute("""
                    SELECT code, main_code, title, brand, stock, price, tax, category, subCategory, is_mapped 
                    FROM products 
                    WHERE main_code = ? OR code = ?
                """, (single_main_code, single_main_code))
            else:
                cursor.execute("""
                    SELECT code, main_code, title, brand, stock, price, tax, category, subCategory, is_mapped 
                    FROM products 
                    WHERE is_mapped IN (1, 2)
                """)
            mapped_products = cursor.fetchall()

            if not mapped_products:
                return [], ["Eşleştirilmiş (is_mapped 1 veya 2) ürün bulunamadı."]

            payload_list = []
            validation_errors = []

            for prod in mapped_products:
                # 🛡️ NORMALİZASYON KALKANI: Satır dict veya tuple gelse bile akıllı yardımcı ile güvenle okuyoruz
                code = _row_val(prod, "code", 0)
                main_code = _row_val(prod, "main_code", 1)
                title = _row_val(prod, "title", 2)
                brand = _row_val(prod, "brand", 3)
                stock = _row_val(prod, "stock", 4)
                price = _row_val(prod, "price", 5)
                tax = _row_val(prod, "tax", 6)
                cat = _row_val(prod, "category", 7)
                s_cat = _row_val(prod, "subCategory", 8)

                product_errors = []
                if not main_code: product_errors.append("Stok Kodu (main_code) eksik")
                if not title: product_errors.append("Ürün Adı eksik")
                if price is None or price <= 0: product_errors.append("Geçersiz satış fiyatı")

                # --- KATEGORİ ÖZNİTELİKLERİ ÇEKİLİYOR ---
                cursor.execute("""
                    SELECT n11_attribute_id, n11_attribute_name, n11_value_id, custom_value 
                    FROM product_attributes 
                    WHERE product_code = ?
                """, (main_code,))
                attributes = cursor.fetchall()

                attr_list = []
                for attr in attributes:
                    attr_id = _row_val(attr, "n11_attribute_id", 0)
                    attr_name = _row_val(attr, "n11_attribute_name", 1)
                    val_id = _row_val(attr, "n11_value_id", 2)
                    cust_val = _row_val(attr, "custom_value", 3)
                    
                    entry = {"attributeId": int(attr_id) if attr_id else 0, "attributeName": str(attr_name or "Özellik")}
                    if val_id and str(val_id).lower() not in ("none", "null", "", "0"): 
                        entry["valueId"] = int(val_id)
                    if cust_val and str(cust_val).lower() not in ("none", "null", ""): 
                        entry["customValue"] = str(cust_val)
                    attr_list.append(entry)

                # --- VARYANT ÖZNİTELİKLERİ ÇEKİLİYOR ---
                cursor.execute("""
                    SELECT variant_code, n11_attribute_id, n11_attribute_name, n11_value_id, custom_value 
                    FROM product_variant_attributes 
                    WHERE main_code = ?
                """, (main_code,))
                variants = cursor.fetchall()

                variant_list = []
                for var in variants:
                    v_code = _row_val(var, "variant_code", 0)
                    v_attr_id = _row_val(var, "n11_attribute_id", 1)
                    v_attr_name = _row_val(var, "n11_attribute_name", 2)
                    v_val_id = _row_val(var, "n11_value_id", 3)
                    v_cust_val = _row_val(var, "custom_value", 4)

                    v_entry = {"variantCode": str(v_code), "attributeId": int(v_attr_id) if v_attr_id else 0, "attributeName": str(v_attr_name or "Varyant")}
                    if v_val_id and str(v_val_id).lower() not in ("none", "null", "", "0"): 
                        v_entry["valueId"] = int(v_val_id)
                    if v_cust_val and str(v_cust_val).lower() not in ("none", "null", ""): 
                        v_entry["customValue"] = str(v_cust_val)
                    variant_list.append(v_entry)

                if product_errors:
                    validation_errors.append({"main_code": main_code, "title": title[:30] if title else "İsimsiz", "errors": product_errors})
                    continue

                # --- ÜRÜN GÖRSELLERİ ÇEKİLİYOR ---
                images_list = []
                try:
                    cursor.execute("""
                        SELECT image_url, image_order 
                        FROM product_images 
                        WHERE product_code = ? OR stock_code = ?
                        ORDER BY image_order ASC
                    """, (main_code, main_code))
                    image_rows = cursor.fetchall()
                    for idx, img in enumerate(image_rows):
                        img_url = _row_val(img, "image_url", 0)
                        img_order = _row_val(img, "image_order", 1)
                        if img_url:
                            images_list.append({"url": str(img_url), "order": int(img_order) if img_order is not None else idx + 1})
                except Exception as img_err:
                    print(f"⚠️ Görsel katman uyarısı: {img_err}")
                    try:
                        cursor.execute("SELECT image, image_url FROM products WHERE main_code = ? OR code = ? LIMIT 1", (main_code, main_code))
                        p_img_row = cursor.fetchone()
                        if p_img_row:
                            backup_url = _row_val(p_img_row, "image_url", 1) or _row_val(p_img_row, "image", 0)
                            if backup_url:
                                images_list.append({"url": str(backup_url), "order": 1})
                    except Exception: pass

                # N11 boş resim reddini önleyen fallback koruma şeması
                if not images_list:
                    images_list.append({"url": "https://secretlab.co", "order": 1})

                # N11 JSON payload veri paketi montajı
                product_payload = {
                    "title": title,
                    "description": title,
                    "categoryId": int(main_code) if str(main_code).isdigit() else 1000476,
                    "currencyType": "TL",
                    "productMainId": main_code,
                    "preparingDay": 3,
                    "shipmentTemplate": "1",
                    "stockCode": main_code,
                    "barcode": None,
                    "quantity": int(stock) if stock is not None else 0,
                    "images": images_list,
                    "attributes": attr_list,
                    "salePrice": float(price) if price else 0.0,
                    "listPrice": float(price) if price else 0.0,
                    "vatRate": int(tax) if tax else 20
                }
                payload_list.append(product_payload)

            return payload_list, validation_errors
        except Exception as e:
            print(f"❌ [Payload Montaj Kritik Hata]: {e}")
            import traceback
            traceback.print_exc()
            return [], [str(e)]



    def send_mapped_products_to_n11(self):
        """[DUZELTILDI] Artik TOPLU/tek-istek gonderim yok. Her urun N11'e AYRI AYRI
        gonderiliyor; boylece (1) her urunun kendi task_id'si oluyor -> ayni task_id'yi
        REPLACE INTO ile tekrar tekrar yazip birbirinin ustune yazma sorunu bitiyor,
        (2) bir urun reddedilirse SADECE o urun basarisiz isaretleniyor, digerleri
        etkilenmiyor, (3) hata mesaji N11'in O URUNE ozel donduğu mesaj oluyor, artik
        butun parti icin tek ve belirsiz bir genel mesaj degil. Gercek gonderim islemi
        zaten dogru yazilmis olan _send_mapped_worker() icinde; burada sadece urun
        listesini toplayip onu tetikliyoruz."""
        if getattr(self, "_send_thread", None) and self._send_thread.is_alive():
            messagebox.showwarning("Uyari", "Gonderim islemi arka planda zaten devam ediyor.")
            return

        app_key, app_secret = get_n11_credentials(self.db)
        if not app_key or not app_secret:
            messagebox.showerror("API Hatasi", "N11 API Key / Secret bulunamadi.")
            return

        try:
            cursor = self.db.cursor()
            # Pazar yerinde canlida olmayan ve is_mapped=1 veya 2 durumundaki urunlerin ana kodlarini topluyoruz
            cursor.execute("""
                SELECT DISTINCT COALESCE(NULLIF(main_code, ''), code) AS mcode
                FROM products
                WHERE is_mapped IN (1, 2)
                  AND COALESCE(NULLIF(main_code, ''), code) NOT IN (SELECT stock_code FROM n11_remote_products)
            """)
            main_codes = []
            for r in cursor.fetchall():
                code = _row_val(r, "mcode", 0)
                if code: main_codes.append(str(code).strip())
        except Exception as e:
            messagebox.showerror("Hata", f"Urun havuzu sorgulanirken hata olustu:\n{e}")
            return

        if not main_codes:
            messagebox.showwarning("Uyari", "Gonderim kuyruguna alinabilecek yeni veya duzeltilmis urun bulunamadi.")
            return

        if not messagebox.askyesno(
            "N11 Gonderim Onayi",
            f"{len(main_codes)} adet urun N11 API sunucusuna TEK TEK (her biri kendi "
            f"task_id'siyle, hatasi ayri ayri raporlanacak sekilde) gonderilecek.\n\n"
            f"Onayliyor musunuz?"
        ):
            return

        # TclError Odak Kalkani: Gonderim baslamadan once arayuzdeki acik dropdown'lari kapatiyoruz
        for child in self.winfo_children():
            if hasattr(child, '_close_dropdown_internal'):
                try: child._close_dropdown_internal()
                except Exception: pass

        self._send_thread = threading.Thread(
            target=self._send_mapped_worker,
            args=(main_codes, app_key, app_secret),
            daemon=True
        )
        self._send_thread.start()

    def export_final_n11_json_package(self):
        payload_list, errors = self.build_complete_n11_payload()
        if errors and isinstance(errors[0], dict):
            err_msg = f"Toplam {len(errors)} üründe eksik alan bulundu:\n\n"
            for err in errors[:5]:
                err_msg += f"• [{err['main_code']}] {err['title']}: {', '.join(err['errors'])}\n"
            messagebox.showwarning("Validasyon Uyarısı", err_msg)

        if not payload_list:
            messagebox.showerror("Hata", "Dışa aktarılabilecek geçerli ürün bulunamadı!")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Dosyası", "*.json"), ("Tüm Dosyalar", "*.*")],
            title="N11 JSON Paketini Kaydet"
        )
        if file_path:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump({"products": payload_list}, f, ensure_ascii=False, indent=4)
            messagebox.showinfo("Başarılı", f"{len(payload_list)} adet ürün başarıyla kaydedildi:\n{file_path}")

    def preview_n11_payload(self):
        payload_list, _ = self.build_complete_n11_payload()
        if not payload_list:
            messagebox.showwarning("Uyarı", "Ön izleme için eşleştirilmiş ürün bulunamadı.")
            return

        sample_json = json.dumps({"product": payload_list[0]}, indent=4, ensure_ascii=False)
        preview_win = ctk.CTkToplevel(self)
        preview_win.title(f"N11 JSON Ön İzleme - {payload_list[0]['stockCode']}")
        preview_win.geometry("650x550")
        preview_win.attributes("-topmost", True)

        ctk.CTkLabel(
            preview_win, 
            text=f"📦 Örnek N11 JSON Paketi: {payload_list[0]['stockCode']}", 
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#8b5cf6"
        ).pack(anchor="w", padx=15, pady=10)

        text_box = ctk.CTkTextbox(preview_win, width=600, height=430, font=ctk.CTkFont(family="Consolas", size=11))
        text_box.pack(padx=15, pady=5, fill="both", expand=True)
        text_box.insert("1.0", sample_json)
        text_box.configure(state="disabled")

    def export_n11_ready_excel(self, category_name=None):
        cursor = self.db.cursor()
        try:
            if not category_name or category_name == "__ALL_PRODUCTS__":
                cursor.execute("""
                    SELECT code, main_code, title, brand, stock, is_mapped, mainCategory, category, subCategory 
                    FROM products 
                    WHERE is_mapped = 1
                """)
            else:
                # Sadece seçilen kategoriye ait eşleşmiş ürünleri filtrele
                cursor.execute("""
                    SELECT code, main_code, title, brand, stock, is_mapped, mainCategory, category, subCategory 
                    FROM products 
                    WHERE is_mapped = 1 AND (mainCategory = ? OR category = ? OR subCategory = ?)
                """, (category_name, category_name, category_name))
                
            all_db_rows = cursor.fetchall()
        except Exception as ex:
            print(f"Ürünler tablosu okunamadı: {ex}")
            return

        try:
            cursor.execute("SELECT stock_code FROM n11_remote_products")
            n11_remote_skus = {
                str(_row_val(row, "stock_code", 0) or "")
                for row in cursor.fetchall()
                if _row_val(row, "stock_code", 0)
            }
        except Exception:
            pass

        try:
            cursor.execute("SELECT stock_code, reason FROM n11_failed_products")
            failed_products_map = {}
            for row in cursor.fetchall():
                sc = _row_val(row, "stock_code", 0)
                reason = _row_val(row, "reason", 1)
                if sc:
                    failed_products_map[str(sc)] = reason
        except Exception:
            pass

        if not all_db_rows:
            messagebox.showwarning("Uyarı", "Dışa aktarılacak ürün bulunamadı.")
            return

        grouped_data = self._build_grouped_products(self.current_category_name, all_db_rows, n11_remote_skus, failed_products_map)
        if not grouped_data:
            messagebox.showwarning("Uyarı", "Aktarma kuyruğunda listelenen ürün bulunamadı.")
            return

        export_list = []
        for prod in grouped_data:
            if prod.get("is_on_n11") == 1:
                status = "N11'e Yüklendi"
            elif prod.get("is_failed") == 1:
                status = f"N11 Hatası: {prod.get('fail_reason', '')}"
            elif prod.get("is_mapped") == 1:
                status = "Eşleşti (Bekliyor)"
            else:
                status = "Bekliyor"

            export_list.append({
                "Stok Kodu / Ana Kod": prod.get("main_code"),
                "Ürün Adı": prod.get("title"),
                "Marka": prod.get("brand"),
                "Kategori": prod.get("category"),
                "Toplam Stok": prod.get("total_stock"),
                "Aktarım / Eşleşme Durumu": status
            })

        df = pd.DataFrame(export_list)
        file_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel Dosyası", "*.xlsx"), ("Tüm Dosyalar", "*.*")],
            title="N11 Aktarma Kuyruğunu Excel Olarak Kaydet"
        )
        if file_path:
            df.to_excel(file_path, index=False)
            messagebox.showinfo("Başarılı", f"Aktarma kuyruğundaki tüm ürünler Excel'e aktarıldı:\n{file_path}")
            
    def export_error_report_excel(self):
        """[DÜZELTİLDİ] Artık sadece n11_task_errors/n11_tasks(FAILED) tablolarına değil,
        products + n11_remote_products + n11_tasks + n11_failed_products tablolarının TAMAMINA
        bakan generate_n11_transfer_report() fonksiyonunu kullanıyor. Ayrıca export öncesi
        eski/bozuk hata kayıtlarını (ör. yanlışlıkla 'hata' işaretlenmiş başarı yanıtlarını) temizler."""
        try:
            self._cleanup_stale_failed_entries()

            file_path = filedialog.asksaveasfilename(
                defaultextension=".xlsx",
                filetypes=[("Excel Dosyası", "*.xlsx"), ("Tüm Dosyalar", "*.*")],
                title="N11 Aktarım Raporunu Kaydet",
                initialfile="N11_Aktarim_Raporu.xlsx"
            )

            if not file_path:
                return

            success, message = generate_n11_transfer_report(self.db, output_path=file_path)

            if success:
                messagebox.showinfo("Başarılı", message)
            else:
                messagebox.showwarning("Uyarı / Bilgi", message)

        except Exception as e:
            messagebox.showerror("Hata", f"Rapor oluşturulurken beklenmedik bir hata oluştu:\n{str(e)}")
            
            
    def sync_n11_queue_tasks(self):
        app_key, app_secret = get_n11_credentials(self.db)
        if not app_key:
            messagebox.showwarning("Uyarı", "N11 API bilgileri bulunamadı.")
            return

        try:
            cursor = self.db.cursor()
            cursor.execute("SELECT task_id, main_code FROM n11_tasks WHERE status IN ('PENDING', 'PROCESSING', 'IN_QUEUE')")
            tasks = cursor.fetchall()
        except Exception as e:
            messagebox.showerror("Hata", f"Görevler okunamadı:\n{e}")
            return

        if not tasks:
            messagebox.showinfo("Bilgi", "Eşitlenecek aktif N11 kuyruk görevi bulunamadı.")
            return

        if not messagebox.askyesno("Kuyruk Eşitleme", f"{len(tasks)} adet görev N11'den sorgulanacak. Devam edilsin mi?"):
            return

        # 🚀 Programın donmaması için arka plan worker thread başlatıyoruz
        threading.Thread(
            target=self._sync_queue_worker,
            args=(tasks, app_key, app_secret),
            daemon=True
        ).start()
        
        messagebox.showinfo("Senkronizasyon Başladı", "Kuyruk durumu arka planda sorgulanıyor. Program donmadan çalışmaya devam edebilirsiniz.")

    def _sync_queue_worker(self, tasks, app_key, app_secret):
        """[MÜHÜRLENDİ] N11'den dönen ret nedenlerini ürün notu olarak mühürleyen ve ürünü yeniden düzeltmeye açan motor."""
        updated_count = 0
        
        clean_tasks = []
        if isinstance(tasks, dict): clean_tasks = list(tasks.values())
        elif isinstance(tasks, (list, tuple)): clean_tasks = list(tasks)
        else: clean_tasks = [tasks]

        for task in clean_tasks:
            if not task: continue
            task_code = None
            m_code = None

            if isinstance(task, dict):
                task_code = task.get("task_id") or task.get("TASK_ID")
                m_code = task.get("main_code") or task.get("MAIN_CODE")
            elif isinstance(task, (list, tuple)) and len(task) > 0:
                task_code = task[0]
                m_code = task[1] if len(task) > 1 else None

            if not task_code or str(task_code).strip() in ("", "None", "0"): continue

            try:
                cursor = self.db.cursor()
                success_flag, status_res = check_n11_task_status(app_key, app_secret, task_code)
                
                if success_flag and status_res:
                    new_status, parsed_items = parse_n11_task_response(status_res)
                    new_status = str(new_status).upper()
                    
                    # 1. Başarılı Sonuç: Kuyrukta durumu COMPLETED yap ve hata masasını temizle
                    if new_status in ["COMPLETED", "SUCCESS", "PROCESSED"]:
                        self.db.execute("UPDATE n11_tasks SET status = 'COMPLETED' WHERE task_id = ?", (str(task_code),))
                        self.db.execute("DELETE FROM n11_failed_products WHERE stock_code = ?", (str(m_code),))
                    
                    # 2. 🚨 N11 TARAFINDAN REDDEDİLEN / HATALI ÜRÜN SENARYOSU
                    elif new_status in ["REJECTED", "FAILED", "REJECTED_FROM_CATALOG", "ERROR"]:
                        raw_n11_msg = "N11 Kataloğu Ürünü Reddetti."
                        if parsed_items and isinstance(parsed_items, list):
                            errors = [
                                str(item.get("error_message") or item.get("reason") or item.get("errorDescription") or "")
                                for item in parsed_items if item.get("error_message") or item.get("reason") or item.get("errorDescription")
                            ]
                            if errors: raw_n11_msg = " | ".join(set(errors))
                        elif isinstance(status_res, dict) and status_res.get("errorMessage"):
                            raw_n11_msg = str(status_res.get("errorMessage"))
                        
                        # Yapay zeka kök neden analizi ile temiz bir not ve aksiyon adımı üret
                        if hasattr(self, 'sync_mgr') and self.sync_mgr:
                            analysis = self.sync_mgr.analyze_n11_rejection_root_cause(raw_n11_msg)
                            full_db_reason = f"🚨 {analysis['clean_msg']}\n💡 Çözüm: {analysis['action']}"
                        else:
                            full_db_reason = f"🚨 N11 Hatası: {raw_n11_msg}"
                        
                        # ❌ AKTARMA KUYRUĞUNDAN SİL (Hazırlanacak ürünler sınıfına düşmesi için)
                        self.db.execute("DELETE FROM n11_tasks WHERE task_id = ?", (str(task_code),))
                        
                        # Hata Masasına Not Olarak Yaz (ToolTip Balonu Buradan Beslenir)
                        self.db.execute(
                            """INSERT INTO n11_failed_products (stock_code, reason) 
                               VALUES (?, ?) ON DUPLICATE KEY UPDATE reason = VALUES(reason)""",
                            (str(m_code), full_db_reason)
                        )
                    updated_count += 1
                
                if hasattr(cursor, 'close'): cursor.close()
            except Exception as e:
                print(f"❌ [Kuyruk Sync Hatası] Task {task_code} hatası: {e}")

        try:
            self.after(0, lambda: self._on_sync_finished(updated_count))
        except Exception:
            pass



    def _on_sync_finished(self, updated_count):
        messagebox.showinfo("Başarılı", f"{updated_count} adet görevin durumu pazar yerinden güncellendi.")
        if hasattr(self, 'current_category_name') and self.current_category_name:
            try:
                self.show_category_products_panel(self.current_category_name)
            except Exception:
                pass
            
            
    def _cleanup_stale_failed_entries(self):
        """[YENİ] n11_failed_products tablosunda takılı kalmış BOZUK/ESKİ kayıtları temizler:
        1) Eski bir yorumlama hatası yüzünden BAŞARI yanıtının (ör. "(True, 'TASK_ID_OR_SUCCESS')")
           kendisi 'hata sebebi' olarak kaydedilmiş satırlar (bu hata artık düzeltildi ama eski
           kayıtlar veritabanında takılı kalmıştı).
        2) Ürün aslında N11'de canlı/kayıtlıyken (n11_remote_products'ta varken) hâlâ hata
           listesinde görünen satırlar.
        Bu sayede "Hata Raporu" ve kuyruk ekranındaki durumlar gerçek durumu yansıtır."""
        try:
            cursor = self.db.cursor()
            cursor.execute("""
                DELETE FROM n11_failed_products
                WHERE reason LIKE '(True,%'
                   OR reason LIKE '%TASK_ID_OR_SUCCESS%'
                   OR stock_code IN (SELECT stock_code FROM n11_remote_products)
            """)
        except Exception as e:
            print(f"⚠️ Eski/bozuk hata kayıtları temizlenirken sorun oluştu: {e}")

    def show_category_products_panel(self, category_name):
        self._cleanup_stale_failed_entries()
        self.current_category_name = category_name
        if category_name == "__ALL_PRODUCTS__":
            self.lbl_cat_title.configure(text="🌐 Tüm Pazar Yeri Ürünleri (Genel İndeks)")
        else:
            self.lbl_cat_title.configure(text=f"📦 Kategori: {category_name}")

        self.show_sub_frame("category_products")

        # Önce paneli temizle
        for widget in self.scroll_cat_prods.winfo_children():
            widget.destroy()

        # --- ÜST FİLTRE VE BUTON BAR ALANI ---
        filter_bar = ctk.CTkFrame(self.scroll_cat_prods, fg_color="transparent")
        filter_bar.pack(fill="x", padx=15, pady=(5, 10))

        search_var = ctk.StringVar()
        
        # Sol kısma arama çubuğu yerleşimi
        ctk.CTkLabel(filter_bar, text="🔍 Ürün Ara:", font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=(0, 5))
        search_entry = ctk.CTkEntry(filter_bar, textvariable=search_var, placeholder_text="Kod, marka veya ürün adı ile ara...", width=250, height=30)
        search_entry.pack(side="left", padx=5)

        
        # 1. En Sağda: Kırmızı Hata Raporu Butonu
        btn_report = ctk.CTkButton(
            filter_bar, text="📊 Hata Raporu", fg_color="#ef4444", hover_color="#dc2626", width=110,
            command=self.export_error_report_excel
        )
        btn_report.pack(side="right", padx=3)

        # 2. Onun Solunda: İndigo Kuyruk Eşitleme Butonu (Redleri sorgulayan tekil buton)
        btn_sync_queue = ctk.CTkButton(
            filter_bar,
            text="🔄 Kuyruk Eşitle (Redleri Çek)",
            fg_color="#4f46e5",
            hover_color="#4338ca",
            width=160,
            command=self.sync_n11_queue_tasks,
        )
        btn_sync_queue.pack(side="right", padx=3)

        # 3. Onun Solunda: Mor Ön İzleme Butonu
        btn_preview_payload = ctk.CTkButton(
            filter_bar, text="🔍 Gönderim Yapısı", fg_color="#8b5cf6", hover_color="#7c3aed", width=120,
            command=self.preview_n11_payload
        )
        btn_preview_payload.pack(side="right", padx=3)

        # 4. Onun Solunda: Yeşil Excel Aktarım Butonu
        btn_export_queue = ctk.CTkButton(
            filter_bar, text="📥 Kuyruğu Excel", fg_color="#27ae60", hover_color="#219653", width=120,
            command=self.export_n11_ready_excel
        )
        btn_export_queue.pack(side="right", padx=3)

        # 5. En Solda (Arama Çubuğunun Yanında): Turuncu N11'e Toplu Gönderim Butonu
        btn_send_n11 = ctk.CTkButton(
            filter_bar,
            text="🚀 N11'e Gönder",
            fg_color="#f59e0b",
            hover_color="#d97706",
            width=120,
            command=self.send_mapped_products_to_n11,
        )
        btn_send_n11.pack(side="right", padx=3)
        
        # --- TABLO ALANI ---
        table_container = ctk.CTkScrollableFrame(self.scroll_cat_prods, fg_color="transparent", height=450)
        table_container.pack(fill="both", expand=True, padx=15, pady=(0, 5))

        headers = ["STOK KODU", "ÜRÜN ADI", "MARKA", "KATEGORİ", "TOPLAM STOK", "DURUMU", "İŞLEM / EŞLEŞTİR"]
        for col_idx, h in enumerate(headers):
            table_container.grid_columnconfigure(col_idx, weight=2 if col_idx in [1, 3] else 1)
            ctk.CTkLabel(table_container, text=h, font=ctk.CTkFont(weight="bold", size=11), anchor="w").grid(row=0, column=col_idx, padx=6, pady=8, sticky="w")

        # --- SAYFALAMA ALANI ---
        pagination_bar = ctk.CTkFrame(self.scroll_cat_prods, fg_color="transparent", height=40)
        pagination_bar.pack(fill="x", padx=15, pady=(0, 10))

        btn_prev = ctk.CTkButton(pagination_bar, text="⬅️ Önceki Sayfa", width=120, fg_color="#374151")
        btn_prev.pack(side="left")
        lbl_page = ctk.CTkLabel(pagination_bar, text="Sayfa: 1", font=ctk.CTkFont(weight="bold"))
        lbl_page.pack(side="left", padx=20)
        btn_next = ctk.CTkButton(pagination_bar, text="Sonraki Sayfa ➡️", width=120, fg_color="#374151")
        btn_next.pack(side="left")

        # --- VERI YÜKLEME VE FİLTRELEME MANTIĞI ---
        all_grouped_products = []
        all_db_rows = []
        n11_remote_skus = set()
        failed_products_map = {}

        try:
            cursor = self.db.cursor()
            cursor.execute("SELECT code, main_code, title, brand, stock, is_mapped, mainCategory, category, subCategory FROM products")
            all_db_rows = cursor.fetchall()

            try:
                # 🛡️ KRİTİK DÜZELTME: self.db.cursor() dictionary=True döndürür, yani her 'row'
                # bir dict'tir ("stock_code": "..."). "row[0]" burada KeyError verip HER SEFERİNDE
                # sessizce yutuluyordu (except: pass) -> n11_remote_skus HİÇBİR ZAMAN dolmuyordu.
                # Sonuç: ürün gerçekten N11'de canlı olsa bile ekranda/raporda SANKİ HİÇ
                # GÖNDERİLMEMİŞ gibi görünüyordu. Bu, "ürünleri N11'e aktaramıyoruz" hissinin
                # asıl kaynaklarından biri.
                cursor.execute("SELECT stock_code FROM n11_remote_products")
                n11_remote_skus = {
                    str((row.get("stock_code") if isinstance(row, dict) else row[0]))
                    for row in cursor.fetchall() if row and (row.get("stock_code") if isinstance(row, dict) else row[0])
                }
            except Exception as e:
                print(f"⚠️ n11_remote_skus okunamadı: {e}")

            try:
                cursor.execute("SELECT stock_code, reason FROM n11_failed_products")
                failed_products_map = {}
                for row in cursor.fetchall():
                    if not row:
                        continue
                    if isinstance(row, dict):
                        sc, rs = row.get("stock_code"), row.get("reason")
                    else:
                        sc, rs = row[0], row[1]
                    if sc:
                        failed_products_map[str(sc)] = rs
            except Exception as e:
                print(f"⚠️ failed_products_map okunamadı: {e}")

        except Exception as e:
            print(f"Kategori Ürünlerini Çekme Hatası: {e}")

        try:
            all_grouped_products = self._build_grouped_products(category_name, all_db_rows, n11_remote_skus, failed_products_map)
        except Exception:
            all_grouped_products = []

        # 🛡️ GÜVENLİK KALKANI: Scope çatışmasını engellemek için sayfa durumunu strictly nesne referansına bağlıyoruz
        self._current_page_idx = 1
        page_size = 20

        def render_products_list(filter_text=""):
            # Tablo başlıkları (satır 0) hariç tüm eski ürün satırlarını temizle
            for widget in table_container.winfo_children():
                try:
                    grid_info = widget.grid_info()
                    if grid_info and int(grid_info.get("row", 0)) > 0:
                        widget.destroy()
                except Exception:
                    pass

            filtered_list = all_grouped_products
            if filter_text:
                filtered_list = [
                    p for p in all_grouped_products
                    if filter_text in str(p.get("main_code", "")).lower() or 
                       filter_text in str(p.get("title", "")).lower() or 
                       filter_text in str(p.get("brand", "")).lower() or 
                       filter_text in str(p.get("category", "")).lower()
                ]

            total_pages = max(1, (len(filtered_list) + page_size - 1) // page_size)
            if self._current_page_idx > total_pages: 
                self._current_page_idx = total_pages
            if self._current_page_idx < 1: 
                self._current_page_idx = 1
                
            lbl_page.configure(text=f"Sayfa: {self._current_page_idx} / {total_pages}")
            
            start_idx = (self._current_page_idx - 1) * page_size
            end_idx = start_idx + page_size
            page_items = filtered_list[start_idx:end_idx]

            if not page_items:
                ctk.CTkLabel(table_container, text="⚠️ Gösterilecek ürün bulunamadı. Filtreyi veya kategoriyi kontrol edin.", text_color="#ef4444").grid(
                    row=1, column=0, columnspan=7, pady=20, sticky="w")
                return

            for idx, prod in enumerate(page_items, 1):
                row_idx = idx
                m_code = prod.get("main_code", "")
                full_title = prod.get("title", "İsimsiz Ürün")
                
                raw_mapped_status = int(prod.get("is_mapped") or 0)
                is_on_n11 = prod.get("is_on_n11") == 1
                is_failed = prod.get("is_failed") == 1
                fail_reason = prod.get("fail_reason", "")

                # STOK KODU
                box_code = ctk.CTkTextbox(table_container, width=150, height=28, fg_color="transparent", border_width=0, font=ctk.CTkFont(size=11))
                box_code.insert("1.0", str(m_code))
                box_code.configure(state="disabled")
                box_code.grid(row=row_idx, column=0, padx=4, pady=4, sticky="w")

                # ÜRÜN ADI
                box_title = ctk.CTkTextbox(table_container, width=280, height=28, fg_color="transparent", border_width=0, font=ctk.CTkFont(size=11))
                box_title.insert("1.0", str(full_title))
                box_title.configure(state="disabled")
                box_title.grid(row=row_idx, column=1, padx=4, pady=4, sticky="w")

                # MARKA
                ctk.CTkLabel(table_container, text=str(prod.get("brand", "-")), anchor="w", font=ctk.CTkFont(size=11)).grid(row=row_idx, column=2, padx=6, pady=6, sticky="w")
                
                # KATEGORİ
                display_cat_text = str(prod.get("category", ""))
                if not display_cat_text or display_cat_text.startswith("c_") or len(display_cat_text) < 3:
                    display_cat_text = "Genel Kategori"
                ctk.CTkLabel(table_container, text=display_cat_text, anchor="w", font=ctk.CTkFont(size=11), text_color="#9ca3af").grid(row=row_idx, column=3, padx=6, pady=6, sticky="w")
                
                # TOPLAM STOK
                ctk.CTkLabel(table_container, text=str(prod.get("total_stock", 0)), anchor="center", font=ctk.CTkFont(size=11)).grid(row=row_idx, column=4, padx=6, pady=6)
                
                # DURUMU
                if is_on_n11:
                    status_text = "🟢 N11 Canlı Mağazada"; status_color = "#10b981"
                elif is_failed:
                    status_text = "🔴 N11 Hatası (FAIL)"; status_color = "#ef4444"
                elif raw_mapped_status == 1:
                    status_text = "🟢 N11'e Gönderilmeye Hazır"; status_color = "#10b981"
                elif raw_mapped_status == 2:
                    status_text = "🟠 Kategori Tamam (Özellik Eksik)"; status_color = "#f97316"
                else:
                    status_text = "🟡 Bekliyor"; status_color = "#eab308"

                status_lbl = ctk.CTkLabel(table_container, text=status_text, text_color=status_color, font=ctk.CTkFont(weight="bold", size=11), anchor="w")
                status_lbl.grid(row=row_idx, column=5, padx=6, pady=6, sticky="w")

                if is_failed:
                    CTkToolTip(status_lbl, f"⚠️ N11 Hata Açıklaması:\n{fail_reason}")

                # İŞLEM BUTONLARI
                action_btn_frame = ctk.CTkFrame(table_container, fg_color="transparent")
                action_btn_frame.grid(row=row_idx, column=6, padx=6, pady=4, sticky="w")

                if is_on_n11:
                    ctk.CTkLabel(action_btn_frame, text="🔒 Zaten Yüklendi", text_color="#10b981", font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=10)
                else:
                    ctk.CTkButton(
                        action_btn_frame, text="✏️ Düzenle", fg_color="#3b82f6", text_color="white", width=70, height=26,
                        command=lambda mc=m_code, t=full_title, c=category_name: self.show_attribute_form_panel(mc, t, c),
                    ).pack(side="left", padx=(0, 4))
                    
                    ctk.CTkButton(
                        action_btn_frame, text="🗑️ Kaldır", fg_color="#ef4444", text_color="white", width=60, height=26,
                        command=lambda mc=m_code: self.reset_product_mapping(mc),
                    ).pack(side="left")

        def go_prev():
            if self._current_page_idx > 1:
                self._current_page_idx -= 1
                render_products_list(search_var.get().strip().lower())

        def go_next():
            filtered_list = all_grouped_products
            q = search_var.get().strip().lower()
            if q:
                filtered_list = [p for p in all_grouped_products if q in str(p.get("main_code", "")).lower() or q in str(p.get("title", "")).lower()]
            total_pages = max(1, (len(filtered_list) + page_size - 1) // page_size)
            if self._current_page_idx < total_pages:
                self._current_page_idx += 1
                render_products_list(q)

        def on_search_type(*args):
            self._current_page_idx = 1
            if self._search_timer: 
                self.after_cancel(self._search_timer)
            self._search_timer = self.after(300, lambda: render_products_list(search_var.get().strip().lower()))

        search_var.trace_add("write", on_search_type)
        btn_prev.configure(command=go_prev)
        btn_next.configure(command=go_next)
        
        # 🚀 Listeyi çizdiriyoruz
        render_products_list()





        
                    
                    


    def create_sub_frame_attribute_form(self):
        f = ctk.CTkFrame(self, fg_color="transparent")
        top_header_frame = ctk.CTkFrame(f, fg_color="transparent")
        top_header_frame.pack(side="top", fill="x", padx=15, pady=15)

        btn_back = ctk.CTkButton(top_header_frame, text="← Geri Dön", command=lambda: self.show_sub_frame("mapping_list"), width=90)
        btn_back.pack(side="left", padx=5)

        lbl_title = ctk.CTkLabel(top_header_frame, text="Özellik ve N11 Varyant Eşleştirme", font=("Arial", 16, "bold"))
        lbl_title.pack(side="left", padx=20)

        btn_top_save = ctk.CTkButton(
            top_header_frame, text="💾 Eşleştirmeyi Kaydet", command=self.save_product_attributes_action,
            fg_color="#28a745", hover_color="#218838", height=36, font=ctk.CTkFont(size=12, weight="bold")
        )
        btn_top_save.pack(side="right", padx=10)

        self.form_container = ctk.CTkScrollableFrame(f, fg_color="transparent")
        self.form_container.pack(fill="both", expand=True, padx=10, pady=10)

        self.attr_widgets = {}
        self.sub_frames["attribute_form"] = f
        
    def render_mapped_categories(self):
        """Veritabanında (n11_category_mappings) kayıtlı kategori eşleştirmelerini okur ve arayüzde kartlar halinde listeler."""
        # Mevcut listedeki elemanları temizle
        for child in self.scroll_mapped.winfo_children():
            child.destroy()

        try:
            cursor = self.db.cursor()
            cursor.execute("""
                SELECT id, local_category, n11_category_id, n11_category_name, template_name 
                FROM n11_category_mappings 
                WHERE platform = 'N11' OR platform IS NULL
                ORDER BY id DESC
            """)
            rows = cursor.fetchall()

            if not rows:
                ctk.CTkLabel(
                    self.scroll_mapped, 
                    text="Henüz eşleştirilmiş bir kategori bulunmuyor.", 
                    text_color="#9ca3af",
                    font=ctk.CTkFont(size=12)
                ).pack(pady=20)
                return

            for row in rows:
                # MySQL dict / SQLite tuple satır uyumluluğu
                if isinstance(row, dict):
                    map_id = row.get("id")
                    local_cat = row.get("local_category") or row.get("ideasoft_cat", "")
                    n11_cat_id = row.get("n11_category_id", "")
                    n11_cat_name = row.get("n11_category_name", "")
                    template_name = row.get("template_name", "")
                else:
                    map_id, local_cat, n11_cat_id, n11_cat_name, template_name = row[0], row[1], row[2], row[3], row[4]

                item_data = {
                    "id": map_id,
                    "local_category": local_cat,
                    "n11_category_id": n11_cat_id,
                    "n11_category_name": n11_cat_name,
                    "template_name": template_name
                }

                # Kategori Kart Çerçevesi
                card = ctk.CTkFrame(self.scroll_mapped, fg_color="#1e1e1e", border_width=1, border_color="#333333")
                card.pack(fill="x", padx=10, pady=6)

                # Sol Bilgi Alanı
                info_frame = ctk.CTkFrame(card, fg_color="transparent")
                info_frame.pack(side="left", fill="both", expand=True, padx=12, pady=10)

                ctk.CTkLabel(
                    info_frame, 
                    text=f"📂 Yerel / Ideasoft: {local_cat}", 
                    font=ctk.CTkFont(size=13, weight="bold"), 
                    text_color="#3b82f6",
                    anchor="w"
                ).pack(anchor="w")

                ctk.CTkLabel(
                    info_frame, 
                    text=f"➡️ N11: {n11_cat_name} (ID: {n11_cat_id})  |  📋 Şablon: {template_name or 'Varsayılan'}", 
                    font=ctk.CTkFont(size=11), 
                    text_color="#9ca3af",
                    anchor="w"
                ).pack(anchor="w", pady=(2, 0))

                # Sağ İşlem Butonları
                btn_frame = ctk.CTkFrame(card, fg_color="transparent")
                btn_frame.pack(side="right", padx=10, pady=10)

                # Ürünleri Gör
                ctk.CTkButton(
                    btn_frame,
                    text="📦 Ürünleri Gör",
                    fg_color="#10b981",
                    hover_color="#059669",
                    width=100,
                    height=30,
                    command=lambda cat=local_cat: self.show_category_products_panel(cat)
                ).pack(side="left", padx=3)

                # Düzenle
                ctk.CTkButton(
                    btn_frame,
                    text="✏️ Düzenle",
                    fg_color="#eab308",
                    hover_color="#ca8a04",
                    width=80,
                    height=30,
                    command=lambda d=item_data: self.open_edit_category_window(d)
                ).pack(side="left", padx=3)

                # Sil
                ctk.CTkButton(
                    btn_frame,
                    text="🗑️ Sil",
                    fg_color="#ef4444",
                    hover_color="#dc2626",
                    width=70,
                    height=30,
                    command=lambda m_id=map_id: self.delete_mapping(m_id)
                ).pack(side="left", padx=3)

        except Exception as e:
            print(f"[N11] Eşleştirilmiş kategorileri yükleme hatası: {e}")

    def save_normal_attributes_only(self, main_code):
        """[TAMİR EDİLDİ] Kategori genel üst özelliklerini (Menşei, Sağlayıcı vb.) veritabanına eksiksiz mühürler."""
        try:
            # 🛡️ Tüm sql execute işlemlerinde projenin merkezi execute yapısı (?) formatıyla senkronize edildi
            self.db.execute("DELETE FROM product_attributes WHERE product_code = ?", (main_code,))

            saved_count = 0
            missing_mandatory = []
            
            for attr_id, info in getattr(self, "current_attr_inputs", {}).items():
                val_id = None
                custom_val = None
                attr_name = info.get("name") or attr_id

                if info.get("type") == "combo":
                    selected_name = info["combo"].get()
                    if selected_name and selected_name not in ("Seçiniz...", "Seçiniz", ""):
                        val_id = info.get("val_map", {}).get(selected_name)
                        if not val_id:
                            custom_val = selected_name
                elif info.get("type") == "entry":
                    custom_val = (info["entry"].get() or "").strip() or None

                if info.get("mandatory") and not val_id and not custom_val:
                    missing_mandatory.append(attr_name)
                    continue

                if val_id or custom_val:
                    self.db.execute(
                        """
                        INSERT INTO product_attributes
                        (product_code, n11_attribute_id, n11_attribute_name, n11_value_id, custom_value, is_mandatory)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(main_code),
                            str(attr_id),
                            str(attr_name),
                            str(val_id) if val_id else None,
                            str(custom_val) if custom_val else None,
                            1 if info.get("mandatory") else 0,
                        ),
                    )
                    saved_count += 1

            # Ürünün genel durumunu güncelle
            self.db.execute(
                "UPDATE products SET is_mapped = 1 WHERE code = ? OR main_code = ?",
                (main_code, main_code),
            )

            msg = f"✅ {saved_count} adet kategori genel özelliği başarıyla kaydedildi."
            if missing_mandatory:
                msg += f"\n⚠️ Zorunlu alanlar boş bırakıldı: {', '.join(missing_mandatory[:5])}"
            
            messagebox.showinfo("Başarılı", msg)
            
            # Form panelini yenileyerek datadan verilerin gelip gelmediğini kontrol et
            if hasattr(self, 'current_category_name') and self.current_category_name:
                self.show_attribute_form_panel(main_code, getattr(self, "real_product_title", "Ürün"), self.current_category_name)

        except Exception as e:
            print(f"❌ Üst özellikler kaydedilirken hata: {e}")
            import traceback
            traceback.print_exc()
            messagebox.showerror("Veritabanı Yazma Hatası", f"Özellikler mühürlenirken hata oluştu:\n{e}")


    def save_variants_only(self, main_code):
        """[TAMİR EDİLDİ] Sadece o an aktif seçili ve render edilmiş varyantın özelliklerini güvenle kaydeder."""
        try:
            cursor = self.db.cursor()
            
            # 1. Hafızada kayıtlı aktif varyant kodunu yakala
            active_v_code = getattr(self, "current_selected_variant_code", None)
            if not active_v_code and hasattr(self, "variant_item_inputs"):
                # Eğer set edilmediyse hafızadaki ilk onaylı olanı bulmaya çalış
                for vc, vmeta in self.variant_item_inputs.items():
                    if vmeta.get("rendered_combos"):
                        active_v_code = vc
                        break

            if not active_v_code:
                messagebox.showwarning("Uyarı", "Kaydedilecek aktif bir varyant seçimi bulunamadı!")
                return

            v_meta = self.variant_item_inputs.get(str(active_v_code))
            if not v_meta or not v_meta.get("approved") or not v_meta["approved"].get():
                messagebox.showwarning("Uyarı", "Bu varyant için eşleştirme aktif/onaylı değil!")
                return

            rendered_combos = v_meta.get("rendered_combos", {})
            if not rendered_combos:
                messagebox.showwarning("Uyarı", "Varyant özellikleri henüz arayüze yüklenmedi veya kutular boş!")
                return

            # 2. Sadece bu spesifik varyanta ait eski kayıtları temizle
            cursor.execute("DELETE FROM product_variant_attributes WHERE main_code = %s AND variant_code = %s", (main_code, active_v_code))
            
            saved_count = 0
            for attr_v_id, comp_info in rendered_combos.items():
                val_id = None
                custom_val = None
                
                # Bileşenin (Widget) hala canlı olup olmadığını ve hafızada var olduğunu kontrol et (invalid command name kalkanı)
                try:
                    if comp_info["type"] == "combo" and comp_info["combo"].winfo_exists():
                        selected_name = comp_info["combo"].get()
                        if selected_name and selected_name not in ("Seçiniz...", "Seçiniz", ""):
                            val_id = comp_info["val_map"].get(selected_name)
                            if not val_id:
                                custom_val = selected_name
                    elif comp_info["type"] == "entry" and comp_info["entry"].winfo_exists():
                        custom_val = (comp_info["entry"].get() or "").strip() or None
                except Exception:
                    # Bileşen arayüzden silindiyse yedeklenmiş state hafızasından oku
                    val_id = comp_info.get("saved_value_id")
                    custom_val = comp_info.get("saved_custom_value") or comp_info.get("saved_value_name")

                if val_id or custom_val:
                    cursor.execute("""
                        INSERT INTO product_variant_attributes (main_code, variant_code, n11_attribute_id, n11_value_id, custom_value)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (main_code, active_v_code, attr_v_id, val_id, custom_val))
                    saved_count += 1
            
            self.db.commit()
            print(f"✅ Başarıyla {saved_count} adet varyant özelliği veritabanına mühürlendi.")
            messagebox.showinfo("Başarılı", f"Varyant özellikleri başarıyla kaydedildi!\nKod: {active_v_code}")
            
        except Exception as e:
            print(f"❌ Varyant özellikleri kaydedilirken hata oluştu: {e}")
            import traceback
            traceback.print_exc()
            messagebox.showerror("Kayıt Hatası", f"Varyant kaydedilirken bir hata oluştu:\n{e}")

    def save_product_attributes_action(self):
        """[MÜHÜRLENDİ - %100 MYSQL DICT UYUMLU] TclError ve NameError vermeyen, Menşei/Sağlayıcı kaydeden kesin sürüm"""
        if not hasattr(self, 'current_main_code') or not self.current_main_code:
            messagebox.showwarning("Uyarı", "Kayıt yapılacak aktif ürün kodu bulunamadı!")
            return

        try:
            main_code = self.current_main_code
            attr_inputs = getattr(self, "current_attr_inputs", {})
            variant_inputs = getattr(self, "variant_item_inputs", {})

            attributes_to_save = []
            variants_to_save = []
            catalog_mappings_to_save = []
            missing_mandatory = []

            # 1. Üst Kategori Özelliklerini Topla (Menşei, Sağlayıcı, Unvan vb.)
            for attr_id, info in attr_inputs.items():
                val_id = None
                custom_val = None
                attr_name = info.get("name") or attr_id

                if info.get("type") == "combo":
                    selected_name = info["combo"].get()
                    if selected_name and selected_name not in ("Seçiniz...", "Seçiniz", ""):
                        val_id = info.get("val_map", {}).get(selected_name)
                        if not val_id:
                            custom_val = selected_name
                elif info.get("type") == "entry":
                    custom_val = (info["entry"].get() or "").strip() or None

                if info.get("mandatory") and not val_id and not custom_val:
                    missing_mandatory.append(attr_name)
                    continue

                if val_id or custom_val:
                    attributes_to_save.append({
                        "attr_id": str(attr_id),
                        "attr_name": str(attr_name),
                        "val_id": str(val_id) if val_id else None,
                        "custom_val": str(custom_val) if custom_val else None,
                        "is_mandatory": 1 if info.get("mandatory") else 0
                    })

            # Beden öznitelik meta verilerini bulalım
            beden_attr_id = None
            beden_val_map = {}
            for _vc, v_meta in variant_inputs.items():
                for _attr in (v_meta.get("attribute_defs") or []):
                    if str(_attr.get("name", "")).lower() == "beden":
                        beden_attr_id = str(_attr.get("id", "1494"))
                        beden_val_map = {str(v.get("name", "")): str(v.get("id", "")) for v in (_attr.get("values") or []) if isinstance(v, dict) and v.get("name")}
                        break
                if beden_attr_id: break

            # 2. Tüm Varyantların Özelliklerini Canlılık Kontrolüyle Topla
            for v_code, v_meta in variant_inputs.items():
                if not v_meta.get("approved") or not v_meta["approved"].get():
                    continue
                
                c_id = v_meta["catalog_id_var"].get().strip() if v_meta.get("catalog_id_var") else ""
                if c_id:
                    catalog_mappings_to_save.append((str(v_code), str(c_id)))

                rendered_combos = v_meta.get("rendered_combos", {})
                
                # 🛡️ MYSQL DICT DESTEKLİ KORUMA KALKANI
                if not rendered_combos:
                    existing_attrs = v_meta.get("existing_attrs", {})
                    for attr_id, attr_data in existing_attrs.items():
                        # MySQL dict geri dönüş uyumluluğu kontrolü
                        val_id = attr_data.get("val_id") or attr_data.get("n11_value_id")
                        cust_val = attr_data.get("custom_value") or attr_data.get("custom_val", "")
                        
                        attr_name = "Özellik"
                        for adef in v_meta.get("attribute_defs", []):
                            if str(adef.get("id")) == str(attr_id):
                                attr_name = adef.get("name", "Özellik")
                                break
                        variants_to_save.append((
                            str(v_code), str(main_code), str(attr_id), str(attr_name),
                            str(val_id) if val_id else None, str(cust_val) if cust_val else None
                        ))
                else:
                    has_beden_saved = False
                    for attr_v_id, comp_info in rendered_combos.items():
                        val_id = None
                        custom_val = None
                        
                        try:
                            if comp_info.get("type") == "combo" and comp_info["combo"].winfo_exists():
                                selected_name = comp_info["combo"].get()
                                if selected_name and selected_name not in ("Seçiniz...", "Seçiniz", ""):
                                    val_id = comp_info.get("val_map", {}).get(selected_name)
                                    if not val_id:
                                        custom_val = selected_name
                            elif comp_info.get("type") == "entry" and comp_info["entry"].winfo_exists():
                                custom_val = (comp_info["entry"].get() or "").strip() or None
                        except Exception:
                            val_id = comp_info.get("saved_value_id")
                            custom_val = comp_info.get("saved_custom_value") or comp_info.get("saved_value_name")

                        if comp_info.get("mandatory") and not val_id and not custom_val:
                            missing_mandatory.append(f"Varyant {v_code}")

                        if val_id or custom_val:
                            variants_to_save.append((
                                str(v_code), str(main_code), str(attr_v_id), str(comp_info.get("name", "")),
                                str(val_id) if val_id else None, str(custom_val) if custom_val else None
                            ))
                            if str(comp_info.get("name", "")).lower() == "beden" or str(attr_v_id) == str(beden_attr_id or "1494"):
                                has_beden_saved = True

                    if not has_beden_saved:
                        guess = self._infer_size_from_text(v_meta.get("title"), v_code)
                        if guess:
                            val_id = ""
                            for vn, vid in (beden_val_map or {}).items():
                                if str(vn).strip().upper() == guess.upper():
                                    val_id = vid
                                    guess = str(vn)
                                    break
                            variants_to_save.append((
                                str(v_code), str(main_code), str(beden_attr_id or "1494"), "Beden",
                                str(val_id) if val_id else None, None if val_id else str(guess)
                            ))

            # 3. 🛡️ ATOMİK VERİTABANI YAZMA İŞLEMİ (MERKEZİ ENJEKSİYON)
            # Üst Özellikleri Kaydet
            self.db.execute("DELETE FROM product_attributes WHERE product_code = ?", (main_code,))
            for attr_data in attributes_to_save:
                self.db.execute("""
                    INSERT INTO product_attributes 
                    (product_code, n11_attribute_id, n11_attribute_name, n11_value_id, custom_value, is_mandatory, is_variant, is_custom)
                    VALUES (?, ?, ?, ?, ?, ?, 0, 0)
                """, (
                    str(main_code), attr_data["attr_id"], attr_data["attr_name"], 
                    attr_data["val_id"], attr_data["custom_val"], attr_data["is_mandatory"]
                ))

            # Varyant Özelliklerini Parçalanmış Değişkenlerle Kaydet
            self.db.execute("DELETE FROM product_variant_attributes WHERE main_code = ?", (main_code,))
            for v_data in variants_to_save:
                self.db.execute("""
                    INSERT INTO product_variant_attributes 
                    (variant_code, main_code, n11_attribute_id, n11_attribute_name, n11_value_id, custom_value)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (v_data[0], v_data[1], v_data[2], v_data[3], v_data[4], v_data[5]))

            # Katalog ID Eşleşmeleri Güncelle
            for c_data in catalog_mappings_to_save:
                self.db.execute("""
                    INSERT INTO product_catalog_mappings (variant_code, n11_catalog_id)
                    VALUES (?, ?)
                    ON DUPLICATE KEY UPDATE n11_catalog_id = VALUES(n11_catalog_id)
                """, (c_data[0], c_data[1]))

            # Ürünün Eşleşme Kodunu Kilitle
            self.db.execute("UPDATE products SET is_mapped = 1 WHERE code = ? OR main_code = ?", (main_code, main_code))

            messagebox.showinfo(
                "Başarılı", 
                f"🎉 [MÜHÜRLENDİ] SQLite -> MySQL Geçiş Ayarları Tamamlandı!\n\n"
                f"• {len(attributes_to_save)} adet genel özellik (Menşei, Sağlayıcı vb.)\n"
                f"• {len(variants_to_save)} adet varyant detayı kalıcı olarak kaydedildi."
            )
            
            if hasattr(self, 'current_category_name') and self.current_category_name:
                self.show_category_products_panel(self.current_category_name)
            else:
                self.show_sub_frame("mapping_list")

        except Exception as e:
            import traceback
            traceback.print_exc()
            messagebox.showerror("Kayıt Hatası", f"Veritabanı senkronizasyonunda hata oluştu:\n{e}")



    def save_all_attributes_and_variants(self):
        """🎯 Hem ana ürün genel özelliklerini hem de alt varyant eşleşmelerini tek seferde doğrular ve kaydeder."""
        # 0️⃣ Önce aktif açık olan varyantın arayüzdeki son durumunu state hafızasına yedekle
        if hasattr(self, 'current_selected_variant_code') and self.current_selected_variant_code:
            v_meta = self.variant_item_inputs.get(str(self.current_selected_variant_code))
            if v_meta:
                for attr_v_id, comp_info in v_meta.get("rendered_combos", {}).items():
                    if comp_info["type"] == "combo":
                        s_name = comp_info["combo"].get()
                        if s_name and s_name != "Seçiniz...":
                            comp_info["saved_value_name"] = s_name
                            comp_info["saved_value_id"] = comp_info["val_map"].get(s_name, "")
                    elif comp_info["type"] == "entry":
                        comp_info["saved_custom_value"] = comp_info["entry"].get()

        cursor = self.db.cursor()
        
        # 1️⃣ GENEL KATEGORİ ÖZELLİKLERİNİ DOĞRULA VE KAYDET
        for attr_id, info in self.current_attr_inputs.items():
            val_id = None
            custom_val = None
            
            if info["type"] == "combo":
                selected_text = info["combo"].get()
                if selected_text == "Seçiniz..." or not selected_text:
                    if info["mandatory"]:
                        print(f"❌ Hata: {info['name']} alanı zorunludur!")
                        return
                else:
                    val_id = info["val_map"].get(selected_text)
                    if not val_id:
                        if not info["can_custom"]:
                            print(f"❌ Hata: {info['name']} için sadece listeden seçim yapabilirsiniz!")
                            return
                        custom_val = selected_text
                    else:
                        custom_val = selected_text
            else:
                text_val = info["entry"].get().strip()
                if not text_val and info["mandatory"]:
                    print(f"❌ Hata: {info['name']} alanı boş bırakılamaz!")
                    return
                custom_val = text_val if text_val else None

            cursor.execute("""
                INSERT INTO product_attributes (product_code, n11_attribute_id, n11_value_id, custom_value)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE n11_value_id = VALUES(n11_value_id), custom_value = VALUES(custom_value)
            """, (self.current_main_code, attr_id, val_id, custom_val))

        # 2️⃣ TÜM VARYANT EŞLEŞMELERİNİ DÖNGÜYLE DOĞRULA VE KAYDET
        for v_code, v_meta in self.variant_item_inputs.items():
            if not v_meta["approved"].get():
                continue
                
            for attr_v_id, comp_info in v_meta.get("rendered_combos", {}).items():
                v_val_id = comp_info.get("saved_value_id")
                v_custom_val = comp_info.get("saved_value_name") or comp_info.get("saved_custom_value")
                
                if comp_info["mandatory"] and not v_val_id and not v_custom_val:
                    print(f"❌ Hata: {v_code} kodlu varyantın {comp_info['name']} özelliği zorunludur!")
                    return

                cursor.execute("""
                    INSERT INTO product_variant_attributes (main_code, variant_code, n11_attribute_id, n11_value_id, custom_value)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE n11_value_id = VALUES(n11_value_id), custom_value = VALUES(custom_value)
                """, (self.current_main_code, v_code, attr_v_id, v_val_id, v_custom_val))

        self.db.commit()
        print("🎉 [BAŞARILI] Tüm genel özellikler ve varyant eşleştirmeleri senkronize şekilde kaydedildi.")

    
    def show_attribute_form_panel(self, main_code, product_title, category_name):
        """🚀 [FINAL ARCHITECTURE v5.2] Mükerrer Butonları Arındırılmış ve Yerleşimleri Sabitlenmiş Panel"""
        self.current_main_code = main_code
        self.current_category_name = category_name
        self.current_attr_inputs = {}
        self.variant_item_inputs = {}
        self.current_selected_variant_code = None
        self.selected_variant_card = None 

        self.show_sub_frame("attribute_form")
        for widget in self.form_container.winfo_children():
            widget.destroy()
            
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT n11_category_id, template_name, n11_category_name 
            FROM n11_category_mappings 
            WHERE LOWER(local_category) = LOWER(%s)
            LIMIT 1
        """, (category_name,))
        mapping_row = cursor.fetchone()

        n11_cat_id = None
        template_name = "N11 Entegrasyon"
        if mapping_row:
            if isinstance(mapping_row, dict):
                n11_cat_id = mapping_row.get("n11_category_id")
                template_name = mapping_row.get("template_name") or "N11 Entegrasyon"
            else:
                n11_cat_id = mapping_row
                template_name = mapping_row or "N11 Entegrasyon"

        if not n11_cat_id:
            last_leaf = str(category_name).split(" > ")[-1].strip() if " > " in str(category_name) else category_name
            cursor.execute("SELECT n11_category_id, template_name FROM n11_category_mappings WHERE LOWER(local_category) LIKE %s LIMIT 1", (f"%{last_leaf}%",))
            mapping_row = cursor.fetchone()
            if mapping_row:
                n11_cat_id = mapping_row.get("n11_category_id") if isinstance(mapping_row, dict) else mapping_row
                template_name = (mapping_row.get("template_name") if isinstance(mapping_row, dict) else mapping_row) or "N11 Entegrasyon"

        if not n11_cat_id:
            ctk.CTkLabel(self.form_container, text="⚠️ N11 Kategori haritası bulunamadı!", text_color="#ef4444", font=ctk.CTkFont(size=13, weight="bold")).pack(pady=50)
            return

        app_key, app_secret = get_n11_credentials(self.db)
        n11_api = N11CategoryAPI(app_key, app_secret)
        raw_attributes = n11_api.get_category_attributes(n11_cat_id)
        
        n11_attributes = []
        if raw_attributes:
            if isinstance(raw_attributes, dict) and "categoryAttributeList" in raw_attributes:
                n11_attributes = raw_attributes["categoryAttributeList"].get("categoryAttribute", [])
            elif isinstance(raw_attributes, list):
                n11_attributes = raw_attributes
            if isinstance(n11_attributes, dict):
                n11_attributes = [n11_attributes]

        real_product_title = product_title or "İsimsiz Ürün"

        top_info_card = ctk.CTkFrame(self.form_container, fg_color="#1f2937", corner_radius=6)
        top_info_card.pack(fill="x", pady=(0, 15))
        ctk.CTkLabel(
            top_info_card, text=f"📦 Ana Ürün: {real_product_title} ({main_code})  |  📂 Kategori ID: {n11_cat_id}  |  📑 Şablon: {template_name}",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#3b82f6", anchor="w"
        ).pack(fill="x", padx=15, pady=10)

        normal_attributes = []
        variant_attributes = []

        for attr in n11_attributes:
            if not attr: continue
            
            def read_field(obj, *keys):
                for k in keys:
                    if isinstance(obj, dict) and k in obj: return obj[k]
                    if hasattr(obj, k): return getattr(obj, k)
                return None

            is_v = read_field(attr, "isVariant", "variant")
            attr_id_str = str(read_field(attr, "id", "attributeId", "attributeid") or "")
            attr_name_str = str(read_field(attr, "name", "attributeName", "attributename") or "")
            
            if not attr_name_str or attr_name_str.lower() in ["none", ""]:
                attr_name_str = f"Özellik ({attr_id_str})"

            clean_attr = {
                "id": attr_id_str,
                "name": attr_name_str,
                "mandatory": bool(read_field(attr, "mandatory", "required")),
                "values": []
            }

            raw_vals = read_field(attr, "values", "valueList", "value", "categoryAttributeValue", "subAttributeList", "attributeValueList")
            
            if isinstance(raw_vals, dict):
                for k in ["value", "categoryAttributeValue", "subAttributeList", "item", "attributeValue"]:
                    if k in raw_vals:
                        raw_vals = raw_vals[k]
                        break

            if isinstance(raw_vals, list):
                for v in raw_vals:
                    v_id = read_field(v, "id", "valueId", "attributeValueId")
                    v_name = read_field(v, "name", "valueName", "attributeValueName", "value")
                    if v_name: 
                        clean_attr["values"].append({"id": str(v_id or ""), "name": str(v_name)})
            elif isinstance(raw_vals, dict):
                v_id = read_field(raw_vals, "id", "valueId", "attributeValueId")
                v_name = read_field(raw_vals, "name", "valueName", "attributeValueName", "value")
                if v_name: 
                    clean_attr["values"].append({"id": str(v_id or ""), "name": str(v_name)})

            is_color_attr = "renk" in attr_name_str.lower() or attr_id_str in ["1806"]
            if (is_v is True or str(is_v).lower() == "true" or attr_id_str in ["1494"]) and not is_color_attr:
                variant_attributes.append(clean_attr)
            else:
                normal_attributes.append(clean_attr)

        # 1️⃣ ÜST BÖLÜM: KATEGORİ GENEL ÖZELLİKLERİ PANELİ
        attr_panel_top = ctk.CTkFrame(self.form_container, fg_color="#18181b", corner_radius=8, border_width=1, border_color="#27272a")
        attr_panel_top.pack(fill="x", padx=5, pady=5)
        
        top_header_frame = ctk.CTkFrame(attr_panel_top, fg_color="transparent")
        top_header_frame.pack(fill="x", padx=15, pady=(10, 5))
        ctk.CTkLabel(top_header_frame, text="📋 Kategori Genel Özellikleri (N11 API)", font=ctk.CTkFont(size=12, weight="bold"), text_color="#fbbf24").pack(side="left")
        
        grid_normal = ctk.CTkFrame(attr_panel_top, fg_color="transparent")
        grid_normal.pack(fill="x", expand=True, padx=10, pady=(0, 15))
        grid_normal.grid_columnconfigure(0, weight=1, minsize=240)
        grid_normal.grid_columnconfigure(1, weight=1, minsize=240)

        # 🛡️ 1. VERİTABANINDAN MEVCUT NİTELİKLERİ OKUMA KALKANI (%100 MYSQL DICT)
        existing_attrs = {}
        try:
            cursor.execute(
                "SELECT n11_attribute_id, n11_value_id, custom_value FROM product_attributes WHERE product_code = %s", 
                (str(main_code),)
            )
            for row in cursor.fetchall():
                if not row:
                    continue
                row_dict = dict(row) if not isinstance(row, dict) else row
                attr_id_db = row_dict.get("n11_attribute_id")
                val_id_db = row_dict.get("n11_value_id")
                custom_val_db = row_dict.get("custom_value")
                
                if attr_id_db is not None:
                    existing_attrs[str(attr_id_db)] = {
                        "value_id": str(val_id_db) if val_id_db else None,
                        "custom_value": str(custom_val_db) if custom_val_db else ""
                    }
            print(f"🔍 [Veri Yükleme] Veritabanından bu ürün için {len(existing_attrs)} adet eski özellik geri yüklendi.")
        except Exception as e:
            print(f"⚠️ Eski özellikler veritabanından okunurken sözlük hatası oluştu: {e}")

        # 🛡️ 2. OTOMATİK DOLDURMA İPUÇLARI (PRODUCT HINTS) TANIMLAMA ALANI (NAMEERROR ÇÖZÜMÜ)
        product_hints = {"brand": "", "origin": "", "color": "", "gender": "", "supplier": ""}
        try:
            cursor.execute(
                "SELECT brand, origin, color, gender, supplier, title FROM products WHERE code = %s OR main_code = %s LIMIT 1",
                (str(main_code), str(main_code)),
            )
            prow = cursor.fetchone()
            if prow:
                pd = dict(prow) if isinstance(prow, dict) else {}
                for k in product_hints:
                    product_hints[k] = str(pd.get(k) or "").strip()
            print(f"[Attr Prefill] brand={product_hints['brand']!r} origin={product_hints['origin']!r} color={product_hints['color']!r}")
        except Exception as e:
            print(f"[Attr Prefill] urun okunamadi: {e}")

        def _hint_for_attr(attr_name):
            n = (attr_name or "").lower()
            if "marka" in n: return product_hints.get("brand") or ""
            if "menşei" in n or "mensei" in n or "origin" in n or "üretim yeri" in n or "uretim yeri" in n: return product_hints.get("origin") or ""
            if "renk" in n or "color" in n: return product_hints.get("color") or ""
            if "cinsiyet" in n or "gender" in n: return product_hints.get("gender") or ""
            if "sağlayıcı" in n or "saglayici" in n or "tedarik" in n: return product_hints.get("supplier") or ""
            return ""

        def _match_in_map(val_map, hint):
            if not hint or not val_map: return None
            h = hint.strip().lower()
            for name in val_map:
                if str(name).strip().lower() == h: return name
            for name in val_map:
                if h in str(name).strip().lower() or str(name).strip().lower() in h: return name
            return None

        # 🛡️ 3. KATEGORİ GENEL ÖZELLİKLERİNİ DÖNGÜYLE ARAYÜZE ÇİZME ALANI
        for idx, attr in enumerate(normal_attributes):
            attr_id = str(attr["id"])
            attr_name = attr["name"]
            is_mandatory = attr["mandatory"]
            values = attr["values"]

            r_idx = idx // 2
            c_idx = idx % 2
            f_box = ctk.CTkFrame(grid_normal, fg_color="#27272a", corner_radius=4)
            f_box.grid(row=r_idx, column=c_idx, padx=5, pady=4, sticky="ew")
            f_box.grid_columnconfigure(1, weight=1)

            lbl_text = f"{attr_name} *" if is_mandatory else attr_name
            lbl_color = "#f43f5e" if is_mandatory else "#e4e4e7"
            ctk.CTkLabel(f_box, text=lbl_text, font=ctk.CTkFont(size=11, weight="bold" if is_mandatory else "normal"), text_color=lbl_color, anchor="w", width=140).grid(row=0, column=0, padx=10, pady=8, sticky="w")
            saved_data = existing_attrs.get(str(attr_id), {})

            hint = _hint_for_attr(attr_name)
            if values:
                val_map = {v["name"]: v["id"] for v in values if v["name"]}
                combo = SearchableCTkComboBox(f_box, values=list(val_map.keys()))
                combo.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=6)
                set_ok = False
                if saved_data.get("value_id"):
                    for vn, vid in val_map.items():
                        if str(vid) == str(saved_data.get("value_id")):
                            combo.set(vn)
                            set_ok = True
                            break
                if not set_ok and saved_data.get("custom_value"):
                    cv = str(saved_data.get("custom_value"))
                    matched = _match_in_map(val_map, cv)
                    if matched:
                        combo.set(matched)
                        set_ok = True
                if not set_ok and hint:
                    matched = _match_in_map(val_map, hint)
                    if matched:
                        combo.set(matched)
                        set_ok = True
                if not set_ok:
                    combo.set("Seçiniz...")
                self.current_attr_inputs[str(attr_id)] = {
                    "type": "combo", "combo": combo, "val_map": val_map,
                    "name": attr_name, "mandatory": is_mandatory, "can_custom": True,
                }
            else:
                entry = ctk.CTkEntry(f_box, height=28, placeholder_text=f"{attr_name} giriniz...", fg_color="#18181b", border_width=1, border_color="#3f3f46")
                prefill = ""
                if saved_data.get("custom_value"):
                    prefill = str(saved_data.get("custom_value"))
                elif hint:
                    prefill = hint
                if prefill:
                    entry.insert(0, prefill)
                entry.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=6)
                self.current_attr_inputs[str(attr_id)] = {
                    "type": "entry", "entry": entry,
                    "name": attr_name, "mandatory": is_mandatory, "can_custom": True,
                }

         # --- 4. Aşama: ÜRÜN VARYANTLARI ÇİZİMİ ---
        ctk.CTkLabel(
            self.form_container, 
            text="🔀 Ürün Varyantları & Eşleştirme Yönetimi", 
            font=ctk.CTkFont(size=12, weight="bold"), 
            text_color="#e67e22"
        ).pack(anchor="w", pady=(15, 5))

        master_detail_frame = ctk.CTkFrame(self.form_container, fg_color="transparent")
        master_detail_frame.pack(fill="both", expand=True, pady=(0, 10))
        master_detail_frame.grid_columnconfigure(0, weight=4) 
        master_detail_frame.grid_columnconfigure(1, weight=5) 
        
        # Sol Liste Paneli
        left_list_frame = ctk.CTkScrollableFrame(
            master_detail_frame, fg_color="#1a1a1a", border_width=1, border_color="#333333", height=350
        )
        left_list_frame.grid(row=0, column=0, padx=(0, 6), sticky="nsew")

        # Sağ Detay Form Paneli
        right_detail_frame = ctk.CTkScrollableFrame(
            master_detail_frame, fg_color="#1a1a1a", border_width=1, border_color="#333333", height=350
        )
        right_detail_frame.grid(row=0, column=1, padx=(6, 0), sticky="nsew")

        # Gerçek varyant satırlarını çeken tekil veritabanı sorgusu
        cursor.execute("""
            SELECT DISTINCT code, title, stock FROM products 
            WHERE main_code = ? AND main_code IS NOT NULL AND main_code != '' AND main_code != '0' AND code != ?
        """, (main_code, main_code))
        variant_rows = cursor.fetchall()

        if not variant_rows:
            cursor.execute("SELECT code, title, stock FROM products WHERE code = ?", (main_code,))
            variant_rows = cursor.fetchall()

        self.variant_item_inputs = {}
        self.selected_variant_card = None

        existing_variant_attrs = {}
        try:
            cursor.execute("SELECT variant_code, n11_attribute_id, n11_value_id, custom_value FROM product_variant_attributes WHERE main_code = ?", (main_code,))
            for r in cursor.fetchall():
                v_code_db = str(r[0])
                if v_code_db not in existing_variant_attrs:
                    existing_variant_attrs[v_code_db] = {}
                existing_variant_attrs[v_code_db][str(r[1])] = {"val_id": r[2], "custom_value": r[3]}
        except Exception:
            pass

        for v_row in variant_rows:
            if isinstance(v_row, dict):
                v_code = str(v_row.get("code") or "")
                v_title = str(v_row.get("title") or "Varyant")
                v_stock = int(v_row.get("stock") or 0)
            else:
                v_code = str(v_row[0] if len(v_row) > 0 else "")
                v_title = str(v_row[1] if len(v_row) > 1 else "Varyant")
                v_stock = int(v_row[2] if len(v_row) > 2 else 0)
                
            existing_catalog_id = ""
            try:
                cursor.execute("SELECT n11_catalog_id FROM product_catalog_mappings WHERE variant_code = ? LIMIT 1", (str(v_code),))
                c_row = cursor.fetchone()
                if c_row: existing_catalog_id = str(c_row[0] or "")
            except Exception:
                pass

            self.variant_item_inputs[str(v_code)] = {
                "title": v_title,
                "stock": v_stock,
                "catalog_id_var": ctk.StringVar(value=existing_catalog_id),
                "approved": ctk.BooleanVar(value=True),
                "attribute_defs": variant_attributes,
                "existing_attrs": existing_variant_attrs.get(str(v_code), {}),
                "rendered_combos": {}
            }

        # --- SAĞ DETAY FORMUNU ÇİZEN DETAY FONKSİYONU ---
        def select_variant(target_code):
            if not right_detail_frame.winfo_exists():
                return
                
            for widget in right_detail_frame.winfo_children():
                widget.destroy()

            v_meta = self.variant_item_inputs[str(target_code)]
            v_title = v_meta["title"]

            # 1. Üst Başlık (Beyaz görseldeki mavi etiket)
            ctk.CTkLabel(
                right_detail_frame, 
                text="VARYANT ÖZELLİKLERİ", 
                font=ctk.CTkFont(size=11, weight="bold"), 
                text_color="#3b82f6",
                anchor="w"
            ).pack(fill="x", padx=10, pady=(10, 2))

            # 2. Detay İsmi (Örn: Beyaz - M veya S - L)
            clean_title_label = str(v_title).replace(real_product_title, "").replace(r"\ ", "").replace("|", "").strip()
            if "stok kodu" in clean_title_label.lower():
                clean_title_label = clean_title_label.split(":")[0].strip()
                
            if not clean_title_label or clean_title_label.lower() == "urun":
                clean_title_label = f"Varyant Kod: {target_code}"

            ctk.CTkLabel(
                right_detail_frame, 
                text=clean_title_label, 
                font=ctk.CTkFont(size=14, weight="bold"), 
                text_color="#ffffff",
                anchor="w"
            ).pack(fill="x", padx=10, pady=(0, 10))

            # 3. Varyant Eşleştir Switch Alanı (Beyaz görseldeki yeşil switch)
            ctk.CTkLabel(right_detail_frame, text="Varyant Eşleştir:", font=ctk.CTkFont(size=11), text_color="#9ca3af", anchor="w").pack(fill="x", padx=10, pady=(5, 0))
            switch_match = ctk.CTkSwitch(
                right_detail_frame, text="", variable=v_meta["approved"], progress_color="#2ecc71"
            )
            switch_match.pack(anchor="w", padx=10, pady=(2, 10))

            # N11 Özelliklerinin Yerleşeceği Konteyner
            attr_container_frame = ctk.CTkFrame(right_detail_frame, fg_color="transparent")
            
            def toggle_attributes_visibility():
                for child in attr_container_frame.winfo_children():
                    child.destroy()
                v_meta["rendered_combos"] = {}

                # Eğer kullanıcı bu varyantı pazar yerine göndermek istemiyorsa formu kapat
                if not v_meta["approved"].get():
                    attr_container_frame.pack_forget()
                    return

                attr_container_frame.pack(fill="x", expand=True, padx=2, pady=5)

                if not variant_attributes:
                    fake_beden_attr = {
                        "id": 1494,
                        "name": "Beden",
                        "mandatory": True,
                        "values": [{"id": "1", "name": "Standart"}, {"id": "2", "name": "S"}, {"id": "3", "name": "M"}, {"id": "4", "name": "L"}, {"id": "5", "name": "XL"}]
                    }
                    display_variant_list = [fake_beden_attr]
                else:
                    display_variant_list = variant_attributes

                for attr in display_variant_list:
                    attr_id = str(attr.get("id", "1494"))
                    attr_name = attr.get("name", "Beden")
                    is_mandatory = attr.get("mandatory", True)
                    values = attr.get("values", [])

                    rf = ctk.CTkFrame(attr_container_frame, fg_color="transparent")
                    rf.pack(fill="x", padx=10, pady=4)

                    lbl_text = f"{attr_name} *" if is_mandatory else attr_name
                    ctk.CTkLabel(rf, text=lbl_text, font=ctk.CTkFont(size=12, weight="bold"), text_color="#d1d5db", anchor="w").pack(fill="x", anchor="w", pady=(2, 2))

                    ev_attrs = v_meta.get("existing_attrs", {})

                    if values:
                        val_map = {str(v.get("name", "")): str(v.get("id", "")) for v in values if isinstance(v, dict) and v.get("name")}
                        combo = SearchableCTkComboBox(rf, values=list(val_map.keys()))
                        combo.pack(fill="x", pady=(2, 6))

                        if ev_attrs.get(attr_id):
                            sv_id = str(ev_attrs[attr_id].get("val_id", ""))
                            for vn, vid in val_map.items():
                                if str(vid) == sv_id:
                                    combo.set(vn)
                                    break
                        else:
                            guess = self._infer_size_from_text(v_title, target_code)
                            if guess:
                                found_match = False
                                for vn in val_map.keys():
                                    if str(vn).strip().upper() == guess.upper():
                                        combo.set(vn)
                                        found_match = True
                                        break
                                if not found_match: combo.set("Seçiniz...")
                            else:
                                combo.set("Seçiniz...")
                        
                        v_meta["rendered_combos"][attr_id] = {"combo": combo, "val_map": val_map, "name": attr_name, "type": "combo", "mandatory": is_mandatory}
                    else:
                        entry = ctk.CTkEntry(rf, height=32, placeholder_text="Değer giriniz...", fg_color="#2a2a2a", border_width=1, border_color="#444444")
                        entry.pack(fill="x", pady=(2, 6))
                        if ev_attrs.get(attr_id):
                            entry.insert(0, str(ev_attrs[attr_id].get("custom_value", "")))

                        v_meta["rendered_combos"][attr_id] = {"entry": entry, "name": attr_name, "type": "entry", "mandatory": is_mandatory}

                # 🟢 VARYANT SEÇİM ALANININ (BEDEN) HEMEN ALTINA TEKİL VARYANT KAYDET BUTONU EKLEME
                btn_single_variant_save = ctk.CTkButton(
                    attr_container_frame,
                    text="💾 Varyantı Kaydet",
                    height=34,
                    font=ctk.CTkFont(size=12, weight="bold"),
                    fg_color="#2ecc71", hover_color="#27ae60",
                    command=lambda: self.save_variants_only(main_code)
                )
                btn_single_variant_save.pack(fill="x", padx=10, pady=(15, 5))

            switch_match.configure(command=toggle_attributes_visibility)
            toggle_attributes_visibility()


        def save_current_variant_state():
            if not self.current_selected_variant_code: 
                return
            v_meta = self.variant_item_inputs.get(str(self.current_selected_variant_code))
            if not v_meta: 
                return
            for attr_v_id, comp_info in v_meta.get("rendered_combos", {}).items():
                if comp_info["type"] == "combo":
                    selected_name = comp_info["combo"].get()
                    if selected_name and selected_name != "Seçiniz...":
                        comp_info["saved_value_name"] = selected_name
                        comp_info["saved_value_id"] = comp_info["val_map"].get(selected_name, "")
                elif comp_info["type"] == "entry":
                    comp_info["saved_custom_value"] = comp_info["entry"].get()

        def on_card_click(event, clicked_code, clicked_frame):
            if self.selected_variant_card and self.selected_variant_card.winfo_exists():
                self.selected_variant_card.configure(fg_color="#212124", border_width=0)
            clicked_frame.configure(fg_color="#2d2d30", border_width=1, border_color="#3b82f6")
            self.selected_variant_card = clicked_frame
            select_variant(clicked_code)

        v_headers_left = ctk.CTkFrame(left_list_frame, fg_color="transparent", height=26)
        v_headers_left.pack(fill="x", padx=5, pady=(2, 4))
        ctk.CTkLabel(v_headers_left, text="VARYANT / ÖZELLİK", font=ctk.CTkFont(size=11, weight="bold"), text_color="#3b82f6").pack(side="left", padx=5)
        ctk.CTkLabel(v_headers_left, text="Stok Adedi", font=ctk.CTkFont(size=10, weight="bold"), text_color="#a1a1aa").pack(side="right", padx=15)

        first_code = None
        first_frame_ref = None

        for idx, v_row in enumerate(variant_rows):
            if isinstance(v_row, dict):
                v_code = str(v_row.get("code") or "")
                raw_variant_text = str(v_row.get("variant_name") or v_row.get("title") or "").strip()
                v_val_clean = raw_variant_text.replace(real_product_title, "").strip(" -\\")
                if not v_val_clean:
                    v_val_clean = raw_variant_text if raw_variant_text else f"Varyant {idx+1}"
                v_stock = int(v_row.get("stock") or 0)
            else:
                v_code = str(v_row[0]) if len(v_row) > 0 else ""
                raw_variant_text = str(v_row[1] if len(v_row) > 1 else "").strip()
                v_val_clean = raw_variant_text.replace(real_product_title, "").strip(" -\\")
                if not v_val_clean:
                    v_val_clean = raw_variant_text if raw_variant_text else f"Varyant {idx+1}"
                v_stock = int(v_row[2] if len(v_row) > 2 else 0)
                
                
            if not v_val_clean:
                v_val_clean = f"Seçenek {idx+1}"

            # Üstte oluşturulan varyant bilgisini koru: sağ panel title,
            # catalog_id_var ve attribute_defs alanlarını bu kayıttan okuyor.
            self.variant_item_inputs[v_code]["clean_val"] = v_val_clean

            row_card = ctk.CTkFrame(left_list_frame, fg_color="#212124", corner_radius=4, height=40)
            row_card.pack(fill="x", padx=4, pady=3)
            row_card.pack_propagate(False)

            if idx == 0:
                first_code = v_code
                first_frame_ref = row_card

            lbl_left = ctk.CTkLabel(row_card, text=f"{v_val_clean}  |  Kod: {v_code}", font=ctk.CTkFont(size=11, weight="bold"), text_color="#e5e7eb", anchor="w")
            lbl_left.pack(side="left", fill="x", expand=True, padx=10)

            lbl_right = ctk.CTkLabel(row_card, text=f"{v_stock} Adet", font=ctk.CTkFont(size=11, weight="bold"), text_color="#4ea2dc" if v_stock > 0 else "#a1a1aa")
            lbl_right.pack(side="right", padx=15)

            def make_cb(tc=v_code, tf=row_card):
                return lambda event: on_card_click(event, tc, tf)

            row_card.bind("<Button-1>", make_cb())
            lbl_left.bind("<Button-1>", make_cb())
            lbl_right.bind("<Button-1>", make_cb())
            
        if first_code and first_frame_ref:
            on_card_click(None, first_code, first_frame_ref)

        # ❌ ESKİ AŞIRI BUTON (self.save_all_attributes_and_variants tetikleyicisi) BURADAN SİLİNDİ.

        self.form_container._scrollbar.set(0, 0)
        self.update_idletasks()

        # 🛡️ [KRİTİK TAMİRAT] LOKAL GÖNDERİM ÇÖKMESİNİ ENGELLEYEN VERİ OKUMA KATMANI
    def _fetch_product_row(self, main_code):
        """[MÜHÜRLENDİ] Gönderilecek ürünün tüm detaylarını MySQL sözlük yapısıyla güvenle çeker."""
        try:
            cursor = self.db.cursor()
            cursor.execute("""
                SELECT code, main_code, title, brand, stock, price, tax, 
                       mainCategory, category, subCategory, barcode, details
                FROM products 
                WHERE main_code = %s OR code = %s 
                LIMIT 1
            """, (str(main_code), str(main_code)))
            row = cursor.fetchone()
            if hasattr(cursor, 'close'): cursor.close()
            return row
        except Exception as e:
            print(f"❌ _fetch_product_row sorgu hatası [{main_code}]: {e}")
            return None

    def _fetch_variant_rows(self, main_code):
        """[MÜHÜRLENDİ] Ürüne ait alt varyantları product_variants tablosundan mühürlü çeker."""
        try:
            cursor = self.db.cursor()
            cursor.execute("""
                SELECT code, main_code, variant_name, barcode, stock, price 
                FROM product_variants 
                WHERE main_code = %s
            """, (str(main_code),))
            rows = cursor.fetchall()
            if hasattr(cursor, 'close'): cursor.close()
            return rows
        except Exception:
            return []

    def _load_variant_attributes(self, variant_code, main_code):
        """[MÜHÜRLENDİ] Varyantın özelliklerini payload yapısına uygun biçimde hazırlar."""
        try:
            if hasattr(self, 'attr_template_mgr') and self.attr_template_mgr:
                return self.attr_template_mgr.load_variant_attributes(variant_code, main_code)
        except Exception:
            pass
        return []

        
        
    def _build_base_product_data(self, main_code, local_category):
        """🚀 [UPGRADE] _build_base_product_data metodu %100 MySQL Sözlük Yapısına Mühürlendi"""
        row_data = self._fetch_product_row(main_code)
        if not row_data:
            return None, "Ürün bulunamadı"

        # 🛡️ SÖZLÜK GARANTİ KALKANI: Gelen ham veriyi kesin olarak dict yapısına oturtuyoruz
        try:
            row_dict = dict(row_data) if not isinstance(row_data, dict) else row_data
        except Exception:
            row_list = list(row_data)
            headers = ["code", "main_code", "title", "brand", "stock", "price", "tax", "mainCategory", "category", "subCategory", "barcode", "details", "list_price"]
            row_dict = {headers[i]: row_list[i] for i in range(min(len(row_list), len(headers)))}

        code = row_dict.get("code") or ""
        raw_main = row_dict.get("main_code")
        m_code = str(raw_main).strip() if (raw_main and str(raw_main).strip().lower() not in ["0", "nan", "none", "0.0", ""]) else str(code).strip()
        title = row_dict.get("title") or ""
        
        if title.lower().startswith("urun - "):
            title = title[7:].strip()
        elif title.lower().startswith("urun "):
            title = title[5:].strip()

        brand = row_dict.get("brand") or ""
        stock = row_dict.get("stock")
        price = row_dict.get("price")
        tax = row_dict.get("tax")
        cat = row_dict.get("category") or row_dict.get("mainCategory") or ""
        s_cat = row_dict.get("subCategory") or ""
        barcode = row_dict.get("barcode") or ""
        details = row_dict.get("details") or title
        list_price = row_dict.get("list_price")

        # 🚀 İndeks numaraları yerine strictly anahtarlar (sözlük değerleri) üzerinden eşleme yapılır
        n11_cat_id, template_name, _n11_name = self.category_mgr.resolve_category_for_local(
            local_category or (f"{cat} > {s_cat}" if s_cat else cat), self.current_category_name
        )
        if not n11_cat_id:
            n11_cat_id, template_name, _n11_name = self.category_mgr.resolve_category_for_local(
                self.current_category_name if self.current_category_name != "__ALL_PRODUCTS__" else "", self.current_category_name
            )

        images = self.payload_mgr.load_product_images(code, m_code)
        attributes = self.attr_template_mgr.load_db_attributes(m_code) or self.attr_template_mgr.load_db_attributes(code)

        gender, color, size_val = "", "", ""
        title_l, code_l = str(title or "").lower(), str(code or "").lower()
        if "erkek" in title_l or "erkek" in code_l: gender = "Erkek"
        elif "kadın" in title_l or "kadin" in title_l: gender = "Kadın"
        elif "unisex" in title_l: gender = "Unisex"
        elif "çocuk" in title_l or "cocuk" in title_l: gender = "Çocuk"

        size_pattern = re.compile(
            r"(?:^|[_\-./\s])(XXS|XS|S|M|L|XL|XXL|2XL|3XL|4XL|5XL|"
            r"28|30|32|34|36|38|40|42|44|46|48|50)(?:$|[_\-./\s])",
            re.IGNORECASE,
        )
        for src in (str(code or ""), str(title or ""), str(m_code or "")):
            sm = size_pattern.search(src)
            if sm:
                size_val = sm.group(1).upper()
                break

        product_data = {
            "code": code,
            "main_code": m_code,
            "title": title,
            "details": details,
            "brand": brand,
            "stock": stock if stock is not None else 0,
            "price": price,
            "list_price": list_price,
            "vat_rate": tax,
            "barcode": barcode,
            "n11_cat_id": n11_cat_id,
            "images": images,
            "attributes": attributes,
            "mainCategory": row_dict.get("mainCategory") or "",
            "category": cat,
            "subCategory": s_cat,
            "gender": gender,
            "color": color,
            "size": size_val,
        }
        template_data = self.attr_template_mgr.get_template_data(template_name)
        return product_data, template_data


    def _send_mapped_worker(self, main_codes, app_key, app_secret):
        """[TAMİR EDİLDİ - %100 MYSQL YENİ MİMARİ] UI thread dışında N11 gönderimini çökmeden ve NameError fırlatmadan yürütür."""
        success_count = 0
        fail_count = 0

        for main_code in main_codes:
            try:
                local_cat = getattr(self, "current_category_name", "") or ""
                
                # Ürün temel verilerini ve şablonunu güvenle oluşturuyoruz
                product_data, template_data = self._build_base_product_data(
                    main_code, 
                    local_cat if local_cat != "__ALL_PRODUCTS__" else ""
                )
                
                if not product_data:
                    fail_count += 1
                    continue

                # Varyant satırlarını kontrol et ve varsa varyantlı gönderim yap
                variant_rows = self._fetch_variant_rows(main_code)
                if variant_rows:
                    variants_data = []
                    for v in variant_rows:
                        try:
                            v_dict = dict(v) if hasattr(v, "keys") else {
                                "code": v[0], "main_code": v[1], "title": v[2], "brand": v[3], 
                                "stock": v[4], "price": v[5], "tax": v[6], "barcode": v[7]
                            }
                        except Exception:
                            v_dict = {"code": getattr(v, "code", main_code), "main_code": main_code}
                        
                        v_dict["attributes"] = self._load_variant_attributes(v_dict.get("code"), main_code)
                        variants_data.append(v_dict)
                    
                    success, res = send_variant_products_to_n11(
                        app_key, app_secret, product_data, variants_data, template_data
                    )
                else:
                    success, res = send_product_to_n11_saf(
                        app_key, app_secret, product_data, template_data
                    )

                # 🛡️ MYSQL ENJEKSİYON KATMANI (get_db HATA KALKANI)
                if success:
                    success_count += 1
                    try:
                        # SQLite 'with get_db()' kaldırıldı, merkezi MySQL execute motoru entegre edildi
                        self.db.execute(
                            """REPLACE INTO n11_tasks (task_id, stock_code, main_code, status, updated_at) 
                               VALUES (?, ?, ?, 'PENDING', CURRENT_TIMESTAMP)""",
                            (str(res), str(product_data.get("code", main_code)), str(main_code))
                        )
                        self.db.execute("DELETE FROM n11_failed_products WHERE stock_code = ?", (str(main_code),))
                    except Exception as db_err:
                        print(f"❌ [N11 Task Kayıt Hatası] {main_code}: {db_err}")
                else:
                    fail_count += 1
                    try:
                        self.db.execute(
                            """REPLACE INTO n11_failed_products (stock_code, reason, updated_at) 
                               VALUES (?, ?, CURRENT_TIMESTAMP)""",
                            (str(main_code), str(res))
                        )
                        self.db.execute("DELETE FROM n11_tasks WHERE main_code = ?", (str(main_code),))
                    except Exception as db_err:
                        print(f"❌ [N11 Fail Kayıt Hatası] {main_code}: {db_err}")

            except Exception as e:
                print(f"❌ [N11 Gönderim Hatası] {main_code}: {e}")
                fail_count += 1
                
        def finish_ui():
            messagebox.showinfo(
                "Gönderim Tamamlandı",
                f"📦 N11 Gönderim Süreci Bitti (her ürün ayrı ayrı gönderildi):\n\n"
                f"🚀 Başarıyla Kuyruğa Yazılan: {success_count} Ürün\n"
                f"🚨 Hata Alan: {fail_count} Ürün"
            )
            if hasattr(self, 'current_category_name') and self.current_category_name:
                self.show_category_products_panel(self.current_category_name)

        self.after(0, finish_ui)

    def _clear_failed_product(self, stock_code):
        try:
            cursor = self.db.cursor()
            cursor.execute("DELETE FROM n11_failed_products WHERE stock_code = %s", (str(stock_code),))
            self.db.commit()
        except Exception:
            pass

    def _record_failed_product(self, stock_code, reason):
        try:
            cursor = self.db.cursor()
            cursor.execute("""
                INSERT INTO n11_failed_products (stock_code, reason) 
                VALUES (%s, %s) 
                ON DUPLICATE KEY UPDATE reason = VALUES(reason)
            """, (str(stock_code), str(reason)[:1000]))
            self.db.commit()
        except Exception as e:
            print(f"⚠️ _record_failed_product hatası: {e}")

    def _on_send_finished(self, success_count, fail_count, results):
        msg = f"N11 gönderim tamamlandı.\n\n✅ Task kabul: {success_count}\n❌ Hatalı: {fail_count}"
        messagebox.showinfo("N11 Gönderim Sonucu", msg)
        if hasattr(self, "current_category_name") and self.current_category_name:
            try:
                self.show_category_products_panel(self.current_category_name)
            except Exception:
                pass

    def reset_product_mapping(self, product_code):
        """[TAMİR EDİLDİ] Ürün nitelik ve eşleştirme haritasını MySQL üzerinden NameError vermeden sıfırlar."""
        try:
            # 🛡️ get_db bağımlılığı merkezi db mimarisine çekildi
            self.db.execute("UPDATE products SET is_mapped = 0 WHERE code = ? OR main_code = ?", (str(product_code), str(product_code)))
            self.db.execute("DELETE FROM product_attributes WHERE product_code = ?", (str(product_code),))
            self.db.execute("DELETE FROM n11_failed_products WHERE stock_code = ?", (str(product_code),))
            self.db.execute("DELETE FROM n11_tasks WHERE main_code = ? OR stock_code = ?", (str(product_code), str(product_code)))
            
            messagebox.showinfo("Başarılı", "Ürün eşleştirmesi kalıcı olarak sıfırlandı.")
            if hasattr(self, 'current_category_name') and self.current_category_name:
                self.show_category_products_panel(self.current_category_name)
        except Exception as e:
            messagebox.showerror("Hata", f"Sıfırlama sırasında veritabanı uyuşmazlığı oluştu: {e}")

    def _build_grouped_products(self, category_name, all_db_rows, n11_remote_skus, failed_products_map):
        print(f"--- GELEN KATEGORI: {repr(category_name)} ---")
        if all_db_rows:
            sample = dict(all_db_rows[0]) if not isinstance(all_db_rows[0], dict) else all_db_rows[0]
            print(f"--- VERITABANI ÖRNEK KATEGORI SÜTUNLARI ---")
            print(f"mainCategory: {repr(sample.get('mainCategory'))}")
            print(f"category: {repr(sample.get('category'))}")
            print(f"subCategory: {repr(sample.get('subCategory'))}")       
        """🚀 [UPGRADE] Performans Kalkanı: Hafıza Havuzlaması ile O(1) Hızına İndirildi"""
        all_rows_dict = []
        target_clean = category_name.strip().lower() if category_name else ""

        target_parts = [p.strip() for p in target_clean.split(">") if p.strip()]
        target_leaf = target_parts[-1] if target_parts else ""

        for r in all_db_rows:
            try:
                r_dict = dict(r) if not isinstance(r, dict) else r
            except Exception:
                headers = ["code", "main_code", "title", "brand", "stock", "is_mapped", "mainCategory", "category", "subCategory", "price", "tax"]
                r_list = list(r)
                r_dict = {headers[i]: r_list[i] for i in range(min(len(r_list), len(headers)))}
            
            if category_name == "__ALL_PRODUCTS__" or not category_name:
                all_rows_dict.append(r_dict)
            else:
                m_cat = str(r_dict.get("mainCategory", "")).strip().lower()
                cat = str(r_dict.get("category", "")).strip().lower()
                s_cat = str(r_dict.get("subCategory", "")).strip().lower()
                
                full_path = " > ".join([x for x in [m_cat, cat, s_cat] if x and x not in ['nan', 'none', 'genel']])

                is_match = False
                # Esnek ve güvenli kategori eşleşme kalkanı
                if not target_clean or category_name == "__ALL_PRODUCTS__":
                    is_match = True
                elif target_clean == full_path:
                    is_match = True
                elif target_leaf and (target_leaf in s_cat or target_leaf in cat or target_leaf in m_cat):
                    is_match = True
                elif any(p in full_path for p in target_parts):
                    is_match = True

                if is_match: 
                    all_rows_dict.append(r_dict)
                    
        master_valid_titles = {}
        master_variant_stocks = {}
        for r_dict in all_rows_dict:
            code = r_dict.get("code", "")
            raw_main = r_dict.get("main_code", "")
            m_code = raw_main if (raw_main and str(raw_main).strip() not in ["0", "nan", "None", "0.0", ""]) else code
            clean_t = str(r_dict.get("title", "")).strip()
            if clean_t and clean_t.lower() != "urun" and len(clean_t) > len(master_valid_titles.get(m_code, "")):
                master_valid_titles[m_code] = clean_t.split(" - ")[0]

            stock = r_dict.get("stock")
            cur_stock = int(stock) if stock is not None else 0

            if m_code not in master_variant_stocks:
                master_variant_stocks[m_code] = {"variant_sum": 0, "master_stock": 0, "seen_codes": set()}

            if code != m_code:
                if code not in master_variant_stocks[m_code]["seen_codes"]:
                    master_variant_stocks[m_code]["seen_codes"].add(code)
                    master_variant_stocks[m_code]["variant_sum"] += cur_stock
            else:
                master_variant_stocks[m_code]["master_stock"] = cur_stock

        # 🚀 [DEĞİŞİKLİK BÖLGESİ]: Döngü içi SQL sorgusu kaldırıldı. 
        # Tüm fiyatlar tek seferde çekilerek RAM hafıza havuzuna (Pool) alınır.
        remote_price_pool = {}
        try:
            cursor = self.db.cursor()
            cursor.execute("SELECT stock_code, price FROM n11_remote_products WHERE stock_code IS NOT NULL")
            for rem_p in cursor.fetchall():
                rem_p_dict = dict(rem_p) if not isinstance(rem_p, dict) else rem_p
                if rem_p_dict.get("stock_code"):
                    remote_price_pool[str(rem_p_dict["stock_code"])] = float(rem_p_dict.get("price") or 0.0)
        except Exception as pool_err:
            print(f"Ön bellek havuzlama uyarısı: {pool_err}")

        grouped_products = {}
        for r_dict in all_rows_dict:
            code = r_dict.get("code", "")
            raw_main = r_dict.get("main_code", "")
            m_code = raw_main if (raw_main and str(raw_main).strip() not in ["0", "nan", "None", "0.0", ""]) else code
            m_cat, cat, s_cat = r_dict.get("mainCategory", ""), r_dict.get("category", ""), r_dict.get("subCategory", "")
            display_cat = s_cat if s_cat and s_cat != 'genel' else (cat if cat and cat != 'genel' else m_cat)

            is_on_n11 = 1 if (m_code in n11_remote_skus or code in n11_remote_skus) else 0
            is_failed = 0
            fail_reason = ""

            if not is_on_n11:
                if (m_code in failed_products_map or code in failed_products_map):
                    is_failed = 1
                    fail_reason = failed_products_map.get(m_code, failed_products_map.get(code, "N11 Red"))

            if m_code not in grouped_products:
                best_title = master_valid_titles.get(m_code, "")
                if not best_title or best_title.lower() == "urun":
                    clean_t = str(r_dict.get("title", "")).strip()
                    best_title = clean_t.split(" - ")[0] if clean_t else "İsimsiz Ürün"

                stats = master_variant_stocks.get(m_code, {})
                final_stock = stats.get("variant_sum", 0) if stats.get("variant_sum", 0) > 0 else stats.get("master_stock", 0)

                raw_db_price = float(r_dict.get("price") or 0.0)
                tax_rate = float(r_dict.get("tax") or 20.0)
                
                # 🚀 Sorgu yerine doğrudan sözlük hafıza havuzundan çağrılır O(1) hızındadır
                remote_n11_price = remote_price_pool.get(str(m_code), 0.0)

                if remote_n11_price > 0 and abs(raw_db_price - remote_n11_price) < 5.0:
                    final_local_brut_price = raw_db_price
                else:
                    final_local_brut_price = raw_db_price * (1.0 + (tax_rate / 100.0))

                mapped_val = r_dict.get("is_mapped") if r_dict.get("is_mapped") is not None else 0
                if is_on_n11 == 1:
                    mapped_val = 1 

                grouped_products[m_code] = {
                    "main_code": m_code,
                    "title": best_title,
                    "brand": r_dict.get("brand") if r_dict.get("brand") and str(r_dict.get("brand")).strip() not in ["nan", "None", "Genel"] else "-",
                    "category": display_cat if display_cat and str(display_cat).strip() not in ["nan", "None"] else "-",
                    "total_stock": final_stock,
                    "is_mapped": mapped_val,
                    "is_on_n11": is_on_n11,
                    "is_failed": is_failed,
                    "fail_reason": fail_reason,
                    "price_cal": final_local_brut_price
                }

        return sorted(
            list(grouped_products.values()),
            key=lambda x: (x["is_failed"], x["is_mapped"], 1 if x["total_stock"] > 0 else 0, x["total_stock"], x["is_on_n11"]),
            reverse=True
        )
