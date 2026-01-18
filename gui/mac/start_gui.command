#!/bin/bash
# =============================================================================
# PANG Config GUI - Mac Starter
# =============================================================================
# Dubbelklicka på denna fil för att starta!
# Allt installeras automatiskt första gången.
# =============================================================================

# Gå till rätt mapp (där skriptet ligger)
cd "$(dirname "$0")"

echo ""
echo "🎯 ==========================================="
echo "   PANG Konfiguration - Mac Edition"
echo "   ==========================================="
echo ""

# ----- STEG 1: Kontrollera Python -----
echo "🔍 Kontrollerar Python..."

PYTHON_CMD=""

# Prova olika Python-kommandon
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
elif [ -f "/usr/local/bin/python3" ]; then
    PYTHON_CMD="/usr/local/bin/python3"
elif [ -f "/opt/homebrew/bin/python3" ]; then
    PYTHON_CMD="/opt/homebrew/bin/python3"
fi

if [ -z "$PYTHON_CMD" ]; then
    echo ""
    echo "❌ Python hittades inte!"
    echo ""
    echo "📥 Installera Python:"
    echo "   1. Gå till: https://www.python.org/downloads/"
    echo "   2. Ladda ner senaste versionen för Mac"
    echo "   3. Installera och försök igen"
    echo ""
    echo "   Alternativt via Homebrew:"
    echo "   brew install python3"
    echo ""
    read -p "Tryck Enter för att stänga..."
    exit 1
fi

echo "   ✅ Hittade Python: $PYTHON_CMD"
$PYTHON_CMD --version

# ----- STEG 2: Installera/uppdatera pip -----
echo ""
echo "🔧 Kontrollerar pip..."

$PYTHON_CMD -m pip --version &> /dev/null
if [ $? -ne 0 ]; then
    echo "   📥 Installerar pip..."
    $PYTHON_CMD -m ensurepip --upgrade 2>/dev/null || true
fi

# ----- STEG 3: Installera customtkinter -----
echo ""
echo "📦 Kontrollerar customtkinter..."

# Kolla om customtkinter är installerat
$PYTHON_CMD -c "import customtkinter" &> /dev/null
if [ $? -ne 0 ]; then
    echo "   📥 Installerar customtkinter (tar ~30 sekunder)..."
    $PYTHON_CMD -m pip install --user customtkinter --quiet
    
    if [ $? -eq 0 ]; then
        echo "   ✅ customtkinter installerat!"
    else
        echo ""
        echo "⚠️  Kunde inte installera customtkinter automatiskt."
        echo "   Kör manuellt: $PYTHON_CMD -m pip install customtkinter"
        echo ""
        read -p "Tryck Enter för att fortsätta ändå..."
    fi
else
    echo "   ✅ customtkinter redan installerat"
fi

# ----- STEG 4: Starta programmet -----
echo ""
echo "🚀 Startar PANG Config GUI..."
echo "   ==========================================="
echo ""

$PYTHON_CMD mac_config_gui.py

# Om programmet kraschar, visa felmeddelande
if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Något gick fel!"
    echo ""
    read -p "Tryck Enter för att stänga..."
fi
