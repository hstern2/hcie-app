#!/usr/bin/env python
"""
Post-install script for hcie-app.

Downloads the HCIE database files (stored in Git LFS) and patches the
installed hcie package so it can find them at runtime.

Usage:
    python postinstall.py

This is idempotent — safe to run multiple times.
"""

import importlib
import importlib.util
import os
import sys
import urllib.request

DATA_FILES = {
    "MoBiVic_2.json": "https://github.com/BrennanGroup/HCIE/raw/main/Data/MoBiVic_2.json",
    "mobivic_by_hash.json": "https://github.com/BrennanGroup/HCIE/raw/main/Data/mobivic_by_hash.json",
}

PATCH_OLD = 'importlib.resources.files("Data")'
PATCH_NEW = 'importlib.resources.files("hcie.Data")'


def get_hcie_install_dir():
    """Find where the hcie package is installed."""
    spec = importlib.util.find_spec("hcie")
    if spec is None or spec.origin is None:
        print("ERROR: hcie package not found. Install it first:", file=sys.stderr)
        print("  uv pip install -e .", file=sys.stderr)
        sys.exit(1)
    return os.path.dirname(spec.origin)


def download_data_files(data_dir):
    """Download the LFS-hosted JSON files into data_dir."""
    os.makedirs(data_dir, exist_ok=True)

    init_file = os.path.join(data_dir, "__init__.py")
    if not os.path.exists(init_file):
        with open(init_file, "w") as f:
            pass

    for filename, url in DATA_FILES.items():
        dest = os.path.join(data_dir, filename)
        if os.path.exists(dest) and os.path.getsize(dest) > 1000:
            print(f"  {filename}: already present ({os.path.getsize(dest)} bytes), skipping")
            continue
        print(f"  {filename}: downloading from GitHub...")
        urllib.request.urlretrieve(url, dest)
        size = os.path.getsize(dest)
        if size < 1000:
            print(f"  WARNING: {filename} is only {size} bytes — download may have failed")
        else:
            print(f"  {filename}: {size:,} bytes")


def patch_database_search(hcie_dir):
    """Patch database_search.py to load data from hcie.Data instead of Data."""
    db_search = os.path.join(hcie_dir, "database_search.py")
    with open(db_search, "r") as f:
        content = f.read()

    if PATCH_NEW in content:
        print("  database_search.py: already patched, skipping")
        return

    if PATCH_OLD not in content:
        print("  WARNING: database_search.py does not contain expected pattern — skipping patch")
        return

    patched = content.replace(PATCH_OLD, PATCH_NEW)
    with open(db_search, "w") as f:
        f.write(patched)
    print("  database_search.py: patched successfully")


def main():
    print("hcie-app post-install")
    print()

    hcie_dir = get_hcie_install_dir()
    print(f"Found hcie at: {hcie_dir}")
    print()

    data_dir = os.path.join(hcie_dir, "Data")
    print("Downloading data files...")
    download_data_files(data_dir)
    print()

    print("Patching hcie package...")
    patch_database_search(hcie_dir)
    print()

    print("Done! You can now run:")
    print("  streamlit run hcie_app/app.py")


if __name__ == "__main__":
    main()
