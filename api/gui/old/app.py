import os, io, zipfile, textwrap, pathlib
from PIL import Image

base_dir = pathlib.Path("/mnt/data/csv_xlsx_downloader_gui")
base_dir.mkdir(parents=True, exist_ok=True)

# Convert provided logo image to PNG
logo_src = pathlib.Path("/mnt/data/jocke.jpg")
logo_dst = base_dir / "logo.png"
img = Image.open(logo_src).convert("RGBA")
# Resize to a reasonable GUI-friendly size while keeping aspect
img = img.resize((128, 128))
img.save(logo_dst, format="PNG")

app_py = r'''# -*- coding: utf-8 -*-
"""
Tkinter GUI för att ladda ner batchade CSV/XLSX-filer från en webb-API med datumintervall.

Antagande om API-kontrakt (enkelt att ändra):
- GET {BASE_URL}{ENDPOINT}
- Query params: start=YYYY-MM-DD, end=YYYY-MM-DD, format=csv|xlsx
- Header: X-API-Key: <nyckel>

Kör:
  pip install requests
  python app.py

Bygg .exe (PyInstaller, Windows):
  pip install pyinstaller
  pyinstaller --noconsole --onefile --name ExportNerladdare --add-data "logo.png;." app.py
"""
from __future__ import annotations

import os
import sys
import json
import queue
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Tuple, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

try:
    import requests
except ImportError as e:  # pragma: no cover
    raise SystemExit("Saknar dependency 'requests'. Kör: pip install requests") from e


APP_TITLE = "Batch Export Nerladdare"
DEFAULT_API_KEY = "12345"
DEFAULT_BASE_URL = "https://example.com/api"
DEFAULT_ENDPOINT = "/export"
SETTINGS_FILE = "settings.json"


def resource_path(relative: str) -> str:
    """
    Returnerar korrekt sökväg både i dev-läge och när appen är packad med PyInstaller.
    """
    # PyInstaller packar filer i en temporär katalog och sätter sys._MEIPASS
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, relative)
    return str(Path(__file__).resolve().parent / relative)


def parse_yyyy_mm_dd(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def daterange_batches(start: date, end: date, mode: str) -> Iterable[Tuple[date, date]]:
    """
    Skapar batchade datumintervall (inklusive start & end).
    mode: "Dag", "Vecka", "Månad"
    """
    if start > end:
        raise ValueError("Startdatum måste vara <= slutdatum.")

    cur = start
    while cur <= end:
        if mode == "Dag":
            batch_end = cur
        elif mode == "Vecka":
            batch_end = cur + timedelta(days=6)
        elif mode == "Månad":
            # Sista dagen i månaden: gå till 1:a i nästa månad och backa en dag
            first_next = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
            batch_end = first_next - timedelta(days=1)
        else:
            raise ValueError(f"Okänt batchläge: {mode}")

        if batch_end > end:
            batch_end = end

        yield cur, batch_end
        cur = batch_end + timedelta(days=1)


@dataclass
class ApiConfig:
    base_url: str
    endpoint: str
    api_key: str
    header_name: str = "X-API-Key"  # kan ändras till t.ex. "Authorization"


class ExportApiClient:
    def __init__(self, cfg: ApiConfig, timeout_s: int = 60) -> None:
        self.cfg = cfg
        self.timeout_s = timeout_s

    def _url(self) -> str:
        return self.cfg.base_url.rstrip("/") + "/" + self.cfg.endpoint.lstrip("/")

    def test_connection(self) -> Tuple[bool, str]:
        """
        En enkel kontroll: gör en GET mot base_url (eller endpoint om du vill).
        """
        try:
            r = requests.get(self.cfg.base_url, timeout=10)
            return True, f"OK: {r.status_code}"
        except Exception as e:
            return False, f"Fel: {e}"

    def download_export(self, start: date, end: date, fmt: str) -> bytes:
        url = self._url()
        headers = {self.cfg.header_name: self.cfg.api_key}

        # Om servern vill ha "Authorization: Bearer <key>" kan du byta header_name och api_key-formatet i GUI:t.
        params = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "format": fmt.lower(),
        }

        with requests.get(url, headers=headers, params=params, timeout=self.timeout_s, stream=True) as r:
            if r.status_code != 200:
                # Försök visa eventuell JSON-error
                content_type = (r.headers.get("Content-Type") or "").lower()
                if "application/json" in content_type:
                    try:
                        data = r.json()
                        raise RuntimeError(f"API-fel {r.status_code}: {json.dumps(data, ensure_ascii=False)}")
                    except Exception:
                        pass
                raise RuntimeError(f"API-fel {r.status_code}: {r.text[:500]}")

            # Läs allt (streaming men samlar till bytes)
            return r.content


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(860, 560)

        self._queue: queue.Queue = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._cancel = threading.Event()

        self._build_ui()
        self._load_settings()
        self.after(100, self._poll_queue)

    def _build_ui(self) -> None:
        # Top header med logo
        header = ttk.Frame(self, padding=(12, 12, 12, 6))
        header.pack(fill="x")

        try:
            self.logo_img = tk.PhotoImage(file=resource_path("logo.png"))
            # Sätt som fönsterikon (på Windows syns ibland inte)
            try:
                self.iconphoto(True, self.logo_img)
            except Exception:
                pass
            ttk.Label(header, image=self.logo_img).pack(side="left", padx=(0, 10))
        except Exception:
            self.logo_img = None

        ttk.Label(
            header,
            text="Ladda ner batchade exporter (CSV/XLSX) från API",
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left")

        # Main content
        main = ttk.Frame(self, padding=12)
        main.pack(fill="both", expand=True)

        main.columnconfigure(0, weight=2)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(3, weight=1)

        form = ttk.LabelFrame(main, text="Inställningar", padding=12)
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 10))

        # Form variables
        self.var_base_url = tk.StringVar(value=DEFAULT_BASE_URL)
        self.var_endpoint = tk.StringVar(value=DEFAULT_ENDPOINT)
        self.var_api_key = tk.StringVar(value=DEFAULT_API_KEY)
        self.var_header = tk.StringVar(value="X-API-Key")
        self.var_format = tk.StringVar(value="csv")
        self.var_batch = tk.StringVar(value="Vecka")

        today = date.today()
        self.var_start = tk.StringVar(value=(today - timedelta(days=30)).isoformat())
        self.var_end = tk.StringVar(value=today.isoformat())

        self.var_outdir = tk.StringVar(value=str((Path.home() / "Downloads").resolve()))

        # Grid form
        r = 0
        ttk.Label(form, text="Base URL").grid(row=r, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.var_base_url, width=48).grid(row=r, column=1, sticky="ew", padx=(8, 0))
        r += 1

        ttk.Label(form, text="Endpoint").grid(row=r, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(form, textvariable=self.var_endpoint, width=48).grid(row=r, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        r += 1

        ttk.Label(form, text="API-header").grid(row=r, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(form, textvariable=self.var_header, width=48).grid(row=r, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        r += 1

        ttk.Label(form, text="API-nyckel").grid(row=r, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(form, textvariable=self.var_api_key, width=48, show="•").grid(row=r, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        r += 1

        ttk.Label(form, text="Format").grid(row=r, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(form, textvariable=self.var_format, values=["csv", "xlsx"], width=10, state="readonly").grid(
            row=r, column=1, sticky="w", padx=(8, 0), pady=(8, 0)
        )
        r += 1

        ttk.Label(form, text="Batchning").grid(row=r, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(form, textvariable=self.var_batch, values=["Dag", "Vecka", "Månad"], width=10, state="readonly").grid(
            row=r, column=1, sticky="w", padx=(8, 0), pady=(8, 0)
        )
        r += 1

        # Dates
        date_row = ttk.Frame(form)
        date_row.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        date_row.columnconfigure(1, weight=1)
        date_row.columnconfigure(3, weight=1)

        ttk.Label(date_row, text="Start (YYYY-MM-DD)").grid(row=0, column=0, sticky="w")
        self.ent_start = ttk.Entry(date_row, textvariable=self.var_start)
        self.ent_start.grid(row=0, column=1, sticky="ew", padx=(8, 18))

        ttk.Label(date_row, text="Slut (YYYY-MM-DD)").grid(row=0, column=2, sticky="w")
        self.ent_end = ttk.Entry(date_row, textvariable=self.var_end)
        self.ent_end.grid(row=0, column=3, sticky="ew", padx=(8, 0))

        r += 1

        # Outdir
        out_row = ttk.Frame(form)
        out_row.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        out_row.columnconfigure(0, weight=1)

        ttk.Entry(out_row, textvariable=self.var_outdir).grid(row=0, column=0, sticky="ew")
        ttk.Button(out_row, text="Välj mapp…", command=self._choose_outdir).grid(row=0, column=1, padx=(8, 0))

        # Buttons
        btns = ttk.Frame(main)
        btns.grid(row=1, column=0, sticky="w", pady=(0, 10))

        self.btn_test = ttk.Button(btns, text="Testa anslutning", command=self._on_test)
        self.btn_test.pack(side="left")

        self.btn_download = ttk.Button(btns, text="Ladda ner", command=self._on_download)
        self.btn_download.pack(side="left", padx=(8, 0))

        self.btn_cancel = ttk.Button(btns, text="Avbryt", command=self._on_cancel, state="disabled")
        self.btn_cancel.pack(side="left", padx=(8, 0))

        self.btn_open = ttk.Button(btns, text="Öppna mapp", command=self._open_outdir)
        self.btn_open.pack(side="left", padx=(8, 0))

        # Progress + log
        side = ttk.Frame(main)
        side.grid(row=0, column=1, rowspan=3, sticky="nsew", pady=(0, 10))
        side.rowconfigure(1, weight=1)

        prog_frame = ttk.LabelFrame(side, text="Status", padding=12)
        prog_frame.grid(row=0, column=0, sticky="ew")

        self.lbl_status = ttk.Label(prog_frame, text="Redo.")
        self.lbl_status.pack(anchor="w")

        self.progress = ttk.Progressbar(prog_frame, orient="horizontal", mode="determinate", length=240)
        self.progress.pack(fill="x", pady=(8, 0))

        log_frame = ttk.LabelFrame(side, text="Logg", padding=12)
        log_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.txt_log = ScrolledText(log_frame, height=18, wrap="word")
        self.txt_log.grid(row=0, column=0, sticky="nsew")

        # Footer hint
        footer = ttk.Frame(self, padding=(12, 0, 12, 12))
        footer.pack(fill="x")
        ttk.Label(
            footer,
            text="Tips: Om din API använder annan parameter-/header-namn, ändra dem här i GUI:t.",
            foreground="#444",
        ).pack(anchor="w")

    def _choose_outdir(self) -> None:
        d = filedialog.askdirectory(title="Välj utdata-mapp")
        if d:
            self.var_outdir.set(d)

    def _open_outdir(self) -> None:
        try:
            os.startfile(self.var_outdir.get())  # Windows
        except Exception:
            messagebox.showinfo("Info", f"Utdata-mapp:\n{self.var_outdir.get()}")

    def _log(self, msg: str) -> None:
        self.txt_log.insert("end", msg + "\n")
        self.txt_log.see("end")

    def _set_status(self, msg: str) -> None:
        self.lbl_status.config(text=msg)

    def _validate(self) -> Tuple[ApiConfig, date, date, str, str, Path]:
        # Enkel validering + tydliga felmeddelanden
        base_url = self.var_base_url.get().strip()
        endpoint = self.var_endpoint.get().strip()
        api_key = self.var_api_key.get().strip()
        header = self.var_header.get().strip() or "X-API-Key"
        fmt = self.var_format.get().strip().lower()
        batch = self.var_batch.get().strip()
        outdir = Path(self.var_outdir.get().strip()).expanduser()

        if not base_url.startswith(("http://", "https://")):
            raise ValueError("Base URL måste börja med http:// eller https://")

        if fmt not in ("csv", "xlsx"):
            raise ValueError("Format måste vara csv eller xlsx.")

        if not outdir.exists():
            outdir.mkdir(parents=True, exist_ok=True)

        # Datum
        try:
            start = parse_yyyy_mm_dd(self.var_start.get())
        except Exception:
            raise ValueError("Startdatum är ogiltigt. Använd YYYY-MM-DD, t.ex. 2025-01-31.")
        try:
            end = parse_yyyy_mm_dd(self.var_end.get())
        except Exception:
            raise ValueError("Slutdatum är ogiltigt. Använd YYYY-MM-DD, t.ex. 2025-01-31.")

        if start > end:
            raise ValueError("Startdatum måste vara före eller samma som slutdatum.")

        cfg = ApiConfig(
            base_url=base_url,
            endpoint=endpoint,
            api_key=api_key,
            header_name=header,
        )
        return cfg, start, end, fmt, batch, outdir

    def _disable_while_running(self, running: bool) -> None:
        self.btn_download.config(state="disabled" if running else "normal")
        self.btn_test.config(state="disabled" if running else "normal")
        self.btn_cancel.config(state="normal" if running else "disabled")

    def _on_test(self) -> None:
        try:
            cfg, *_ = self._validate()
        except Exception as e:
            messagebox.showerror("Fel", str(e))
            return

        self._log("Testar anslutning…")
        ok, msg = ExportApiClient(cfg).test_connection()
        if ok:
            self._log(msg)
            messagebox.showinfo("Test", msg)
        else:
            self._log(msg)
            messagebox.showerror("Test", msg)

        self._save_settings()

    def _on_download(self) -> None:
        try:
            cfg, start, end, fmt, batch, outdir = self._validate()
        except Exception as e:
            messagebox.showerror("Fel", str(e))
            return

        self._save_settings()

        batches = list(daterange_batches(start, end, batch))
        if not batches:
            messagebox.showinfo("Info", "Inget att ladda ner.")
            return

        self.progress["value"] = 0
        self.progress["maximum"] = len(batches)
        self._set_status("Startar…")
        self._disable_while_running(True)
        self._cancel.clear()

        self._worker = threading.Thread(
            target=self._worker_download,
            args=(cfg, fmt, outdir, batches),
            daemon=True,
        )
        self._worker.start()

    def _on_cancel(self) -> None:
        if self._worker and self._worker.is_alive():
            self._cancel.set()
            self._log("Avbryt begärt…")

    def _worker_download(
        self,
        cfg: ApiConfig,
        fmt: str,
        outdir: Path,
        batches: Iterable[Tuple[date, date]],
    ) -> None:
        client = ExportApiClient(cfg)
        total = 0
        ok_count = 0

        for idx, (s, e) in enumerate(batches, start=1):
            if self._cancel.is_set():
                self._queue.put(("status", "Avbruten av användaren."))
                break

            total += 1
            self._queue.put(("status", f"Hämtar {s} → {e} ({idx}/{len(list(batches))})…"))

            try:
                data = client.download_export(s, e, fmt)
                filename = f"export_{s.strftime('%Y%m%d')}_{e.strftime('%Y%m%d')}.{fmt}"
                path = outdir / filename
                path.write_bytes(data)

                ok_count += 1
                self._queue.put(("log", f"✓ Sparade: {path} ({len(data):,} bytes)"))
            except Exception as ex:
                self._queue.put(("log", f"✗ Fel för {s} → {e}: {ex}"))

            self._queue.put(("progress", idx))

        self._queue.put(("done", (ok_count, total)))

    def _poll_queue(self) -> None:
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]
                payload = item[1] if len(item) > 1 else None

                if kind == "log":
                    self._log(str(payload))
                elif kind == "status":
                    self._set_status(str(payload))
                elif kind == "progress":
                    self.progress["value"] = int(payload)
                elif kind == "done":
                    ok_count, total = payload
                    self._disable_while_running(False)
                    self._set_status("Redo.")
                    self._log(f"Klart. Lyckades: {ok_count}/{total}")
                    if self._cancel.is_set():
                        messagebox.showinfo("Klart", f"Avbruten. Lyckades: {ok_count}/{total}")
                    else:
                        messagebox.showinfo("Klart", f"Lyckades: {ok_count}/{total}")
        except queue.Empty:
            pass
        finally:
            self.after(120, self._poll_queue)

    def _settings_path(self) -> Path:
        return Path(resource_path(SETTINGS_FILE))

    def _load_settings(self) -> None:
        p = self._settings_path()
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            self.var_base_url.set(data.get("base_url", DEFAULT_BASE_URL))
            self.var_endpoint.set(data.get("endpoint", DEFAULT_ENDPOINT))
            self.var_header.set(data.get("header_name", "X-API-Key"))
            self.var_api_key.set(data.get("api_key", DEFAULT_API_KEY))
            self.var_format.set(data.get("format", "csv"))
            self.var_batch.set(data.get("batch", "Vecka"))
            self.var_start.set(data.get("start", self.var_start.get()))
            self.var_end.set(data.get("end", self.var_end.get()))
            self.var_outdir.set(data.get("outdir", self.var_outdir.get()))
        except Exception:
            # Om settings är korrupt – ignorera.
            return

    def _save_settings(self) -> None:
        p = self._settings_path()
        data = {
            "base_url": self.var_base_url.get().strip(),
            "endpoint": self.var_endpoint.get().strip(),
            "header_name": self.var_header.get().strip(),
            "api_key": self.var_api_key.get().strip(),
            "format": self.var_format.get().strip(),
            "batch": self.var_batch.get().strip(),
            "start": self.var_start.get().strip(),
            "end": self.var_end.get().strip(),
            "outdir": self.var_outdir.get().strip(),
        }
        try:
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


if __name__ == "__main__":
    App().mainloop()
'''

# Fix a small bug: inside _worker_download I used len(list(batches)) which consumes iter. We'll rewrite that in file.
# Let's create final app.py with corrected code (precompute batch list and pass count).
app_py_fixed = app_py.replace(
    "args=(cfg, fmt, outdir, batches),",
    "args=(cfg, fmt, outdir, batches),",
)

# Let's programmatically rewrite parts properly
lines = app_py.splitlines()

# We'll reconstruct with corrected worker signature: pass batches as list and use total_batches = len(batches)
# Find and replace section in _on_download and _worker_download
import re

app_py_fixed = app_py
# Ensure batches is list and we pass it
app_py_fixed = re.sub(
    r"batches = list\(daterange_batches\(start, end, batch\)\)",
    r"batches = list(daterange_batches(start, end, batch))",
    app_py_fixed
)

# In _worker_download, remove len(list(batches)) and instead use total_batches variable
app_py_fixed = app_py_fixed.replace(
    "def _worker_download(\n        self,\n        cfg: ApiConfig,\n        fmt: str,\n        outdir: Path,\n        batches: Iterable[Tuple[date, date]],\n    ) -> None:",
    "def _worker_download(\n        self,\n        cfg: ApiConfig,\n        fmt: str,\n        outdir: Path,\n        batches: list[Tuple[date, date]],\n    ) -> None:"
)

app_py_fixed = app_py_fixed.replace(
    "for idx, (s, e) in enumerate(batches, start=1):",
    "total_batches = len(batches)\n\n        for idx, (s, e) in enumerate(batches, start=1):"
)

app_py_fixed = app_py_fixed.replace(
    "self._queue.put((\"status\", f\"Hämtar {s} → {e} ({idx}/{len(list(batches))})…\"))",
    "self._queue.put((\"status\", f\"Hämtar {s} → {e} ({idx}/{total_batches})…\"))"
)

(app_path := base_dir / "app.py").write_text(app_py_fixed, encoding="utf-8")

readme = r"""# Batch Export Nerladdare (Tkinter)

En liten Win-vänlig Tkinter-app som laddar ner batchade exporter (CSV/XLSX) från en webb-API baserat på datumintervall.

## Förväntat API-kontrakt (enkelt att ändra)
- **GET** `{base_url}{endpoint}`
- Query params:
  - `start=YYYY-MM-DD`
  - `end=YYYY-MM-DD`
  - `format=csv` eller `format=xlsx`
- Header (default):
  - `X-API-Key: 12345`

Om din API använder annat:
- Ändra **API-header** (t.ex. `Authorization`)
- Och skriv nyckeln som t.ex. `Bearer 12345` i fältet **API-nyckel**

## Installera och kör
```bash
pip install -r requirements.txt
python app.py
