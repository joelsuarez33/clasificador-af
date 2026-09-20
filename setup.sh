#!/usr/bin/env bash
# Setup reproducible (Linux/macOS): verifica Python 3.12, crea .venv, instala dependencias pineadas
# y corre chequeos de sanity. Uso: ./setup.sh   (o PYTHON=/ruta/python3.12 ./setup.sh)
set -euo pipefail
cd "$(dirname "$0")"

REQUERIDA="3.12"

version_de() {
  "$1" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || true
}

buscar_python() {
  local candidato
  for candidato in "${PYTHON:-}" python3.12 python3 python; do
    [ -n "$candidato" ] || continue
    command -v "$candidato" >/dev/null 2>&1 || continue
    if [ "$(version_de "$candidato")" = "$REQUERIDA" ]; then
      echo "$candidato"
      return 0
    fi
  done
  return 1
}

echo "==> Verificando Python $REQUERIDA"
if ! PY="$(buscar_python)"; then
  cat >&2 <<EOF
ERROR: no se encontró Python $REQUERIDA en el PATH.
Instalalo y volvé a correr este script:
  macOS:          brew install python@3.12
  Ubuntu/Debian:  sudo apt install python3.12 python3.12-venv   (o PPA deadsnakes)
  pyenv:          pyenv install 3.12.7 && pyenv local 3.12.7
O indicá el intérprete: PYTHON=/ruta/a/python3.12 ./setup.sh
EOF
  exit 1
fi
echo "    Usando $("$PY" --version) ($(command -v "$PY"))"

if [ -x .venv/bin/python ] && [ "$(version_de .venv/bin/python)" != "$REQUERIDA" ]; then
  echo "==> .venv existente usa otra versión de Python: se recrea"
  rm -rf .venv
fi

if [ ! -x .venv/bin/python ]; then
  echo "==> Creando entorno virtual .venv"
  "$PY" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Instalando dependencias (pyproject.toml, versiones exactas)"
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

echo "==> Sanity check de imports"
python -c "import google.genai, google.cloud.bigquery, fastapi; print('    imports OK')"

echo "==> Tests (sin llamadas a GCP)"
python -m pytest

echo "==> Configuración"
if [ -f .env ]; then
  python -m app.config || echo "AVISO: revisá .env y la ruta del JSON de Service Account (ver README)."
else
  echo "AVISO: no existe .env. Copiá .env.example a .env y completá los valores."
fi

cat <<EOF

Listo. Para trabajar:
  source .venv/bin/activate
  python -m preprocess.load_catalogo
  python -m preprocess.build_index
  python -m app.main
EOF
