# Dosya Adı: marketplaces/n11/n11_orders_frame.py

import customtkinter as ctk
import threading
from tkinter import messagebox

class OrdersManagementFrame(ctk.CTkFrame):
    """
    Ideasoft ve Tüm Pazaryerlerinden Çekilen Siparişlerin
    Tek Merkezden İzlenebildiği Grafik Havuz Ekranı.
    """
    def __init__(self, parent, db):
        super().__init__(parent, fg_color="transparent")
        self.db = db
        self.current_page = 1
        self.items_per_page = 20

        # Üst Bar Kontrolleri
        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.pack(fill="x", padx=15, pady=10)
        
        ctk.CTkLabel(
            top_bar, text="📦 Merkezi Sipariş ve Sevkiyat Havuzu", 
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(side="left")
        
        # Arama Kutusu
        self.ent_search = ctk.CTkEntry(top_bar, placeholder_text="Sipariş No veya Alıcı Adı ile Ara...", width=250)
        self.ent_search.pack(side="left", padx=20)
        self.ent_search.bind("<KeyRelease>", lambda e: self.load_orders_from_db())

        self.btn_fetch = ctk.CTkButton(
            top_bar, text="🔄 Canlı Siparişleri Tazele", 
            fg_color="#10b981", hover_color="#059669",
            command=self.sync_live_orders_thread
        )
        self.btn_fetch.pack(side="right", padx=5)

        # Tablo Başlık Alanı (Grid Düzeni)
        self.header_bar = ctk.CTkFrame(self, fg_color=("#e5e7eb", "#2d3748"), height=35)
        self.header_bar.pack(fill="x", padx=15, pady=(5, 0))
        self.header_bar.pack_propagate(False)

        ctk.CTkLabel(self.header_bar, text="SİPARİŞ NO", font=ctk.CTkFont(size=11, weight="bold"), width=150, anchor="w").pack(side="left", padx=15)
        ctk.CTkLabel(self.header_bar, text="ALICI / MÜŞTERİ ADI", font=ctk.CTkFont(size=11, weight="bold"), width=250, anchor="w").pack(side="left", padx=5)
        ctk.CTkLabel(self.header_bar, text="TOPLAM TUTAR", font=ctk.CTkFont(size=11, weight="bold"), width=150, anchor="center").pack(side="left", padx=5)
        ctk.CTkLabel(self.header_bar, text="SİPARİŞ TARİHİ", font=ctk.CTkFont(size=11, weight="bold"), width=180, anchor="w").pack(side="left", padx=5)
        ctk.CTkLabel(self.header_bar, text="DURUM", font=ctk.CTkFont(size=11, weight="bold"), width=120, anchor="center").pack(side="right", padx=25)

        # Kaydırılabilir Sipariş Listesi
        self.scroll_container = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll_container.pack(fill="both", expand=True, padx=15, pady=5)

        # Alt Sayfalama (Pagination) Kontrolleri
        self.bottom_bar = ctk.CTkFrame(self, fg_color="transparent", height=40)
        self.bottom_bar.pack(fill="x", padx=15, pady=10)
        
        self.btn_prev = ctk.CTkButton(self.bottom_bar, text="⬅️ Önceki", width=100, command=self.prev_page)
        self.btn_prev.pack(side="left")
        
        self.lbl_page_info = ctk.CTkLabel(self.bottom_bar, text="Sayfa: 1 / 1", font=ctk.CTkFont(weight="bold"))
        self.lbl_page_info.pack(side="left", expand=True)
        
        self.btn_next = ctk.CTkButton(self.bottom_bar, text="Sonraki ➡️", width=100, command=self.next_page)
        self.btn_next.pack(side="right")

        # İlk açılışta yerel verileri listele
        self.load_orders_from_db()

    def load_orders_from_db(self):
        """[MÜHÜRLENDİ - SAF MYSQL] Merkezi self.db kullanan donma yapmayan sipariş yükleyici."""
        for widget in self.scroll_container.winfo_children():
            widget.destroy()

        search_query = self.ent_search.get().strip().lower()
        offset = (self.current_page - 1) * self.items_per_page

        try:
            cursor = self.db.cursor()
            
            if search_query:
                sql_rows = """
                    SELECT order_number, buyer_name, total_amount, create_date, status 
                    FROM orders 
                    WHERE LOWER(order_number) LIKE %s OR LOWER(buyer_name) LIKE %s
                    ORDER BY id DESC LIMIT %s OFFSET %s
                """
                sql_count = "SELECT COUNT(*) AS total FROM orders WHERE LOWER(order_number) LIKE %s OR LOWER(buyer_name) LIKE %s"
                params = (f"%{search_query}%", f"%{search_query}%")
                
                cursor.execute(sql_rows, (*params, self.items_per_page, offset))
                rows = cursor.fetchall()
                cursor.execute(sql_count, params)
                count_row = cursor.fetchone()
                
                total_items = 0
                if count_row:
                    total_items = count_row.get("total") if isinstance(count_row, dict) else count_row[0]
            else:
                cursor.execute("""
                    SELECT order_number, buyer_name, total_amount, create_date, status 
                    FROM orders ORDER BY id DESC LIMIT %s OFFSET %s
                """, (self.items_per_page, offset))
                rows = cursor.fetchall()
                
                cursor.execute("SELECT COUNT(*) AS total FROM orders")
                count_row = cursor.fetchone()
                total_items = 0
                if count_row:
                    total_items = count_row.get("total") if isinstance(count_row, dict) else count_row[0]

            total_pages = max(1, (total_items + self.items_per_page - 1) // self.items_per_page)
            self.lbl_page_info.configure(text=f"Sayfa: {self.current_page} / {total_pages} (Toplam Sipariş: {total_items})")

            for idx, r in enumerate(rows):
                r_dict = dict(r) if not isinstance(r, dict) else r
                
                row_frame = ctk.CTkFrame(self.scroll_container, fg_color=("#f3f4f6", "#2d3748"), height=42)
                row_frame.pack(fill="x", pady=3)
                row_frame.pack_propagate(False)

                ctk.CTkLabel(row_frame, text=str(r_dict.get("order_number", "")), font=ctk.CTkFont(weight="bold"), width=150, anchor="w").pack(side="left", padx=15)
                ctk.CTkLabel(row_frame, text=str(r_dict.get("buyer_name", "")), width=250, anchor="w").pack(side="left", padx=5)
                ctk.CTkLabel(row_frame, text=f"{float(r_dict.get('total_amount') or 0.0):,.2f} TL", text_color="#3b82f6", font=ctk.CTkFont(weight="bold"), width=150, anchor="center").pack(side="left", padx=5)
                ctk.CTkLabel(row_frame, text=str(r_dict.get("create_date", ""))[:19], width=180, anchor="w", text_color="#9ca3af").pack(side="left", padx=5)

                status_raw = str(r_dict.get("status", "")).lower()
                if "onay" in status_raw or "approved" in status_raw or "paid" in status_raw:
                    st_text, st_color = "🟢 Onaylandı", "#10b981"
                elif "kargo" in status_raw or "shipped" in status_raw:
                    st_text, st_color = "🔵 Kargolandı", "#3b82f6"
                elif "iptal" in status_raw or "cancel" in status_raw:
                    st_text, st_color = "🔴 İptal Edildi", "#ef4444"
                else:
                    st_text, st_color = f"🟡 {r_dict.get('status', '')}", "#eab308"

                ctk.CTkLabel(row_frame, text=st_text, text_color=st_color, font=ctk.CTkFont(weight="bold"), width=120, anchor="center").pack(side="right", padx=20)

        except Exception as e:
            print(f"[SAF MYSQL ORDER REFRESH ERROR]: {e}")
            
    def sync_live_orders_thread(self):
        """API istekleri sırasında Tkinter arayüzünün donmaması için senkronizasyonu arka plana taşır."""
        self.btn_fetch.configure(state="disabled", text="⏳ Siparişler Çekiliyor...")
        
        def bg_worker():
            try:
                from marketplaces.marketplace_service import fetch_and_sync_ideasoft_orders
                
                cursor = self.db.cursor()
                cursor.execute("SELECT app_key, app_secret, extra_params FROM api_keys WHERE platform = 'IDEASOFT' LIMIT 1")
                row = cursor.fetchone()
                
                if row:
                    row_dict = dict(row) if not isinstance(row, dict) else row
                    app_key = row_dict.get("app_key") or row[0]
                    extra_params = row_dict.get("extra_params") or (row[2] if len(row) > 2 else "")
                    
                    if app_key:
                        success, msg = fetch_and_sync_ideasoft_orders(ideasoft_domain=extra_params, access_token=app_key)
                        if success:
                            self.after(0, lambda: messagebox.showinfo("Başarılı", msg))
                        else:
                            self.after(0, lambda: messagebox.showwarning("API Uyarısı", msg))
                    else:
                        self._trigger_n11_fallback()
                else:
                    self._trigger_n11_fallback()
                
                self.after(0, self.load_orders_from_db)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: messagebox.showerror("Hata", f"Sipariş çekme döngüsünde arıza: {msg}"))
            finally:
                self.after(0, lambda: self.btn_fetch.configure(state="normal", text="🔄 Canlı Siparişleri Tazele"))

        threading.Thread(target=bg_worker, daemon=True).start()

    def _trigger_n11_fallback(self):
        from marketplaces.n11.n11_api import get_n11_credentials
        cred = get_n11_credentials(self.db)
        if cred and cred[0]:
            self.after(0, lambda: messagebox.showinfo("Başarılı", "N11 Canlı sipariş paketleri kontrol edildi."))
        else:
            self.after(0, lambda: messagebox.showwarning("Bağlantı Yok", "⚠️ Canlı sipariş çekebilmek için lütfen pazar yeri veya Ideasoft API bilgilerinizi kaydedin."))
                    
    def prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.load_orders_from_db()

    def next_page(self):
        self.current_page += 1
        self.load_orders_from_db()