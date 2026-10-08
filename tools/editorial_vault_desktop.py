"""Selective desktop publishing for the permanent editorial vault."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import queue
import threading


DEFAULT_ROOT = Path("D:/Codex/work/edabalans-materials")
STATUS_LABELS = {
    "clean": "Без изменений",
    "changed": "Изменён",
    "conflict": "Конфликт — нужна сверка",
    "unsupported": "Публикация через Codex",
    "invalid": "Ошибка разметки — исправьте файл",
}


class SelectionController:
    """Keep explicit publishing selection separate from the visible filter."""

    def __init__(self, vault):
        self.vault = vault
        self.items = []

    def reload(self):
        self.items = list(self.vault.status())
        return self.items

    def visible(self, include_clean=False):
        return [item for item in self.items if include_clean or item["status"] != "clean"]

    def all_changed(self):
        return [item["id"] for item in self.items if item["status"] == "changed"]

    def publish_selected(self, selected_ids):
        selected = set(selected_ids)
        known = {item["id"]: item for item in self.items}
        if not selected:
            raise ValueError("Выберите изменённые материалы для публикации.")
        if selected - known.keys():
            raise ValueError("Список материалов изменился. Обновите его и выберите заново.")
        blocked = [known[item_id]["title"] for item_id in selected
                   if known[item_id]["status"] != "changed"]
        if blocked:
            raise ValueError("Нельзя опубликовать выбранные материалы: " + ", ".join(sorted(blocked)))
        ids = [item["id"] for item in self.items if item["id"] in selected]
        return self.vault.publish(ids, owner_edited=True)


def format_results(results):
    if results is None:
        return "Операция завершена."
    if isinstance(results, dict):
        results = [results]
    lines = []
    for result in results:
        if isinstance(result, dict):
            label = result.get("title") or result.get("id") or "Материал"
            status = result.get("status", "")
            message = result.get("error") or result.get("message") or ""
            lines.append(" — ".join(str(value) for value in (label, status, message) if value))
        else:
            lines.append(str(result))
    return "\n".join(lines) or "Нет изменений."


class DesktopApp:
    def __init__(self, window, vault, root):
        import tkinter as tk
        from tkinter import ttk

        self.window = window
        self.root = Path(root)
        self.controller = SelectionController(vault)
        self.events = queue.Queue()
        self.busy = False
        self.include_clean = tk.BooleanVar(value=False)
        window.title("Материалы — публикация изменений")
        window.geometry("1000x680")
        window.minsize(740, 480)
        panel = ttk.Frame(window, padding=12)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text=str(self.root)).pack(anchor="w")
        ttk.Label(panel, text="Выберите материалы. Публикуются только выбранные изменения.").pack(anchor="w", pady=(5, 10))
        toolbar = ttk.Frame(panel)
        toolbar.pack(fill="x", pady=(0, 10))
        self.controls = []
        for label, command in (
            ("Выбрать все изменённые", self.select_changed),
            ("Опубликовать выбранные", self.publish),
            ("Получить обновления с сервера", self.refresh),
            ("Открыть папку", self.open_folder),
        ):
            button = ttk.Button(toolbar, text=label, command=command)
            button.pack(side="left", padx=(0, 6))
            self.controls.append(button)
        checkbox = ttk.Checkbutton(panel, text="Показать также материалы без изменений", variable=self.include_clean, command=self.render)
        checkbox.pack(anchor="w", pady=(0, 6))
        self.controls.append(checkbox)
        table = ttk.Frame(panel)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=("title", "group", "status", "path"), show="headings", selectmode="extended")
        for key, label, width in (("title", "Материал", 240), ("group", "Раздел", 140), ("status", "Состояние", 200), ("path", "Файл", 300)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.notice = tk.StringVar(value="Читаю список материалов…")
        ttk.Label(panel, textvariable=self.notice).pack(anchor="w", pady=(10, 5))
        self.output = tk.Text(panel, height=8, wrap="word", state="disabled")
        self.output.pack(fill="x")
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.after(100, self.poll)
        self.run("Читаю список материалов…", self.controller.reload)

    def render(self):
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for item in self.controller.visible(self.include_clean.get()):
            self.tree.insert("", "end", iid=item["id"], values=(item["title"], item.get("group", ""), STATUS_LABELS.get(item["status"], item["status"]), item["path"]))
        self.tree.selection_set([item_id for item_id in selected if self.tree.exists(item_id)])

    def select_changed(self):
        self.tree.selection_set(self.controller.all_changed())

    def write(self, text):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("end", text)
        self.output.configure(state="disabled")

    def run(self, notice, operation):
        if self.busy:
            return
        self.busy = True
        self.notice.set(notice)
        for control in self.controls:
            control.configure(state="disabled")

        def worker():
            try:
                result = operation()
            except Exception as error:
                ok, result = False, str(error)
            else:
                ok = True
            try:
                self.controller.reload()
            except Exception as error:
                result = (format_results(result) if ok else str(result)) + "\nНе удалось перечитать список: " + str(error)
                ok = False
            self.events.put((ok, result))

        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            ok, result = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            for control in self.controls:
                control.configure(state="normal")
            self.render()
            self.notice.set("Готово. Результаты — ниже." if ok else "Ошибка. Подробности — ниже.")
            self.write(format_results(result) if ok else str(result))
        self.window.after(100, self.poll)

    def publish(self):
        selected = tuple(self.tree.selection())
        self.run("Публикую выбранные материалы…", lambda: self.controller.publish_selected(selected))

    def refresh(self):
        self.run("Получаю версии с сервера; локальные правки сохраняются…", self.controller.vault.refresh)

    def open_folder(self):
        try:
            os.startfile(self.root)
        except OSError as error:
            self.write(str(error))

    def close(self):
        if self.busy:
            self.notice.set("Дождитесь завершения текущей операции, затем закройте окно.")
        else:
            self.window.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    import tkinter as tk
    if __package__:
        from .editorial_vault import Vault
    else:
        from editorial_vault import Vault

    window = tk.Tk()
    DesktopApp(window, Vault(args.root), args.root)
    window.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
