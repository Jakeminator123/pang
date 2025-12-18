#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clear_chrome_cache.py

Rensar onödig cache från chrome_profile för att spara utrymme.
Behåller viktiga data som:
- Extensions (inkl. vår ext_bolag)
- Cookies & Login Data
- Preferences & Settings
- History & Bookmarks
"""

import os
import sys
import shutil
import io
from pathlib import Path

# Fixa encoding för Windows-terminal
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).parent.parent.resolve()  # Point to 1_poit root
PROFILE_DIR = BASE_DIR / "chrome_profile"

# Mappar som kan raderas säkert (cache och temporära filer)
SAFE_TO_DELETE = [
    # Cache directories
    "Cache",
    "Code Cache",
    "GPUCache",
    "ShaderCache",
    "DawnGraphiteCache",
    "DawnWebGPUCache",
    "GrShaderCache",
    "GraphiteDawnCache",
    
    # Browser metrics (onödiga logs)
    "BrowserMetrics",
    "BrowserMetrics-spare.pma",
    "CrashpadMetrics-active.pma",
    "DeferredBrowserMetrics",
    
    # Crashpad reports (onödiga)
    "Crashpad",
    
    # Safe Browsing cache
    "Safe Browsing",
    
    # Service Worker cache
    "Default/Service Worker/CacheStorage",
    "Default/Cache",
    "Default/Code Cache",
    "Default/GPUCache",
    "Default/DawnGraphiteCache",
    "Default/DawnWebGPUCache",
    
    # Temporary storage
    "Default/blob_storage",
    "Default/Web Applications/Temp",
]

# Filer som kan raderas (logs och temp)
SAFE_FILES_TO_DELETE = [
    "*.log",
    "*.tmp",
    "LOG",
    "LOG.old",
    "*-journal",  # SQLite journals (återskapas automatiskt)
]

def get_folder_size(path):
    """Beräkna mappstorleken"""
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat().st_size
            elif entry.is_dir(follow_symlinks=False):
                total += get_folder_size(entry.path)
    except:
        pass
    return total

def format_size(bytes_size):
    """Formatera storlek i MB/GB"""
    mb = bytes_size / (1024 * 1024)
    if mb < 1024:
        return f"{mb:.1f} MB"
    else:
        return f"{mb/1024:.2f} GB"

def main():
    print("=" * 60)
    print("CHROME PROFILE CACHE CLEANER")
    print("=" * 60)
    
    if not PROFILE_DIR.exists():
        print(f"[ERROR] Chrome profile hittades inte: {PROFILE_DIR}")
        return
    
    # Beräkna initial storlek
    print("\n[*] Beräknar initial storlek...")
    initial_size = get_folder_size(PROFILE_DIR)
    print(f"Initial storlek: {format_size(initial_size)}")
    
    # Räknare
    deleted_folders = 0
    deleted_files = 0
    freed_space = 0
    
    # Radera cache-mappar
    print("\n[*] Rensar cache-mappar...")
    for cache_dir in SAFE_TO_DELETE:
        full_path = PROFILE_DIR / cache_dir
        if full_path.exists():
            try:
                # Beräkna storlek före radering
                size = get_folder_size(full_path)
                
                # Radera
                if full_path.is_dir():
                    shutil.rmtree(full_path)
                    deleted_folders += 1
                else:
                    full_path.unlink()
                    deleted_files += 1
                
                freed_space += size
                print(f"  ✓ Raderad: {cache_dir} ({format_size(size)})")
            except Exception as e:
                print(f"  ✗ Misslyckades radera {cache_dir}: {e}")
    
    # Radera log-filer och journals rekursivt
    print("\n[*] Rensar log-filer och journals...")
    for root, dirs, files in os.walk(PROFILE_DIR):
        for file in files:
            # Kolla om filen matchar något av våra mönster
            should_delete = False
            
            if file.endswith('.log') or file.endswith('.tmp') or file.endswith('.old'):
                should_delete = True
            elif file in ['LOG', 'LOG.old']:
                should_delete = True
            elif file.endswith('-journal'):
                should_delete = True
            
            if should_delete:
                try:
                    file_path = Path(root) / file
                    size = file_path.stat().st_size
                    file_path.unlink()
                    deleted_files += 1
                    freed_space += size
                except Exception:
                    pass  # Skippa om filen är låst
    
    print(f"  ✓ Raderade {deleted_files} log/temp-filer")
    
    # Beräkna slutlig storlek
    print("\n[*] Beräknar slutlig storlek...")
    final_size = get_folder_size(PROFILE_DIR)
    
    # Sammanfattning
    print("\n" + "=" * 60)
    print("SAMMANFATTNING")
    print("=" * 60)
    print(f"Mappar raderade: {deleted_folders}")
    print(f"Filer raderade: {deleted_files}")
    print(f"Utrymme frigjort: {format_size(freed_space)}")
    print(f"\nFöre: {format_size(initial_size)}")
    print(f"Efter: {format_size(final_size)}")
    print(f"Minskning: {format_size(initial_size - final_size)} ({((initial_size - final_size) / initial_size * 100):.1f}%)")
    print("\n✅ Cache rensad! Extensions och inloggningar bevarade.")

if __name__ == "__main__":
    main()

