# -*- coding: utf-8 -*-
"""
Snygg och enkel Tkinter/ttk-GUI för att ladda ner batchade exporter (CSV/XLSX) via datumintervall.

API-kontrakt (antaget):
  GET  {API_BASE_URL}{API_ENDPOINT}
  Query params: start=YYYY-MM-DD, end=YYYY-MM-DD, format=csv|xlsx
  Header: X-API-Key: 12345

Dependencies:
  pip install requests

Bygg .exe (Windows 11 / PyInstaller):
  pip install pyinstaller
  pyinstaller --noconsole --onefile --name ExportNerladdare --add-data "logo.png;." app.py

Tips om du vill ha snygg ikon i Windows:
  - skapa en .ico och bygg med: --icon app.ico
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Tuple, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import requests
except ImportError as e:
    raise SystemExit("Saknar 'requests'. Kör: pip install requests") from e


# =========================
# KONFIG (håll GUI:t rent)
# =========================
APP_TITLE = "Export Nerladdare"
APP_SUBTITLE = "Batchade CSV/XLSX-exporter via datumintervall"

API_BASE_URL = "https://example.com/api"   # <-- ÄNDRA HÄR
API_ENDPOINT = "/export"                  # <-- ÄNDRA HÄR

API_KEY = "12345"                         # Fast nyckel enligt din spec
API_HEADER_NAME = "X-API-Key"

DEFAULT_BATCH_MODE = "Vecka"              # "Vecka" eller "Månad"
DEFAULT_FORMAT = "csv"                    # "csv" eller "xlsx"


# =========================
# Hjälpfunktioner
# =========================
def resource_path(relative: str) -> str:
    """Fungerar både i dev och PyInstaller."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, relative)
    return str(Path(__file__).resolve().parent / relative)


def app_config_dir(app_name: str = "export_nerladdare") -> Path:
    """Skrivbar settings-mapp (bra för .exe)."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    d = Path(base) / app_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def parse_yyyy_mm_dd(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def month_end(d: date) -> date:
    first_next = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
    return first_next - timedelta(days=1)


def build_batches(start: date, end: date, mode: str) -> List[Tuple[date, date]]:
    if start > end:
        raise ValueError("Startdatum måste vara före eller samma som slutdatum.")

    batches: List[Tuple[date, date]] = []
    cur = start

    while cur <= end:
        if mode == "Vecka":
            b_end = min(cur + timedelta(days=6), end)
        elif mode == "Månad":
            b_end = min(month_end(cur), end)
        else:
            raise ValueError("Okänt batchläge (endast Vecka/Månad).")

        batches.append((cur, b_end))
        cur = b_end + timedelta(days=1)

    return batches


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def safe_filename(s: str) -> str:
    bad = '<>:"/\\|?*'
    for ch in bad:
        s = s.replace(ch, "_")
    return s


@dataclass
class ApiConfig:
    base_url: str
    endpoint: str
    api_key: str
    header_name: str = "X-API-Key"


class ExportApiClient:
    def __init__(self, cfg: ApiConfig, timeout_s: int = 90) -> None:
        self.cfg = cfg
        self.timeout_s = timeout_s

    def url(self) -> str:
        return self.cfg.base_url.rstrip("/") + "/" + self.cfg.endpoint.lstrip("/")

    def download_export(self, start: date, end: date, fmt: str) -> bytes:
        headers = {self.cfg.header_name: self.cfg.api_key}
        params = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "format": fmt.lower(),
        }

        with requests.get(self.url(), headers=headers, params=params, timeout=self.timeout_s) as r:
            if r.status_code != 200:
                raise RuntimeError(f"API-fel {r.status_code}: {r.text[:500]}")
            return r.content


# =========================
# GUI
# =========================
class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(820, 520)

        # Lite bättre scaling på Windows
        try:
            self.tk.call("tk", "scaling", 1.15)
        except Exception:
            pass

        self._q: queue.Queue = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._cancel = threading.Event()

        self.settings_path = app_config_dir() / "settings.json"

        self._setup_style()
        self._build_ui()
        self._load_settings()

        self.after(120, self._poll)

    def _setup_style(self) -> None:
        style = ttk.Style(self)

        # 'clam' brukar se renare ut än default på Windows
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("TLabel", font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Sub.TLabel", font=("Segoe UI", 10))
        style.configure("Card.TLabelframe", padding=14)
        style.configure("Card.TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(12, 8))
        style.configure("TButton", padding=(10, 7))
        style.configure("TEntry", padding=6)
        style.configure("TCombobox", padding=4)

    def _build_ui(self) -> None:
        # Header (banner)
        header = ttk.Frame(self, padding=(16, 14, 16, 10))
        header.pack(fill="x")

        self._logo_img = None
        logo_path = resource_path("logo.png")
        if os.path.exists(logo_path):
            try:
                self._logo_img = tk.PhotoImage(file=logo_path)
                try:
                    self.iconphoto(True, self._logo_img)
                except Exception:
                    pass
                ttk.Label(header, image=self._logo_img).pack(side="left", padx=(0, 12))
            except Exception:
                self._logo_img = None

        title_box = ttk.Frame(header)
        title_box.pack(side="left", fill="x", expand=True)
        ttk.Label(title_box, text=APP_TITLE, style="Title.TLabel").pack(anchor="w")
        ttk.Label(title_box, text=APP_SUBTITLE, style="Sub.TLabel").pack(anchor="w", pady=(2, 0))

        # Main
        main = ttk.Frame(self, padding=(16, 8, 16, 10))
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        card = ttk.Labelframe(main, text="Nerladdning", style="Card.TLabelframe")
        card.grid(row=0, column=0, sticky="ew")
        card.columnconfigure(1, weight=1)

        # Vars
        today = date.today()
        self.var_start = tk.StringVar(value=(today - timedelta(days=30)).isoformat())
        self.var_end = tk.StringVar(value=today.isoformat())
        self.var_format = tk.StringVar(value=DEFAULT_FORMAT)
        self.var_batch = tk.StringVar(value=DEFAULT_BATCH_MODE)
        self.var_outdir = tk.StringVar(value=str((Path.home() / "Downloads").resolve()))

        # Layout: datumrad
        ttk.Label(card, text="Start (YYYY-MM-DD)").grid(row=0, column=0, sticky="w")
        ttk.Entry(card, textvariable=self.var_start, width=18).grid(row=0, column=1, sticky="w", padx=(10, 0))

        ttk.Label(card, text="Slut (YYYY-MM-DD)").grid(row=0, column=2, sticky="w", padx=(24, 0))
        ttk.Entry(card, textvariable=self.var_end, width=18).grid(row=0, column=3, sticky="w", padx=(10, 0))

        # format + batch
        fmt_box = ttk.Frame(card)
        fmt_box.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(14, 0))

        ttk.Label(fmt_box, text="Format").pack(side="left")
        ttk.Radiobutton(fmt_box, text="CSV", value="csv", variable=self.var_format).pack(side="left", padx=(10, 6))
        ttk.Radiobutton(fmt_box, text="XLSX", value="xlsx", variable=self.var_format).pack(side="left", padx=6)

        ttk.Label(fmt_box, text="Batch").pack(side="left", padx=(22, 8))
        ttk.Combobox(fmt_box, textvariable=self.var_batch, values=["Vecka", "Månad"], width=10, state="readonly").pack(
            side="left"
        )

        # Outdir
        out_box = ttk.Frame(card)
        out_box.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(14, 0))
        out_box.columnconfigure(0, weight=1)

        ttk.Label(out_box, text="Utdatamapp").grid(row=0, column=0, sticky="w")
        ttk.Entry(out_box, textvariable=self.var_outdir).grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(out_box, text="Välj…", command=self._choose_outdir).grid(row=1, column=1, padx=(10, 0), pady=(6, 0))

        # Status + progress + buttons
        bottom = ttk.Frame(main, padding=(2, 16, 2, 0))
        bottom.grid(row=1, column=0, sticky="nsew")
        bottom.columnconfigure(0, weight=1)

        self.var_status = tk.StringVar(value="Redo.")
        ttk.Label(bottom, textvariable=self.var_status).grid(row=0, column=0, sticky="w")

        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        btn_row = ttk.Frame(bottom)
        btn_row.grid(row=2, column=0, sticky="w", pady=(14, 0))

        self.btn_download = ttk.Button(btn_row, text="Ladda ner", style="Primary.TButton", command=self._start_download)
        self.btn_download.pack(side="left")

        self.btn_cancel = ttk.Button(btn_row, text="Avbryt", command=self._cancel_download, state="disabled")
        self.btn_cancel.pack(side="left", padx=(10, 0))

        self.btn_open = ttk.Button(btn_row, text="Öppna mapp", command=self._open_outdir)
        self.btn_open.pack(side="left", padx=(10, 0))

    def _choose_outdir(self) -> None:
        d = filedialog.askdirectory(title="Välj utdatamapp")
        if d:
            self.var_outdir.set(d)
            self._save_settings()

    def _open_outdir(self) -> None:
        try:
            os.startfile(self.var_outdir.get())
        except Exception:
            messagebox.showinfo("Mapp", self.var_outdir.get())

    def _set_running(self, running: bool) -> None:
        self.btn_download.config(state="disabled" if running else "normal")
        self.btn_cancel.config(state="normal" if running else "disabled")

    def _validate_inputs(self) -> Tuple[date, date, str, str, Path]:
        try:
            start = parse_yyyy_mm_dd(self.var_start.get())
        except Exception:
            raise ValueError("Ogiltigt startdatum. Använd format YYYY-MM-DD, t.ex. 2025-01-31.")
        try:
            end = parse_yyyy_mm_dd(self.var_end.get())
        except Exception:
            raise ValueError("Ogiltigt slutdatum. Använd format YYYY-MM-DD, t.ex. 2025-01-31.")

        if start > end:
            raise ValueError("Startdatum måste vara före eller samma som slutdatum.")

        fmt = self.var_format.get().strip().lower()
        if fmt not in ("csv", "xlsx"):
            raise ValueError("Format måste vara CSV eller XLSX.")

        batch = self.var_batch.get().strip()
        if batch not in ("Vecka", "Månad"):
            raise ValueError("Batch måste vara Vecka eller Månad.")

        outdir = Path(self.var_outdir.get().strip()).expanduser()
        ensure_dir(outdir)

        return start, end, fmt, batch, outdir

    def _start_download(self) -> None:
        if self._worker and self._worker.is_alive():
            return

        try:
            start, end, fmt, batch, outdir = self._validate_inputs()
        except Exception as e:
            messagebox.showerror("Fel", str(e))
            return

        self._save_settings()

        batches = build_batches(start, end, batch)
        if not batches:
            messagebox.showinfo("Info", "Inget att ladda ner.")
            return

        self.progress["value"] = 0
        self.progress["maximum"] = len(batches)
        self.var_status.set(f"Startar… ({len(batches)} batchar)")
        self._set_running(True)
        self._cancel.clear()

        cfg = ApiConfig(
            base_url=API_BASE_URL,
            endpoint=API_ENDPOINT,
            api_key=API_KEY,
            header_name=API_HEADER_NAME,
        )

        self._worker = threading.Thread(
            target=self._worker_fn,
            args=(cfg, batches, fmt, outdir),
            daemon=True,
        )
        self._worker.start()

    def _cancel_download(self) -> None:
        self._cancel.set()
        self.var_status.set("Avbryter…")

    def _worker_fn(self, cfg: ApiConfig, batches: List[Tuple[date, date]], fmt: str, outdir: Path) -> None:
        client = ExportApiClient(cfg)
        ok = 0

        for idx, (s, e) in enumerate(batches, start=1):
            if self._cancel.is_set():
                self._q.put(("done", (ok, len(batches), True)))
                return

            self._q.put(("status", f"Hämtar {s.isoformat()} → {e.isoformat()} ({idx}/{len(batches)})…"))

            try:
                data = client.download_export(s, e, fmt)
                name = safe_filename(f"export_{s:%Y%m%d}_{e:%Y%m%d}.{fmt}")
                path = outdir / name
                path.write_bytes(data)
                ok += 1
            except Exception as ex:
                self._q.put(("error", f"Fel vid {s} → {e}:\n{ex}"))

            self._q.put(("progress", idx))

        self._q.put(("done", (ok, len(batches), False)))

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self._q.get_nowait()

                if kind == "status":
                    self.var_status.set(str(payload))

                elif kind == "progress":
                    self.progress["value"] = int(payload)

                elif kind == "error":
                    # Visa fel utan att stoppa hela körningen
                    messagebox.showwarning("API-fel", str(payload))

                elif kind == "done":
                    ok, total, cancelled = payload
                    self._set_running(False)
                    self.var_status.set("Redo.")

                    if cancelled:
                        messagebox.showinfo("Klart", f"Avbrutet.\nLyckades: {ok}/{total}")
                    else:
                        messagebox.showinfo("Klart", f"Färdigt!\nLyckades: {ok}/{total}")
        except queue.Empty:
            pass
        finally:
            self.after(120, self._poll)

    def _load_settings(self) -> None:
        if not self.settings_path.exists():
            return
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            self.var_start.set(data.get("start", self.var_start.get()))
            self.var_end.set(data.get("end", self.var_end.get()))
            self.var_format.set(data.get("format", self.var_format.get()))
            self.var_batch.set(data.get("batch", self.var_batch.get()))
            self.var_outdir.set(data.get("outdir", self.var_outdir.get()))
        except Exception:
            return

    def _save_settings(self) -> None:
        data = {
            "start": self.var_start.get().strip(),
            "end": self.var_end.get().strip(),
            "format": self.var_format.get().strip(),
            "batch": self.var_batch.get().strip(),
            "outdir": self.var_outdir.get().strip(),
        }
        try:
            self.settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


if __name__ == "__main__":
    App().mainloop()
