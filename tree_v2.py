#!/usr/bin/env python3
from pathlib import Path

# Lista med namn som ska ignoreras
IGNORE = {".git", ".cursoerignore", ".cursorrules", ".cursor"}

def tree(path: Path, prefix: str = '', file=None):
    # Filtrera bort ignorerade filer/mappar
    contents = [c for c in path.iterdir() if c.name not in IGNORE]
    contents = sorted(contents)
    pointers = ['├── '] * (len(contents) - 1) + ['└── '] if contents else []

    for pointer, child in zip(pointers, contents):
        line = prefix + pointer + child.name
        print(line)
        print(line, file=file)
        if child.is_dir():
            extension = '│   ' if pointer == '├── ' else '    '
            tree(child, prefix + extension, file=file)

if __name__ == "__main__":
    cwd = Path.cwd()
    output_file = cwd / "tree_structure.txt"

    with output_file.open('w', encoding='utf-8') as f:
        print(cwd.name)
        print(cwd.name, file=f)
        tree(cwd, file=f)
