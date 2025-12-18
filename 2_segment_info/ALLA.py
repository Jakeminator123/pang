#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ALLA_simple.py - Pipeline runner with AI research

Runs 3 steps:
1. 1_extract.py - Extract company data from content.txt
2. 2_research.py - AI web search + domain crawling/verification
3. 3_generate_mail.py - Generate personalized sales emails

Usage:
    python ALLA_simple.py

Environment variables:
    OPENAI_API_KEY - Required for steps 2 and 3
"""

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
SIMPLE_STEPS = BASE / "simple_steps"

# Load .env
try:
    from dotenv import load_dotenv

    env_path = BASE.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass


def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str):
    print(f"[{ts()}] {msg}")


def run_step(script_path: Path) -> tuple[int, float]:
    """Run a step and return (exit_code, duration)."""
    log(f"Starting: {script_path.name}")
    start = time.time()

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(BASE),
            capture_output=False,
            text=True,
        )
        return result.returncode, time.time() - start
    except Exception as e:
        log(f"ERROR: {e}")
        return 1, time.time() - start


def main() -> int:
    # Flush all output before starting to prevent buffering issues
    import sys

    sys.stdout.flush()
    sys.stderr.flush()

    print()
    print("=" * 70)
    print("  PIPELINE WITH AI RESEARCH")
    print("=" * 70)
    log(f"Working directory: {BASE}")
    print()
    sys.stdout.flush()

    if not SIMPLE_STEPS.exists():
        log("ERROR: simple_steps folder not found")
        return 1

    # Steps
    steps = [
        ("1_extract.py", "Extract company data from content.txt"),
        ("2_research.py", "AI web search + domain verification"),
        ("3_generate_mail.py", "Generate personalized sales emails"),
    ]

    # Check scripts exist
    for script_name, _ in steps:
        if not (SIMPLE_STEPS / script_name).exists():
            log(f"ERROR: {script_name} not found")
            return 1

    # Check API key
    if not os.getenv("OPENAI_API_KEY"):
        log("WARNING: OPENAI_API_KEY not set")

    print("Steps:")
    for i, (name, desc) in enumerate(steps, 1):
        print(f"  {i}. {name}: {desc}")
    print()
    sys.stdout.flush()

    # Run
    results = []
    total_start = time.time()

    for i, (script_name, description) in enumerate(steps, 1):
        print()
        print("-" * 70)
        log(f"STEP {i}/{len(steps)}: {description}")
        print("-" * 70)
        print()
        sys.stdout.flush()  # Ensure header is printed before subprocess output

        exit_code, duration = run_step(SIMPLE_STEPS / script_name)
        results.append((script_name, exit_code, duration))

        status = "OK" if exit_code == 0 else "FAILED"
        print()
        log(f"Completed: {script_name} - {status} ({duration:.1f}s)")
        sys.stdout.flush()

        if exit_code != 0:
            log(f"ERROR: Step {i} failed")
            break

    # Summary
    total_duration = time.time() - total_start

    print()
    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print()

    all_ok = True
    for script_name, exit_code, duration in results:
        status = "OK" if exit_code == 0 else "FAILED"
        print(f"  {script_name:25} {status:10} ({duration:.1f}s)")
        if exit_code != 0:
            all_ok = False

    print()
    print(f"  Total: {total_duration:.1f}s ({total_duration / 60:.1f} min)")
    print()

    if all_ok:
        print("  SUCCESS! Check:")
        print("    - djupanalys/<date>/mail_ready.xlsx (all mails)")
        print("    - djupanalys/<date>/K*/mail.txt (individual mails)")
    else:
        print("  FAILED - check errors above")

    print()
    print("=" * 70)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
