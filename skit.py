from __future__ import annotations

import argparse
import ast
import os
import sys
import sysconfig
from pathlib import Path


DEFAULT_SKIP_DIRS = {
    ".git", ".hg", ".svn",
    "__pycache__",
    ".venv", "venv", "env",
    ".tox",
    ".mypy_cache", ".pytest_cache",
    "site-packages",
    "build", "dist",
    "node_modules",
}


def get_stdlib_names() -> set[str]:
    # Bäst: Python 3.10+ (ofta 3.11/3.12 på Win 11) har detta.
    names = set(getattr(sys, "stdlib_module_names", ()))
    names.update(sys.builtin_module_names)

    # Fallback om stdlib_module_names saknas: scanna stdlib-katalogen.
    if not names:
        stdlib_path = sysconfig.get_paths().get("stdlib")
        if stdlib_path:
            p = Path(stdlib_path)
            if p.exists():
                # .py-filer
                for f in p.glob("*.py"):
                    names.add(f.stem)
                # paketmappar
                for d in p.iterdir():
                    if d.is_dir() and (d / "__init__.py").exists():
                        names.add(d.name)

    # Några vanliga “ska inte med”
    names.update({"__future__", "typing", "types"})
    return names


def iter_py_files(root: Path, skip_dirs: set[str]) -> list[Path]:
    py_files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skippa mappar tidigt
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for fn in filenames:
            if fn.endswith(".py"):
                py_files.append(Path(dirpath) / fn)
    return py_files


def parse_imports(py_file: Path) -> set[str]:
    try:
        text = py_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = py_file.read_text(encoding="latin-1", errors="ignore")

    try:
        tree = ast.parse(text, filename=str(py_file))
    except SyntaxError:
        return set()

    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # Ignorera relativa imports: from .foo import bar
            if getattr(node, "level", 0) and node.level > 0:
                continue
            if node.module:
                mods.add(node.module.split(".")[0])

    return mods


def get_local_top_level_names(root: Path, py_files: list[Path]) -> set[str]:
    """
    Heuristik för lokala imports:
    - root/*.py => lokalt modulnamn
    - root/<paket>/... => lokalt paketnamn (första mappen i sökvägen)
    """
    local: set[str] = set()

    for p in py_files:
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue

        if len(rel.parts) == 1:
            local.add(p.stem)
        else:
            local.add(rel.parts[0])

    return local


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Scanna en mapp rekursivt och lista troliga tredjeparts-imports (requirements-gissning)."
    )
    ap.add_argument("path", nargs="?", default=".", help="Rotmapp att scanna (default: .)")
    ap.add_argument("--write", default="", help="Skriv resultat till fil (t.ex. requirements_guess.txt)")
    ap.add_argument("--skip", action="append", default=[], help="Skippa ytterligare mappnamn (kan anges flera gånger)")
    args = ap.parse_args()

    root = Path(args.path).resolve()
    skip_dirs = set(DEFAULT_SKIP_DIRS)
    skip_dirs.update(args.skip)

    stdlib = get_stdlib_names()
    py_files = iter_py_files(root, skip_dirs)
    local = get_local_top_level_names(root, py_files)

    imported: set[str] = set()
    for f in py_files:
        imported |= parse_imports(f)

    # Filtrera: bort med stdlib, lokalt och “konstiga” namn
    candidates = {
        m for m in imported
        if m and m not in stdlib and m not in local and not m.startswith("_")
    }

    result = sorted(candidates, key=str.lower)

    if args.write:
        out = Path(args.write).resolve()
        out.write_text("\n".join(result) + ("\n" if result else ""), encoding="utf-8")
        print(f"Skrev {len(result)} rader till: {out}")
    else:
        print("\n".join(result))

    print("\nOBS: Detta är import-namn (inte alltid samma som pip-namn). Ex: PIL -> Pillow, bs4 -> beautifulsoup4.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
