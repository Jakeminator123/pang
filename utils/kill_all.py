#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kill_all.py - Dödar alla Python-processer, Flask-servrar och Chrome-instanser

Användning:
    python utils/kill_all.py
"""

import os
import sys
import subprocess
import signal
import time

def kill_processes_by_name(name_patterns):
    """Döda processer som matchar namn-mönster."""
    killed = []
    try:
        if sys.platform == "win32":
            # Windows: använd taskkill
            for pattern in name_patterns:
                try:
                    # Hitta processer
                    result = subprocess.run(
                        ["tasklist", "/FI", f"IMAGENAME eq {pattern}", "/FO", "CSV"],
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='ignore'
                    )
                    
                    if pattern in result.stdout:
                        # Döda processer
                        subprocess.run(
                            ["taskkill", "/F", "/IM", pattern],
                            capture_output=True,
                            text=True,
                            encoding='utf-8',
                            errors='ignore'
                        )
                        killed.append(pattern)
                        print(f"✓ Dödade processer: {pattern}")
                except Exception as e:
                    print(f"⚠️  Kunde inte döda {pattern}: {e}")
        else:
            # Unix/Linux/Mac: använd pkill
            for pattern in name_patterns:
                try:
                    subprocess.run(["pkill", "-9", "-f", pattern], 
                                 capture_output=True, text=True)
                    killed.append(pattern)
                    print(f"✓ Dödade processer: {pattern}")
                except Exception as e:
                    print(f"⚠️  Kunde inte döda {pattern}: {e}")
    except Exception as e:
        print(f"⚠️  Fel vid dödning av processer: {e}")
    
    return killed

def kill_processes_by_port(port):
    """Döda processer som lyssnar på en specifik port."""
    killed = []
    try:
        if sys.platform == "win32":
            # Windows: använd netstat och taskkill
            try:
                # Hitta PID för porten
                result = subprocess.run(
                    ["netstat", "-ano"],
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore'
                )
                
                pids = []
                for line in result.stdout.split('\n'):
                    if f':{port}' in line and 'LISTENING' in line:
                        parts = line.split()
                        if len(parts) > 4:
                            pid = parts[-1]
                            if pid.isdigit():
                                pids.append(pid)
                
                # Döda alla PIDs
                for pid in set(pids):
                    try:
                        subprocess.run(
                            ["taskkill", "/F", "/PID", pid],
                            capture_output=True,
                            text=True,
                            encoding='utf-8',
                            errors='ignore'
                        )
                        killed.append(f"PID {pid} (port {port})")
                        print(f"✓ Dödade process på port {port}: PID {pid}")
                    except Exception:
                        pass
            except Exception as e:
                print(f"⚠️  Kunde inte döda processer på port {port}: {e}")
        else:
            # Unix/Linux/Mac: använd lsof och kill
            try:
                result = subprocess.run(
                    ["lsof", "-ti", f":{port}"],
                    capture_output=True,
                    text=True
                )
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    if pid:
                        try:
                            os.kill(int(pid), signal.SIGKILL)
                            killed.append(f"PID {pid} (port {port})")
                            print(f"✓ Dödade process på port {port}: PID {pid}")
                        except Exception:
                            pass
            except Exception:
                pass
    except Exception as e:
        print(f"⚠️  Fel vid dödning av processer på port {port}: {e}")
    
    return killed

def main():
    print("=" * 60)
    print("DÖDAR ALLA PYTHON-PROCESSER, SERVRAR OCH CHROME")
    print("=" * 60)
    print()
    
    all_killed = []
    
    # 1. Döda Flask-server på port 51234
    print("[1] Dödar Flask-server (port 51234)...")
    killed = kill_processes_by_port(51234)
    all_killed.extend(killed)
    if not killed:
        print("  ℹ️  Ingen server körde på port 51234")
    print()
    
    # 2. Döda Python-processer
    print("[2] Dödar Python-processer...")
    python_patterns = ["python.exe", "pythonw.exe", "py.exe"]
    killed = kill_processes_by_name(python_patterns)
    all_killed.extend(killed)
    if not killed:
        print("  ℹ️  Inga Python-processer hittades")
    print()
    
    # 3. Döda Chrome-processer (om de körs från scraping)
    print("[3] Dödar Chrome-processer...")
    chrome_patterns = ["chrome.exe"]
    killed = kill_processes_by_name(chrome_patterns)
    all_killed.extend(killed)
    if not killed:
        print("  ℹ️  Inga Chrome-processer hittades")
    print()
    
    # Sammanfattning
    print("=" * 60)
    if all_killed:
        print(f"✅ Dödade {len(all_killed)} processer/portar:")
        for item in all_killed:
            print(f"   - {item}")
    else:
        print("ℹ️  Inga processer att döda")
    print("=" * 60)
    
    # Vänta lite så processerna hinner avslutas
    time.sleep(1)

if __name__ == "__main__":
    main()

