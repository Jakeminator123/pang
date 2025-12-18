"""
Script to zip all date folders in data_input directory.
Zips are saved to ../data_bundles/ for GitHub deployment.

Usage:
    python zip_folders.py
"""

import re
import zipfile
from pathlib import Path


def is_date_folder(name: str) -> bool:
    """Check if folder name is a date format (YYYYMMDD)"""
    return bool(re.match(r"^\d{8}$", name))


def zip_folder(folder_path: Path, output_path: Path) -> None:
    """Create a zip file from a folder"""
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file in folder_path.rglob("*"):
            if file.is_file() and not file.name.endswith(".zip"):
                arcname = file.relative_to(folder_path)
                zipf.write(file, arcname)
                print(f"  Added: {arcname}")


def main():
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    bundles_dir = project_root / "data_bundles"

    # Create output directory
    bundles_dir.mkdir(exist_ok=True)

    # Find all date folders
    date_folders = [
        d for d in script_dir.iterdir() if d.is_dir() and is_date_folder(d.name)
    ]

    if not date_folders:
        print("No date folders found (format: YYYYMMDD)")
        return

    print(f"Found {len(date_folders)} date folder(s):\n")

    for folder in sorted(date_folders):
        zip_name = f"{folder.name}.zip"
        zip_path = bundles_dir / zip_name

        print(f"Zipping {folder.name}/")
        zip_folder(folder, zip_path)

        size_mb = zip_path.stat().st_size / (1024 * 1024)
        print(f"  -> Created: data_bundles/{zip_name} ({size_mb:.2f} MB)\n")

    print("Done! Zip files are in data_bundles/")
    print("Push to GitHub and Render will extract them to /var/data")


if __name__ == "__main__":
    main()
