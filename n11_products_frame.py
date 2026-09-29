# Dosya: marketplaces/n11/n11_products_frame.py
# Güncelleme: %100 MySQL Dictionary, KDV Dahil Güvenlik Kalkanı ve Kusursuz Girinti Senkronizasyonu (Eylül 2026)

import customtkinter as ctk
from tkinter import messagebox
import threading
from database import Database
from ui.datatable import DataTable

from marketplaces.n11.n11_api import (
    fetch_and_sync_n11_remote_products,  
    update_product_price_and_stock_n11, 
    get_n11_credentials                  
)

class N11ProductsManagementFrame(ctk.CTkFrame):
    def __init__(self, parent, db=None, controller=None):
        super().__init__(parent)
        self.controller = controller
        # Projenin merkezi MySQL veritabanı nesnesi güvenle bağlanıyor
        self.db = db if db else Database()
        self.detected_differences = []  
        self.all_loaded_data = []

        self.big_title_font = ctk.CTkFont(family="Arial", size=18, weight="bold")
        self.big_button_font = ctk.CTkFont(family="Arial", size=13, weight="bold")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._create_header_controls()
        self._create_table_area()
        self._create_status_and_diff_bar()
        self.load_remote_products()

    def _create_header_controls(self):
        header_frame = ctk.CTkFrame(self, height=60)
        header_frame.grid(row=0, column=0, sticky="ew", padx=15, pady=(15, 5))

        title_label = ctk.CTkLabel(
            header_frame, 
            text="🛍️ N11 Canlı Mağaza Envanteri ve Karşılaştırma Otomasyonu", 
            font=self.big_title_font
        )
        title_label.pack(side="left", padx=15, pady=10)

        self.btn_fetch = ctk.CTkButton(
            header_frame, text="🔄 Canlı Mağazayı İndir", command=self.fetch_from_n11,
            font=self.big_button_font, height=38, width=170, fg_color="#1f538d"
        )
        self.btn_fetch.pack(side="right", padx=8, pady=10)

        self.btn_check_diff = ctk.CTkButton(
            header_frame, text="🔍 Uyuşmazlıkları (Farkları) Tara", command=self.scan_and_find_differences,
            font=self.big_button_font, height=38, width=210, fg_color="#ea580c", hover_color="#c2410c"
        )
        self.btn_check_diff.pack(side="right", padx=8, pady=10)

    def _create_table_area(self):
        columns = [
            ("n11_id", "N11 ID", 130, "center"),
            ("product_seller_code", "Stok Kodu", 150, "w"),
            ("title", "Ürün Adı", 290, "w"),
            ("price", "N11 Fiyatı (KDV Dahil)", 125, "e"),
            ("local_price", "Bizim Fiyat (KDV Dahil)", 125, "e"),
            ("stock_items", "N11 Stok", 90, "center"),
            ("local_stock", "Bizim Stok", 90, "center"),
            ("sync_status", "Eşitleme Durumu", 150, "center")
        ]
        
        self.table = DataTable(self, columns=columns)
        self.table.grid(row=1, column=0, sticky="nsew", padx=15, pady=5)

    def _create_status_and_diff_bar(self):
        self.bottom_bar = ctk.CTkFrame(self, height=55)
        self.bottom_bar.grid(row=2, column=0, sticky="ew", padx=15, pady=15)

        self.lbl_diff_status = ctk.CTkLabel(
            self.bottom_bar, 
            text="💡 Sistem KDV Dahil (Brüt) fiyat eşitleme modunda çalışıyor. Güvenli bölgedesiniz.",
            font=ctk.CTkFont(family="Arial", size=13, weight="bold"),
            text_color="#9ca3af"
        )
        self.lbl_diff_status.pack(side="left", padx=15, pady=10)

        self.btn_mass_sync = ctk.CTkButton(
            self.bottom_bar, 
            text="🚀 Bulunan Tüm Farkları Otomatik Eşitle", 
            command=self.sync_all_detected_differences,
            font=self.big_button_font,
            fg_color="#10b981",
            hover_color="#059669",
            height=40,
            width=250,
            state="disabled"  
        )
        self.btn_mass_sync.pack(side="right", padx=15, pady=8)

    def load_remote_products(self):
        """[MÜHÜRLENDİ - MYSQL GÜVENLİ] Yerel veritabanındaki N11 kayıtlarını Akıllı Varyant motoruyla listeler."""
        if hasattr(self.table, "show_message"):
            self.table.show_message("Veriler listeleniyor...")

        ui_rows = []
        try:
            cursor = self.db.cursor()
            
            cursor.execute("SELECT n11_id, stock_code AS product_seller_code, title, price, stock_items FROM n11_remote_products")
            rows = cursor.fetchall()
            
            for r in rows:
                row_dict = dict(r) if isinstance(r, dict) else r
                sc = str(row_dict.get("product_seller_code", "")).strip()
                if not sc: continue

                # 🛡️ Ön ek (nt_) temizlik filtresi (Sahte eşitlik uyuşmazlığını çözer)
                clean_sc = sc
                if sc.lower().startswith("nt_"): clean_sc = sc[3:]
                elif sc.lower().startswith("n11_"): clean_sc = sc[4:]
                
                l_price = 0.0
                l_stock = 0
                status_txt = "Eşit / Stabil"
                product_found = False

                raw_n11_price = row_dict.get("price")
                raw_n11_stock = row_dict.get("stock_items")

                n_price = float(str(raw_n11_price).replace(",", ".").strip()) if raw_n11_price not in [None, "", "None", "null"] else 0.0
                n_stock = int(float(str(raw_n11_stock).strip())) if raw_n11_stock not in [None, "", "None", "null", ""] else 0

                # 1️⃣ AŞAMA: Önce product_variants tablosunda ara (%s formatı sağlandı)
                try:
                    cursor.execute("SELECT price, stock, main_code FROM product_variants WHERE code = %s LIMIT 1", (clean_sc,))
                    v_row = cursor.fetchone()
                    if not v_row:
                        cursor.execute("SELECT price, stock, main_code FROM product_variants WHERE code = %s LIMIT 1", (sc,))
                        v_row = cursor.fetchone()
                        
                    if v_row:
                        v_dict = dict(v_row) if isinstance(v_row, dict) else v_row
                        raw_v_price = v_dict.get("price") or 0.0
                        l_stock = int(v_dict.get("stock") or 0)

                        # KDV dahil olduğu için çarpma işlemi kaldırıldı, doğrudan atandı:
                        l_price = float(raw_v_price)
                        product_found = True
                except Exception: pass

                # 2️⃣ AŞAMA: Varyantta yoksa products tablosuna bak (%s formatı sağlandı)
                if not product_found:
                    try:
                        cursor.execute("SELECT price, stock, tax FROM products WHERE code = %s OR main_code = %s LIMIT 1", (clean_sc, clean_sc))
                        local_row = cursor.fetchone()
                        if not local_row:
                            cursor.execute("SELECT price, stock, tax FROM products WHERE code = %s OR main_code = %s LIMIT 1", (sc, sc))
                            local_row = cursor.fetchone()
                            
                        if local_row:
                            l_dict = dict(local_row) if isinstance(local_row, dict) else local_row
                            raw_price = l_dict.get("price") or 0.0
                            tax_rate = float(l_dict.get("tax") or 20.0)
                            l_stock = int(l_dict.get("stock") or 0)
                            
                            l_price = float(raw_price) * (1.0 + (tax_rate / 100.0))
                            product_found = True
                    except Exception: pass

                # 3️⃣ AŞAMA: Karşılaştırma Mantığı (Yuvarlama sapması 0.01 e eşitlendi)
                if product_found:
                    l_price = round(l_price, 2)
                    n_price = round(n_price, 2)
                    if abs(n_price - l_price) > 0.01 or n_stock != l_stock:
                        status_txt = "⚠️ Uyuşmuyor (Güncellenmeli)"
                else:
                    l_price = 0.00
                    l_stock = 0
                    status_txt = "🔴 Bizde Yok / Kod Uyuşmuyor"

                ui_rows.append({
                    "n11_id": row_dict.get("n11_id"),
                    "product_seller_code": sc,
                    "title": row_dict.get("title") or "İsimsiz Ürün",
                    "price": f"{n_price:.2f}",
                    "local_price": f"{l_price:.2f}" if product_found else "0.00",
                    "stock_items": n_stock,  
                    "local_stock": l_stock if product_found else 0,
                    "sync_status": status_txt
                })
                
        except Exception as e:
            print(f"[N11 UI Yükleme Hatası]: {e}")

        if hasattr(self.table, "set_data"):
            self.table.set_data(ui_rows)

    def fetch_from_n11(self):
        """[MÜHÜRLENDİ] N11 ID alanlarını dolduran ve yeni ürün getiren bağımsız indirme motoru."""
        self.btn_fetch.configure(state="disabled", text="⏳ İndiriliyor...")

        def bg_worker():
            try:
                target_db = getattr(self.db, "conn", self.db)
                app_key, app_secret = get_n11_credentials(target_db)
                success, res = fetch_and_sync_n11_remote_products(app_key, app_secret, target_db)
                
                cursor = target_db.cursor()
                cursor.execute("""
                    UPDATE n11_remote_products r
                    JOIN n11_tasks t ON r.stock_code = t.main_code OR r.stock_code = t.stock_code
                    SET r.n11_id = t.task_id
                    WHERE r.n11_id IS NULL OR r.n11_id = '' OR r.n11_id = '0'
                """)
                
                cursor.execute("""
                    UPDATE n11_remote_products 
                    SET n11_id = CONCAT('N11-', id)
                    WHERE n11_id IS NULL OR n11_id = '' OR n11_id = '0'
                """)
                
                target_db.commit()

                if success:
                    self.after(0, lambda: messagebox.showinfo("Başarılı", "🎉 N11 canlı mağaza envanteri ve boş envanter ID'leri başarıyla güncellendi."))
                else:
                    # HTML etiketleri tespit edilirse temiz mesaj göster
                    clean_res = str(res)
                    if "<html" in clean_res.lower() or "<body" in clean_res.lower():
                        clean_res = "N11 Sunucusu geçici olarak erişilemiyor veya isteği engelledi (HTTP 503 / Bakım Modu).\nLütfen birkaç dakika bekleyip tekrar deneyiniz."
                    
                    self.after(0, lambda msg=clean_res: messagebox.showwarning("Mağaza Durumu", f"Sonucu İnceleyin:\n\n{msg}"))
                    
                self.after(0, self.load_remote_products)
                
            except Exception as e:
                print(f"❌ [fetch_from_n11 Arka Plan Hatası]: {e}")
                self.after(0, lambda msg=str(e): messagebox.showerror("Hata", f"Bağlantı veya Kayıt sırasında MySQL uyuşmazlığı: {msg}"))
            finally:
                try:
                    if 'cursor' in locals() and cursor:
                        cursor.close()
                except Exception:
                    pass
                self.after(0, lambda: self.btn_fetch.configure(state="normal", text="🔄 Canlı Mağazayı İndir"))

        threading.Thread(target=bg_worker, daemon=True).start()

    def scan_and_find_differences(self):
        """[MÜHÜRLENDİ] Uyuşmazlıkları strictly stok_code alias uyumuyla tespit eden tarama fonksiyonu."""
        self.btn_check_diff.configure(state="disabled", text="🔍 Taranıyor...")
        self.detected_differences = []
        diff_ui_rows = []

        def scan_worker():
            try:
                cursor = self.db.cursor()
                
                # 🛡️ Kolon alias yapısı ile alt kod bloklarındaki sözlük anahtarları strictly eşitlendi
                cursor.execute("SELECT n11_id, stock_code, title, price, stock_items AS stock FROM n11_remote_products")
                remote_rows = cursor.fetchall()
                
                for r in remote_rows:
                    r_dict = dict(r) if isinstance(r, dict) else r
                    sc = str(r_dict.get("stock_code", "")).strip()
                    if not sc: 
                        continue

                    clean_sc = sc
                    if sc.lower().startswith("nt_"): 
                        clean_sc = sc[3:]
                    elif sc.lower().startswith("n11_"): 
                        clean_sc = sc[4:]
                    
                    l_price = 0.0
                    l_stock = 0
                    product_found = False

                    # 1. Varyant Kontrolü
                    try:
                        cursor.execute("SELECT price, stock FROM product_variants WHERE code = %s LIMIT 1", (clean_sc,))
                        v_row = cursor.fetchone()
                        if not v_row:
                            cursor.execute("SELECT price, stock FROM product_variants WHERE code = %s LIMIT 1", (sc,))
                            v_row = cursor.fetchone()
                            
                        if v_row:
                            v_dict = dict(v_row) if isinstance(v_row, dict) else v_row
                            raw_v_price = v_dict.get("price") or 0.0
                            l_stock = int(v_dict.get("stock") or 0)
                            l_price = float(raw_v_price)
                            product_found = True
                    except Exception: 
                        pass

                    # 2. Ana Ürün Kontrolü
                    if not product_found:
                        try:
                            cursor.execute("SELECT price, stock, tax FROM products WHERE code = %s OR main_code = %s LIMIT 1", (clean_sc, clean_sc))
                            local_row = cursor.fetchone()
                            if not local_row:
                                cursor.execute("SELECT price, stock, tax FROM products WHERE code = %s OR main_code = %s LIMIT 1", (sc, sc))
                                local_row = cursor.fetchone()
                                
                            if local_row:
                                l_dict = dict(local_row) if isinstance(local_row, dict) else local_row
                                raw_price = l_dict.get("price") or 0.0
                                tax_rate = float(l_dict.get("tax") or 20.0)
                                l_stock = int(l_dict.get("stock") or 0)
                                l_price = float(raw_price) * (1.0 + (tax_rate / 100.0))
                                product_found = True
                        except Exception: 
                            pass

                    # 3. Karşılaştırma Algoritması
                    if product_found:
                        n_price = float(r_dict.get("price") or 0.0)
                        n_stock = int(r_dict.get("stock") or 0)
                        
                        l_price = round(l_price, 2)
                        n_price = round(n_price, 2)
                        
                        # Fiyat veya stok pazar yeriyle uyuşmuyorsa listeye ekle
                        if abs(n_price - l_price) > 0.01 or n_stock != l_stock:
                            self.detected_differences.append({
                                "stockCode": sc, "salePrice": float(l_price), "quantity": int(l_stock)
                            })
                            diff_ui_rows.append({
                                "n11_id": r_dict.get("n11_id"), 
                                "product_seller_code": sc, 
                                "title": r_dict.get("title") or "İsimsiz Ürün",
                                "price": f"{n_price:.2f}", 
                                "local_price": f"{l_price:.2f}",
                                "stock_items": n_stock, 
                                "local_stock": l_stock, 
                                "sync_status": "⚠️ Uyuşmuyor (Güncellenmeli)"
                            })
                    else:
                        # Bizde olmayan ürünü de senkronizasyon dışı bırakmak veya sıfırlamak için ekliyoruz
                        diff_ui_rows.append({
                            "n11_id": r_dict.get("n11_id"), 
                            "product_seller_code": sc, 
                            "title": r_dict.get("title") or "İsimsiz Ürün",
                            "price": f"{float(r_dict.get('price', 0)):.2f}", 
                            "local_price": "0.00",
                            "stock_items": int(r_dict.get("stock", 0)), 
                            "local_stock": 0, 
                            "sync_status": "🔴 Bizde Yok / Kod Uyuşmuyor"
                        })

                # Arayüz güncellemelerini ana thread'e (after) güvenle fırlatıyoruz
                if diff_ui_rows:
                    # Sadece uyuşmayanları göstermek yerine uyuşmayan durumları vurgula
                    self.after(0, lambda: self.table.set_data(diff_ui_rows))
                    self.after(0, lambda: self.lbl_diff_status.configure(
                        text=f"🚨 Tarama Bitti: {len(self.detected_differences)} adet uyuşmazlık otomatik eşitlemeye hazır!", 
                        text_color="#ef4444"
                    ))
                    if self.detected_differences:
                        self.after(0, lambda: self.btn_mass_sync.configure(state="normal"))
                    self.after(0, lambda: messagebox.showwarning("Farklar Yakalandı!", f"Toplam {len(self.detected_differences)} üründe fiyat/stok farkı bulundu."))
                else:
                    self.after(0, self.load_remote_products)
                    self.after(0, lambda: self.lbl_diff_status.configure(
                        text="✅ Harika! Tüm varyant stokları pazar yeriyle tam eşitlendi.", 
                        text_color="#10b981"
                    ))
                    self.after(0, lambda: self.btn_mass_sync.configure(state="disabled"))
                    self.after(0, lambda: messagebox.showinfo("Eşitlik Sağlandı", "Pazar yerindeki canlı envanter verileriyle yerel verileriniz %100 uyumlu!"))

            except Exception as e:
                print(f"❌ [scan_worker Hatası]: {e}")
                self.after(0, lambda msg=str(e): messagebox.showerror("Hata", f"Tarama motorunda arıza oluştu: {msg}"))
            finally:
                if 'cursor' in locals() and cursor:
                    try: cursor.close()
                    except Exception: pass
                self.after(0, lambda: self.btn_check_diff.configure(state="normal", text="🔍 Uyuşmazlıkları (Farkları) Tara"))
                
        threading.Thread(target=scan_worker, daemon=True).start()

    def sync_all_detected_differences(self):
        """[TAMİR EDİLDİ - %100 MYSQL] Tespit edilen uyuşmazlıkları toplu paket halinde N11'e gönderir."""
        if not self.detected_differences:
            messagebox.showwarning("Uyarı", "Güncellenecek uyumsuz ürün bulunmuyor.")
            return

        if not messagebox.askyesno("Toplu Eşitleme Onayı", f"Uyuşmayan {len(self.detected_differences)} adet ürünün güncel fiyat ve stok verisi N11'e gönderilecek.\n\nOnaylıyor musunuz?"):
            return

        self.btn_mass_sync.configure(state="disabled", text="⚡ Senkronize Ediliyor...")
        
        def sync_worker():
            try:
                target_db = getattr(self.db, "conn", self.db)
                app_key, app_secret = get_n11_credentials(target_db)
                if not app_key:
                    self.after(0, lambda: messagebox.showerror("Hata", "N11 API Kimlik bilgileri okunamadı."))
                    return
                
                success, msg = update_product_price_and_stock_n11(app_key, app_secret, self.detected_differences)
                
                if success:
                    self.after(0, lambda: messagebox.showinfo("Başarılı", f"🎉 Toplu envanter senkronizasyon emri N11'e iletildi!\n\n{msg}"))
                    self.detected_differences = []
                    self.after(0, lambda: self.lbl_diff_status.configure(text="✅ Güncelleme paketi iletildi, pazar yerinin işlemesi bekleniyor.", text_color="#10b981"))
                else:
                    self.after(0, lambda: messagebox.showerror("Pazar Yeri Hatası", f"Toplu eşitleme pazar yeri tarafından reddedildi:\n{msg}"))
                
                self.after(0, self.load_remote_products)
                
            except Exception as e:
                print(f"❌ [sync_worker Hatası]: {e}")
                self.after(0, lambda: messagebox.showerror("Sistem Hatası", f"Eşitleme sırasında beklenmeyen bir arıza oluştu:\n{e}"))
            finally:
                self.after(0, lambda: self.btn_mass_sync.configure(state="disabled", text="🚀 Bulunan Tüm Farkları Otomatik Eşitle"))

        threading.Thread(target=sync_worker, daemon=True).start()