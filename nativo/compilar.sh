#!/bin/sh
# Compila nativo/bitwise_simd.c como librería compartida y genera el ensamblador bitwise_simd.s.
# Linux: libbitwise_simd.so · macOS: libbitwise_simd.dylib. Usa gcc o, si no está, clang.
set -e
cd "$(dirname "$0")"

if command -v gcc >/dev/null 2>&1; then CC=gcc
elif command -v clang >/dev/null 2>&1; then CC=clang
else
    echo "No se encontró gcc ni clang (Ubuntu: sudo apt install build-essential; macOS: xcode-select --install)"
    exit 1
fi

case "$(uname -s)" in
    Darwin) SALIDA=libbitwise_simd.dylib ;;
    *) SALIDA=libbitwise_simd.so ;;
esac

echo "Compilando con $CC..."
$CC -O2 -shared -fPIC -o "$SALIDA" bitwise_simd.c
# -S: solo traduce a ensamblador. En x86 se pide sintaxis Intel (en ARM no hay SIMD x86: queda el escalar).
case "$(uname -m)" in
    x86_64|i?86) $CC -O2 -S -masm=intel -fno-asynchronous-unwind-tables -o bitwise_simd.s bitwise_simd.c ;;
    *) $CC -O2 -S -o bitwise_simd.s bitwise_simd.c ;;
esac

echo "Listo: nativo/$SALIDA y nativo/bitwise_simd.s"
echo "Probar: .venv/bin/python -m pytest tests/test_nativo.py -q"
echo "Medir:  .venv/bin/python -m homeguard.preproceso.benchmark"
