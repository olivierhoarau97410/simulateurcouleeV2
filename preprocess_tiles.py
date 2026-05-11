#!/usr/bin/env python3
"""
preprocess_tiles.py
====================
Generates tiled binary terrain data for SIMUL_LAVE_2.5D from:
  - LITTO3D .asc files (5m resolution, 200x200 cells per tile)
  - LiDAR HD .tif files (0.5m resolution, resampled to 5m => 200x200)

LiDAR HD has priority when both sources cover the same tile.

Output structure:
  tiles/
    manifest.json          -- tile index + global metadata
    overview.bin           -- low-res terrain overview (Float32Array)
    overview_hs.bin        -- low-res hillshade overview (Float32Array)
    terrain/
      EEEE_NNNNNNN.bin     -- Float32Array 200x200 (terrain altitude)
      EEEE_NNNNNNN_hs.bin  -- Float32Array 200x200 (hillshade)

Usage:
    python3 preprocess_tiles.py
"""

import numpy as np
import os, sys, json, glob, struct

# ─── Configuration ────────────────────────────────────────────────────────────

LITTO3D_DIR = '/tmp/lidar_extract'
LIDAR_HD_DIR = 'LIdar'
OUTPUT_DIR = 'tiles'
TERRAIN_DIR = os.path.join(OUTPUT_DIR, 'terrain')

TILE_SIZE = 200       # cells per tile side (200 x 200 = 1km at 5m/cell)
CELL_RES  = 5.0       # meters per cell

# Overview resolution: 1 pixel per 1km tile
OVERVIEW_SUBSAMPLE = 1

# ─── Helpers ──────────────────────────────────────────────────────────────────

def fill_nodata(arr, nodata_val=-9999.0, iterations=30):
    """Fill nodata by propagation from valid neighbors."""
    result = arr.copy()
    mask = (result <= nodata_val - 1) | ~np.isfinite(result)
    if not mask.any():
        return result
    for _ in range(iterations):
        if not mask.any():
            break
        for dy, dx in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]:
            shifted = np.roll(np.roll(result, dy, axis=0), dx, axis=1)
            s_valid = ~((shifted <= nodata_val - 1) | ~np.isfinite(shifted))
            to_fill = mask & s_valid
            result[to_fill] = shifted[to_fill]
            mask &= ~to_fill
    result[mask] = 0.0
    return result


def compute_hillshade(terrain, cell_size=5.0, azimuth=315, altitude=35, ve=2.0):
    """Compute hillshade from a terrain array."""
    az = azimuth * np.pi / 180
    alt = altitude * np.pi / 180
    lx = np.sin(az) * np.cos(alt)
    ly = np.cos(az) * np.cos(alt)
    lz = np.sin(alt)

    dzdx = (np.roll(terrain, -1, axis=1) - np.roll(terrain, 1, axis=1)) / (2 * cell_size) * ve
    dzdy = (np.roll(terrain, -1, axis=0) - np.roll(terrain, 1, axis=0)) / (2 * cell_size) * ve
    mag = np.sqrt(dzdx**2 + dzdy**2 + 1.0)
    hs = np.clip((-dzdx * lx - dzdy * ly + lz) / mag, 0.0, 1.0)
    return hs.astype(np.float32)


def read_asc_file(filepath):
    """Read an ESRI ASCII grid file. Returns (data, header_dict)."""
    KNOWN_KEYS = {'ncols', 'nrows', 'xllcorner', 'yllcorner', 'xllcenter',
                  'yllcenter', 'cellsize', 'nodata_value'}
    header = {}
    header_lines = 0
    with open(filepath, 'r') as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 2 and parts[0].lower() in KNOWN_KEYS:
                key = parts[0].lower()
                try:
                    header[key] = float(parts[1])
                except ValueError:
                    pass
                header_lines += 1
            else:
                break

    ncols = int(header.get('ncols', 200))
    nrows = int(header.get('nrows', 200))
    nodata = header.get('nodata_value', -9999.9)

    # Read data line by line to handle ragged lines (coastal tiles)
    data = np.full((nrows, ncols), nodata, dtype=np.float32)
    with open(filepath, 'r') as f:
        for _ in range(header_lines):
            next(f)
        for row in range(nrows):
            line = f.readline()
            if not line:
                break
            vals = line.strip().split()
            n = min(len(vals), ncols)
            for col in range(n):
                try:
                    data[row, col] = float(vals[col])
                except ValueError:
                    data[row, col] = nodata

    # ASC files: row 0 = NORTH → flip to row 0 = SOUTH
    data = np.flipud(data)

    # Fill nodata
    data[np.abs(data - nodata) < 1.0] = -9999.0
    data = fill_nodata(data)

    # Upsample from native 5m (200x200) to 2m (500x500) via bilinear interpolation
    if data.shape != (TILE_SIZE, TILE_SIZE):
        from scipy.ndimage import zoom as scipy_zoom
        zoom_factor = TILE_SIZE / data.shape[0]
        data = scipy_zoom(data, zoom_factor, order=1).astype(np.float32)
        # Ensure exact size
        if data.shape != (TILE_SIZE, TILE_SIZE):
            result = np.zeros((TILE_SIZE, TILE_SIZE), dtype=np.float32)
            h_copy = min(data.shape[0], TILE_SIZE)
            w_copy = min(data.shape[1], TILE_SIZE)
            result[:h_copy, :w_copy] = data[:h_copy, :w_copy]
            data = result

    return data, header


def read_tif_file(filepath):
    """Read a GeoTIFF and resample from 0.5m to 2m resolution (500x500 output)."""
    import rasterio
    from rasterio.enums import Resampling

    with rasterio.open(filepath) as src:
        data = src.read(
            1,
            out_shape=(TILE_SIZE, TILE_SIZE),
            resampling=Resampling.bilinear
        ).astype(np.float32)

        nodata = src.nodata if src.nodata is not None else -9999.0
        data[data == nodata] = np.nan

    # rasterio: row 0 = NORTH → flip to row 0 = SOUTH
    data = np.flipud(data)
    data = fill_nodata(np.where(np.isnan(data), -9999.0, data))
    return data


def compute_hillshade_with_neighbors(tile_data, neighbors, cell_size=5.0):
    """Compute hillshade for a tile, using neighbor tiles for border accuracy.

    neighbors is a dict with keys like 'N','S','E','W','NE','NW','SE','SW'
    containing the neighbor tile data (200x200) or None.
    """
    # Build a padded array using 1-pixel borders from neighbors
    pad = 1
    H, W = tile_data.shape
    padded = np.zeros((H + 2*pad, W + 2*pad), dtype=np.float32)
    padded[pad:pad+H, pad:pad+W] = tile_data

    # Fill borders from neighbors or mirror
    # Top row (North neighbor)
    if neighbors.get('N') is not None:
        padded[pad+H, pad:pad+W] = neighbors['N'][0, :]  # South row of N neighbor
    else:
        padded[pad+H, pad:pad+W] = tile_data[-1, :]

    # Bottom row (South neighbor)
    if neighbors.get('S') is not None:
        padded[0, pad:pad+W] = neighbors['S'][-1, :]  # North row of S neighbor
    else:
        padded[0, pad:pad+W] = tile_data[0, :]

    # Right col (East neighbor)
    if neighbors.get('E') is not None:
        padded[pad:pad+H, pad+W] = neighbors['E'][:, 0]
    else:
        padded[pad:pad+H, pad+W] = tile_data[:, -1]

    # Left col (West neighbor)
    if neighbors.get('W') is not None:
        padded[pad:pad+H, 0] = neighbors['W'][:, -1]
    else:
        padded[pad:pad+H, 0] = tile_data[:, 0]

    # Corners
    padded[0, 0] = padded[1, 0]
    padded[0, pad+W] = padded[1, pad+W]
    padded[pad+H, 0] = padded[pad+H-1, 0]
    padded[pad+H, pad+W] = padded[pad+H-1, pad+W]

    hs_full = compute_hillshade(padded, cell_size)
    return hs_full[pad:pad+H, pad:pad+W]


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"{'='*60}")
    print(f"  preprocess_tiles.py — La Reunion terrain tiles")
    print(f"{'='*60}")

    # ── Step 1: Scan all available tiles ──────────────────────────────────────

    # Dict: (E_km, N_km) -> {'source': 'litto3d'|'lidar_hd', 'path': ...}
    tiles = {}

    # 1a. Scan LITTO3D .asc files
    asc_pattern = os.path.join(LITTO3D_DIR, '*/LITTO3D_REU_*_*_*/MNT5m/*.asc')
    asc_files = glob.glob(asc_pattern)
    print(f"\n  Scanning LITTO3D: {len(asc_files)} .asc files found")

    for f in asc_files:
        base = os.path.basename(f)
        # Pattern: LITTO3D_REU_EEEE_NNNN_MNT5_...
        parts = base.split('_')
        try:
            E = int(parts[2])
            N = int(parts[3])
            tiles[(E, N)] = {'source': 'litto3d', 'path': f}
        except (IndexError, ValueError):
            print(f"  WARNING: Could not parse tile coords from {base}")

    # 1b. Scan LiDAR HD .tif files (these override LITTO3D)
    tif_pattern = os.path.join(LIDAR_HD_DIR, 'LHD_REU_*_MNT_O_0M50_RGR92UTM40S_REUN89.tif')
    tif_files = sorted(glob.glob(tif_pattern))
    lidar_hd_count = 0
    for f in tif_files:
        base = os.path.basename(f)
        parts = base.split('_')
        try:
            E = int(parts[2])
            N = int(parts[3])
            tiles[(E, N)] = {'source': 'lidar_hd', 'path': f}
            lidar_hd_count += 1
        except (IndexError, ValueError):
            print(f"  WARNING: Could not parse tile coords from {base}")

    print(f"  Scanning LiDAR HD: {len(tif_files)} .tif files found ({lidar_hd_count} override LITTO3D)")
    print(f"\n  Total unique tiles: {len(tiles)}")

    if not tiles:
        sys.exit("ERROR: No terrain tiles found!")

    # ── Step 2: Compute global extent ─────────────────────────────────────────

    all_E = sorted(set(k[0] for k in tiles))
    all_N = sorted(set(k[1] for k in tiles))

    GLOBAL_MIN_E = min(all_E) * 1000  # meters UTM
    GLOBAL_MAX_E = (max(all_E) + 1) * 1000
    GLOBAL_MIN_N = min(all_N) * 1000
    GLOBAL_MAX_N = (max(all_N) + 1) * 1000

    # Global grid dimensions in cells
    E_range = max(all_E) - min(all_E) + 1
    N_range = max(all_N) - min(all_N) + 1
    GLOBAL_W = E_range * TILE_SIZE  # total cells in E
    GLOBAL_H = N_range * TILE_SIZE  # total cells in N

    print(f"\n  E range: {min(all_E)} - {max(all_E)} km ({E_range} tiles, {GLOBAL_W} cells)")
    print(f"  N range: {min(all_N)} - {max(all_N)} km ({N_range} tiles, {GLOBAL_H} cells)")
    print(f"  Coverage: {E_range} x {N_range} km")

    # ── Step 3: Create output directories ─────────────────────────────────────

    os.makedirs(TERRAIN_DIR, exist_ok=True)

    # ── Step 4: Read all tiles and generate .bin files ────────────────────────

    print(f"\n  Processing tiles...")
    tile_cache = {}  # (E, N) -> np.array for hillshade neighbor access
    tile_meta = {}   # (E, N) -> {alt_min, alt_max}
    processed = 0
    total = len(tiles)

    # First pass: read all tiles into cache
    for (E, N), info in sorted(tiles.items()):
        source = info['source']
        path = info['path']

        try:
            if source == 'lidar_hd':
                data = read_tif_file(path)
            else:
                data, _ = read_asc_file(path)
        except Exception as ex:
            print(f"  ERROR reading {path}: {ex}")
            continue

        # Ensure correct shape (2D, TILE_SIZE x TILE_SIZE)
        if data.ndim == 1:
            side = int(np.sqrt(len(data)))
            if side * side == len(data):
                data = data.reshape(side, side)
            else:
                print(f"  WARNING: 1D data with {len(data)} values, skipping {E}_{N}")
                continue
        if data.shape != (TILE_SIZE, TILE_SIZE):
            result = np.zeros((TILE_SIZE, TILE_SIZE), dtype=np.float32)
            h_copy = min(data.shape[0], TILE_SIZE)
            w_copy = min(data.shape[1], TILE_SIZE)
            result[:h_copy, :w_copy] = data[:h_copy, :w_copy]
            data = result

        tile_cache[(E, N)] = data

        valid = data[data > -9000]
        alt_min = float(valid.min()) if len(valid) else 0.0
        alt_max = float(valid.max()) if len(valid) else 0.0
        tile_meta[(E, N)] = {'alt_min': round(alt_min, 1), 'alt_max': round(alt_max, 1)}

        processed += 1
        if processed % 50 == 0 or processed == total:
            print(f"    Read {processed}/{total} tiles...")

    print(f"  Read {processed} tiles into memory")

    # ── Step 5: Compute hillshade and write .bin files ────────────────────────

    print(f"\n  Computing hillshade and writing .bin files...")
    written = 0

    global_alt_min = float('inf')
    global_alt_max = float('-inf')

    for (E, N), data in sorted(tile_cache.items()):
        meta = tile_meta[(E, N)]
        if meta['alt_min'] < global_alt_min:
            global_alt_min = meta['alt_min']
        if meta['alt_max'] > global_alt_max:
            global_alt_max = meta['alt_max']

        # Get neighbors for hillshade
        neighbors = {
            'N': tile_cache.get((E, N + 1)),
            'S': tile_cache.get((E, N - 1)),
            'E': tile_cache.get((E + 1, N)),
            'W': tile_cache.get((E - 1, N)),
        }

        hs = compute_hillshade_with_neighbors(data, neighbors, CELL_RES)

        # Write terrain .bin
        key = f"{E}_{N}"
        terrain_path = os.path.join(TERRAIN_DIR, f"{key}.bin")
        data.astype(np.float32).tofile(terrain_path)

        # Write hillshade .bin
        hs_path = os.path.join(TERRAIN_DIR, f"{key}_hs.bin")
        hs.astype(np.float32).tofile(hs_path)

        written += 1
        if written % 50 == 0 or written == len(tile_cache):
            print(f"    Written {written}/{len(tile_cache)} tiles...")

    print(f"  Written {written} tile pairs (terrain + hillshade)")

    # ── Step 6: Generate overview (low-res minimap) ───────────────────────────

    print(f"\n  Generating overview...")

    # Overview: 1 pixel per tile
    OV_W = E_range
    OV_H = N_range
    overview = np.zeros((OV_H, OV_W), dtype=np.float32)
    overview_hs = np.zeros((OV_H, OV_W), dtype=np.float32)

    min_E_val = min(all_E)
    min_N_val = min(all_N)

    for (E, N), data in tile_cache.items():
        ei = E - min_E_val
        ni = N - min_N_val
        # Mean altitude for overview pixel
        valid = data[data > -9000]
        overview[ni, ei] = float(np.mean(valid)) if len(valid) else 0.0

    # Compute hillshade on overview
    overview_hs = compute_hillshade(overview, cell_size=1.0)

    # Save overview
    overview_path = os.path.join(OUTPUT_DIR, 'overview.bin')
    overview.astype(np.float32).tofile(overview_path)

    overview_hs_path = os.path.join(OUTPUT_DIR, 'overview_hs.bin')
    overview_hs.astype(np.float32).tofile(overview_hs_path)

    print(f"  Overview: {OV_W} x {OV_H} pixels")

    # ── Step 7: Generate manifest.json ────────────────────────────────────────

    print(f"\n  Writing manifest.json...")

    # Build tile list for manifest
    tile_list = {}
    for (E, N), meta in tile_meta.items():
        key = f"{E}_{N}"
        tile_list[key] = {
            'E': E, 'N': N,
            'alt_min': meta['alt_min'],
            'alt_max': meta['alt_max'],
            'source': tiles[(E, N)]['source']
        }

    manifest = {
        'version': 1,
        'tile_size': TILE_SIZE,
        'cell_resolution': CELL_RES,
        'global_min_E': GLOBAL_MIN_E,
        'global_max_E': GLOBAL_MAX_E,
        'global_min_N': GLOBAL_MIN_N,
        'global_max_N': GLOBAL_MAX_N,
        'global_W': GLOBAL_W,
        'global_H': GLOBAL_H,
        'E_range': E_range,
        'N_range': N_range,
        'min_E_km': min(all_E),
        'max_E_km': max(all_E),
        'min_N_km': min(all_N),
        'max_N_km': max(all_N),
        'alt_min': round(global_alt_min, 1),
        'alt_max': round(global_alt_max, 1),
        'overview_W': OV_W,
        'overview_H': OV_H,
        'tile_count': len(tile_list),
        'tiles': tile_list
    }

    manifest_path = os.path.join(OUTPUT_DIR, 'manifest.json')
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)

    # ── Summary ───────────────────────────────────────────────────────────────

    total_bin_size = sum(
        os.path.getsize(os.path.join(TERRAIN_DIR, f))
        for f in os.listdir(TERRAIN_DIR) if f.endswith('.bin')
    )

    print(f"\n{'='*60}")
    print(f"  DONE!")
    print(f"{'='*60}")
    print(f"  Tiles generated:  {written}")
    print(f"  Coverage:         {E_range} x {N_range} km")
    print(f"  Global extent:    E {GLOBAL_MIN_E/1000:.0f}-{GLOBAL_MAX_E/1000:.0f} km | N {GLOBAL_MIN_N/1000:.0f}-{GLOBAL_MAX_N/1000:.0f} km")
    print(f"  Altitude:         {global_alt_min:.0f} - {global_alt_max:.0f} m")
    print(f"  Total .bin size:  {total_bin_size / 1e6:.1f} MB")
    print(f"  Overview:         {OV_W} x {OV_H} pixels")
    print(f"\n  Next steps:")
    print(f"    cd {os.path.dirname(os.path.abspath(__file__))}")
    print(f"    python3 -m http.server 8765")
    print(f"    -> open http://localhost:8765/simul_lave_25d_RUN.html")
    print()


if __name__ == '__main__':
    main()
