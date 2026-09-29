# Dosya Yolu: C:\entegrasyon1\main.py
# İşlem Tarihi: 21 Eylül 2026
# Açıklama: Pazar Yeri Entegrator - Çoklu Kanal Modüler Ana Uygulama Dosyası

import threading
import warnings
import logging
import customtkinter as ctk
from diff_report_frame import DiffReportFrame
from product_frame import ProductManagementFrame
from template_frame import TemplateManagementFrame
from utils.credentials_manager import get_credentials, save_credentials
from datetime import datetime
import sys
import traceback
import importlib  
from mysql_database import get_mysql_db as get_db, MySQLDatabase
from tkinter import messagebox

# =========================================================================
# 📦 PAZAR YERİ MODÜL IMPORTLARI (%100 SİMETRİK VE STANDART HALE GELDİ!)
# =========================================================================

# 🔴 N11 Modülü
from marketplaces.n11.n11_api import N11CategoryAPI as N11Service
from marketplaces.n11.n11_mapping_frame import CategoryAndAttributeMappingFrame
from marketplaces.n11.n11_products_frame import N11ProductsManagementFrame
from marketplaces.n11.n11_orders_frame import OrdersManagementFrame
from marketplaces.n11.n11_sync_frame import SyncManagementFrame

# 🔵 Hepsiburada Modülü
from marketplaces.hepsiburada.hepsiburada_api import HepsiburadaService
from marketplaces.hepsiburada.hepsiburada_mapping_frame import HepsiburadaMappingFrame
from marketplaces.hepsiburada.hepsiburada_products_frame import HepsiburadaProductsManagementFrame
from marketplaces.hepsiburada.hepsiburada_orders_frame import HepsiburadaOrdersManagementFrame
from marketplaces.hepsiburada.hepsiburada_sync_frame import HepsiburadaSyncManagementFrame

# 🟢 Trendyol Modülü
from marketplaces.trendyol.trendyol_api import TrendyolService
from marketplaces.trendyol.trendyol_mapping_frame import TrendyolMappingFrame  
from marketplaces.trendyol.trendyol_products_frame import TrendyolProductsManagementFrame
from marketplaces.trendyol.trendyol_orders_frame import TrendyolOrdersManagementFrame
from marketplaces.trendyol.trendyol_sync_frame import TrendyolSyncManagementFrame

# 🟡 Pazarama Modülü
from marketplaces.pazarama.pazarama_api import PazaramaService
from marketplaces.pazarama.pazarama_mapping_frame import PazaramaMappingFrame
from marketplaces.pazarama.pazarama_products_frame import PazaramaProductsManagementFrame
from marketplaces.pazarama.pazarama_sync_frame import PazaramaSyncManagementFrame

# 🟣 Idefix Modülü
from marketplaces.idefix.idefix_api import IdefixService
from marketplaces.idefix.idefix_mapping_frame import IdefixMappingFrame
from marketplaces.idefix.idefix_products_frame import IdefixProductsManagementFrame
from marketplaces.idefix.idefix_sync_frame import IdefixSyncManagementFrame


def global_hata_yakalayici(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    hata_detayi = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    
    # Kullanıcıya ekranda da gösterelim ki hatasız takip edilsin
    messagebox.showerror("Kritik Hata Yakalandı", f"Hata: {exc_value}\n\nDetaylar hata_gunlugu.txt dosyasına yazıldı.")
    
    # Dosyaya yazma işlemleri...
    sys.__excepthook__(exc_type, exc_value, exc_traceback)
    
    
def setup_logging():
    logging.basicConfig(level=logging.INFO)

def get_logger(name):
    return logging.getLogger(name)

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

setup_logging()
log = get_logger("main")

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class EntegratorApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Pazar Yeri Entegrator - Çoklu Kanal Sürümü")
        self.geometry("1200x780")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # 1. Merkezi Ortak Veritabanı (Tüm Pazar Yerleri Aynı Datayı Kullanır)
        self.db = MySQLDatabase()
        if hasattr(self.db, "init"):
            self.db.init()

        # 2. Sol Menü (Sidebar) Çerçevesi
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        ctk.CTkLabel(
            self.sidebar, text="ENTEGRATOR",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(padx=20, pady=20)

        self.menu_buttons_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.menu_buttons_frame.pack(fill="both", expand=True)

        # 3. Sağ İçerik Konteyneri
        self.right_container = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.right_container.pack(side="right", fill="both", expand=True, padx=15, pady=15)

        # Üst Pazar Yeri Seçim Barı
        self.top_marketplace_bar = ctk.CTkFrame(self.right_container, height=45)
        self.top_marketplace_bar.pack(fill="x", pady=(0, 10))
        
        ctk.CTkLabel(
            self.top_marketplace_bar, text="Aktif Pazar Yeri:",
            font=ctk.CTkFont(weight="bold")
        ).pack(side="left", padx=15)
        
        self.combo_marketplace = ctk.CTkComboBox(
            self.top_marketplace_bar, width=220,
            values=[
                "Trendyol Entegrasyonu", 
                "N11 Entegrasyonu", 
                "Hepsiburada Entegrasyonu",
                "Pazarama Entegrasyonu",
                "İdefix Entegrasyonu",
                "PTTAVM Entegrasyonu"
                
            ],
            command=self.on_marketplace_changed
        )
        self.combo_marketplace.pack(side="left", padx=10)
        self.combo_marketplace.set("N11 Entegrasyonu")

        self.container = ctk.CTkFrame(self.right_container, fg_color="transparent")
        self.container.pack(fill="both", expand=True)

        # 4. Sayfa Yapılandırıcıları (Ortak Stok + Pazar Yeri Modülleri)
        self._builders = {
            "products":     lambda: ProductManagementFrame(self.container, self.db),
            "templates":    lambda: TemplateManagementFrame(self.container, self.db),
            "api":          self._build_api_frame,
            
            # N11 Modül Sayfaları
            "n11_prods":    lambda: N11ProductsManagementFrame(self.container, self.db),
            "mapping":      lambda: CategoryAndAttributeMappingFrame(self.container, self.db),
            "orders":       lambda: OrdersManagementFrame(self.container, self.db),
            "sync":         lambda: SyncManagementFrame(self.container, self.db),
            "diff_report":  lambda: DiffReportFrame(self.container, self.db),

            # 🟡 Pazarama Modül Sayfaları
            "pazarama_prods": lambda: PazaramaProductsManagementFrame(self.container, self.db),
        }
        self.frames: dict[str, ctk.CTkBaseClass] = {}
        self.active_key: str | None = None

        # İlk açılış menüsünü yükle
        self.rebuild_sidebar_menu("N11 Entegrasyonu")
        self.switch_frame("products")

    def on_marketplace_changed(self, selected_marketplace):
        """Pazar yeri değiştiğinde sol menüyü ve ilgili modül ekranlarını günceller."""
        log.info(f"Pazar yeri değiştirildi: {selected_marketplace}")
        self.rebuild_sidebar_menu(selected_marketplace)
        
        # Eski çerçeveyi temizle (Eğer varsa)
        if hasattr(self, "current_frame") and self.current_frame:
            self.current_frame.destroy()

        # PTTAVM Entegrasyonu seçildiyse özel çerçevemizi yükle
        if "PTTAVM" in selected_marketplace.upper() or "PTT" in selected_marketplace.upper():
            try:
                from marketplaces.pttavm.pttavm_products_frame import PttavmProductsManagementFrame
                self.current_frame = PttavmProductsManagementFrame(self.container, self.db) # DÜZELTME: self.content_area -> self.container
                self.current_frame.pack(fill="both", expand=True)
                return
            except Exception as e:
                log.error(f"PttAVM ekranı yüklenirken hata oluştu: {e}")

        # Diğer pazar yerleri için standart akış
        if self.active_key == "api":
            self.load_api_keys()
        else:
            self.switch_frame("products")
            
            
    def rebuild_sidebar_menu(self, marketplace_name):
        """Seçilen pazar yerine göre sol menü butonlarını dinamik olarak kurar."""
        for widget in self.menu_buttons_frame.winfo_children():
            widget.destroy()

        base_menu = [
            ("API Ayarları", "api", None, None),
            ("Şablon Yönetimi", "templates", None, None),
            ("Ortak Ürün Listesi", "products", None, None),
        ]

        if marketplace_name == "N11 Entegrasyonu":
            specific_menu = [
                ("N11 Mağaza Envanteri", "n11_prods", "#0d9488", "#0f766e"),
                ("Kategori & Özellik Eşle", "mapping", None, None),
                ("Siparişler", "orders", None, None),
                ("Canlı Ürün Gönder", "sync", "#16a34a", "#15803d"),
                ("Stok Fark Raporu", "diff_report", None, None),
            ]
        elif marketplace_name == "Pazarama Entegrasyonu":
            specific_menu = [
                ("Excel Ürün Karşılaştır", "pazarama_prods", "#3b82f6", "#2563eb"),
                ("Kategori Eşleştirme", "mapping", None, None),
                ("Siparişler", "orders", None, None),
            ]
        else:
            specific_menu = [
                ("Kategori Eşleştirme", "mapping", None, None),
                ("Siparişler", "orders", None, None),
            ]

        for text, key, fg, hover in (base_menu + specific_menu):
            kwargs = {}
            if fg:
                kwargs.update(fg_color=fg, hover_color=hover)
            ctk.CTkButton(
                self.menu_buttons_frame, text=text,
                command=lambda k=key: self.switch_frame(k),
                **kwargs
            ).pack(padx=15, pady=6, fill="x")
            
    def hot_reload_modules(self):
        """
        🚀 [EVRENSEL HOT RELOAD MOTORU - THREAD KORUMALI]
        Arayüzü dondurmadan (Yanıt Vermiyor hatasına düşmeden) modülleri arka planda RAM'e deşifre eder.
        """
        def background_reload():
            try:
                log.info("⚡ Evrensel Hot Reload başlatılıyor, modüller arka planda tazeleniyor...")
                import importlib
                import sys

                modules_to_reload = [
                    "product_frame",
                    "marketplaces.n11.n11_api",
                    "marketplaces.n11.n11_products_frame",
                    "marketplaces.n11.n11_mapping_frame"
                ]

                for mod_name in modules_to_reload:
                    if mod_name in sys.modules:
                        try:
                            importlib.reload(sys.modules[mod_name])
                            print(f"✅ [RELOAD SUCCESS]: {mod_name} modülü güncellendi.")
                        except Exception as reload_err:
                            print(f"⚠️ [RELOAD WARNING] {mod_name} tazelenirken hata: {reload_err}")

                import product_frame
                import marketplaces.n11.n11_products_frame as n11_prod_mod
                import marketplaces.n11.n11_mapping_frame as n11_map_mod

                # Sınıf referanslarını güvenli şekilde güncelliyoruz
                self._builders["products"] = lambda: product_frame.ProductManagementFrame(self.container, self.db)
                self._builders["n11_prods"] = lambda: n11_prod_mod.N11ProductsManagementFrame(self.container, self.db)
                self._builders["mapping"] = lambda: n11_map_mod.CategoryAndAttributeMappingFrame(self.container, self.db)

                current_active_key = self.active_key

                # Arayüz güncellemelerini ana iş parçacığına (Main Thread) güvenle devrediyoruz
                def apply_ui_refresh():
                    if current_active_key in self.frames:
                        try:
                            self.frames[current_active_key].pack_forget()
                            self.frames[current_active_key].destroy()
                        except Exception:
                            pass
                        del self.frames[current_active_key]

                    self.switch_frame(current_active_key)

                    if hasattr(self, "lbl_api_status") and self.lbl_api_status.winfo_exists():
                        self.lbl_api_status.configure(
                            text="⚡ [HOT RELOAD] product_frame ve tüm N11 sayfaları başarıyla güncellendi!",
                            text_color="#10b981"
                        )
                    print("🚀 [HOT RELOAD MOTORU] Tüm entegrasyon ekranları başarıyla canlıya alındı!")

                self.after(0, apply_ui_refresh)

            except Exception as e:
                log.exception("Hot reload sırasında kritik hata")
                self.after(0, lambda: messagebox.showerror("Hot Reload Başarısız", f"Yazdığınız kodlarda syntax/yazım veya parantez hatası olabilir.\n\nDetay: {e}"))

        # F5'e basıldığında ana pencereyi dondurmaması için işlemi Thread'e fırlatıyoruz
        threading.Thread(target=background_reload, daemon=True).start()

    def switch_frame(self, page_name: str):
        """Sayfalar arası geçişi yönetir. PttAVM için özel şablon ekranını güvenle tetikler."""
        
        # --- PTTAVM İÇİN GÜVENLİ İZOLE KONTROL (Diğer kanalları asla bozmaz) ---
        try:
            market_str = self.combo_marketplace.get().upper()
        except Exception:
            market_str = ""

        if "PTTAVM" in market_str or "PTT" in market_str:
            # PttAVM seçiliyse ve ürün/şablon menülerine tıklandıysa özel şablon ekranımızı aç
            if page_name in ["products", "templates", "ortak_urun_listesi", "sablon_yonetimi"]:
                if self.active_key and self.active_key in self.frames:
                    try:
                        self.frames[self.active_key].pack_forget()
                    except Exception:
                        pass
                
                ptt_key = f"pttavm_{page_name}"
                if ptt_key not in self.frames:
                    try:
                        from marketplaces.pttavm.pttavm_products_frame import PttavmProductsManagementFrame
                        self.frames[ptt_key] = PttavmProductsManagementFrame(self.container, self.db) # DÜZELTME: self.content_area -> self.container
                    except Exception as e:
                        log.exception("PttAVM şablon ekranı yüklenemedi")
                        return
                
                frame = self.frames[ptt_key]
                frame.pack(fill="both", expand=True)
                self.active_key = ptt_key
                return
        # ---------------------------------------------------------------------

        # --- DİĞER PAZAR YERLERİ İÇİN ORİJİNAL AKIŞ ---
        if page_name not in self._builders:
            log.warning("Bilinmeyen sayfa: %s", page_name)
            return

        if page_name not in self.frames:
            try:
                self.frames[page_name] = self._builders[page_name]()
            except Exception:
                log.exception("Sayfa oluşturulamadı: %s", page_name)
                return

        if self.active_key and self.active_key in self.frames:
            self.frames[self.active_key].pack_forget()

        frame = self.frames[page_name]
        frame.pack(fill="both", expand=True)
        self.active_key = page_name

        if page_name == "api":
            self.load_api_keys()
        elif page_name == "diff_report":
            frame.load_diff_data()
        elif page_name == "mapping" and hasattr(frame, "show_sub_frame"):
            frame.show_sub_frame("mapping_list")
            
    def _build_api_frame(self):
        frame = ctk.CTkFrame(self.container, fg_color="transparent")
        
        self.lbl_api_title = ctk.CTkLabel(
            frame, text="Pazar Yeri API Bağlantı Ayarları",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.lbl_api_title.pack(pady=15)

        self.ent_extra = ctk.CTkEntry(frame, width=350)
        self.ent_key = ctk.CTkEntry(frame, width=350)
        self.ent_secret = ctk.CTkEntry(frame, show="*", width=350)

        self.lbl_extra = ctk.CTkLabel(frame, text="", font=ctk.CTkFont(size=12))
        
        self.ent_extra.pack(pady=5)
        self.ent_key.pack(pady=5)
        self.ent_secret.pack(pady=5)

        ctk.CTkButton(
            frame, text="API Bilgilerini Kaydet", fg_color="green",
            hover_color="#15803d", command=self.save_api
        ).pack(pady=15)

        self.lbl_api_status = ctk.CTkLabel(frame, text="", font=ctk.CTkFont(weight="bold"))
        self.lbl_api_status.pack(pady=5)

        ctk.CTkLabel(
            frame, wraplength=520, text_color="#9ca3af",
            text="🔒 Güvenlik: API bilgileri seçili pazar yerine özel izole edilerek veritabanında saklanır."
        ).pack(pady=10, padx=30)

        return frame

    def load_api_keys(self):
        try:
            market_str = self.combo_marketplace.get().upper()
            
            if "TRENDYOL" in market_str:
                current_market = "TRENDYOL"
            elif "HEPSIBURADA" in market_str:
                current_market = "HEPSIBURADA"
            elif "PAZARAMA" in market_str:
                current_market = "PAZARAMA"
            elif "IDEFIX" in market_str or "İDEFİX" in market_str:
                current_market = "IDEFIX"
            elif "PTTAVM" in market_str or "PTT" in market_str:  # <-- YENİ EKLENEN GÜVENLİ KONTROL
                current_market = "PTTAVM"
            else:
                current_market = "N11"
            
            self.lbl_api_title.configure(text=f"🔑 {current_market} API Bağlantı Ayarları")
            
            if current_market in ["TRENDYOL", "HEPSIBURADA", "PAZARAMA", "IDEFIX"]:
                self.ent_extra.configure(placeholder_text=f"{current_market} Satıcı / Merchant ID")
                self.ent_key.configure(placeholder_text=f"{current_market} API Key / Client ID")
                self.ent_secret.configure(placeholder_text=f"{current_market} API Secret / Password")
                self.ent_extra.pack(pady=5)
            else:
                # PTTAVM veya N11 için ekstra alan gerekmiyorsa gizle
                self.ent_extra.pack_forget()
                self.ent_key.configure(placeholder_text=f"{current_market} App Key / Token")
                self.ent_secret.configure(placeholder_text=f"{current_market} App Secret / Password")

            app_key, secret = get_credentials(getattr(self.db, "conn", self.db), current_market)
            
            self.ent_extra.delete(0, "end")
            self.ent_key.delete(0, "end")
            self.ent_secret.delete(0, "end")
            
            if app_key:
                if ":" in app_key and current_market not in ["N11", "PTTAVM"]:
                    extra, actual_key = app_key.split(":", 1)
                    self.ent_extra.insert(0, extra)
                    self.ent_key.insert(0, actual_key)
                else:
                    self.ent_key.insert(0, app_key)
                
            if secret:
                self.ent_secret.insert(0, secret)
            
            if app_key and secret:
                self.lbl_api_status.configure(
                    text=f"✅ {current_market} API Bilgileri veritabanında kayıtlı.",
                    text_color="#22c55e"
                )
            else:
                self.lbl_api_status.configure(
                    text=f"⚠️ {current_market} API Bilgileri eksik veya henüz kayıtlı değil.",
                    text_color="#eab308"
                )
        except Exception:
            log.exception("load_api_keys hatası")

    def save_api(self):
        market_str = self.combo_marketplace.get().upper()
        
        if "TRENDYOL" in market_str:
            current_market = "TRENDYOL"
        elif "HEPSIBURADA" in market_str:
            current_market = "HEPSIBURADA"
        elif "PAZARAMA" in market_str:
            current_market = "PAZARAMA"
        elif "IDEFIX" in market_str or "İDEFİX" in market_str:
            current_market = "IDEFIX"
        elif "PTTAVM" in market_str or "PTT" in market_str:  # <-- YENİ EKLENEN GÜVENLİ KONTROL
            current_market = "PTTAVM"
        else:
            current_market = "N11"
        
        extra_id = self.ent_extra.get().strip()
        key = self.ent_key.get().strip()
        secret = self.ent_secret.get().strip()

        if current_market not in ["N11", "PTTAVM"] and extra_id:
            key = f"{extra_id}:{key}"

        if not key or not secret:
            self.lbl_api_status.configure(
                text="❌ API anahtarları boş bırakılamaz.", 
                text_color="#ef4444"
            )
            return

        try:
            conn_target = getattr(self.db, "conn", self.db)
            save_credentials(conn_target, current_market, key, secret)
            self.lbl_api_status.configure(
                text=f"✅ {current_market} API Bilgileri başarıyla kaydedildi.",
                text_color="#22c55e"
            )
        except Exception as e:
            log.exception("API Kaydetme Hatası")
            self.lbl_api_status.configure(
                text=f"❌ Kaydetme sırasında hata oluştu: {e}",
                text_color="#ef4444"
            )
            
    def on_close(self):
        try:
            if hasattr(self.db, "close"):
                self.db.close()
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    app = EntegratorApp()
    
    # 🛡️ KLAVYE HOT-RELOAD TETİKLEYİCİSİ
    app.bind("<F5>", lambda event: app.hot_reload_modules())
    
    app.mainloop()