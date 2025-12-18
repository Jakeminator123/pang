#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
add_preview_links.py

Syfte:
- För varje företagsmapp (K*-25) som fått en genererad sajt (preview_url.txt)
  och redan har ett mail (mail.txt), lägg till en kort rad i mailet med länk
  till den genererade landningssidan.

Körningsexempel:
  py 3_sajt/add_preview_links.py              # kör på senaste datum-mapp
  py 3_sajt/add_preview_links.py 20251209     # kör på angivet datum

Krav:
- preview_url.txt ska finnas i företagsmappen (skapas av batch_generate)
- mail.txt ska finnas i samma mapp
"""

import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DJUPANALYS_DIR = PROJECT_ROOT / "2_segment_info" / "djupanalys"


def log(msg: str):
    print(msg, flush=True)


def get_latest_date_dir(base: Path) -> Optional[Path]:
    if not base.exists():
        return None
    date_dirs = [p for p in base.iterdir() if p.is_dir() and p.name.isdigit() and len(p.name) == 8]
    if not date_dirs:
        return None
    return sorted(date_dirs, key=lambda p: p.name)[-1]


def append_link_to_mail(mail_path: Path, url: str) -> bool:
    """Lägg till länkrad i mail.txt om den saknas. Returnerar True om ändrat."""
    content = mail_path.read_text(encoding="utf-8")
    if url in content:
        return False
    footer = f"\n\nPS: Vi tog oss friheten att autogenerera en liten landningssida åt er: {url}\n"
    mail_path.write_text(content + footer, encoding="utf-8")
    return True


def process_date_dir(date_dir: Path):
    k_dirs = [d for d in date_dir.iterdir() if d.is_dir() and d.name.startswith("K") and "-25" in d.name]
    if not k_dirs:
        log(f"❌ Inga företagsmappar hittades i {date_dir}")
        return

    changed = 0
    skipped = 0

    for k_dir in k_dirs:
        preview_file = k_dir / "preview_url.txt"
        mail_file = k_dir / "mail.txt"
        if not preview_file.exists() or not mail_file.exists():
            skipped += 1
            continue

        url = preview_file.read_text(encoding="utf-8").strip()
        if not url:
            skipped += 1
            continue

        if append_link_to_mail(mail_file, url):
            changed += 1
        else:
            skipped += 1

    log(f"✅ Klart för {date_dir.name}: {changed} mail uppdaterade, {skipped} hoppade över.")


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        date_arg = argv[1]
        date_dir = DJUPANALYS_DIR / date_arg
        if not date_dir.exists():
            log(f"❌ Datum-mapp saknas: {date_dir}")
            return 1
    else:
        date_dir = get_latest_date_dir(DJUPANALYS_DIR)
        if not date_dir:
            log("❌ Hittade ingen datum-mapp i djupanalys/")
            return 1

    log(f"📂 Bearbetar datum: {date_dir.name}")
    process_date_dir(date_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

