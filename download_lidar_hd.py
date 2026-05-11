#!/usr/bin/env python3
"""
download_lidar_hd.py
=====================
Télécharge toutes les tuiles LiDAR HD MNT (0.5m) pour La Réunion
depuis le service WFS/WMS-R de l'IGN (data.geopf.fr).

~2665 tuiles, ~40 GB total. Les fichiers existants sont ignorés.

Usage:
    python3 download_lidar_hd.py
"""

import json, os, sys, time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

WFS_URL = (
    "https://data.geopf.fr/wfs/ows?SERVICE=WFS&REQUEST=GetFeature"
    "&VERSION=2.0.0&TYPENAMES=IGNF_MNT-LIDAR-HD:dalle"
    "&outputFormat=application/json"
    "&CQL_FILTER=name_download%20LIKE%20'LHD_REU%25'"
    "&COUNT=3000"
)

DEST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'LIdar')
MAX_WORKERS = 4
MAX_RETRIES = 3


def download_tile(url, filename):
    dest = os.path.join(DEST_DIR, filename)
    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        return 'skip', filename

    for attempt in range(MAX_RETRIES):
        try:
            urllib.request.urlretrieve(url, dest)
            size = os.path.getsize(dest)
            if size < 1000:
                os.remove(dest)
                return 'fail', f"{filename}: fichier trop petit ({size} bytes)"
            return 'ok', filename
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
            else:
                return 'fail', f"{filename}: {e}"

    return 'fail', filename


def main():
    print(f"{'='*60}")
    print(f"  download_lidar_hd.py — LiDAR HD La Réunion")
    print(f"{'='*60}")

    # Fetch tile list from WFS
    print(f"\n  Requête WFS pour lister les tuiles...")
    try:
        with urllib.request.urlopen(WFS_URL, timeout=30) as resp:
            data = json.load(resp)
    except Exception as e:
        sys.exit(f"Erreur WFS: {e}")

    tiles = []
    for f in data.get('features', []):
        p = f.get('properties', {})
        url = p.get('url')
        name = p.get('name_download')
        if url and name:
            tiles.append((url, name))

    print(f"  {len(tiles)} tuiles disponibles pour La Réunion")

    os.makedirs(DEST_DIR, exist_ok=True)

    # Count already downloaded
    existing = sum(1 for _, name in tiles
                   if os.path.exists(os.path.join(DEST_DIR, name))
                   and os.path.getsize(os.path.join(DEST_DIR, name)) > 1000)
    to_download = len(tiles) - existing
    print(f"  {existing} déjà téléchargées, {to_download} à télécharger")

    if to_download == 0:
        print(f"\n  Tout est déjà téléchargé !")
        return

    print(f"\n  Téléchargement en cours ({MAX_WORKERS} workers)...\n")

    ok_count = 0
    skip_count = 0
    fail_count = 0
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(download_tile, url, name): name
            for url, name in tiles
        }

        for i, future in enumerate(as_completed(futures), 1):
            status, info = future.result()
            if status == 'ok':
                ok_count += 1
                elapsed = time.time() - start_time
                rate = ok_count / elapsed if elapsed > 0 else 0
                remaining = (to_download - ok_count) / rate if rate > 0 else 0
                print(f"  [{i}/{len(tiles)}] OK   {info}  "
                      f"({ok_count}/{to_download} | ~{remaining/60:.0f} min restantes)")
            elif status == 'skip':
                skip_count += 1
            else:
                fail_count += 1
                print(f"  [{i}/{len(tiles)}] FAIL {info}")

    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"  TERMINÉ en {elapsed/60:.1f} minutes")
    print(f"  OK: {ok_count} | Ignorées: {skip_count} | Échouées: {fail_count}")
    print(f"{'='*60}")

    if fail_count > 0:
        print(f"\n  Relancez le script pour réessayer les {fail_count} tuiles échouées.")

    print(f"\n  Prochaine étape:")
    print(f"    python3 preprocess_tiles.py")
    print()


if __name__ == '__main__':
    main()
