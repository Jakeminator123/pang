#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
install.py - Install all dependencies for the pang pipeline

Usage:
    python install.py
"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"


def main():
    print("=" * 60)
    print("INSTALLERAR ALLA DEPENDENCIES FÖR PANG PIPELINE")
    print("=" * 60)
    print(f"Projektrot: {PROJECT_ROOT}")
    print(f"Requirements: {REQUIREMENTS_FILE}")
    print()

    if not REQUIREMENTS_FILE.exists():
        print(f"❌ FEL: {REQUIREMENTS_FILE} saknas!")
        return 1

    print("📦 Installerar från requirements.txt...")
    print()

    try:
        # Uppgradera pip först
        print("[1/3] Uppgraderar pip...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--upgrade", "pip"],
            cwd=str(PROJECT_ROOT),
        )
        print("✅ pip uppgraderad")
        print()

        # Installera alla dependencies
        print("[2/3] Installerar dependencies...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)],
            cwd=str(PROJECT_ROOT),
        )
        print("✅ Dependencies installerade")
        print()

        # Installera Playwright browsers (om playwright finns)
        print("[3/3] Installerar Playwright browsers (om behövs)...")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print("✅ Playwright browsers installerade")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("ℹ️  Playwright inte installerat eller redan klar")
        print()

        print("=" * 60)
        print("✅ INSTALLATION KLAR!")
        print("=" * 60)
        print()
        print("Nästa steg:")
        print("  1. Skapa .env-fil med OPENAI_API_KEY (om behövs)")
        print("  2. Kör: python main.py -5")
        print()

        return 0

    except subprocess.CalledProcessError as e:
        print(f"❌ Installation misslyckades: {e}")
        return 1
    except KeyboardInterrupt:
        print("\n❌ Installation avbruten av användaren")
        return 1
    except Exception as e:
        print(f"❌ Oväntat fel: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
