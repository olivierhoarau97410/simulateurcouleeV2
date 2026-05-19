// tile_loader.js — Tile-based terrain loader with Working Region (WR)
// Replaces terrain_lidar.js for SIMUL_LAVE_2.5D
//
// Exports (global variables):
//   MANIFEST         — parsed manifest.json
//   wrTerrain        — Float32Array WR_W * WR_H (terrain altitude, row 0 = South)
//   wrHillshd        — Float32Array WR_W * WR_H (hillshade)
//   WR_W, WR_H       — Working Region dimensions in cells
//   wr_gx0, wr_gy0   — WR origin in global grid coords (cells from SW corner)
//   GLOBAL_MIN_E, GLOBAL_MAX_E, GLOBAL_MIN_N, GLOBAL_MAX_N — UTM bounds (meters)
//   TILE_SIZE         — cells per tile side (200)
//   CELL_RES          — meters per cell (5.0)

// ─── Configuration ───────────────────────────────────────────────────────────

const WR_TILES_W = 16;  // WR width in tiles (16 tiles = 16 km)
const WR_TILES_H = 16;  // WR height in tiles (16 tiles = 16 km)
const WR_EXPAND_MARGIN = 600; // cells from WR border to trigger expansion (3 km buffer)

const TILE_CACHE_MAX = 800; // max tiles in LRU cache

// ─── Global state ────────────────────────────────────────────────────────────

let MANIFEST = null;
let TILE_SIZE = 200;
let CELL_RES = 5.0;
let GLOBAL_MIN_E = 0, GLOBAL_MAX_E = 0, GLOBAL_MIN_N = 0, GLOBAL_MAX_N = 0;
let GLOBAL_W = 0, GLOBAL_H = 0;
let MIN_E_KM = 0, MIN_N_KM = 0, MAX_E_KM = 0, MAX_N_KM = 0;
let ALT_MIN_GLOBAL = 0, ALT_MAX_GLOBAL = 0;

// Working Region
let WR_W = 0, WR_H = 0;
let wr_gx0 = 0, wr_gy0 = 0;  // WR origin in global cell coords
let wrTerrain = null;  // Float32Array
let wrHillshd = null;  // Float32Array

// Overview (low-res minimap)
let overviewTerrain = null;  // Float32Array OV_W * OV_H
let overviewHillshd = null;  // Float32Array OV_W * OV_H
let OV_W = 0, OV_H = 0;

// ─── Tile Cache (LRU) ───────────────────────────────────────────────────────

const tileCache = new Map();      // key -> { terrain: Float32Array, hillshade: Float32Array, lastUsed: number }
let tileCacheOrder = [];           // keys ordered by last use (oldest first)
let tileCacheAccessCount = 0;

function evictOldTiles() {
    while (tileCache.size > TILE_CACHE_MAX) {
        // Find least recently used
        let oldestKey = null, oldestTime = Infinity;
        for (const [key, entry] of tileCache) {
            if (entry.lastUsed < oldestTime) {
                oldestTime = entry.lastUsed;
                oldestKey = key;
            }
        }
        if (oldestKey) tileCache.delete(oldestKey);
        else break;
    }
}

// ─── Fetch a single tile ─────────────────────────────────────────────────────

async function fetchTile(key) {
    // Check cache first
    if (tileCache.has(key)) {
        const entry = tileCache.get(key);
        entry.lastUsed = ++tileCacheAccessCount;
        return entry;
    }

    // Fetch terrain + hillshade in parallel
    const [terrainBuf, hsBuf] = await Promise.all([
        fetch(`tiles/terrain/${key}.bin`).then(r => {
            if (!r.ok) throw new Error(`Tile ${key}.bin not found`);
            return r.arrayBuffer();
        }),
        fetch(`tiles/terrain/${key}_hs.bin`).then(r => {
            if (!r.ok) throw new Error(`Tile ${key}_hs.bin not found`);
            return r.arrayBuffer();
        })
    ]);

    const entry = {
        terrain: new Float32Array(terrainBuf),
        hillshade: new Float32Array(hsBuf),
        lastUsed: ++tileCacheAccessCount
    };

    tileCache.set(key, entry);
    evictOldTiles();

    return entry;
}

// ─── Load manifest ──────────────────────────────────────────────────────────

async function loadManifest() {
    const resp = await fetch('tiles/manifest.json');
    if (!resp.ok) throw new Error('manifest.json not found — run preprocess_tiles.py first');
    MANIFEST = await resp.json();

    TILE_SIZE = MANIFEST.tile_size;
    CELL_RES = MANIFEST.cell_resolution;
    GLOBAL_MIN_E = MANIFEST.global_min_E;
    GLOBAL_MAX_E = MANIFEST.global_max_E;
    GLOBAL_MIN_N = MANIFEST.global_min_N;
    GLOBAL_MAX_N = MANIFEST.global_max_N;
    GLOBAL_W = MANIFEST.global_W;
    GLOBAL_H = MANIFEST.global_H;
    MIN_E_KM = MANIFEST.min_E_km;
    MIN_N_KM = MANIFEST.min_N_km;
    MAX_E_KM = MANIFEST.max_E_km;
    MAX_N_KM = MANIFEST.max_N_km;
    ALT_MIN_GLOBAL = MANIFEST.alt_min;
    ALT_MAX_GLOBAL = MANIFEST.alt_max;
    OV_W = MANIFEST.overview_W;
    OV_H = MANIFEST.overview_H;

    // Load overview
    const [ovBuf, ovHsBuf] = await Promise.all([
        fetch('tiles/overview.bin').then(r => r.arrayBuffer()),
        fetch('tiles/overview_hs.bin').then(r => r.arrayBuffer())
    ]);
    overviewTerrain = new Float32Array(ovBuf);
    overviewHillshd = new Float32Array(ovHsBuf);
}

// ─── Blit a tile into the Working Region ─────────────────────────────────────

function blitTileIntoWR(tileEntry, tileE, tileN) {
    // Convert tile position to global cell coords
    const tile_gx0 = (tileE - MIN_E_KM) * TILE_SIZE;
    const tile_gy0 = (tileN - MIN_N_KM) * TILE_SIZE;

    // Compute overlap with WR
    const src_x0 = Math.max(0, wr_gx0 - tile_gx0);
    const src_y0 = Math.max(0, wr_gy0 - tile_gy0);
    const dst_x0 = Math.max(0, tile_gx0 - wr_gx0);
    const dst_y0 = Math.max(0, tile_gy0 - wr_gy0);
    const copy_w = Math.min(TILE_SIZE - src_x0, WR_W - dst_x0);
    const copy_h = Math.min(TILE_SIZE - src_y0, WR_H - dst_y0);

    if (copy_w <= 0 || copy_h <= 0) return;

    // Copy row by row using TypedArray.set for speed
    const terrain = tileEntry.terrain;
    const hillshade = tileEntry.hillshade;

    for (let row = 0; row < copy_h; row++) {
        const srcOff = (src_y0 + row) * TILE_SIZE + src_x0;
        const dstOff = (dst_y0 + row) * WR_W + dst_x0;
        wrTerrain.set(terrain.subarray(srcOff, srcOff + copy_w), dstOff);
        wrHillshd.set(hillshade.subarray(srcOff, srcOff + copy_w), dstOff);
    }
}

// ─── Grow WR to the right (no relocation — preserves all physics state) ──────

async function growWorkingRegionRight(nTiles, onProgress) {
    const addW  = nTiles * TILE_SIZE;
    const NEW_W = WR_W + addW;

    // Allocate expanded terrain arrays
    const newTerrain = new Float32Array(NEW_W * WR_H);
    const newHillshd = new Float32Array(NEW_W * WR_H);
    newHillshd.fill(0.5);

    // Copy existing data row-by-row (left portion of new arrays)
    for (let row = 0; row < WR_H; row++) {
        newTerrain.set(wrTerrain.subarray(row * WR_W, (row + 1) * WR_W), row * NEW_W);
        newHillshd.set(wrHillshd.subarray(row * WR_W, (row + 1) * WR_W), row * NEW_W);
    }

    // Update globals so blitTileIntoWR uses the new stride
    const oldWR_W   = WR_W;
    WR_W            = NEW_W;
    wrTerrain       = newTerrain;
    wrHillshd       = newHillshd;

    // Compute tile range for the new (right) columns
    const newTileE0 = Math.floor((wr_gx0 + oldWR_W) / TILE_SIZE) + MIN_E_KM;
    const wrTileN0  = Math.floor(wr_gy0 / TILE_SIZE) + MIN_N_KM;
    const nTilesY   = Math.ceil(WR_H / TILE_SIZE);

    const tilesToLoad = [];
    for (let te = newTileE0; te < newTileE0 + nTiles; te++) {
        for (let tn = wrTileN0; tn < wrTileN0 + nTilesY; tn++) {
            const key = `${te}_${tn}`;
            if (MANIFEST.tiles[key]) tilesToLoad.push({ key, E: te, N: tn });
        }
    }

    const BATCH = 8;
    for (let i = 0; i < tilesToLoad.length; i += BATCH) {
        const batch   = tilesToLoad.slice(i, i + BATCH);
        const results = await Promise.all(
            batch.map(t => fetchTile(t.key).catch(() => null))
        );
        for (let j = 0; j < batch.length; j++) {
            if (results[j]) blitTileIntoWR(results[j], batch[j].E, batch[j].N);
        }
        if (onProgress) onProgress((i + batch.length) / Math.max(1, tilesToLoad.length));
    }
    // wr_gx0/wr_gy0 unchanged — expansion is purely to the right
}

// ─── Grow WR to the left (shifts all WR-local coords by addW) ────────────────

async function growWorkingRegionLeft(nTiles, onProgress) {
    const addW  = nTiles * TILE_SIZE;
    const NEW_W = WR_W + addW;

    const newTerrain = new Float32Array(NEW_W * WR_H);
    const newHillshd = new Float32Array(NEW_W * WR_H);
    newHillshd.fill(0.5);

    // Copy old data into the RIGHT portion of the new arrays (offset by addW)
    for (let row = 0; row < WR_H; row++) {
        newTerrain.set(wrTerrain.subarray(row * WR_W, (row + 1) * WR_W), row * NEW_W + addW);
        newHillshd.set(wrHillshd.subarray(row * WR_W, (row + 1) * WR_W), row * NEW_W + addW);
    }

    // WR origin shifts left; update globals before blit so blitTileIntoWR uses correct stride/origin
    wr_gx0   -= addW;
    WR_W      = NEW_W;
    wrTerrain = newTerrain;
    wrHillshd = newHillshd;

    // Load new tiles that now cover the LEFT extension
    const newTileE0 = Math.floor(wr_gx0 / TILE_SIZE) + MIN_E_KM;
    const wrTileN0  = Math.floor(wr_gy0 / TILE_SIZE) + MIN_N_KM;
    const nTilesY   = Math.ceil(WR_H / TILE_SIZE);

    const tilesToLoad = [];
    for (let te = newTileE0; te < newTileE0 + nTiles; te++) {
        for (let tn = wrTileN0; tn < wrTileN0 + nTilesY; tn++) {
            const key = `${te}_${tn}`;
            if (MANIFEST.tiles[key]) tilesToLoad.push({ key, E: te, N: tn });
        }
    }

    const BATCH = 8;
    for (let i = 0; i < tilesToLoad.length; i += BATCH) {
        const batch   = tilesToLoad.slice(i, i + BATCH);
        const results = await Promise.all(batch.map(t => fetchTile(t.key).catch(() => null)));
        for (let j = 0; j < batch.length; j++)
            if (results[j]) blitTileIntoWR(results[j], batch[j].E, batch[j].N);
        if (onProgress) onProgress((i + batch.length) / Math.max(1, tilesToLoad.length));
    }
    return addW; // caller must shift all WR-local coords by +addW
}

// ─── Grow WR downward / South (shifts all WR-local y-coords by addH) ─────────

async function growWorkingRegionDown(nTiles, onProgress) {
    const addH  = nTiles * TILE_SIZE;
    const NEW_H = WR_H + addH;

    const newTerrain = new Float32Array(WR_W * NEW_H);
    const newHillshd = new Float32Array(WR_W * NEW_H);
    newHillshd.fill(0.5);

    // Copy old data into the UPPER portion (offset by addH rows)
    for (let row = 0; row < WR_H; row++) {
        newTerrain.set(wrTerrain.subarray(row * WR_W, (row + 1) * WR_W), (row + addH) * WR_W);
        newHillshd.set(wrHillshd.subarray(row * WR_W, (row + 1) * WR_W), (row + addH) * WR_W);
    }

    // Update globals BEFORE blit so blitTileIntoWR uses correct wr_gy0/WR_H
    wr_gy0 -= addH;
    WR_H    = NEW_H;
    wrTerrain = newTerrain;
    wrHillshd = newHillshd;

    // Load new south tiles
    const wrTileE0  = Math.floor(wr_gx0 / TILE_SIZE) + MIN_E_KM;
    const newTileN0 = Math.floor(wr_gy0 / TILE_SIZE) + MIN_N_KM;
    const nTilesX   = Math.ceil(WR_W / TILE_SIZE);

    const tilesToLoad = [];
    for (let tn = newTileN0; tn < newTileN0 + nTiles; tn++)
        for (let te = wrTileE0; te < wrTileE0 + nTilesX; te++) {
            const key = `${te}_${tn}`;
            if (MANIFEST.tiles[key]) tilesToLoad.push({ key, E: te, N: tn });
        }

    const BATCH = 8;
    for (let i = 0; i < tilesToLoad.length; i += BATCH) {
        const batch   = tilesToLoad.slice(i, i + BATCH);
        const results = await Promise.all(batch.map(t => fetchTile(t.key).catch(() => null)));
        for (let j = 0; j < batch.length; j++)
            if (results[j]) blitTileIntoWR(results[j], batch[j].E, batch[j].N);
        if (onProgress) onProgress((i + batch.length) / Math.max(1, tilesToLoad.length));
    }
    return addH; // caller must shift all WR-local y-coords by +addH
}

// ─── Grow WR upward / North (wr_gy0 unchanged, no y-coord shift) ─────────────

async function growWorkingRegionUp(nTiles, onProgress) {
    const addH  = nTiles * TILE_SIZE;
    const NEW_H = WR_H + addH;

    const newTerrain = new Float32Array(WR_W * NEW_H);
    const newHillshd = new Float32Array(WR_W * NEW_H);
    newHillshd.fill(0.5);

    // Copy old data into the LOWER portion (rows unchanged)
    for (let row = 0; row < WR_H; row++) {
        newTerrain.set(wrTerrain.subarray(row * WR_W, (row + 1) * WR_W), row * WR_W);
        newHillshd.set(wrHillshd.subarray(row * WR_W, (row + 1) * WR_W), row * WR_W);
    }

    const oldWR_H = WR_H;
    WR_H      = NEW_H;
    wrTerrain = newTerrain;
    wrHillshd = newHillshd;

    // Load new north tiles
    const wrTileE0  = Math.floor(wr_gx0 / TILE_SIZE) + MIN_E_KM;
    const newTileN0 = Math.floor((wr_gy0 + oldWR_H) / TILE_SIZE) + MIN_N_KM;
    const nTilesX   = Math.ceil(WR_W / TILE_SIZE);

    const tilesToLoad = [];
    for (let tn = newTileN0; tn < newTileN0 + nTiles; tn++)
        for (let te = wrTileE0; te < wrTileE0 + nTilesX; te++) {
            const key = `${te}_${tn}`;
            if (MANIFEST.tiles[key]) tilesToLoad.push({ key, E: te, N: tn });
        }

    const BATCH = 8;
    for (let i = 0; i < tilesToLoad.length; i += BATCH) {
        const batch   = tilesToLoad.slice(i, i + BATCH);
        const results = await Promise.all(batch.map(t => fetchTile(t.key).catch(() => null)));
        for (let j = 0; j < batch.length; j++)
            if (results[j]) blitTileIntoWR(results[j], batch[j].E, batch[j].N);
        if (onProgress) onProgress((i + batch.length) / Math.max(1, tilesToLoad.length));
    }
    return 0; // wr_gy0 unchanged, no y-shift needed
}

// ─── Setup / relocate Working Region ─────────────────────────────────────────

async function setupWorkingRegion(centerGx, centerGy, onProgress) {
    // WR dimensions
    WR_W = WR_TILES_W * TILE_SIZE;
    WR_H = WR_TILES_H * TILE_SIZE;

    // Center the WR, snapped to tile boundaries
    let wrTileE = Math.round(centerGx / TILE_SIZE) - Math.floor(WR_TILES_W / 2);
    let wrTileN = Math.round(centerGy / TILE_SIZE) - Math.floor(WR_TILES_H / 2);

    // Clamp to global bounds + ocean margin (tiles au-delà du terrain = altitude 0 = mer)
    // OCEAN_MARGIN permet au WR de déborder dans l'océan pour que la lave puisse y parvenir
    const OCEAN_MARGIN = WR_TILES_W; // jusqu'à 1 WR entier au-delà du terrain
    const maxTileE = MIN_E_KM + Math.floor(GLOBAL_W / TILE_SIZE) - WR_TILES_W + OCEAN_MARGIN;
    const maxTileN = MIN_N_KM + Math.floor(GLOBAL_H / TILE_SIZE) - WR_TILES_H + OCEAN_MARGIN;
    const minTileE = MIN_E_KM - OCEAN_MARGIN;
    const minTileN = MIN_N_KM - OCEAN_MARGIN;
    wrTileE = Math.max(minTileE, Math.min(maxTileE, wrTileE + MIN_E_KM));
    wrTileN = Math.max(minTileN, Math.min(maxTileN, wrTileN + MIN_N_KM));

    wr_gx0 = (wrTileE - MIN_E_KM) * TILE_SIZE;
    wr_gy0 = (wrTileN - MIN_N_KM) * TILE_SIZE;

    // Allocate WR arrays
    const totalCells = WR_W * WR_H;
    wrTerrain = new Float32Array(totalCells);
    wrHillshd = new Float32Array(totalCells);
    wrHillshd.fill(0.5); // default mid-gray

    // Load all tiles that overlap with WR
    const tilesToLoad = [];
    for (let te = wrTileE; te < wrTileE + WR_TILES_W; te++) {
        for (let tn = wrTileN; tn < wrTileN + WR_TILES_H; tn++) {
            const key = `${te}_${tn}`;
            if (MANIFEST.tiles[key]) {
                tilesToLoad.push({ key, E: te, N: tn });
            }
        }
    }

    // Fetch tiles (batch for parallelism, but limited concurrency)
    const BATCH = 8;
    for (let i = 0; i < tilesToLoad.length; i += BATCH) {
        const batch = tilesToLoad.slice(i, i + BATCH);
        const results = await Promise.all(
            batch.map(t => fetchTile(t.key).catch(() => null))
        );
        for (let j = 0; j < batch.length; j++) {
            if (results[j]) {
                blitTileIntoWR(results[j], batch[j].E, batch[j].N);
            }
        }
        if (onProgress) {
            onProgress(Math.min(1, (i + batch.length) / tilesToLoad.length));
        }
    }

    return { wrTileE, wrTileN };
}

// ─── Relocate WR (shift WR keeping simulation state) ────────────────────────

async function relocateWorkingRegion(newCenterGx, newCenterGy, simArrays, onProgress) {
    // Save old WR position
    const old_gx0 = wr_gx0;
    const old_gy0 = wr_gy0;
    const oldTerrain = wrTerrain;
    const oldHillshd = wrHillshd;
    const old_WR_W = WR_W;
    const old_WR_H = WR_H;

    // Setup new WR
    await setupWorkingRegion(newCenterGx, newCenterGy, onProgress);

    // Copy simulation state (h, T) from old WR to new WR
    if (simArrays && simArrays.h && simArrays.T) {
        const { h, T, h_new, fx: fxArr, fy: fyArr } = simArrays;

        // Create new simulation arrays
        const totalCells = WR_W * WR_H;
        const new_h = new Float32Array(totalCells);
        const new_T = new Float32Array(totalCells);
        new_T.fill(1200);
        const new_h_new = new Float32Array(totalCells);
        const new_fx = new Float32Array(totalCells);
        const new_fy = new Float32Array(totalCells);

        // Compute overlap between old and new WR
        const overlap_x0 = Math.max(old_gx0, wr_gx0);
        const overlap_y0 = Math.max(old_gy0, wr_gy0);
        const overlap_x1 = Math.min(old_gx0 + old_WR_W, wr_gx0 + WR_W);
        const overlap_y1 = Math.min(old_gy0 + old_WR_H, wr_gy0 + WR_H);

        if (overlap_x1 > overlap_x0 && overlap_y1 > overlap_y0) {
            const ow = overlap_x1 - overlap_x0;
            for (let gy = overlap_y0; gy < overlap_y1; gy++) {
                const oldOff = (gy - old_gy0) * old_WR_W + (overlap_x0 - old_gx0);
                const newOff = (gy - wr_gy0) * WR_W + (overlap_x0 - wr_gx0);
                new_h.set(h.subarray(oldOff, oldOff + ow), newOff);
                new_T.set(T.subarray(oldOff, oldOff + ow), newOff);
            }
        }

        // Return new arrays for the caller to adopt
        return { h: new_h, T: new_T, h_new: new_h_new, fx: new_fx, fy: new_fy };
    }

    return null;
}

// ─── Utility: global cell coords to UTM ──────────────────────────────────────

function globalCellToUTM(gx, gy) {
    return {
        E: GLOBAL_MIN_E + gx * CELL_RES,
        N: GLOBAL_MIN_N + gy * CELL_RES
    };
}

// ─── Utility: WR-local cell to global cell ───────────────────────────────────

function wrToGlobal(wx, wy) {
    return { gx: wr_gx0 + wx, gy: wr_gy0 + wy };
}

function globalToWR(gx, gy) {
    return { wx: gx - wr_gx0, wy: gy - wr_gy0 };
}

// ─── Check if WR needs expansion ─────────────────────────────────────────────

function needsWRRelocation(lava_vx0, lava_vx1, lava_vy0, lava_vy1) {
    // Check if lava bounding box is close to WR edges
    if (lava_vx0 < WR_EXPAND_MARGIN) return true;
    if (lava_vy0 < WR_EXPAND_MARGIN) return true;
    if (lava_vx1 > WR_W - WR_EXPAND_MARGIN) return true;
    if (lava_vy1 > WR_H - WR_EXPAND_MARGIN) return true;
    return false;
}

// ─── Find a good default center (highest point with LiDAR HD data) ───────────

function findDefaultCenter() {
    // Try to find Piton de la Fournaise area (around E367-370, N7648-7650)
    let bestKey = null, bestAlt = -Infinity;

    for (const [key, info] of Object.entries(MANIFEST.tiles)) {
        if (info.alt_max > bestAlt) {
            bestAlt = info.alt_max;
            bestKey = key;
        }
    }

    if (bestKey) {
        const parts = bestKey.split('_');
        const E = parseInt(parts[0]);
        const N = parseInt(parts[1]);
        const gx = (E - MIN_E_KM) * TILE_SIZE + TILE_SIZE / 2;
        const gy = (N - MIN_N_KM) * TILE_SIZE + TILE_SIZE / 2;
        return { gx, gy, E, N };
    }

    // Fallback: center of the map
    return { gx: GLOBAL_W / 2, gy: GLOBAL_H / 2 };
}
