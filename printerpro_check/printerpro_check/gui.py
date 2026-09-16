"""Tkinter GUI for the PrinterPro file checker.

Pick an order folder (or a parent folder of many order folders), run the
checks, watch progress in the log, then open the folder to grab the
corrected PDFs and the report.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .cli import _order_subfolders, _write_reports
from .report import render_text_report
from .validator import ValidatorConfig, validate_folder


def _open_in_file_manager(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception:
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PrinterPro bestandscontrole")
        self.geometry("760x560")
        self.minsize(640, 420)

        self.folder_var = tk.StringVar()
        self.batch_var = tk.BooleanVar(value=False)
        self.fix_var = tk.BooleanVar(value=True)
        self._log_queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._last_folder: Path | None = None

        self._build_ui()
        self.after(100, self._poll_log_queue)

    def _build_ui(self):
        pad = {"padx": 8, "pady": 6}

        top = ttk.Frame(self)
        top.pack(fill="x", **pad)

        ttk.Label(top, text="Ordermap:").pack(side="left")
        entry = ttk.Entry(top, textvariable=self.folder_var)
        entry.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(top, text="Bladeren...", command=self._browse).pack(side="left")

        opts = ttk.Frame(self)
        opts.pack(fill="x", **pad)
        ttk.Checkbutton(
            opts,
            text="Submappen verwerken (elke submap is een aparte order)",
            variable=self.batch_var,
        ).pack(side="left")
        ttk.Checkbutton(
            opts,
            text="Automatisch corrigeren (nieuwe *_corrected.pdf aanmaken)",
            variable=self.fix_var,
        ).pack(side="left", padx=(16, 0))

        actions = ttk.Frame(self)
        actions.pack(fill="x", **pad)
        self.run_btn = ttk.Button(actions, text="Controleren starten", command=self._run)
        self.run_btn.pack(side="left")
        self.open_btn = ttk.Button(
            actions, text="Map openen", command=self._open_folder, state="disabled"
        )
        self.open_btn.pack(side="left", padx=(8, 0))

        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", **pad)

        self.log = scrolledtext.ScrolledText(self, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, **pad)

    def _browse(self):
        chosen = filedialog.askdirectory(title="Kies de ordermap")
        if chosen:
            self.folder_var.set(chosen)

    def _log(self, text: str):
        self._log_queue.put(text)

    def _poll_log_queue(self):
        try:
            while True:
                text = self._log_queue.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", text + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def _run(self):
        folder_str = self.folder_var.get().strip()
        if not folder_str:
            messagebox.showwarning("Geen map gekozen", "Kies eerst een ordermap.")
            return
        folder = Path(folder_str)
        if not folder.is_dir():
            messagebox.showerror("Map niet gevonden", f"{folder} bestaat niet.")
            return

        self.run_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.progress.start(12)
        self._last_folder = folder

        batch = self.batch_var.get()
        apply_fix = self.fix_var.get()
        self._worker = threading.Thread(target=self._worker_run, args=(folder, batch, apply_fix), daemon=True)
        self._worker.start()

    def _worker_run(self, folder: Path, batch: bool, apply_fix: bool):
        config = ValidatorConfig(apply_fixes=apply_fix)
        folders = _order_subfolders(folder) if batch else [folder]
        if batch and not folders:
            self._log("Geen submappen gevonden om te verwerken.")
        any_failures = False
        for f in folders:
            self._log(f"Bezig met: {f}")
            try:
                report = validate_folder(f, config)
                _write_reports(f, report)
                self._log(render_text_report(report))
                if any(r.has_failures() for r in report.results):
                    any_failures = True
            except Exception as exc:
                self._log(f"FOUT bij verwerken van {f}: {exc}")
                any_failures = True
            self._log("")
        self._log("Klaar." + (" Er zijn nog openstaande fouten." if any_failures else " Alles OK."))
        self.after(0, self._on_run_done)

    def _on_run_done(self):
        self.progress.stop()
        self.run_btn.configure(state="normal")
        self.open_btn.configure(state="normal")

    def _open_folder(self):
        if self._last_folder:
            _open_in_file_manager(self._last_folder)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
