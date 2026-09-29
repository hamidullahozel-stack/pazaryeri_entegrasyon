# Dosya: C:\entegrator52\test_worker.py
# İşlem Tarihi: 14 Eylül 2026

import time
from marketplaces.marketplace_task_worker import MarketplaceTaskWorker

def run_test():
    print("🚀 Marketplace Task Worker Testi Başlatılıyor...")
    
    # Worker'ı 5 saniye aralıkla çalışacak şekilde başlatıyoruz
    worker = MarketplaceTaskWorker(interval=5)
    worker.start()
    
    print("⏳ Worker arka planda çalışıyor. Test için 15 saniye bekleniyor...")
    try:
        time.sleep(15)
    except KeyboardInterrupt:
        pass
    
    print("🛑 Worker durduruluyor...")
    worker.stop()
    worker.join(timeout=2)
    print("✅ Test tamamlandı.")

if __name__ == "__main__":
    run_test()