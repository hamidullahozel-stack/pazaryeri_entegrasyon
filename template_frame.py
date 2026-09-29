# Dosya: template_frame.py
# İşlem Tarihi: 16 Eylül 2026 / Tamamlanmış ve Eksiksiz Sürüm

from datetime import datetime, timedelta

import customtkinter as ctk
from tkinter import messagebox

from app_logging import get_logger

log = get_logger("templates")

PREP_OPTIONS = ["Seciniz", "1 Gun", "2 Gun", "3 Gun", "4 Gun", "5 Gun", "7 Gun", "10 Gun"]
DELIVERY_OPTIONS = ["Seciniz", "Varsayilan Teslimat", "Ucretsiz Kargo", "Alici Oder"]
PRICE_FIELDS = ["Fiyat 1", "Fiyat 2", "Fiyat 3", "Fiyat 4", "Fiyat 5"]
OPERATORS = ["x", "+", "-"]


def _valid_date(text: str) -> bool:
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return True
    except ValueError:
        return False


class N11TemplateWindow(ctk.CTkToplevel):
    def __init__(self, parent, db, template_id=None, on_save_callback=None):
        super().__init__(parent)
        self.db = db
        self.template_id = template_id
        self.on_save_callback = on_save_callback

        is_edit = template_id is not None
        self.title("N11 Sablon Duzenle" if is_edit else "Yeni N11 Sablon Olustur")
        self.geometry("540x760")
        self.resizable(False, False)
        self.lift()
        self.focus_force()
        self.grab_set()

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=15, pady=15)
        self.main_scroll = scroll

        def label(text):
            ctk.CTkLabel(scroll, text=text,
                         font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(5, 2))

        label("Sablon Ismi:")
        self.ent_name = ctk.CTkEntry(scroll, placeholder_text="Orn: Giyim Sablonu (%20)", width=480)
        self.ent_name.pack(pady=(0, 10))

        label("Kargo Hazirlik Suresi:")
        self.combo_prep = ctk.CTkComboBox(scroll, values=PREP_OPTIONS, width=480)
        self.combo_prep.set("Seciniz")
        self.combo_prep.pack(pady=(0, 10))

        label("Teslimat Sablonu:")
        self.combo_delivery = ctk.CTkComboBox(scroll, values=DELIVERY_OPTIONS, width=480)
        self.combo_delivery.set("Seciniz")
        self.combo_delivery.pack(pady=(0, 10))

        label("Satis Fiyati:")
        price_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        price_frame.pack(fill="x", pady=(0, 10))
        self.combo_price_field = ctk.CTkComboBox(price_frame, values=PRICE_FIELDS, width=150)
        self.combo_price_field.set("Fiyat 1")
        self.combo_price_field.pack(side="left", padx=(0, 10))
        self.combo_operator = ctk.CTkComboBox(price_frame, values=OPERATORS, width=100)
        self.combo_operator.set("x")
        self.combo_operator.pack(side="left", padx=(0, 10))
        self.ent_price_value = ctk.CTkEntry(price_frame, width=200)
        self.ent_price_value.insert(0, "1")
        self.ent_price_value.pack(side="left")

        label("Indirim Orani (%):")
        self.ent_discount = ctk.CTkEntry(scroll, width=480)
        self.ent_discount.insert(0, "0")
        self.ent_discount.pack(pady=(0, 10))

        date_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        date_frame.pack(fill="x", pady=(0, 10))
        left = ctk.CTkFrame(date_frame, fg_color="transparent")
        left.pack(side="left", expand=True, fill="x", padx=(0, 5))
        ctk.CTkLabel(left, text="Indirim Baslangic (YYYY-AA-GG):",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(5, 2))
        self.ent_start_date = ctk.CTkEntry(left, width=230)
        self.ent_start_date.insert(0, datetime.now().strftime("%Y-%m-%d"))
        self.ent_start_date.pack(fill="x")

        right = ctk.CTkFrame(date_frame, fg_color="transparent")
        right.pack(side="right", expand=True, fill="x", padx=(5, 0))
        ctk.CTkLabel(right, text="Indirim Bitis (YYYY-AA-GG):",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(5, 2))
        self.ent_end_date = ctk.CTkEntry(right, width=230)
        self.ent_end_date.insert(0, (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"))
        self.ent_end_date.pack(fill="x")

        label("Maksimum Satin Alma Sayisi:")
        self.ent_max_purchase = ctk.CTkEntry(scroll, width=480)
        self.ent_max_purchase.insert(0, "99")
        self.ent_max_purchase.pack(pady=(0, 15))

        btn_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(10, 0))
        ctk.CTkButton(btn_frame, text="Kapat", fg_color="#ef4444", width=120,
                      command=self.destroy).pack(side="right", padx=(10, 0))
        ctk.CTkButton(btn_frame, text="Guncelle" if is_edit else "Kaydet",
                      fg_color="#84cc16", text_color="black",
                      font=ctk.CTkFont(weight="bold"), width=120,
                      command=self.save_template).pack(side="right")

        if is_edit:
            self.load_template_data()

    def load_template_data(self):
        try:
            row = self.db.query_one(
                """SELECT name, prep_time, delivery_template, price_field, operator,
                          price_value, discount_rate, start_date, end_date, max_purchase
                   FROM templates WHERE id = ?""",
                (self.template_id,),
            )
            if not row:
                messagebox.showwarning("Uyari", "Sablon bulunamadi (silinmis olabilir).")
                self.destroy()
                return

            self.ent_name.delete(0, "end"); self.ent_name.insert(0, row["name"] or "")
            if row["prep_time"]:
                self.combo_prep.set(row["prep_time"])
            if row["delivery_template"]:
                self.combo_delivery.set(row["delivery_template"])
            if row["price_field"]:
                self.combo_price_field.set(row["price_field"])
            if row["operator"]:
                self.combo_operator.set(row["operator"])

            self.ent_price_value.delete(0, "end")
            self.ent_price_value.insert(0, str(row["price_value"] if row["price_value"] is not None else 1.0))
            self.ent_discount.delete(0, "end")
            self.ent_discount.insert(0, str(row["discount_rate"] if row["discount_rate"] is not None else 0.0))
            if row["start_date"]:
                self.ent_start_date.delete(0, "end"); self.ent_start_date.insert(0, row["start_date"])
            if row["end_date"]:
                self.ent_end_date.delete(0, "end"); self.ent_end_date.insert(0, row["end_date"])
            self.ent_max_purchase.delete(0, "end")
            self.ent_max_purchase.insert(0, str(row["max_purchase"] if row["max_purchase"] is not None else 99))
        except Exception as e:
            log.exception("Sablon verisi yuklenemedi")
            messagebox.showerror("Hata", f"Sablon yuklenemedi:\n{e}")

    def save_template(self):
        name = self.ent_name.get().strip()
        if not name:
            messagebox.showwarning("Uyari", "Sablon ismi bos birakilamaz!")
            return

        start_date = self.ent_start_date.get().strip()
        end_date = self.ent_end_date.get().strip()
        for label_text, value in (("Baslangic", start_date), ("Bitis", end_date)):
            if value and not _valid_date(value):
                messagebox.showwarning("Uyari", f"{label_text} tarihi YYYY-AA-GG formatinda olmali.")
                return
        if start_date and end_date and start_date > end_date:
            messagebox.showwarning("Uyari", "Baslangic tarihi bitis tarihinden sonra olamaz.")
            return

        def _float(entry, default):
            try:
                return float(entry.get().strip().replace(",", "."))
            except ValueError:
                return default

        price_val = _float(self.ent_price_value, 1.0)
        discount = _float(self.ent_discount, 0.0)
        try:
            max_purchase = int(self.ent_max_purchase.get().strip())
        except ValueError:
            max_purchase = 99

        params = (name, self.combo_prep.get(), self.combo_delivery.get(),
                  self.combo_price_field.get(), self.combo_operator.get(),
                  price_val, discount, start_date, end_date, max_purchase)

        try:
            if self.template_id:
                self.db.execute(
                    """UPDATE templates SET name=?, prep_time=?, delivery_template=?,
                       price_field=?, operator=?, price_value=?, discount_rate=?,
                       start_date=?, end_date=?, max_purchase=? WHERE id=?""",
                    (*params, self.template_id),
                )
            else:
                self.db.execute(
                    """INSERT INTO templates
                       (name, prep_time, delivery_template, price_field, operator,
                        price_value, discount_rate, start_date, end_date, max_purchase)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    params,
                )
        except Exception as e:
            if "UNIQUE" in str(e).upper():
                messagebox.showerror("Hata", f"'{name}' isimli bir sablon zaten var.")
            else:
                log.exception("Sablon kayit hatasi")
                messagebox.showerror("Hata", f"Kayit hatasi:\n{e}")
            return

        if self.on_save_callback:
            self.on_save_callback()
        self.destroy()


class TemplateManagementFrame(ctk.CTkFrame):
    def __init__(self, parent, db):
        super().__init__(parent, fg_color="transparent")
        self.db = db

        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.pack(fill="x", padx=15, pady=10)
        ctk.CTkLabel(top_bar, text="Kayıtlı Satış & Fiyat Şablonları",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        ctk.CTkButton(top_bar, text="Yeni Şablon Oluştur", fg_color="#1f538d",
                      command=self.open_add_template_popup).pack(side="right")

        # Başlık Bilgi Çubuğu
        header_bar = ctk.CTkFrame(self, fg_color=("#e5e7eb", "#2d3748"), height=35)
        header_bar.pack(fill="x", padx=15, pady=(5, 0))
        header_bar.pack_propagate(False)

        ctk.CTkLabel(header_bar, text="ID", font=ctk.CTkFont(size=12, weight="bold"), width=50, anchor="center").pack(side="left", padx=5)
        ctk.CTkLabel(header_bar, text="ŞABLON ADI", font=ctk.CTkFont(size=12, weight="bold"), width=180, anchor="w").pack(side="left", padx=5)
        ctk.CTkLabel(header_bar, text="KARGO SÜRESİ", font=ctk.CTkFont(size=12, weight="bold"), width=120, anchor="w").pack(side="left", padx=5)
        ctk.CTkLabel(header_bar, text="TESLİMAT", font=ctk.CTkFont(size=12, weight="bold"), width=140, anchor="w").pack(side="left", padx=5)
        ctk.CTkLabel(header_bar, text="FİYAT FORMÜLÜ", font=ctk.CTkFont(size=12, weight="bold"), width=140, anchor="w").pack(side="left", padx=5)
        ctk.CTkLabel(header_bar, text="İNDİRİM", font=ctk.CTkFont(size=12, weight="bold"), width=80, anchor="center").pack(side="left", padx=5)
        ctk.CTkLabel(header_bar, text="İŞLEMLER", font=ctk.CTkFont(size=12, weight="bold"), width=180, anchor="center").pack(side="right", padx=10)

        # Şablonların listeleneceği kaydırılabilir alan
        self.scroll_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll_frame.pack(fill="both", expand=True, padx=15, pady=10)

        self.load_templates()

    def open_add_template_popup(self):
        N11TemplateWindow(self, self.db, None, self.load_templates)

    def _edit_template(self, template_id):
        N11TemplateWindow(self, self.db, template_id=int(template_id), on_save_callback=self.load_templates)

    def _delete_template(self, template_id, template_name):
        if not messagebox.askyesno("Onay", f"'{template_name}' isimli şablonu silmek istediğinize emin misiniz?"):
            return
        try:
            self.db.execute("DELETE FROM templates WHERE id = ?", (int(template_id),))
            self.db.execute("UPDATE n11_category_mappings SET template_id = NULL WHERE template_id = ?",
                            (int(template_id),))
            self.load_templates()
        except Exception as e:
            log.exception("Şablon silme hatası")
            messagebox.showerror("Hata", f"Silinemedi:\n{e}")

    def load_templates(self):
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        try:
            rows = self.db.query("""
                SELECT id, name, prep_time, delivery_template, price_field, operator, price_value, discount_rate
                FROM templates
                ORDER BY id DESC
            """)
        except Exception as e:
            log.exception("Şablon listeleme hatası")
            ctk.CTkLabel(self.scroll_frame, text=f"Şablonlar yüklenemedi: {e}", text_color="#ef4444").pack(padx=10, pady=10)
            return

        if not rows:
            ctk.CTkLabel(self.scroll_frame, text="Kayıtlı şablon bulunamadı.", text_color="#9ca3af").pack(pady=20)
            return

        for r in rows:
            t_id = r["id"]
            t_name = r["name"] or ""
            t_prep = r["prep_time"] or "-"
            t_delivery = r["delivery_template"] or "-"
            t_formula = f"{r['price_field']} {r['operator']} {r['price_value']}"
            t_discount = f"%{r['discount_rate']}" if r['discount_rate'] else "%0"

            row_frame = ctk.CTkFrame(self.scroll_frame, fg_color=("#ffffff", "#1f2937"), height=42, corner_radius=6)
            row_frame.pack(fill="x", pady=4)
            row_frame.pack_propagate(False)

            ctk.CTkLabel(row_frame, text=str(t_id), width=50, anchor="center").pack(side="left", padx=5)
            ctk.CTkLabel(row_frame, text=t_name, width=180, anchor="w").pack(side="left", padx=5)
            ctk.CTkLabel(row_frame, text=t_prep, width=120, anchor="w").pack(side="left", padx=5)
            ctk.CTkLabel(row_frame, text=t_delivery, width=140, anchor="w").pack(side="left", padx=5)
            ctk.CTkLabel(row_frame, text=t_formula, width=140, anchor="w").pack(side="left", padx=5)
            ctk.CTkLabel(row_frame, text=t_discount, width=80, anchor="center").pack(side="left", padx=5)

            btn_del = ctk.CTkButton(
                row_frame, text="Sil", fg_color="#ef4444", hover_color="#dc2626", width=60, height=28,
                command=lambda tid=t_id, tn=t_name: self._delete_template(tid, tn)
            )
            btn_del.pack(side="right", padx=5)

            btn_edit = ctk.CTkButton(
                row_frame, text="Düzenle", fg_color="#3b82f6", hover_color="#2563eb", width=70, height=28,
                command=lambda tid=t_id: self._edit_template(tid)
            )
            btn_edit.pack(side="right", padx=5)