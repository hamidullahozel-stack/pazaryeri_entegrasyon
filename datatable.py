# Dosya: ui/datatable.py
# İşlem Tarihi: 14 Eylül 2026

import customtkinter as ctk
from tkinter import ttk

class DataTable(ctk.CTkFrame):
    def __init__(self, master, columns, **kwargs):
        # CustomTkinter tarafından desteklenmeyen argümanları ayıklıyoruz
        kwargs.pop("on_double_click", None)
        
        super().__init__(master, **kwargs)
        self.columns = columns

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Treeview ve Scrollbar bileşenleri
        self.tree_frame = ctk.CTkFrame(self)
        self.tree_frame.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        self.tree_frame.grid_rowconfigure(0, weight=1)
        self.tree_frame.grid_columnconfigure(0, weight=1)

        col_ids = [col[0] for col in columns]
        self.tree = ttk.Treeview(self.tree_frame, columns=col_ids, show="headings")

        for col_id, col_name, width, anchor in columns:
            self.tree.heading(col_id, text=col_name)
            self.tree.column(col_id, width=width, anchor=anchor)

        scrollbar_y = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        scrollbar_x = ttk.Scrollbar(self.tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        scrollbar_x.grid(row=1, column=0, sticky="ew")

    def set_data(self, rows):
        for item in self.tree.get_children():
            self.tree.delete(item)

        for row in rows:
            values = [row.get(col[0], "") for col in self.columns]
            self.tree.insert("", "end", values=values)

    def set_rows(self, rows):
        """TemplateFrame ve diğer ekranlar ile uyumluluk için set_data fonksiyonunun takma adıdır."""
        self.set_data(rows)