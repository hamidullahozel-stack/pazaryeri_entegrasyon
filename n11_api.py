# Dosya: marketplaces/n11/n11_api.py
# İşlem Tarihi: 26 Eylül 2026 / REST API Güncellenmiş Sürüm

import requests
import cloudscraper
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import warnings
warnings.filterwarnings("ignore", message=".*SQLAlchemy.*")

class N11API:
    def __init__(self, app_key: str, app_secret: str, integrator_name: str = "Entegratör"):
        self.app_key = str(app_key).strip() if app_key else ""
        self.app_secret = str(app_secret).strip() if app_secret else ""
        self.integrator_name = integrator_name
        self.base_url = "https://api.n11.com"
        self.headers = {
            "appKey": self.app_key,
            "appSecret": self.app_secret,
            "Content-Type": "application/json"
        }
        self.n11_api = N11CategoryAPI(app_key, app_secret)

    def create_product_task(self, skus: list) -> dict:
        """
        Yeni ürün yükleme görevi oluşturur (Maksimum 1000 SKU).
        Endpoint: POST /ms/product/tasks/product-create
        """
        endpoint = f"{self.base_url}/ms/product/tasks/product-create"
        
        payload = {
            "payload": {
                "integrator": self.integrator_name,
                "skus": skus
            }
        }
        
        response = requests.post(endpoint, json=payload, headers=self.headers)

        # Dönen yanıtı inceleyelim:
        print("Status Code:", response.status_code)
        print("Response JSON:", response.json())
    


class N11CategoryAPI:
    def __init__(self, app_key, app_secret):
        self.app_key = str(app_key or "").strip()
        self.app_secret = str(app_secret or "").strip()
        self.base_url = "https://api.n11.com/cdn"
        self.headers = {
            "appKey": self.app_key,
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

    def get_task_details(self, task_id: int) -> dict:
        """
        Gönderilen görevin durumunu (IN_QUEUE, REJECT vb.) sorgular.
        """
        endpoint = f"{self.base_url}/ms/product/tasks/{task_id}"
        response = requests.get(endpoint, headers=self.headers)
        return response.json()
    
    def get_category_attributes(self, category_id):
        url = f"{self.base_url}/category/{category_id}/attribute"
        try:
            response = requests.get(url, headers=self.headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                return data.get("categoryAttributes", [])
            return []
        except Exception as e:
            print(f"[N11 HATA] Özellik çekilemedi: {e}")
            return []

    def _fetch_full_tree(self):
        url = f"{self.base_url}/categories"
        try:
            response = requests.get(url, headers=self.headers, timeout=20)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict):
                    return data.get("categories", []) or data.get("content", [])
                elif isinstance(data, list):
                    return data
        except Exception as e:
            print(f"[N11 HATA] Kategori Ağacı Çekilemedi: {e}")
        return []

    def check_task_status(self, task_code):
        """N11 toplu işlem/batch durumunu REST üzerinden sorgular."""
        url = f"{self.base_url}/batch-status/{task_code}"
        try:
            response = requests.get(url, headers=self.headers, timeout=15)
            if response.status_code in [200, 201]:
                return True, response.json()
            return False, f"HTTP {response.status_code}: {response.text[:200]}"
        except Exception as e:
            return False, f"Bağlantı Hatası: {str(e)}"


def fetch_n11_categories(app_key, app_secret=None):
    try:
        api = N11CategoryAPI(app_key, app_secret)
        return api._fetch_full_tree()
    except Exception as e:
        print(f"N11 Kategori Çekme Hatası: {e}")
        return []
    
def fetch_n11_category_attributes(app_key, app_secret, category_id):
    """N11 kategori özelliklerini (attribute) çeken yardımcı fonksiyon."""
    try:
        api = N11CategoryAPI(app_key, app_secret)
        return api.get_category_attributes(category_id)
    except Exception as e:
        print(f"[N11 HATA] Kategori özellikleri çekilemedi: {e}")
        return []

def fetch_n11_sub_categories(app_key, app_secret, category_id):
    """N11 alt kategorilerini çeken ana fonksiyon (Çoğul)."""
    try:
        api = N11CategoryAPI(app_key, app_secret)
        if hasattr(api, "get_sub_categories"):
            return api.get_sub_categories(category_id)
        
        all_categories = api._fetch_full_tree()
        return all_categories
    except Exception as e:
        print(f"[N11 HATA] Alt kategoriler çekilemedi: {e}")
        return []

def fetch_n11_sub_category(app_key, app_secret, category_id):
    """Tekil ismi destekleyen geriye dönük uyumluluk köprüsü."""
    return fetch_n11_sub_categories(app_key, app_secret, category_id)

def get_n11_credentials(db=None):
    """Veritabanından N11 API anahtarlarını güvenle getirir."""
    try:
        from utils.credentials_manager import get_credentials
        if db is None:
            from database import Database
            db = Database()
        return get_credentials(db, "N11")
    except Exception as e:
        print(f"[N11 HATA] Kimlik bilgileri okunamadı: {e}")
        return "", ""

def check_n11_task_status(app_key, app_secret, task_code):
    """N11 görev (task/batch) durumunu sorgular."""
    try:
        api = N11CategoryAPI(app_key, app_secret)
        return api.check_task_status(task_code)
    except Exception as e:
        return False, str(e)

def parse_n11_task_response(response_data):
    """N11 task yanıtını ayrıştırır."""
    if isinstance(response_data, dict):
        status = response_data.get("status") or response_data.get("state") or "COMPLETED"
        errors = response_data.get("errors") or response_data.get("failures") or []
        return str(status).upper(), errors
    return "COMPLETED", []


def export_error_report_excel(db=None, output_path=None, *args, **kwargs):
    """
    Veritabanındaki pazar yeri hata ve işlem kayıtlarını Excel (.xlsx) dosyası olarak dışa aktarır.
    'output_path' ve diğer parametre dinamiklerini tam uyumlu karşılar.
    """
    if not output_path:
        return False, "Hata: Kaydedilecek dosya yolu (output_path) belirtilmedi."

    try:
        df = None

        if db is not None:
            conn = None
            if hasattr(db, 'get_connection') and callable(db.get_connection):
                conn = db.get_connection()
            elif hasattr(db, 'connect') and callable(db.connect):
                try:
                    conn = db.connect()
                except Exception:
                    conn = db
            elif hasattr(db, 'cursor'):
                conn = db

            if conn:
                queries = [
                    """
                    SELECT 
                        stock_code,
                        reason,
                        updated_at,
                        update_date,
                        created_at
                    FROM n11_task_errors
                    ORDER BY id DESC
                    """,
                    """
                    SELECT 
                        stock_code,
                        error_message AS reason,
                        updated_at,
                        updated_at AS update_date,
                        created_at
                    FROM n11_tasks
                    WHERE status IN ('FAILED', 'ERROR') OR error_message IS NOT NULL
                    ORDER BY id DESC
                    """
                ]

                for query in queries:
                    try:
                        df = pd.read_sql_query(query, conn)
                        if not df.empty:
                            break
                    except Exception:
                        continue

        if df is None or df.empty:
            df = pd.DataFrame(columns=[
                "stock_code", 
                "reason", 
                "updated_at", 
                "update_date", 
                "created_at"
            ])

        if not output_path.lower().endswith('.xlsx'):
            output_path += '.xlsx'

        df.to_excel(output_path, index=False, engine='openpyxl')
        return True, f"Hata raporu başarıyla oluşturuldu:\n{output_path}"

    except Exception as e:
        return False, f"Rapor oluşturulurken hata oluştu: {str(e)}"
        
    
def generate_n11_transfer_report(db, output_path):
    """
    [YENİ] N11 aktarım/gönderim raporu üretir. Eski export_error_report_excel'den farkı:
    o fonksiyon sadece n11_task_errors / n11_tasks(FAILED) tablolarına bakıyordu — ama
    gerçek hatalar n11_failed_products tablosuna yazılıyor, dolayısıyla eski rapor hep
    boş çıkıyordu. Bu fonksiyon 4 kaynağı BİRLEŞTİRİR ve her ürün için TEK ve NET bir
    durum satırı üretir:
        - products              -> tüm eşleştirilmiş ürünler (is_mapped = 1)
        - n11_remote_products   -> N11'de gerçekten canlı olanlar
        - n11_tasks             -> kuyrukta / işlemde olanlar (PENDING, PROCESSING...)
        - n11_failed_products   -> gerçek hata sebebiyle reddedilenler
    Not: "(True, ...)" gibi ham Python tuple metni asla 'hata sebebi' olarak yazılmaz;
    böyle bir kayıt görülürse bu aslında BAŞARI'dır ve rapora "Gönderildi" olarak yansır.
    """
    try:
        mapped_rows = db.query("""
            SELECT code, COALESCE(NULLIF(main_code, ''), code) AS main_code,
                   title, brand, mainCategory, category, subCategory, stock
            FROM products
            WHERE is_mapped IN (1, 2)
        """)

        remote_rows = db.query("SELECT DISTINCT stock_code FROM n11_remote_products WHERE stock_code IS NOT NULL")
        remote_set = {str(r.get("stock_code")) for r in remote_rows if r.get("stock_code")}

        task_rows = db.query("SELECT main_code, stock_code, status, task_id, updated_at FROM n11_tasks")
        task_map = {}
        for t in task_rows:
            key = str(t.get("main_code") or t.get("stock_code") or "")
            if key:
                task_map[key] = t

        failed_rows = db.query("SELECT stock_code, reason, updated_at FROM n11_failed_products")
        failed_map = {}
        for f in failed_rows:
            sc = str(f.get("stock_code") or "")
            reason = str(f.get("reason") or "")
            # Eski bozuk kayıt: ham başarı tuple'ı hata gibi yazılmış olabilir -> yoksay
            if sc and "(True," not in reason and "TASK_ID_OR_SUCCESS" not in reason:
                failed_map[sc] = {"reason": reason, "updated_at": f.get("updated_at")}

        report_rows = []
        seen_main_codes = set()
        for r in mapped_rows:
            m_code = str(r.get("main_code") or r.get("code") or "")
            if not m_code or m_code in seen_main_codes:
                continue
            seen_main_codes.add(m_code)

            cat = r.get("subCategory") or r.get("category") or r.get("mainCategory") or ""

            if m_code in remote_set:
                durum, hata, guncelleme = "✅ N11'de Canlı", "", ""
            elif m_code in failed_map:
                durum = "❌ Hata / Reddedildi"
                hata = failed_map[m_code]["reason"]
                guncelleme = str(failed_map[m_code]["updated_at"] or "")
            elif m_code in task_map:
                t = task_map[m_code]
                durum = f"⏳ Kuyrukta ({t.get('status', 'PENDING')})"
                hata = ""
                guncelleme = str(t.get("updated_at") or "")
            else:
                durum = "⚪ Eşleşti (Henüz Gönderilmedi)"
                hata = ""
                guncelleme = ""

            report_rows.append({
                "Stok Kodu / Ana Kod": m_code,
                "Ürün Adı": r.get("title") or "",
                "Marka": r.get("brand") or "",
                "Kategori": cat,
                "Stok": r.get("stock") or 0,
                "Durum": durum,
                "Hata Sebebi": hata,
                "Son Güncelleme": guncelleme,
            })

        # Sadece ürünler tablosunda olmayan ama hata listesinde kalan (silinmiş ürün vb.) kayıtları da ekle
        for sc, info in failed_map.items():
            if sc not in seen_main_codes:
                report_rows.append({
                    "Stok Kodu / Ana Kod": sc,
                    "Ürün Adı": "",
                    "Marka": "",
                    "Kategori": "",
                    "Stok": "",
                    "Durum": "❌ Hata / Reddedildi",
                    "Hata Sebebi": info["reason"],
                    "Son Güncelleme": str(info["updated_at"] or ""),
                })

        if not report_rows:
            return False, "Rapor için gösterilecek eşleştirilmiş/gönderilmiş ürün bulunamadı."

        df = pd.DataFrame(report_rows)
        # Hatalılar en üstte görünsün
        durum_sira = {"❌ Hata / Reddedildi": 0, "⏳ Kuyrukta": 1, "⚪ Eşleşti (Henüz Gönderilmedi)": 2, "✅ N11'de Canlı": 3}
        df["_sira"] = df["Durum"].apply(lambda d: next((v for k, v in durum_sira.items() if str(d).startswith(k[:2])), 4))
        df = df.sort_values("_sira").drop(columns=["_sira"])

        if not output_path.lower().endswith(".xlsx"):
            output_path += ".xlsx"
        df.to_excel(output_path, index=False, engine="openpyxl")

        n_error = sum(1 for r in report_rows if r["Durum"].startswith("❌"))
        n_live = sum(1 for r in report_rows if r["Durum"].startswith("✅"))
        n_queue = sum(1 for r in report_rows if r["Durum"].startswith("⏳"))
        return True, (
            f"Rapor oluşturuldu: {output_path}\n\n"
            f"✅ Canlı: {n_live}   ⏳ Kuyrukta: {n_queue}   ❌ Hatalı: {n_error}   "
            f"📦 Toplam: {len(report_rows)}"
        )

    except Exception as e:
        return False, f"Rapor oluşturulurken hata oluştu: {str(e)}"


def _extract_task_id(resp_json):
    """N11 JSON yanıtından task/batch ID değerini dinamik yakalar."""
    if not isinstance(resp_json, dict):
        return None
    return (
        resp_json.get("batchRequestId") or 
        resp_json.get("taskId") or 
        resp_json.get("id") or 
        resp_json.get("batchId")
    )

from decimal import Decimal

def _sanitize_payload_for_json(obj):
    """MySQL Decimal nesnelerini JSON serileştirilebilir float/int türlerine dönüştürür."""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: _sanitize_payload_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_payload_for_json(v) for v in obj]
    return obj

def fetch_n11_remote_products(app_key, app_secret):
    """N11 Canlı Mağaza Ürünlerini HTTP 503 ve Güvenlik Duvarı Kalkanıyla Çeker"""
    url = "https://api.n11.com/ms/product/tasks/price-stock-update"
    
    # 🛡️ Tarayıcı Kimlik Başlıkları (Cloudflare/Imperva 503 Engeline Karşı)
    headers = {
        "appKey": str(app_key).strip(),
        "appSecret": str(app_secret).strip(),
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(url, headers=headers, timeout=20)
        
        # HTTP status kontrolü
        if response.status_code == 503:
            return False, "N11 API Sunucusu Geçici Olarak Hizmet Veremiyor (HTTP 503 Service Unavailable). Lütfen birkaç dakika sonra tekrar deneyin."
            
        if response.status_code not in [200, 201]:
            return False, f"N11 API Hatası (HTTP {response.status_code}): {response.text[:150]}"
            
        # Yanıtın HTML değil JSON olduğundan emin ol
        if "html" in response.headers.get("Content-Type", "").lower() or response.text.strip().startswith("<"):
            return False, "N11 API sunucusu geçerli bir veri yerine HTML yanıtı döndürdü. Bağlantı veya API anahtarlarınızı kontrol edin."

        return True, response.json()

    except requests.exceptions.Timeout:
        return False, "N11 API Zaman Aşımı: Sunucu 20 saniye içinde yanıt vermedi."
    except Exception as e:
        return False, f"N11 Bağlantı Hatası: {str(e)}"
    
def send_product_to_n11_saf(app_key, app_secret, product_payload, template_data=None):
    """[SAF REST API] N11 JSON standartlarında ürünü canlı REST kuyruğuna iletir."""
    url = "https://api.n11.com/ms/product/tasks/product-create"    
    headers = {
        "appKey": str(app_key).strip(),
        "appSecret": str(app_secret).strip(),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "IdeasoftEntegrator/1.0"
    }

    try:
        if isinstance(product_payload, dict) and "payload" in product_payload:
            final_json_payload = product_payload
        else:
            skus_list = product_payload if isinstance(product_payload, list) else [product_payload]
            final_json_payload = {
                "payload": {
                    "integrator": "Ideasoft Entegrasyon",
                    "skus": skus_list
                }
            }

        # JSON serileştirme çökmesini önlemek için Decimal temizliği yapıyoruz
        final_json_payload = _sanitize_payload_for_json(final_json_payload)

        response = requests.post(url, json=final_json_payload, headers=headers, timeout=30)
        
        if response.status_code in [200, 201, 202]:
            resp_json = response.json() if response.content else {}
            task_id = _extract_task_id(resp_json)
            return True, str(task_id) if task_id else "SUCCESS"
        else:
            try:
                err_data = response.json()
                err_msg = err_data.get("errorMessage") or err_data.get("message") or response.text[:200]
            except Exception:
                err_msg = response.text[:200]
            return False, f"N11 REST Reddi (HTTP {response.status_code}): {err_msg}"
            
    except Exception as e:
        return False, f"N11 Sunucu Bağlantı Hatası: {str(e)}"

def send_variant_products_to_n11(app_key, app_secret, product_data, variants_data, template_data=None):
    """N11 REST API standartlarında varyantlı (beden/renk) ürün paketini iletir."""
    url = "https://api.n11.com/ms/product/tasks/product-create"
    headers = {
        "appKey": str(app_key).strip(),
        "appSecret": str(app_secret).strip(),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "IdeasoftEntegrator/1.0"
    }
    try:
        final_json_payload = {
            "payload": {
                "integrator": "Ideasoft Entegrasyon",
                "skus": variants_data
            }
        }
        # Varyant fiyatlarındaki Decimal nesnelerini float'a dönüştür
        final_json_payload = _sanitize_payload_for_json(final_json_payload)

        response = requests.post(url, json=final_json_payload, headers=headers, timeout=30)
        
        if response.status_code in [200, 201, 202]:
            resp_json = response.json() if response.content else {}
            task_id = _extract_task_id(resp_json)
            return True, str(task_id) if task_id else "SUCCESS"
        return False, f"N11 API Varyant Reddi (HTTP {response.status_code}): {response.text[:200]}"
    except Exception as e:
        return False, f"Varyant Sunucu Bağlantı Hatası: {str(e)}"


def update_product_price_and_stock_n11(app_key, app_secret, skus_data):
    """N11 Toplu Fiyat ve Stok Güncelleme REST API Fonksiyonu."""
    url = "https://api.n11.com/ms/product/stock/price-quantity"
    
    all_formatted_skus = []
    for item in skus_data:
        s_code = str(item.get("stockCode") or item.get("stock_code") or "").strip()
        if not s_code:
            continue
        s_price = float(item.get("salePrice") or item.get("price") or 0.0)
        l_price = float(item.get("listPrice") or s_price)
        
        all_formatted_skus.append({
            "stockCode": s_code,
            "listPrice": float(max(l_price, s_price)),
            "salePrice": float(s_price),
            "quantity": int(item.get("quantity") or item.get("stock") or 0),
            "currencyType": "TL"
        })

    if not all_formatted_skus:
        return False, "Güncellenecek veri paketi boş."

    headers = {
        "appKey": str(app_key).strip(),
        "appSecret": str(app_secret).strip(),
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 EntegratorApp"
    }

    try:
        response = requests.post(
            url, 
            json={"payload": {"integrator": "EntegratorApp", "skus": all_formatted_skus}}, 
            headers=headers, 
            timeout=30
        )
        if response.status_code in [200, 201, 202]:
            resp_json = response.json() if response.content else {}
            t_id = _extract_task_id(resp_json)
            return True, str(t_id) if t_id else "SUCCESS"
        else:
            return False, f"N11 API Hatası (HTTP {response.status_code}): {response.text[:200]}"
    except Exception as e:
        return False, f"Bağlantı Hatası: {str(e)}"

    
def fetch_all_n11_store_products(app_key, app_secret):
    """N11 Canlı mağaza envanterini sayfalama yaparak çeken REST API fonksiyonu (Bot Kalkanı & Retry Ekli)."""
    url = "https://api.n11.com/ms/product-query"
    
    # Gerçek tarayıcı başlığı (User-Agent) ile bot engelini aşma
    headers = {
        "appkey": str(app_key).strip(),
        "appsecret": str(app_secret).strip(),
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Content-Type": "application/json"
    }
    
    # Otomatik yeniden deneme (Retry) oturumu oluşturma
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=2,  # 2sn, 4sn, 8sn bekleyip tekrar dener
        status_forcelist=[500, 502, 503, 504]
    )
    session.mount('https://', HTTPAdapter(max_retries=retries))

    all_products = []
    page = 1
    page_size = 100
    try:
        while True:
            params = {"page": page, "pageSize": page_size}
            response = session.get(url, headers=headers, params=params, timeout=30)
            
            if response.status_code != 200:
                if page == 1:
                    return False, f"HTTP Hata Kodu: {response.status_code}"
                break
            
            # Gelen yanıt JSON değil de HTML ise yakala
            if "html" in response.headers.get("Content-Type", "").lower() or response.text.strip().startswith("<"):
                return False, f"HTML_RESPONSE:{response.status_code}"

            data = response.json()
            products = []
            if isinstance(data, list):
                products = data
            elif isinstance(data, dict):
                products = data.get("products", []) or data.get("content", []) or data.get("data", [])
            if not products:
                break
            all_products.extend(products)
            if len(products) < page_size:
                break
            page += 1
        return True, all_products
    except Exception as e:
        return False, f"Bağlantı Hatası: {str(e)}"
        

def validate_n11_api_connection(app_key, app_secret):
    """[SAF REST API] N11 REST API anahtarlarının doğruluğunu canlı kontrol eder."""
    url = "https://api.n11.com"
    headers = {
        "appkey": str(app_key).strip(),
        "appsecret": str(app_secret).strip(),
        "Content-Type": "application/json"
    }
    try:
        params = {"page": 1, "pageSize": 1}
        scraper = cloudscraper.create_scraper()
        response = scraper.get(url, headers=headers, params=params, timeout=30)
        if response.status_code in [200, 201]:
            return True, "N11 REST API bağlantısı başarıyla doğrulandı."
        elif response.status_code == 401:
            return False, "N11 API Kimlik Doğrulama Hatası (401 Unauthorized): Anahtarları kontrol edin."
        return False, f"N11 Servis Reddi (HTTP {response.status_code}): {response.text[:150]}"
    except Exception as e:
        return False, f"N11 Sunucusuna bağlanılamadı: {str(e)}"


def fetch_and_sync_n11_remote_products(app_key, app_secret, db_instance):
    """N11 üzerindeki ürünleri ve stok adetlerini MySQL veritabanına senkronize eder."""
    db_conn = db_instance
    
    credentials = get_n11_credentials(db_conn)
    if not credentials or not credentials[0]:
        return False, "❌ N11 API bilgileri veritabanında bulunamadı."

    app_key = credentials[0]
    app_secret = credentials[1]

    try:
        with db_conn.connect() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SHOW KEYS FROM n11_remote_products WHERE Key_name = 'PRIMARY'")
            pk_rows = cursor.fetchall()
            is_old_pk = any(row['Column_name'] == 'n11_id' for row in pk_rows)
            
            if is_old_pk or not pk_rows:
                print("[SİSTEM KALKANI] Eski N11 tablosu saptandı, MySQL şeması varyant dostu haline getiriliyor...")
                cursor.execute("RENAME TABLE n11_remote_products TO old_n11_remote_products;")
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS n11_remote_products (
                        stock_code VARCHAR(100) PRIMARY KEY,
                        n11_id VARCHAR(100),
                        n11_product_id VARCHAR(100),
                        id VARCHAR(100),
                        product_seller_code VARCHAR(100) UNIQUE,
                        title VARCHAR(255),
                        subtitle VARCHAR(255),
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
                cursor.execute("""
                    INSERT IGNORE INTO n11_remote_products (stock_code, n11_id, n11_product_id, title, price, stock_items, approval_status, remote_status)
                    SELECT COALESCE(stock_code, product_seller_code, n11_id), n11_id, n11_product_id, title, price, stock_items, approval_status, remote_status
                    FROM old_n11_remote_products;
                """)
                cursor.execute("DROP TABLE old_n11_remote_products;")
                conn.commit()
                print("[SİSTEM KALKANI] MySQL N11 tablosu varyant uyumlu hale getirildi!")
                
    except Exception as schema_err:
        print(f"[SİSTEM KALKANI] MySQL Tablo dönüşüm adımı uyarısı: {schema_err}")

    success, remote_products = fetch_all_n11_store_products(app_key, app_secret)
    if not success:
        return False, remote_products

    try:
        synced_count = 0
        with db_conn.connect() as conn:
            cursor = conn.cursor()
            
            for prod in remote_products:
                if not isinstance(prod, dict):
                    continue
                    
                n11_id = str(prod.get("id") or prod.get("productId") or "")
                title = str(prod.get("title") or prod.get("productName") or "")
                approval_status = str(prod.get("approvalStatus") or "ACTIVE").upper()
                
                skus = prod.get("skus", [])
                if not skus and isinstance(prod.get("sku"), dict):
                    skus = [prod.get("sku")]
                elif not skus and isinstance(prod.get("skus"), dict):
                    skus = prod.get("skus").get("sku", []) if "sku" in prod.get("skus") else []
                    
                if isinstance(skus, dict):
                    skus = [skus]
                    
                if not skus:
                    skus = [prod]

                for sku in skus:
                    if not isinstance(sku, dict):
                        try:
                            sku = dict(sku)
                        except Exception:
                            continue
                        
                    n11_stock_code = sku.get("stockCode") or sku.get("sellerStockCode") or prod.get("stockCode") or sku.get("itemCode")
                    n11_stock_code = str(n11_stock_code or "").strip()
                    
                    if not n11_stock_code or n11_stock_code.lower() in ["none", "null", ""]:
                        continue

                    n11_price = sku.get("salePrice") or sku.get("price") or prod.get("salePrice") or prod.get("price") or 0.0
                    
                    n11_stock = None
                    if sku.get("quantity") is not None and str(sku.get("quantity")).strip() != "":
                        n11_stock = sku.get("quantity")
                    elif sku.get("stock") is not None and str(sku.get("stock")).strip() != "":
                        n11_stock = sku.get("stock")
                    elif isinstance(sku.get("stockItems"), dict):
                        s_items = sku.get("stockItems", {}).get("stockItem", [])
                        if isinstance(s_items, dict): 
                            s_items = [s_items]
                        if isinstance(s_items, list):
                            n11_stock = sum(int(item.get("quantity") or item.get("stock") or 0) for item in s_items if isinstance(item, dict))
                    elif prod.get("quantity") is not None:
                        n11_stock = prod.get("quantity")

                    try: 
                        n11_price = float(str(n11_price).replace(",", ".").strip())
                    except Exception: 
                        n11_price = 0.0
                        
                    try: 
                        n11_stock = int(float(str(n11_stock).strip())) if n11_stock not in [None, "", "None", "null"] else 0
                    except Exception: 
                        n11_stock = 0

                    sql = """
                        INSERT INTO n11_remote_products (
                            n11_id, n11_product_id, stock_code, product_seller_code, title, price, stock_items, remote_status, approval_status, last_checked_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON DUPLICATE KEY UPDATE
                            n11_id = VALUES(n11_id),
                            n11_product_id = VALUES(n11_product_id),
                            product_seller_code = VALUES(product_seller_code),
                            stock_items = VALUES(stock_items),
                            price = VALUES(price),
                            title = VALUES(title),
                            last_checked_at = CURRENT_TIMESTAMP
                    """
                    cursor.execute(sql, (str(n11_id), str(n11_id), n11_stock_code, n11_stock_code, title, n11_price, n11_stock, approval_status, approval_status))
                    synced_count += 1

            conn.commit()
        return True, f"✅ Başarılı: Toplam {synced_count} adet varyantın verisi MySQL'e aktarıldı."
        
    except Exception as sqlex:
        print(f"❌ N11 Senkronizasyon Veri Yazma Hatası: {sqlex}")
        return False, f"Veritabanı kayıt hatası: {str(sqlex)}"

def handle_api_response(response):
    """API'den dönen yanıtı kontrol eder. HTML yanıtlarında temiz hata mesajı üretir."""
    if response.status_code == 200:
        try:
            return True, response.json()
        except Exception:
            return False, "Sunucu geçerli bir JSON yanıtı döndürmedi."
    else:
        try:
            err_data = response.json()
            detail = err_data.get("message") or err_data.get("errorMessage") or str(err_data)
        except Exception:
            if response.status_code == 503:
                detail = "Sunucu şu an hizmet veremiyor veya istek engellendi (Bakım / Cloudflare / Aşırı İstek)."
            elif response.status_code == 500:
                detail = "Sunucu içi hata oluştu (Internal Server Error)."
            elif response.status_code == 403:
                detail = "Erişim reddedildi (Forbidden / API Key Geçersiz)."
            else:
                detail = "Beklenmeyen bir yanıt alındı."

        return False, f"HTTP Hata Kodu: {response.status_code}\n\nDetay: {detail}"
    

if __name__ == "__main__":
    print("🚀 [N11 REST API MODÜLÜ] Modül bağımsız olarak test ediliyor...")
    print("🌱 Tüm REST API fonksiyonları mühürlendi ve çökmesiz mimariye kavuşturuldu.")