#!/bin/bash
# =====================================================
#  start_simulation.sh
#  Lance le serveur local pour simul_lave_25d_v2.html
# =====================================================

cd "$(dirname "$0")"

PORT=8765
HTML="simul_lave_25d_v2.html"

echo ""
echo "  🌋  SIMUL_LAVE_2.5D — La Réunion LiDAR HD"
echo "  ========================================="
echo ""

# Vérifier que le simulateur existe
if [ ! -f "$HTML" ]; then
    echo "  ⚠️  $HTML introuvable !"
    echo "  Vérifiez que vous êtes dans le bon dossier."
    echo ""
    exit 1
fi

# Vérifier que les tuiles sont présentes
if [ ! -f "tiles/manifest.json" ]; then
    echo "  ⚠️  tiles/manifest.json introuvable !"
    echo "  Téléchargez les tuiles terrain depuis les Releases GitHub du projet."
    echo ""
    exit 1
fi

TILE_COUNT=$(ls tiles/terrain/*.bin 2>/dev/null | wc -l | tr -d ' ')
if [ "$TILE_COUNT" -eq 0 ]; then
    echo "  ⚠️  Aucune tuile terrain trouvée dans tiles/terrain/"
    echo "  Téléchargez l'archive tiles_terrain.zip depuis les Releases GitHub"
    echo "  et décompressez-la ici."
    echo ""
    exit 1
fi

echo "  ✅  Simulateur : $HTML"
echo "  ✅  Tuiles terrain : $TILE_COUNT fichiers"
echo "  🌐  Serveur démarré sur http://localhost:$PORT"
echo ""
echo "  → Ouvrez votre navigateur à :"
echo "    http://localhost:$PORT/$HTML"
echo ""
echo "  (Ctrl+C pour arrêter)"
echo ""

# Ouvrir le navigateur automatiquement (macOS)
if command -v open &> /dev/null; then
    sleep 1 && open "http://localhost:$PORT/$HTML" &
fi

# Lancer le serveur Python
python3 -m http.server $PORT
