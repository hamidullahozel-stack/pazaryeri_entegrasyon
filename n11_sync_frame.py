# Dosya Yolu: marketplaces/n11/n11_sync_frame.py
# Güncelleme Tarihi: 19 Eylül 2026 (Tam Düzeltilmiş ve Eksiksiz Sürüm)

import customtkinter as ctk
import threading
import time
import re
from datetime import datetime
from tkinter import filedialog, messagebox
import pandas as pd

from marketplaces.n11.n11_api import (
    send_product_to_n11_saf,
    update_product_price_and_stock_n11,
    check_n11_task_status,
    parse_n11_task_response,
    get_n11_credentials,
    fetch_and_sync_n11_remote_products
)


class SyncManagementFrame(ctk.CTkFrame):
    def __init__(self, parent, db):
        super().__init__(parent, fg_color="transparent")
        self.db = db

        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.pack(fill="x", padx=15, pady=10)
        ctk.CTkLabel(top_bar, text="🔄 Ürün Aktarımı ve Canlı Senkronizasyon",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")

        btn_action_box = ctk.CTkFrame(top_bar, fg_color="transparent")
        btn_action_box.pack(side="right")

        self.btn_export_errors = ctk.CTkButton(
            btn_action_box, text="📥 Hata Raporu Al (Excel)", fg_color="#dc2626", hover_color="#b91c1c",
            command=self.export_failed_products_excel
        )
        self.btn_export_errors.pack(side="right", padx=5)

        self.btn_fetch_remote = ctk.CTkButton(
            btn_action_box, text="🔄 N11 Ürünlerini Çek", fg_color="#8b5cf6", hover_color="#7c3aed",
            command=self.start_fetch_remote_products
        )
        self.btn_fetch_remote.pack(side="right", padx=5)

        self.btn_price_stock_sync = ctk.CTkButton(
            btn_action_box, text="📊 Fiyat & Stok Güncelle", fg_color="#3b82f6", hover_color="#2563eb", 
            command=self.start_price_stock_sync
        )
        self.btn_price_stock_sync.pack(side="right", padx=5)

        self.btn_start_sync = ctk.CTkButton(
            btn_action_box, text="▶️ Yeni Ürünleri Gönder", fg_color="#10b981", hover_color="#059669", 
            command=self.start_live_sync
        )
        self.btn_start_sync.pack(side="right", padx=5)

        self.btn_export_excel = ctk.CTkButton(
            btn_action_box, text="📥 Kuyruğu Excel'e Aktar", fg_color="#27ae60", hover_color="#219653",
            command=self.export_n11_queue_to_excel
        )
        self.btn_export_excel.pack(side="right", padx=5)

        self.log_box = ctk.CTkTextbox(self, height=450, font=ctk.CTkFont(family="Consolas", size=12))
        self.log_box.pack(fill="both", expand=True, padx=15, pady=10)

    def _log_safe(self, message):
        now_str = datetime.now().strftime('%H:%M:%S')
        self.after(0, lambda: (
            self.log_box.insert("end", f"[{now_str}] {message}\n"),
            self.log_box.see("end")
        ))

    def _log_failed_product(self, cursor, code, reason):
        """[MÜHÜRLENDİ] MySQL uyumlu ON DUPLICATE KEY UPDATE hata kayıt fonksiyonu."""
        try:
            # 🛡️ SQLite 'INSERT OR REPLACE' deyimi MySQL standardına dönüştürüldü
            cursor.execute("""
                INSERT INTO n11_failed_products (stock_code, reason)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE reason = VALUES(reason)
            """, (code, str(reason)))
        except Exception as e:
            print(f"Hata loglama başarısız: {e}")

    def background_sync(self):
        """[TAMİR EDİLDİ] Önceki sürümde bu fonksiyonun gövdesi eksikti: task_id, code,
        main_code, current_sku hiçbir yerde tanımlı değildi. Bu yüzden fonksiyon her
        çalıştığında anında NameError fırlatıyor, geniş 'except' bloğu bunu sessizce
        konsola yazıp yutuyordu -> arayüzde hiçbir hata görünmeden hiçbir ürün gitmiyordu.
        Şimdi: eşleştirilmiş ve henüz N11'de olmayan ürünleri TEK TEK N11'e gönderir,
        her ürünün sonucunu (başarı/hata) ayrı ayrı log_box'a ve veritabanına yazar."""
        app_key, app_secret = get_n11_credentials(self.db)
        if not app_key or not app_secret:
            self._log_safe("⚠️ Önce 'API Ayarları' sekmesinden N11 anahtarlarınızı girin!")
            return

        try:
            cursor = self.db.cursor()
            cursor.execute("""
                SELECT DISTINCT COALESCE(NULLIF(main_code, ''), code) AS mcode
                FROM products
                WHERE is_mapped IN (1, 2)
                  AND COALESCE(NULLIF(main_code, ''), code) NOT IN (SELECT stock_code FROM n11_remote_products)
            """)
            main_codes = []
            for r in cursor.fetchall():
                r = dict(r) if not isinstance(r, dict) else r
                if r.get("mcode"):
                    main_codes.append(str(r["mcode"]).strip())
        except Exception as e:
            self._log_safe(f"💥 Ürün havuzu okunamadı: {e}")
            return

        if not main_codes:
            self._log_safe("ℹ️ Gönderilecek yeni/eşleştirilmiş ürün bulunamadı.")
            return

        success_count = 0
        fail_count = 0

        for main_code in main_codes:
            try:
                cursor = self.db.cursor()
                cursor.execute("""
                    SELECT code, title, brand, price, stock, tax, barcode, mainCategory, category, subCategory
                    FROM products WHERE code = %s OR main_code = %s LIMIT 1
                """, (main_code, main_code))
                row = cursor.fetchone()
                if not row:
                    fail_count += 1
                    continue
                row = dict(row) if not isinstance(row, dict) else row

                full_path = " > ".join([x for x in [row.get("mainCategory"), row.get("category"), row.get("subCategory")] if x])
                mapping = self.get_flexible_category_mapping(cursor, full_path, row.get("subCategory"))
                if not mapping or not mapping.get("n11_category_id"):
                    reason = "Kategori eşleştirmesi bulunamadı (Kategori & Özellik Eşle ekranından eşleştirin)"
                    self._log_failed_product(cursor, main_code, reason)
                    self._log_safe(f"❌ {main_code}: {reason}")
                    fail_count += 1
                    continue

                product_payload = {
                    "code": row.get("code"),
                    "main_code": main_code,
                    "title": row.get("title") or "",
                    "brand": row.get("brand") or "",
                    "price": float(row.get("price") or 0.0),
                    "stock": int(row.get("stock") or 0),
                    "vat_rate": int(row.get("tax") or 18),
                    "barcode": row.get("barcode") or "",
                    "n11_cat_id": mapping.get("n11_category_id"),
                }

                success, res = send_product_to_n11_saf(app_key, app_secret, product_payload)

                if success:
                    cursor.execute("""
                        INSERT INTO n11_tasks (task_id, stock_code, main_code, status, created_at, updated_at)
                        VALUES (%s, %s, %s, 'PENDING', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        ON DUPLICATE KEY UPDATE status = 'PENDING', updated_at = CURRENT_TIMESTAMP
                    """, (str(res), row.get("code"), main_code))
                    cursor.execute("DELETE FROM n11_failed_products WHERE stock_code = %s", (main_code,))
                    success_count += 1
                    self._log_safe(f"✅ {main_code} gönderildi (task: {res})")
                else:
                    self._log_failed_product(cursor, main_code, res)
                    cursor.execute("DELETE FROM n11_tasks WHERE main_code = %s", (main_code,))
                    fail_count += 1
                    self._log_safe(f"❌ {main_code} reddedildi: {res}")

            except Exception as e:
                try:
                    self._log_failed_product(self.db.cursor(), main_code, str(e))
                except Exception:
                    pass
                fail_count += 1
                self._log_safe(f"💥 {main_code} işlenirken hata: {e}")

        self._log_safe(f"🏁 Tamamlandı. ✅ {success_count} başarılı, ❌ {fail_count} hatalı.")


    def _format_mapping_row(self, row):
        # 🛡️ DÜZELTME: self.db.cursor() dictionary=True kullanıyor, yani 'row' bir dict —
        # "row[0]" burada KeyError verirdi (tuple değil). Alttaki SELECT'lere AS takma ad
        # eklendi, bu fonksiyon da artık sadece isimle (dict) okuyor.
        row = dict(row) if not isinstance(row, dict) else row
        return {
            "n11_category_id": row.get("n11_category_id"),
            "delivery_template": row.get("delivery_template") or "Varsayılan",
            "prep_time": row.get("prep_time") if row.get("prep_time") is not None else 3
        }

    def get_flexible_category_mapping(self, cursor, full_path, sub_cat):
        query_exact = """
            SELECT m.n11_category_id AS n11_category_id,
                   COALESCE(t.delivery_template, t.shipment_template, m.template_name, 'Varsayılan') AS delivery_template,
                   COALESCE(t.prep_time, t.preparing_day, 3) AS prep_time
            FROM n11_category_mappings m
            LEFT JOIN templates t ON ((m.template_id IS NOT NULL AND t.id = m.template_id) OR (m.template_id IS NULL AND TRIM(LOWER(t.name)) = TRIM(LOWER(m.template_name))))
            WHERE TRIM(LOWER(COALESCE(m.local_category, m.ideasoft_cat))) = TRIM(LOWER(?))
            ORDER BY m.updated_at DESC, m.id DESC LIMIT 1
        """
        if full_path:
            cursor.execute(query_exact, (full_path,))
            row = cursor.fetchone()
            if row: return self._format_mapping_row(row)

        if sub_cat:
            cursor.execute(query_exact, (sub_cat,))
            row = cursor.fetchone()
            if row: return self._format_mapping_row(row)

        query_like = """
            SELECT m.n11_category_id AS n11_category_id,
                   COALESCE(t.delivery_template, t.shipment_template, m.template_name, 'Varsayılan') AS delivery_template,
                   COALESCE(t.prep_time, t.preparing_day, 3) AS prep_time
            FROM n11_category_mappings m
            LEFT JOIN templates t ON ((m.template_id IS NOT NULL AND t.id = m.template_id) OR (m.template_id IS NULL AND TRIM(LOWER(t.name)) = TRIM(LOWER(m.template_name))))
            WHERE LOWER(COALESCE(m.local_category, m.ideasoft_cat)) LIKE LOWER(?)
            ORDER BY m.updated_at DESC, m.id DESC LIMIT 1
        """
        target_search = sub_cat if sub_cat else full_path
        if target_search:
            cursor.execute(query_like, (f"%{target_search}%",))
            row = cursor.fetchone()
            if row: return self._format_mapping_row(row)
        return None

    def queue_products_for_sync(self):
        products = self.get_selected_or_all_products()
        queued_count = 0
        
        for prod in products:
            stock_code = prod.get("stock_code")
            local_category = prod.get("mainCategory")
            
            mapping = self.db.query_one(
                "SELECT n11_category_id FROM n11_category_mappings WHERE local_category = ?", 
                (local_category,)
            )
            
            if not mapping or not mapping["n11_category_id"]:
                continue
                
            task_id = f"N11-{stock_code}-{int(time.time())}"
            success = self.db.save_n11_task(task_id, stock_code, prod.get("main_code", ""))
            if success:
                queued_count += 1
                
        messagebox.showinfo("Bilgi", f"Toplam {queued_count} ürün aktarım kuyruğuna (n11_tasks) eklendi.")
     
    def export_failed_products_excel(self):
        """📥 Hata Raporunu Excel Olarak Dışa Aktarır"""
        try:
            conn = self.db.conn if hasattr(self.db, 'conn') else self.db
            query = "SELECT * FROM n11_failed_products"
            df = pd.read_sql(query, conn)
            
            if df.empty:
                messagebox.showinfo("Bilgi", "Dışa aktarılacak hata kaydı bulunamadı.", parent=self)
                return
                
            file_path = filedialog.asksaveasfilename(
                defaultextension=".xlsx",
                filetypes=[("Excel Dosyası", "*.xlsx"), ("Tüm Dosyalar", "*.*")],
                title="N11 Hata Raporunu Kaydet",
                parent=self
            )
            
            if file_path:
                df.to_excel(file_path, index=False)
                messagebox.showinfo("Başarılı", f"Hata raporu başarıyla kaydedildi:\n{file_path}", parent=self)
                
        except Exception as e:
            messagebox.showerror("Hata", f"Hata raporu dışa aktarılamadı:\n{str(e)}", parent=self)

    def export_n11_queue_to_excel(self):
        """📥 N11 Gönderim Kuyruğunu Excel Olarak Dışa Aktarır"""
        try:
            conn = self.db.conn if hasattr(self.db, 'conn') else self.db
            query = "SELECT * FROM n11_tasks"
            df = pd.read_sql(query, conn)
            
            if df.empty:
                messagebox.showinfo("Bilgi", "Dışa aktarılacak kuyruk kaydı bulunamadı.", parent=self)
                return
                
            file_path = filedialog.asksaveasfilename(
                defaultextension=".xlsx",
                filetypes=[("Excel Dosyası", "*.xlsx"), ("Tüm Dosyalar", "*.*")],
                title="N11 Kuyruğunu Kaydet",
                parent=self
            )
            
            if file_path:
                df.to_excel(file_path, index=False)
                messagebox.showinfo("Başarılı", f"Kuyruk listesi başarıyla kaydedildi:\n{file_path}", parent=self)
                
        except Exception as e:
            messagebox.showerror("Hata", f"Kuyruk listesi dışa aktarılamadı:\n{str(e)}", parent=self)

    def start_fetch_remote_products(self):
        """🔄 N11'deki mevcut ürünleri çeker"""
        self.btn_fetch_remote.configure(state="disabled")
        self.log_box.delete("1.0", "end")
        self._log_safe("🔄 [N11 ÜRÜNLERİNİ ÇEK] Uzak mağaza ürünleri sorgulanıyor...")
        threading.Thread(target=self.background_fetch_remote, daemon=True).start()

    def background_fetch_remote(self):
        try:
            cursor = self.db.cursor()
            cursor.execute("SELECT app_key, app_secret FROM api_keys WHERE platform = 'N11'")
            row = cursor.fetchone()
            # 🛡️ DÜZELTME: self.db.cursor() dictionary=True döndürür -> row bir dict.
            # "row[0]" burada KeyError verir, "app_key, app_secret = row" ise dict'i
            # iterasyona sokup DEĞERLERİ değil ANAHTAR İSİMLERİNİ ('app_key','app_secret')
            # değişkenlere atardı. Doğrusu .get() ile anahtar üzerinden okumak.
            row = dict(row) if row and not isinstance(row, dict) else (row or {})
            app_key = row.get("app_key")
            app_secret = row.get("app_secret")
            if not app_key:
                self._log_safe("⚠️ Önce 'API Ayarları' sekmesinden N11 anahtarlarınızı girin!")
                return

            success, msg = fetch_and_sync_n11_remote_products(app_key, app_secret, self.db)
            if success:
                self._log_safe(f"✅ {msg}")
            else:
                self._log_safe(f"❌ Ürünler çekilemedi: {msg}")
        except Exception as e:
            self._log_safe(f"💥 Ürün çekme hatası: {e}")
        finally:
            self.after(0, lambda: self.btn_fetch_remote.configure(state="normal"))
            self._log_safe("🏁 [N11 ÜRÜNLERİNİ ÇEK] İşlem tamamlandı.")

    def start_price_stock_sync(self):
        """📊 Fiyat ve stok güncellemelerini başlatır"""
        self.btn_price_stock_sync.configure(state="disabled")
        self.log_box.delete("1.0", "end")
        self._log_safe("📊 [FİYAT & STOK] Güncelleme motoru başlatıldı...")
        threading.Thread(target=self.background_price_stock_sync, daemon=True).start()

    def background_price_stock_sync(self):
        try:
            cursor = self.db.cursor()
            cursor.execute("SELECT app_key, app_secret FROM api_keys WHERE platform = 'N11'")
            row = cursor.fetchone()
            # 🛡️ DÜZELTME: aynı dict/row[0] hatası burada da vardı, düzeltildi.
            row = dict(row) if row and not isinstance(row, dict) else (row or {})
            app_key = row.get("app_key")
            app_secret = row.get("app_secret")
            if not app_key:
                self._log_safe("⚠️ Önce 'API Ayarları' sekmesinden N11 anahtarlarınızı girin!")
                return

            # 🛡️ DÜZELTME: update_product_price_and_stock_n11 bir SKU LİSTESİ bekliyor,
            # önceki kod burada self.db (veritabanı nesnesinin kendisini) gönderiyordu.
            # Önce N11'de olan/eşleştirilmiş ürünleri gerçek fiyat-stok listesine çeviriyoruz.
            cursor.execute("""
                SELECT COALESCE(NULLIF(main_code, ''), code) AS stock_code, price, stock
                FROM products
                WHERE is_mapped IN (1, 2)
                  AND COALESCE(NULLIF(main_code, ''), code) IN (SELECT stock_code FROM n11_remote_products)
            """)
            rows = cursor.fetchall()
            skus_data = []
            for r in rows:
                r = dict(r) if not isinstance(r, dict) else r
                if r.get("stock_code"):
                    skus_data.append({
                        "stockCode": str(r["stock_code"]),
                        "price": float(r.get("price") or 0.0),
                        "quantity": int(r.get("stock") or 0),
                    })

            if not skus_data:
                self._log_safe("ℹ️ Fiyat/stok güncellenecek (N11'de canlı ve eşleştirilmiş) ürün bulunamadı.")
                return

            success, msg = update_product_price_and_stock_n11(app_key, app_secret, skus_data)
            if success:
                self._log_safe(f"✅ Fiyat ve stoklar güncellendi: {msg}")
            else:
                self._log_safe(f"❌ Güncelleme hatası: {msg}")
        except Exception as e:
            self._log_safe(f"💥 Fiyat/Stok güncelleme hatası: {e}")
        finally:
            self.after(0, lambda: self.btn_price_stock_sync.configure(state="normal"))
            self._log_safe("🏁 [FİYAT & STOK] İşlem tamamlandı.")
            
            
    # Örnek Güvenli Karşılaştırma ve Tip Denetimi (N11 Payload / Servis Katmanı İçin)
    def validate_and_pack_n11_item(item_data):
        try:
            # Stok değerinin sayısal olduğundan emin olunur (None veya metin gelirse 0 yapılır)
            stock_val = item_data.get("stock", 0)
            stock = int(stock_val) if stock_val is not None and str(stock_val).strip() != "" else 0
            
            # Fiyat değerinin float olduğundan emin olunur
            price_val = item_data.get("price", 0.0)
            price = float(str(price_val).replace(",", ".")) if price_val is not None and str(price_val).strip() != "" else 0.0
            
            # Karşılaştırma işleminde (örneğin <= kontrolü) tip hatasını önleyen güvenli kıyaslama:
            MAX_ALLOWED_STOCK = 99999
            if stock <= 0:
                stock = 0
            elif stock > MAX_ALLOWED_STOCK:
                stock = MAX_ALLOWED_STOCK
                
            # Payload paketleme işlemleri...
            payload = {
                "stockCode": str(item_data.get("stock_code", "")).strip(),
                "price": round(price, 2),
                "quantity": stock
            }
            return payload
        except Exception as e:
            print(f"N11 payload paketleme tip hatası önlendi: {e}")
            return None


    def start_live_sync(self):
        """[YENİ ÜRÜN KALKANI] Sadece N11'de kesinlikle kaydı olmayan ürünleri sıradan ekler."""
        self.btn_start_sync.configure(state="disabled")
        self.log_box.delete("1.0", "end")
        self._log_safe("🚀 [YENİ ÜRÜN AKTARIMI] Kural denetimleri ve filtreleme motoru başlatıldı...")
        threading.Thread(target=self.background_sync, daemon=True).start()

