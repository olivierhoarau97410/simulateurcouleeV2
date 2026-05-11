#!/usr/bin/env python3
"""
recompute_hillshade.py
======================
Recomputes all _hs.bin hillshade files from the existing terrain .bin files,
using neighbor-aware padding to eliminate tile-boundary seam artifacts.

Run from the lave/ directory:
    python3 recompute_hillshade.py
"""

import numpy as np
import os, sys, json

TILES_DIR   = 'tiles/terrain'
OUTPUT_DIR  = 'tiles'
MANIFEST    = 'tiles/manifest.json'


def compute_hillshade(terrain, cell_size=5.0, azimuth=315, altitude=35, ve=2.0):
    az  = azimuth  * np.pi / 180
    alt = altitude * np.pi / 180
    lx  = np.sin(az) * np.cos(alt)
    ly  = np.cos(az) * np.cos(alt)
    lz  = np.sin(alt)
    dzdx = (np.roll(terrain, -1, axis=1) - np.roll(terrain,  1, axis=1)) / (2 * cell_size) * ve
    dzdy = (np.roll(terrain, -1, axis=0) - np.roll(terrain,  1, axis=0)) / (2 * cell_size) * ve
    mag  = np.sqrt(dzdx**2 + dzdy**2 + 1.0)
    hs   = np.clip((-dzdx * lx - dzdy * ly + lz) / mag, 0.0, 1.0)
    return hs.astype(np.float32)


def compute_hillshade_with_neighbors(tile_data, neighbors, cell_size=5.0):
    pad = 1
    H, W = tile_data.shape
    padded = np.zeros((H + 2*pad, W + 2*pad), dtype=np.float32)
    padded[pad:pad+H, pad:pad+W] = tile_data

    # North border (row above tile = south row of N neighbor)
    padded[pad+H, pad:pad+W] = neighbors['N'][0, :] if neighbors.get('N') is not None else tile_data[-1, :]
    # South border (row below tile = north row of S neighbor)
    padded[0,     pad:pad+W] = neighbors['S'][-1,:] if neighbors.get('S') is not None else tile_data[0,  :]
    # East border  (col right of tile = west col of E neighbor)
    padded[pad:pad+H, pad+W] = neighbors['E'][:, 0] if neighbors.get('E') is not None else tile_data[:, -1]
    # West border  (col left of tile  = east col of W neighbor)
    padded[pad:pad+H, 0]     = neighbors['W'][:,-1] if neighbors.get('W') is not None else tile_data[:,  0]

    # Corners (nearest interior border value)
    padded[0,     0    ] = padded[1,     0    ]
    padded[0,     pad+W] = padded[1,     pad+W]
    padded[pad+H, 0    ] = padded[pad+H-1, 0  ]
    padded[pad+H, pad+W] = padded[pad+H-1, pad+W]

    hs_full = compute_hillshade(padded, cell_size)
    return hs_full[pad:pad+H, pad:pad+W]


def main():
    print("=" * 60)
    print("  recompute_hillshade.py — neighbor-aware hillshade repair")
    print("=" * 60)

    with open(MANIFEST) as f:
        manifest = json.load(f)

    TILE_SIZE = manifest['tile_size']
    CELL_RES  = manifest['cell_resolution']
    MIN_E_KM  = manifest['min_E_km']
    MIN_N_KM  = manifest['min_N_km']
    OV_W      = manifest['overview_W']
    OV_H      = manifest['overview_H']

    # -- Step 1: Load all terrain tiles into memory ---------------------------
    print(f"\n  Loading {manifest['tile_count']} terrain tiles...")
    tile_cache = {}   # (E, N) -> np.array
    loaded = 0
    for key, info in manifest['tiles'].items():
        E, N = info['E'], info['N']
        path = os.path.join(TILES_DIR, f'{key}.bin')
        try:
            data = np.fromfile(path, dtype=np.float32).reshape(TILE_SIZE, TILE_SIZE)
            tile_cache[(E, N)] = data
            loaded += 1
        except Exception as ex:
            print(f"  WARNING: could not load {key}.bin: {ex}")
    print(f"  Loaded {loaded} tiles.")

    # -- Step 2: Recompute hillshade for each tile with neighbor padding ------
    print(f"\n  Recomputing hillshade (with neighbor padding)...")
    written = 0
    for idx, ((E, N), data) in enumerate(sorted(tile_cache.items())):
        neighbors = {
            'N': tile_cache.get((E, N + 1)),
            'S': tile_cache.get((E, N - 1)),
            'E': tile_cache.get((E + 1, N)),
            'W': tile_cache.get((E - 1, N)),
        }
        hs = compute_hillshade_with_neighbors(data, neighbors, CELL_RES)
        hs_path = os.path.join(TILES_DIR, f'{E}_{N}_hs.bin')
        hs.tofile(hs_path)
        written += 1
        if written % 200 == 0 or written == loaded:
            print(f"    {written}/{loaded} done...")

    print(f"  Wrote {written} hillshade files.")

    # -- Step 3: Recompute overview hillshade ---------------------------------
    print(f"\n  Recomputing overview hillshade...")
    overview = np.fromfile(os.path.join(OUTPUT_DIR, 'overview.bin'), dtype=np.float32).reshape(OV_H, OV_W)
    overview_hs = compute_hillshade(overview, cell_size=1.0)
    overview_hs.tofile(os.path.join(OUTPUT_DIR, 'overview_hs.bin'))
    print(f"  Overview hillshade updated ({OV_W}x{OV_H}).")

    print(f"\n{'=' * 60}")
    print(f"  DONE — hillshade seams fixed!")
    print(f"  Reload the simulator in your browser (Ctrl+Shift+R).")
    print(f"{'=' * 60}\n")


if __name__ == '__main__':
    main()
