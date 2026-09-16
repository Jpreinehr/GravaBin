#!/usr/bin/env bash
# =============================================================================
# build_deb.sh — Constrói o pacote .deb do GravaBin
# Uso: bash build_deb.sh
# =============================================================================
set -e
cd "$(dirname "$0")"

PKG_NAME="gravabin"
PKG_VERSION="1.0.1"
PKG_ARCH="all"

# Diretórios de trabalho (ignorados pelo git):
#   build/ -> staging do pacote     dist/ -> .deb final
BUILD_DIR="build"
DIST_DIR="dist"
PKG_DIR="${BUILD_DIR}/${PKG_NAME}_${PKG_VERSION}_${PKG_ARCH}"
DEB_FILE="${DIST_DIR}/${PKG_NAME}_${PKG_VERSION}_${PKG_ARCH}.deb"

MAINTAINER="GravaBin Project <gravabin@github.com>"

# Fontes do logo (pasta "GravaBin Logo Design").
LOGO_DIR="GravaBin Logo Design/export"
LOGO_SVG="$LOGO_DIR/gravabin.svg"
LOGO_PNG_DIR="$LOGO_DIR/icones"

# ---------------------------------------------------------------------------
echo "==> Verificando dependências de build..."

missing=()
command -v dpkg-deb >/dev/null 2>&1 || missing+=("dpkg-dev")

# Conversor SVG->PNG só é necessário para tamanhos sem PNG pronto em icones/.
if command -v rsvg-convert >/dev/null 2>&1; then
    ICON_CONV="rsvg"
elif command -v inkscape >/dev/null 2>&1; then
    ICON_CONV="inkscape"
elif command -v convert >/dev/null 2>&1; then
    ICON_CONV="imagemagick"
else
    ICON_CONV=""
fi

[ -f "$LOGO_SVG" ] || missing+=("$LOGO_SVG (pasta do logo)")

if [ "${#missing[@]}" -gt 0 ]; then
    echo "ERRO: Dependências de build ausentes:"
    for dep in "${missing[@]}"; do
        echo "    - $dep"
    done
    echo
    echo "Instale com:  sudo apt install dpkg-dev librsvg2-bin"
    exit 1
fi
echo "    Conversor de ícone: ${ICON_CONV:-(nenhum; usando PNGs prontos)}"
echo "    dpkg-deb: OK"

# ---------------------------------------------------------------------------
echo "==> Criando estrutura de diretórios do pacote..."
rm -rf "$PKG_DIR"
mkdir -p "$BUILD_DIR" "$DIST_DIR"

ICON_SIZES=(16 24 32 48 64 96 128 256)
for SIZE in "${ICON_SIZES[@]}"; do
    mkdir -p "$PKG_DIR/usr/share/icons/hicolor/${SIZE}x${SIZE}/apps"
done
mkdir -p "$PKG_DIR/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$PKG_DIR/usr/share/pixmaps"
mkdir -p "$PKG_DIR/usr/share/applications"
mkdir -p "$PKG_DIR/usr/lib/$PKG_NAME/icones"
mkdir -p "$PKG_DIR/usr/bin"
mkdir -p "$PKG_DIR/DEBIAN"

# ---------------------------------------------------------------------------
echo "==> Gerando ícones hicolor (PNG pronto de icones/ ou conversão do SVG)..."
convert_svg() {  # $1=size  $2=dest
    case "$ICON_CONV" in
        rsvg) rsvg-convert -w "$1" -h "$1" "$LOGO_SVG" -o "$2" ;;
        inkscape) inkscape --export-type=png --export-width="$1" \
                  --export-height="$1" --export-filename="$2" "$LOGO_SVG" 2>/dev/null ;;
        imagemagick) convert -background none -resize "${1}x${1}" "$LOGO_SVG" "$2" ;;
        *) return 1 ;;
    esac
}

for SIZE in "${ICON_SIZES[@]}"; do
    DEST="$PKG_DIR/usr/share/icons/hicolor/${SIZE}x${SIZE}/apps/$PKG_NAME.png"
    SRC="$LOGO_PNG_DIR/gravabin-${SIZE}.png"
    if [ -f "$SRC" ]; then
        cp "$SRC" "$DEST"
        echo "    ${SIZE}x${SIZE} -> icones/gravabin-${SIZE}.png"
    elif convert_svg "$SIZE" "$DEST"; then
        echo "    ${SIZE}x${SIZE} -> convertido do SVG"
    else
        echo "    ${SIZE}x${SIZE} -> IGNORADO (sem PNG pronto e sem conversor)"
    fi
done

# SVG escalável + pixmap fallback (256px)
cp "$LOGO_SVG" "$PKG_DIR/usr/share/icons/hicolor/scalable/apps/$PKG_NAME.svg"
if [ -f "$PKG_DIR/usr/share/icons/hicolor/256x256/apps/$PKG_NAME.png" ]; then
    cp "$PKG_DIR/usr/share/icons/hicolor/256x256/apps/$PKG_NAME.png" \
       "$PKG_DIR/usr/share/pixmaps/$PKG_NAME.png"
fi
echo "    SVG scalable -> OK"

# ---------------------------------------------------------------------------
echo "==> Copiando arquivos da aplicação..."
cp gravabin.py      "$PKG_DIR/usr/lib/$PKG_NAME/"
cp requirements.txt "$PKG_DIR/usr/lib/$PKG_NAME/"
cp "$LOGO_SVG"      "$PKG_DIR/usr/lib/$PKG_NAME/icon.svg"
# Logo em vários tamanhos (usado pelo canto da interface e pelo ícone da janela)
cp "$LOGO_PNG_DIR"/gravabin-*.png "$PKG_DIR/usr/lib/$PKG_NAME/icones/"
# Fallback local para root.iconphoto()
if [ -f "$LOGO_PNG_DIR/gravabin-48.png" ]; then
    cp "$LOGO_PNG_DIR/gravabin-48.png" "$PKG_DIR/usr/lib/$PKG_NAME/$PKG_NAME.png"
fi

# ---------------------------------------------------------------------------
echo "==> Criando script lançador /usr/bin/gravabin..."
cat > "$PKG_DIR/usr/bin/$PKG_NAME" << 'LAUNCHER'
#!/usr/bin/env bash
# Lançador do GravaBin — usa o venv instalado pelo postinst
VENV="/usr/lib/gravabin/.venv"
if [ -d "$VENV" ]; then
    exec "$VENV/bin/python3" /usr/lib/gravabin/gravabin.py "$@"
else
    exec python3 /usr/lib/gravabin/gravabin.py "$@"
fi
LAUNCHER
chmod 755 "$PKG_DIR/usr/bin/$PKG_NAME"

# ---------------------------------------------------------------------------
echo "==> Criando .desktop entry..."
cat > "$PKG_DIR/usr/share/applications/$PKG_NAME.desktop" << 'DESKTOP'
[Desktop Entry]
Type=Application
Name=GravaBin
GenericName=ESP Flash Tool
Comment=Gravador de binários ESP8266/ESP32
Exec=gravabin
Icon=gravabin
Terminal=false
StartupNotify=true
StartupWMClass=Gravabin
Categories=Development;Electronics;
Keywords=ESP32;ESP8266;flash;firmware;esptool;
DESKTOP

# ---------------------------------------------------------------------------
echo "==> Calculando tamanho instalado..."
INSTALLED_SIZE=$(du -sk "$PKG_DIR" | cut -f1)

# ---------------------------------------------------------------------------
echo "==> Criando DEBIAN/control..."
cat > "$PKG_DIR/DEBIAN/control" << EOF
Package: $PKG_NAME
Version: $PKG_VERSION
Architecture: $PKG_ARCH
Maintainer: $MAINTAINER
Installed-Size: $INSTALLED_SIZE
Depends: python3 (>= 3.8), python3-venv, python3-tk, python3-pip
Section: devel
Priority: optional
Homepage: https://github.com/Jpreinehr/GravaBin
Description: Gravador gráfico de binários para ESP8266/ESP32
 Interface gráfica (Tkinter) para gravação de firmware em dispositivos
 ESP8266 e ESP32 usando o esptool. Suporta múltiplos binários com
 offsets configuráveis, seleção de porta serial, baud rate, modo e
 frequência de flash.
EOF

# ---------------------------------------------------------------------------
echo "==> Criando DEBIAN/postinst..."
cat > "$PKG_DIR/DEBIAN/postinst" << 'POSTINST'
#!/usr/bin/env bash
set -e

APP_DIR="/usr/lib/gravabin"
VENV_DIR="$APP_DIR/.venv"

echo "GravaBin: configurando ambiente Python..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" --quiet
echo "GravaBin: dependências instaladas com sucesso."

# Atualiza cache de ícones e base de dados de aplicações
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications 2>/dev/null || true
fi

# Adiciona o usuário ao grupo 'dialout' para acesso à porta serial
REAL_USER="${SUDO_USER:-}"
if [ -z "$REAL_USER" ] && [ -n "${PKEXEC_UID:-}" ]; then
    REAL_USER=$(id -un "$PKEXEC_UID" 2>/dev/null || true)
fi
if [ -n "$REAL_USER" ] && [ "$REAL_USER" != "root" ]; then
    if usermod -a -G dialout "$REAL_USER" 2>/dev/null; then
        echo "GravaBin: usuário '$REAL_USER' adicionado ao grupo 'dialout'."
        echo "          Faça logout/login para o grupo entrar em vigor."
    fi
fi

echo "GravaBin instalado. Execute com:  gravabin"
POSTINST
chmod 755 "$PKG_DIR/DEBIAN/postinst"

# ---------------------------------------------------------------------------
echo "==> Criando DEBIAN/prerm..."
cat > "$PKG_DIR/DEBIAN/prerm" << 'PRERM'
#!/usr/bin/env bash
set -e
# Remove o venv para evitar sobras no sistema
rm -rf /usr/lib/gravabin/.venv
PRERM
chmod 755 "$PKG_DIR/DEBIAN/prerm"

# ---------------------------------------------------------------------------
echo "==> Criando DEBIAN/postrm..."
cat > "$PKG_DIR/DEBIAN/postrm" << 'POSTRM'
#!/usr/bin/env bash
set -e
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications 2>/dev/null || true
fi
POSTRM
chmod 755 "$PKG_DIR/DEBIAN/postrm"

# ---------------------------------------------------------------------------
echo "==> Ajustando permissões..."
find "$PKG_DIR" -type d -exec chmod 755 {} \;
find "$PKG_DIR/usr" -type f -exec chmod 644 {} \;
chmod 755 "$PKG_DIR/usr/bin/$PKG_NAME"
chmod 755 "$PKG_DIR/DEBIAN/postinst" \
          "$PKG_DIR/DEBIAN/prerm" \
          "$PKG_DIR/DEBIAN/postrm"

# ---------------------------------------------------------------------------
echo "==> Construindo pacote .deb..."
dpkg-deb --build --root-owner-group "$PKG_DIR" "$DEB_FILE"

echo
echo "============================================================"
echo " Pacote criado: ${DEB_FILE}"
echo "============================================================"
echo " Para instalar:  sudo dpkg -i ${DEB_FILE}"
echo " Para remover:   sudo apt remove gravabin"
echo "============================================================"
