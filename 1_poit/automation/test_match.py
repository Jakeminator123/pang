#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_match.py - Testa bildmatchning direkt utan att köra hela pipelinen.

Användning:
    python test_match.py

Detta skript:
1. Tar en screenshot av Chrome-fönstret
2. Försöker matcha alla bilder i 2_sok_kunngorelse/
3. Sparar debug-bilder med matchningsresultat
4. Visar exakt vilka skalor och poäng som hittades
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# Fixa encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)
os.environ["PYTHONUNBUFFERED"] = "1"

import cv2 as cv
import numpy as np
import pygetwindow as gw
import mss

# Paths
BASE_DIR = Path(__file__).parent.parent.resolve()
SOK_DIR = BASE_DIR / "bilder" / "2_sok_kunngorelse"
DEBUG_DIR = BASE_DIR / "debug"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

# Scales to test - very wide range for small screens
SCALES = [round(x, 2) for x in np.arange(0.10, 2.05, 0.05)]

def find_chrome_window():
    """Hitta Chrome-fönster"""
    wins = [w for w in gw.getAllWindows() 
            if "Chrome" in (w.title or "") 
            and not w.isMinimized 
            and w.width > 200 
            and w.height > 200]
    if wins:
        wins.sort(key=lambda x: (x.width * x.height), reverse=True)
        return wins[0]
    return None

def grab_window(win):
    """Ta screenshot av fönster"""
    with mss.mss() as sct:
        bbox = {
            "left": win.left,
            "top": win.top,
            "width": win.width,
            "height": win.height,
        }
        img = sct.grab(bbox)
        return np.array(img)[:, :, :3]  # BGR

def match_template(screen_gray, templ_gray, scale=1.0):
    """Matcha template mot skärm"""
    t = templ_gray
    if scale != 1.0:
        h, w = t.shape[:2]
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        t = cv.resize(t, (new_w, new_h), interpolation=cv.INTER_AREA if scale < 1 else cv.INTER_CUBIC)
    
    if screen_gray.shape[0] < t.shape[0] or screen_gray.shape[1] < t.shape[1]:
        return None, None, None
    
    res = cv.matchTemplate(screen_gray, t, cv.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv.minMaxLoc(res)
    return max_val, max_loc, (t.shape[1], t.shape[0])

def test_image(screen_bgr, screen_gray, img_path, ts):
    """Testa matchning för en bild"""
    img_name = img_path.name
    templ = cv.imread(str(img_path), cv.IMREAD_GRAYSCALE)
    if templ is None:
        print(f"  [FEL] Kunde inte läsa: {img_path}")
        return
    
    templ_h, templ_w = templ.shape[:2]
    print(f"\n  Template: {img_name} ({templ_w}x{templ_h} pixlar)")
    
    # Testa alla skalor
    best_score = -1.0
    best_scale = None
    best_loc = None
    best_size = None
    
    all_scores = []
    
    for sc in SCALES:
        score, loc, size = match_template(screen_gray, templ, scale=sc)
        if score is not None:
            all_scores.append((sc, score))
            if score > best_score:
                best_score = score
                best_scale = sc
                best_loc = loc
                best_size = size
    
    # Visa resultat
    print(f"  Bästa matchning: score={best_score:.4f} vid skala={best_scale}")
    
    # Visa top 5 skalor
    all_scores.sort(key=lambda x: x[1], reverse=True)
    print(f"  Top 5 skalor:")
    for sc, score in all_scores[:5]:
        print(f"    skala={sc:.2f}: score={score:.4f}")
    
    # Spara debug-bild
    if best_loc and best_size:
        out = screen_bgr.copy()
        x, y = best_loc
        tw, th = best_size
        color = (0, 255, 0) if best_score >= 0.50 else (0, 0, 255)
        cv.rectangle(out, (x, y), (x + tw, y + th), color, 2)
        cv.putText(out, f"{img_name}: {best_score:.3f}", (x, y - 10), 
                   cv.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        
        debug_path = DEBUG_DIR / f"test_{img_name.replace('.', '_')}_{best_score:.3f}_{ts}.png"
        cv.imwrite(str(debug_path), out)
        print(f"  Debug-bild: {debug_path}")

def main():
    print("=" * 60)
    print("TEST BILDMATCHNING")
    print("=" * 60)
    
    # Hitta Chrome
    print("\n[1] Letar efter Chrome-fönster...")
    win = find_chrome_window()
    if not win:
        print("[FEL] Hittade inget Chrome-fönster!")
        print("Starta Chrome och navigera till poit.bolagsverket.se först.")
        return 1
    
    print(f"  Hittade: {win.title[:50]}...")
    print(f"  Position: x={win.left}, y={win.top}")
    print(f"  Storlek: {win.width}x{win.height}")
    
    # Ta screenshot
    print("\n[2] Tar screenshot...")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    screen_bgr = grab_window(win)
    screen_gray = cv.cvtColor(screen_bgr, cv.COLOR_BGR2GRAY)
    
    # Spara original screenshot
    screen_path = DEBUG_DIR / f"test_screen_{ts}.png"
    cv.imwrite(str(screen_path), screen_bgr)
    print(f"  Sparad: {screen_path}")
    print(f"  Storlek: {screen_bgr.shape[1]}x{screen_bgr.shape[0]}")
    
    # Hitta alla bilder att testa
    print("\n[3] Testar bilder i 2_sok_kunngorelse/...")
    images = list(SOK_DIR.glob("*.jpg")) + list(SOK_DIR.glob("*.png"))
    
    if not images:
        print(f"  [FEL] Inga bilder hittades i {SOK_DIR}")
        return 1
    
    for img_path in images:
        test_image(screen_bgr, screen_gray, img_path, ts)
    
    print("\n" + "=" * 60)
    print("KLAR!")
    print(f"Debug-bilder sparade i: {DEBUG_DIR}")
    print("=" * 60)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
