# SIMUL_LAVE_2.5D 🌋
### Simulateur de coulée de lave sur le relief réel de La Réunion

Simulation d'écoulement de lave basaltique en 2.5D, basée sur la physique Navier-Stokes (rhéologie de Bingham) et le refroidissement radiatif (Stefan-Boltzmann), appliquée sur les données **LiDAR HD IGN à 5 m de résolution** du Piton de la Fournaise.

Le simulateur tourne entièrement dans le navigateur web — sans installation lourde, sans cloud, sans abonnement.

---

## Captures d'écran

| Vue température | Vue épaisseur |
|---|---|
| Gradient blanc→jaune→orange de la fissure au front | Chenaux et levées naturels |

---

## Prérequis

| Élément | Détail |
|---|---|
| Python 3 | `python3 --version` — sinon téléchargez sur [python.org](https://python.org) |
| Navigateur | Chrome, Firefox, Safari ou Edge (version récente) |
| Espace disque | ~900 Mo pour les tuiles terrain pré-calculées |

---

## Installation

### 1. Cloner le dépôt

```bash
git clone https://github.com/olivierhoarau97410/simulateurcouleeV2.git
cd simulateurcouleeV2
```

### 2. Télécharger les tuiles terrain

Les tuiles terrain (~860 Mo) ne sont pas dans le dépôt Git. Téléchargez **`tiles_terrain.zip`** depuis la section [Releases](https://github.com/olivierhoarau97410/simulateurcouleeV2/releases) et décompressez-le dans le dossier du projet :

```
simulateurcouleeV2/
└── tiles/
    └── terrain/      ← décompressez tiles_terrain.zip ici
        ├── 313_7668.bin
        ├── 313_7668_hs.bin
        └── …  (~5500 fichiers)
```

> ⚠️ Sans ces tuiles, la carte reste noire au démarrage.

### 3. Lancer le simulateur

**Mac / Linux :**
```bash
bash start_simulation.sh
```

**Windows :**
```bash
python -m http.server 8765
```
Puis ouvrez : `http://localhost:8765/simul_lave_25d_v2.html`

---

## Utilisation

### Premiers pas
1. Cliquez **▶ Démarrer** — le simulateur charge les tuiles terrain autour de la fissure
2. La lave commence à couler vers le Grand Brûlé (côte est)
3. Naviguez : **cliquez-glissez** pour déplacer, **molette** pour zoomer
4. Déplacez les poignées **A** et **B** pour repositionner la fissure

### Contrôles

| Bouton / Curseur | Effet |
|---|---|
| ▶ Démarrer | Lance la simulation (premier départ) |
| ⏸ Pause | Suspend le calcul — la lave reste en place |
| ▶ Reprendre | Continue exactement où on s'était arrêté |
| ■ Reset | Remet la lave à zéro |
| INJ: ON/OFF | Active ou coupe l'arrivée de lave à la fissure |
| Débit (m³/s) | De 10 (filet mince) à 500 (nappe massive) |
| TEMP / ÉPAISS | Bascule entre vue Température et vue Épaisseur |

### Deux modes de simulation

| Mode | Vitesse max | Refroidissement | Usage |
|---|---|---|---|
| ⏱ RÉALISTE | 3 m/s | Lent (5%) | Observer chenaux, levées, figeage |
| ⚡ ACCÉLÉRÉ | 15 m/s | Rapide (20%) | Voir en quelques minutes ce qui prendrait des heures |

### Ce que vous observez
- **Blanc → jaune → orange** : gradient de température de la fissure (1200°C) vers le front (~800°C)
- **Chenaux** : la lave suit naturellement les ravines du terrain LiDAR
- **Levées** : les bords minces refroidissent et figent, canalisant le flux central
- **Dôme sur terrain plat** : comportement physiquement correct (pas de pente = pas d'écoulement)

---

## Physique

La lave est modélisée comme un **fluide de Bingham** : elle ne coule que si la contrainte de cisaillement dépasse un seuil τ₀ (qui dépend de la température).

```
Vitesse = (h² / 3η) × (ρgh·pente − τ₀)   si ρgh·pente > τ₀
        = 0                                 sinon
```

Le refroidissement suit la loi de **Stefan-Boltzmann** :
```
dT/dt = −k_croûte × ε·σ·(T⁴ − T_amb⁴) / (ρ·h·cp)
```

| Paramètre | Valeur | Description |
|---|---|---|
| τ₀ | 110 × exp(0.011 × (1200−T)) Pa | Seuil de Bingham |
| η | 160 × exp(0.009 × (1200−T)) Pa·s | Viscosité dynamique |
| ρ | 2600 kg/m³ | Densité basalte |
| ε | 0.95 | Émissivité |
| Résolution | 5 m/pixel | LiDAR HD IGN |

---

## Mise à jour des données LiDAR (optionnel)

Pour régénérer les tuiles depuis le LiDAR brut IGN :

```bash
# 1. Installer les dépendances
pip install -r requirements.txt

# 2. Télécharger les dalles LiDAR HD (~40 Go, 3-8h)
python3 download_lidar_hd.py

# 3. Générer les tuiles binaires (10-30 min)
python3 preprocess_tiles.py

# 4. Recalculer l'ombrage si nécessaire
python3 recompute_hillshade.py
```

---

## Problèmes fréquents

**La carte reste noire** → Le serveur local n'est pas lancé, ou vous avez ouvert le `.html` directement (double-clic). Passez par `http://localhost:8765/simul_lave_25d_v2.html`.

**La lave ne coule pas** → Vérifiez que `tiles/terrain/` contient bien ~5500 fichiers `.bin`.

**`python3 : commande introuvable` (Windows)** → Installez Python depuis [python.org](https://python.org) en cochant *Add Python to PATH*.

---

## Données

Données LiDAR HD IGN — [data.geopf.fr](https://data.geopf.fr) — accès libre  
Piton de la Fournaise, La Réunion

---

## Licence

Projet pédagogique — libre d'utilisation pour l'enseignement et la recherche.
