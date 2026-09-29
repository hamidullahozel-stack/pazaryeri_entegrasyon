# Dosya: marketplaces/n11/n11_products_frame_mysql.py
# Güncelleme: MySQL uyumlu, KDV Dahil fiyat kıyaslama (25 Eylül 2026)

import customtkinter as ctk
from tkinter import messagebox
import threading
import mysql.connector
from ui.datatable import DataTable

from marketplaces.n11.n11_api import (
    fetch_and_sync_n11_remote_products,
    update_product_price_and_stock_n11,
    get_n11_credentials
)

class N11ProductsManagementFrame(ctk.CTkFrame):
    def __init__(self, parent, db_config=None, controller=None):
        super().__init__(parent)
        self.controller = controller
        self.db = mysql.connector.connect(**db_config)
        self.detected_differences = []

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
            text="🛍️ N11 MySQL Envanteri ve Karşılaştırma",
            font=self.big_title_font
        )
        title_label.pack(side="left", padx=15, pady=10)

        self.btn_fetch = ctk.CTkButton(
            header_frame, text="🔄 Canlı Mağazayı İndir", command=self.fetch_from_n11,
            font=self.big_button_font, height=38, width=170, fg_color="#1f538d"
        )
        self.btn_fetch.pack(side="right", padx=8, pady=10)

        self.btn_check_diff = ctk.CTkButton(
            header_frame, text="🔍 Uyuşmazlıkları Tara", command=self.scan_and_find_differences,
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
            text="💡 Sistem KDV Dahil fiyat eşitleme modunda çalışıyor.",
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
        """MySQL veritabanındaki N11 kayıtlarını KDV Dahil fiyatla listeler."""
        if hasattr(self.table, "show_message"):
            self.table.show_message("Veriler listeleniyor...")

        ui_rows = []
        try:
            cursor = self.db.cursor(dictionary=True)
            cursor.execute("SELECT n11_id, stock_code AS product_seller_code, title, price, stock AS stock_items FROM n11_remote_products")
            rows = cursor.fetchall()

            for r_dict in rows:
                sc = str(r_dict.get("product_seller_code", "")).strip()
                l_price, l_stock, status_txt = 0.0, 0, "Eşit / Stabil"
                product_found = False

                # Varyant kontrolü
                cursor.execute("SELECT price, stock, main_code FROM product_variants WHERE code = %s LIMIT 1", (sc,))
                v_row = cursor.fetchone()
                if v_row:
                    raw_v_price = v_row.get("price") or 0.0
                    l_stock = int(v_row.get("stock") or 0)
                    m_code = v_row.get("main_code")
                    cursor.execute("SELECT tax FROM products WHERE code = %s OR main_code = %s LIMIT 1", (m_code, m_code))
                    t_row = cursor.fetchone()
                    tax_rate = float(t_row.get("tax") or 20.0) if t_row else 20.0
                    l_price = float(raw_v_price) * (1.0 + (tax_rate / 100.0))
                    product_found = True

                # Ana ürün kontrolü
                if not product_found:
                    cursor.execute("SELECT price, stock, tax FROM products WHERE code = %s OR main_code = %s LIMIT 1", (sc, sc))
                    local_row = cursor.fetchone()
                    if local_row:
                        raw_price = local_row.get("price") or 0.0
                        tax_rate = float(local_row.get("tax") or 20.0)
                        l_stock = int(local_row.get("stock") or 0)
                        l_price = float(raw_price) * (1.0 + (tax_rate / 100.0))
                        product_found = True

                # Karşılaştırma
                n_price = float(r_dict.get("price") or 0.0)
                n_stock = int(r_dict.get("stock_items") or 0)
                if product_found:
                    if abs(n_price - l_price) > 0.10 or n_stock != l_stock:
                        status_txt = "⚠️ Uyuşmuyor (Güncellenmeli)"
                else:
                    status_txt = "Ürün Bizde Bulunamadı"

                ui_rows.append({
                    "n11_id": r_dict.get("n11_id"),
                    "product_seller_code": sc,
                    "title": r_dict.get("title"),
                    "price": f"{n_price:.2f}",
                    "local_price": f"{l_price:.2f}" if product_found else "-",
                    "stock_items": n_stock,
                    "local_stock": l_stock if product_found else "-",
                    "sync_status": status_txt
                })

        except Exception as e:
            print(f"[MySQL UI Yükleme Hatası]: {e}")

        if hasattr(self.table, "set_data"):
            self.table.set_data(ui_rows)

    def fetch_from_n11(self):
        """Canlı pazar yerindeki verileri çeker ve MySQL indekslerini doğrular."""
        self.btn_fetch.configure(state="disabled", text="⏳ İndiriliyor...")
        try:
            cursor = self.db.cursor()
            cursor.execute("ALTER TABLE n11_remote_products ADD UNIQUE INDEX ux_n11_remote_stock_code (stock_code);")
            self.db.commit()
        except Exception as idx_err:
            print(f"[İndeks Uyarısı]: {idx_err}")

        def bg_worker():
            try:
                success, res = fetch_and_sync_n11_remote_products(self.db)
                if success:
                    self.after(0, lambda: messagebox.showinfo("Başarılı", "N11 canlı mağaza envanteri başarıyla indirildi."))
                else:
                    self.after(0, lambda: messagebox.showwarning("Mağaza Durumu", f"Sonucu İnceleyin:\n{res}"))
                self.after(0, self.load_remote_products)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Hata", f"Bağlantı sırasında hata: {e}"))
            finally:
                self.after(0, lambda: self.btn_fetch.configure(state="normal", text="🔄 Canlı Mağazayı İndir"))

        threading.Thread(target=bg_worker, daemon=True).start()

    def scan_and_find_differences(self):
        """[MySQL - VARYANT VE KDV DAHİL AKILLI TARAMA MOTORU]"""
        self.btn_check_diff.configure(state="disabled", text="🔍 Taranıyor...")
        self.detected_differences = []
        diff_ui_rows = []

        try:
            cursor = self.db.cursor(dictionary=True)
            cursor.execute("SELECT n11_id, stock_code, title, price, stock FROM n11_remote_products")
            remote_rows = cursor.fetchall()

            for r_dict in remote_rows:
                sc = str(r_dict.get("stock_code", "")).strip()
                l_price, l_stock, product_found = 0.0, 0, False

                # Varyant kontrolü
                cursor.execute("SELECT price, stock, main_code FROM product_variants WHERE code = %s LIMIT 1", (sc,))
                v_row = cursor.fetchone()
                if v_row:
                    raw_v_price = v_row.get("price") or 0.0
                    l_stock = int(v_row.get("stock") or 0)
                    m_code = v_row.get("main_code")
                    cursor.execute("SELECT tax FROM products WHERE code = %s OR main_code = %s LIMIT 1", (m_code, m_code))
                    t_row = cursor.fetchone()
                    tax_rate = float(t_row.get("tax") or 20.0) if t_row else 20.0
                    l_price = float(raw_v_price) * (1.0 + (tax_rate / 100.0))
                    product_found = True

                # Ana ürün kontrolü
                if not product_found:
                    cursor.execute("SELECT price, stock, tax FROM products WHERE code = %s OR main_code = %s LIMIT 1", (sc, sc))
                    local_row = cursor.fetchone()
                    if local_row:
                        raw_price = local_row.get("price") or 0.0
                        tax_rate = float(local_row.get("tax") or 20.0)
                        l_stock = int(local_row.get("stock") or 0)
                        l_price = float(raw_price) * (1.0 + (tax_rate / 100.0))
                        product_found = True

                if product_found:
                    n_price = float(r_dict.get("price") or 0.0)
                    n_stock = int(r_dict.get("stock") or 0)

                    if abs(n_price - l_price) > 0.10 or n_stock != l_stock:
                        payload_item = {
                            "stockCode": sc,
                            "salePrice": l_price,
                            "quantity": l_stock
                        }
                        self.detected_differences.append(payload_item)

                        diff_ui_rows.append({
                            "n11_id": r_dict.get("n11_id"),
                            "product_seller_code": sc,
                            "title": r_dict.get("title"),
                            "price": f"{n_price:.2f}",
                            "local_price": f"{l_price:.2f}",
                            "stock_items": n_stock,
                            "local_stock": l_stock,
                            "sync_status": "🔴 Güncellenmesi Gerekiyor"
                        })

            if diff_ui_rows:
                if hasattr(self.table, "set_data"):
                    self.table.set_data(diff_ui_rows)
                self.lbl_diff_status.configure(
                    text=f"🚨 Tarama Bitti: {len(diff_ui_rows)} adet uyumsuz ürün bulundu!",
                    text_color="#ef4444"
                )
                self.btn_mass_sync.configure(state="normal")
            else:
                self.load_remote_products()
                self.lbl_diff_status.configure(
                    text="✅ Tüm stoklar ve KDV dahil fiyatlar eşitlendi.",
                    text_color="#10b981"
                )
                self.btn_mass_sync.configure(state="disabled")

        except Exception as e:
            messagebox.showerror("Hata", f"Tarama motorunda arıza oluştu: {e}")
        finally:
            self.btn_check_diff.configure(state="normal", text="🔍 Uyuşmazlıkları Tara")

    def sync_all_detected_differences(self):
        """Tespit edilen tüm uyuşmazlıkları N11'e gönderir."""
        if not self.detected_differences:
            messagebox.showwarning("Uyarı", "Güncellenecek uyumsuz ürün bulunmuyor.")
            return

        if not messagebox.askyesno("Toplu Eşitleme Onayı", f"Uyuşmayan {len(self.detected_differences)} ürün N11'e gönderilecek.\nOnaylıyor musunuz?"):
            return

        self.btn_mass_sync.configure(state="disabled", text="⚡ Senkronize Ediliyor...")

        def sync_worker():
            try:
                app_key, app_secret = get_n11_credentials(self.db)
                if not app_key:
                    self.after(0, lambda: messagebox.showerror("Hata", "N11 API kimlik bilgileri okunamadı."))
                    return

                success, msg = update_product_price_and_stock_n11(app_key, app_secret, self.detected_differences)

                if success:
                    self.after(0, lambda: messagebox.showinfo("Başarılı", f"Toplu güncelleme başarıyla iletildi!\n{msg}"))
                    self.detected_differences = []
                    self.after(0, lambda: self.lbl_diff_status.configure(text="✅ Güncelleme paketi iletildi.", text_color="#10b981"))
                else:
                    self.after(0, lambda: messagebox.showerror("Pazar Yeri Hatası", f"Toplu eşitleme başarısız:\n{msg}"))

                self.after(0, self.load_remote_products)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Hata", f"Sistem hatası: {e}"))
            finally:
                self.after(0, lambda: self.btn_mass_sync.configure(state="disabled", text="🚀 Bulunan Tüm Farkları Otomatik Eşitle"))

        threading.Thread(target=sync_worker, daemon=True).start()
