#!/usr/bin/env bash
# Instalador do GravaBin para Linux Mint / Ubuntu / Debian.
# Cria um virtualenv local em ./.venv e instala as dependências.
set -e

cd "$(dirname "$0")"

echo "==> Instalando pacotes do sistema (sudo)…"
if command -v apt >/dev/null 2>&1; then
    sudo apt update
    sudo apt install -y python3 python3-venv python3-tk python3-pip
fi

echo "==> Criando virtualenv (.venv)…"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Instalando dependências Python…"
pip install --upgrade pip
pip install -r requirements.txt

echo
echo "==> Adicionando seu usuário ao grupo 'dialout' (acesso à serial)…"
sudo usermod -a -G dialout "$USER" || true
echo "    (faça logout/login para o grupo entrar em vigor)"

echo
echo "==> Pronto! Execute com:  ./run.sh"
