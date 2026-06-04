# SIMUL_LAVE_2.5D 🌋

### Simulateur de coulée de lave sur le relief réel de La Réunion

Simulation d'écoulement de lave basaltique en 2.5D, basée sur la physique Navier-Stokes (rhéologie de Bingham) et le refroidissement radiatif (Stefan-Boltzmann), appliquée sur les données **LiDAR HD IGN à 5 m de résolution** du Piton de la Fournaise.

Le simulateur tourne entièrement dans le navigateur web — sans installation lourde, sans cloud, sans abonnement.

---

## Captures d'écran

| Vue température                                    | Vue épaisseur              |
| -------------------------------------------------- | -------------------------- |
| Gradient blanc→jaune→orange de la fissure au front | Chenaux et levées naturels |

---

## Prérequis

| Élément       | Détail                                                                       |
| ------------- | ---------------------------------------------------------------------------- |
| Python 3      | `python3 --version` — sinon téléchargez sur [python.org](https://python.org) |
| Navigateur    | Chrome, Firefox, Safari ou Edge (version récente)                            |
| Espace disque | ~900 Mo pour les tuiles terrain pré-calculées                                |

---

## 🛠️ INSTALLATION

> Suivez ces 3 étapes dans l'ordre. Comptez environ **10 minutes** pour tout mettre en place.

### Étape 1 — Cloner le dépôt

Ouvrez un terminal et tapez :

```bash
git clone https://github.com/olivierhoarau97410/simulateurcouleeV2.git
cd simulateurcouleeV2
```

> 💡 Si vous n'avez pas Git, téléchargez l'archive ZIP depuis le bouton vert **Code → Download ZIP** sur cette page, puis décompressez-la.

---

### Étape 2 — Télécharger les tuiles terrain

Les tuiles terrain (~860 Mo) ne sont **pas incluses** dans le dépôt Git car elles sont trop volumineuses.

1. Rendez-vous dans la section [**Releases**](https://github.com/olivierhoarau97410/simulateurcouleeV2/releases)
2. Téléchargez le fichier **`tiles_terrain.zip`**
3. Décompressez-le dans le dossier du projet, de sorte à obtenir cette structure :

```
simulateurcouleeV2/
└── tiles/
    └── terrain/      ← contenu de tiles_terrain.zip
        ├── 313_7668.bin
        ├── 313_7668_hs.bin
        └── …  (~5500 fichiers .bin)
```

> ⚠️ **Sans ces tuiles, la carte reste noire au démarrage.** C'est la cause n°1 des problèmes.

---

### Étape 3 — Lancer le simulateur

**Mac / Linux :**

```bash
bash start_simulation.sh
```

**Windows :**

```bash
python -m http.server 8765
```

Puis ouvrez votre navigateur à l'adresse :

```
http://localhost:8765/simul_lave_25d_v2.html
```

> ⚠️ N'ouvrez **pas** le fichier `.html` par double-clic — cela ne fonctionne pas. Vous devez passer par `http://localhost:8765/...`

---

## 🚀 PRISE EN MAIN TRÈS SIMPLIFIÉE DU SIMULATEUR

Vous n'avez besoin de rien connaître à la physique pour commencer. Voici l'essentiel en 4 actions.

### 1. Lancer la simulation

Cliquez sur **▶ Démarrer**.

La lave commence à couler depuis la fissure éruptive vers le Grand Brûlé (côte est). Les tuiles du terrain se chargent automatiquement.

---

### 2. Se déplacer sur la carte

| Action          | Résultat                    |
| --------------- | --------------------------- |
| Cliquer-glisser | Déplacer la vue             |
| Molette souris  | Zoomer / dézoomer           |

---

### 3. Les 3 boutons essentiels

| Bouton      | Ce qu'il fait                                         |
| ----------- | ----------------------------------------------------- |
| ⏸ **Pause** | Fige la lave — utile pour observer un moment précis   |
| ▶ **Reprendre** | Continue exactement là où on s'est arrêté         |
| ■ **Reset** | Efface toute la lave et repart de zéro                |

---

### 4. Choisir un mode de simulation

| Mode           | À utiliser quand…                                             |
| -------------- | ------------------------------------------------------------- |
| ⏱ **RÉALISTE** | Vous voulez observer la progression naturelle (chenaux, levées, figeage) |
| ⚡ **ACCÉLÉRÉ** | Vous voulez voir le résultat final en quelques minutes        |

---

### Ce que vous voyez à l'écran

- **Vue TEMP** : les couleurs vont du blanc (très chaud, ~1200°C) à l'orange foncé (refroidi, ~800°C)
- **Vue ÉPAISS** : montre l'accumulation de lave — plus c'est épais, plus c'est visible
- La lave suit **automatiquement** les ravines et vallées du terrain LiDAR réel

---

### Pour aller plus loin (optionnel)

- **Déplacer la fissure** : faites glisser les poignées **A** et **B** sur la carte
- **Changer le débit** : curseur *Débit (m³/s)* — de 10 (filet) à 500 (nappe massive)
- **Couper l'arrivée de lave** : bouton **INJ: ON/OFF** — la lave déjà coulée continue de s'écouler mais plus rien n'est injecté

---

## Problèmes fréquents

**La carte reste noire** → Le serveur local n'est pas lancé, ou vous avez ouvert le `.html` directement (double-clic). Passez par `http://localhost:8765/simul_lave_25d_v2.html`.

**La lave ne coule pas** → Vérifiez que `tiles/terrain/` contient bien ~5500 fichiers `.bin`.

**`python3 : commande introuvable` (Windows)** → Installez Python depuis [python.org](https://python.org) en cochant *Add Python to PATH*.

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

| Paramètre  | Valeur                           | Description         |
| ---------- | -------------------------------- | ------------------- |
| τ₀         | 110 × exp(0.011 × (1200−T)) Pa   | Seuil de Bingham    |
| η          | 160 × exp(0.009 × (1200−T)) Pa·s | Viscosité dynamique |
| ρ          | 2600 kg/m³                       | Densité basalte     |
| ε          | 0.95                             | Émissivité          |
| Résolution | 5 m/pixel                        | LiDAR HD IGN        |

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

## Données

Données LiDAR HD IGN — [data.geopf.fr](https://data.geopf.fr) — accès libre  
Piton de la Fournaise, La Réunion

---

## Licence

Projet pédagogique — libre d'utilisation pour l'enseignement et la recherche.
