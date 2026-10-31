/*
 * HomeGuard AI - Fase 7 (opcional): operaciones de bits con instrucciones SIMD.
 *
 * Python (NumPy/OpenCV) ya usa SIMD por dentro, pero ahí no se ve. Este archivo
 * hace lo mismo "a mano" para mostrar qué instrucciones de la CPU ejecutan el XOR
 * y el AND de dos imágenes:
 *
 *   escalar : 1 byte por iteración          s[i] = a[i] ^ b[i]
 *   SSE2    : 16 bytes por instrucción      registros XMM de 128 bits  -> pxor / pand
 *   AVX2    : 32 bytes por instrucción      registros YMM de 256 bits  -> vpxor / vpand
 *
 * Un frame gris de 640x480 son 307 200 bytes: el bucle escalar da 307 200 vueltas,
 * SSE2 da 19 200 y AVX2 da 9 600.
 *
 * Funciones exportadas (las carga homeguard/preproceso/nativo.py con ctypes):
 *   hg_xor(a, b, s, n)        s = a XOR b
 *   hg_and(a, b, s, n)        s = a AND b
 *   hg_xor_and(a, b, m, s, n) s = (a XOR b) AND m   (cambio dentro de una máscara)
 *   hg_nivel_detectado()      0 = escalar, 1 = SSE2, 2 = AVX2 (lo que soporta esta CPU)
 *   hg_nivel()                nivel que se está usando
 *   hg_forzar_nivel(k)        usa como máximo el nivel k (-1 = volver al detectado); para el benchmark
 *
 * Todos los buffers son uint8 contiguos de n bytes. Se usan cargas "no alineadas"
 * (loadu/storeu), así no hace falta que NumPy entregue memoria alineada a 16/32.
 *
 * Compilar: compilar.bat (Windows) o compilar.sh (Linux/macOS).
 */
#include <stddef.h>
#include <stdint.h>

/* SIMD x86 solo en procesadores x86/x64. En otro procesador (ej. ARM) queda el escalar. */
#if defined(__x86_64__) || defined(_M_X64) || defined(__i386__) || defined(_M_IX86)
#define HG_X86 1
/* Informe, ecuación de las instrucciones SIMD: 16 bytes por pxor/pand (SSE2), 32 por vpxor/vpand (AVX2). */
#include <emmintrin.h> /* SSE2: __m128i, _mm_xor_si128, _mm_and_si128 */
#include <immintrin.h> /* AVX2: __m256i, _mm256_xor_si256, _mm256_and_si256 */
#if defined(_MSC_VER)
#include <intrin.h> /* __cpuidex, _xgetbv */
#endif
#else
#define HG_X86 0
#endif

/* Exportar símbolos de la librería compartida (.dll en Windows, .so/.dylib en Linux/macOS). */
#ifdef __cplusplus
#define HG_EXTERN_C extern "C"
#else
#define HG_EXTERN_C
#endif
#ifdef _WIN32
#define HG_EXPORTAR HG_EXTERN_C __declspec(dllexport)
#else
#define HG_EXPORTAR HG_EXTERN_C __attribute__((visibility("default")))
#endif

/* AVX2 se compila solo para estas funciones (atributo target), sin pedir -mavx2 a todo el
 * archivo: así la librería también carga en una CPU vieja y el código AVX2 solo se ejecuta
 * si la detección en tiempo de ejecución dice que la CPU lo soporta. MSVC no lo necesita. */
#if defined(__GNUC__) || defined(__clang__)
#define HG_AVX2 __attribute__((target("avx2")))
#define HG_SSE2 __attribute__((target("sse2"))) /* solo hace falta al compilar para x86 de 32 bits */
#else
#define HG_AVX2
#define HG_SSE2
#endif

/* El escalar es la línea base: se le pide al compilador que NO lo vectorice por su cuenta
 * (con -O2/-O3 gcc lo convertiría solo en SSE2 y la comparación no mostraría nada). */
#if defined(__GNUC__) && !defined(__clang__)
#define HG_SIN_VECTORIZAR __attribute__((optimize("no-tree-vectorize")))
#else
#define HG_SIN_VECTORIZAR
#endif
#if defined(__clang__)
#define HG_PRAGMA_BUCLE_ESCALAR _Pragma("clang loop vectorize(disable) interleave(disable)")
#elif defined(_MSC_VER)
#define HG_PRAGMA_BUCLE_ESCALAR __pragma(loop(no_vector))
#else
#define HG_PRAGMA_BUCLE_ESCALAR
#endif

enum { NIVEL_ESCALAR = 0, NIVEL_SSE2 = 1, NIVEL_AVX2 = 2 };

/* ------------------------------------------------------------------------ */
/* Versión escalar: un byte por vuelta. También procesa la "cola" que sobra  */
/* cuando n no es múltiplo de 16 (SSE2) o 32 (AVX2).                        */
/* ------------------------------------------------------------------------ */

HG_SIN_VECTORIZAR
static void xor_escalar(const uint8_t *a, const uint8_t *b, uint8_t *s, size_t n) {
    HG_PRAGMA_BUCLE_ESCALAR
    for (size_t i = 0; i < n; i++) s[i] = (uint8_t)(a[i] ^ b[i]); /* x86: xor  al, [b+i] */
}

HG_SIN_VECTORIZAR
static void and_escalar(const uint8_t *a, const uint8_t *b, uint8_t *s, size_t n) {
    HG_PRAGMA_BUCLE_ESCALAR
    for (size_t i = 0; i < n; i++) s[i] = (uint8_t)(a[i] & b[i]); /* x86: and  al, [b+i] */
}

HG_SIN_VECTORIZAR
static void xor_and_escalar(const uint8_t *a, const uint8_t *b, const uint8_t *m, uint8_t *s, size_t n) {
    HG_PRAGMA_BUCLE_ESCALAR
    for (size_t i = 0; i < n; i++) s[i] = (uint8_t)((a[i] ^ b[i]) & m[i]);
}

#if HG_X86
/* ------------------------------------------------------------------------ */
/* SSE2: 16 bytes por instrucción (registro XMM de 128 bits).               */
/*   _mm_loadu_si128  -> movdqu xmm, [mem]   (carga 16 bytes, no alineada)  */
/*   _mm_xor_si128    -> pxor   xmm, xmm                                    */
/*   _mm_and_si128    -> pand   xmm, xmm                                    */
/*   _mm_storeu_si128 -> movdqu [mem], xmm   (guarda 16 bytes)              */
/* SSE2 es parte de x86-64: toda CPU de 64 bits lo tiene.                   */
/* ------------------------------------------------------------------------ */

HG_SSE2
static void xor_sse2(const uint8_t *a, const uint8_t *b, uint8_t *s, size_t n) {
    size_t i = 0;
    for (; i + 16 <= n; i += 16) {
        __m128i va = _mm_loadu_si128((const __m128i *)(a + i));
        __m128i vb = _mm_loadu_si128((const __m128i *)(b + i));
        _mm_storeu_si128((__m128i *)(s + i), _mm_xor_si128(va, vb));
    }
    xor_escalar(a + i, b + i, s + i, n - i); /* cola: menos de 16 bytes */
}

HG_SSE2
static void and_sse2(const uint8_t *a, const uint8_t *b, uint8_t *s, size_t n) {
    size_t i = 0;
    for (; i + 16 <= n; i += 16) {
        __m128i va = _mm_loadu_si128((const __m128i *)(a + i));
        __m128i vb = _mm_loadu_si128((const __m128i *)(b + i));
        _mm_storeu_si128((__m128i *)(s + i), _mm_and_si128(va, vb));
    }
    and_escalar(a + i, b + i, s + i, n - i);
}

HG_SSE2
static void xor_and_sse2(const uint8_t *a, const uint8_t *b, const uint8_t *m, uint8_t *s, size_t n) {
    size_t i = 0;
    for (; i + 16 <= n; i += 16) {
        __m128i va = _mm_loadu_si128((const __m128i *)(a + i));
        __m128i vb = _mm_loadu_si128((const __m128i *)(b + i));
        __m128i vm = _mm_loadu_si128((const __m128i *)(m + i));
        /* pxor + pand: dos instrucciones para 16 píxeles */
        _mm_storeu_si128((__m128i *)(s + i), _mm_and_si128(_mm_xor_si128(va, vb), vm));
    }
    xor_and_escalar(a + i, b + i, m + i, s + i, n - i);
}

/* ------------------------------------------------------------------------ */
/* AVX2: 32 bytes por instrucción (registro YMM de 256 bits).               */
/*   _mm256_loadu_si256  -> vmovdqu ymm, [mem]                              */
/*   _mm256_xor_si256    -> vpxor   ymm, ymm, ymm                           */
/*   _mm256_and_si256    -> vpand   ymm, ymm, ymm                           */
/*   _mm256_storeu_si256 -> vmovdqu [mem], ymm                              */
/* Las instrucciones VEX (prefijo v) tienen 3 operandos: el destino no      */
/* pisa a los operandos de entrada.                                         */
/* ------------------------------------------------------------------------ */

HG_AVX2
static void xor_avx2(const uint8_t *a, const uint8_t *b, uint8_t *s, size_t n) {
    size_t i = 0;
    for (; i + 32 <= n; i += 32) {
        __m256i va = _mm256_loadu_si256((const __m256i *)(a + i));
        __m256i vb = _mm256_loadu_si256((const __m256i *)(b + i));
        _mm256_storeu_si256((__m256i *)(s + i), _mm256_xor_si256(va, vb));
    }
    xor_escalar(a + i, b + i, s + i, n - i); /* cola: menos de 32 bytes */
}

HG_AVX2
static void and_avx2(const uint8_t *a, const uint8_t *b, uint8_t *s, size_t n) {
    size_t i = 0;
    for (; i + 32 <= n; i += 32) {
        __m256i va = _mm256_loadu_si256((const __m256i *)(a + i));
        __m256i vb = _mm256_loadu_si256((const __m256i *)(b + i));
        _mm256_storeu_si256((__m256i *)(s + i), _mm256_and_si256(va, vb));
    }
    and_escalar(a + i, b + i, s + i, n - i);
}

HG_AVX2
static void xor_and_avx2(const uint8_t *a, const uint8_t *b, const uint8_t *m, uint8_t *s, size_t n) {
    size_t i = 0;
    for (; i + 32 <= n; i += 32) {
        __m256i va = _mm256_loadu_si256((const __m256i *)(a + i));
        __m256i vb = _mm256_loadu_si256((const __m256i *)(b + i));
        __m256i vm = _mm256_loadu_si256((const __m256i *)(m + i));
        _mm256_storeu_si256((__m256i *)(s + i), _mm256_and_si256(_mm256_xor_si256(va, vb), vm));
    }
    xor_and_escalar(a + i, b + i, m + i, s + i, n - i);
}
#endif /* HG_X86 */

/* ------------------------------------------------------------------------ */
/* Detección de la CPU en tiempo de ejecución                               */
/* ------------------------------------------------------------------------ */

static int detectar_nivel(void) {
#if !HG_X86
    return NIVEL_ESCALAR;
#elif defined(_MSC_VER)
    int r[4]; /* eax, ebx, ecx, edx */
    __cpuidex(r, 1, 0);
    int osxsave = (r[2] >> 27) & 1; /* el sistema operativo guarda los registros extendidos */
    int avx = (r[2] >> 28) & 1;
    int sse2 = (r[3] >> 26) & 1;
    int avx2 = 0;
    if (osxsave && avx && (_xgetbv(0) & 6) == 6) { /* bits 1-2 de XCR0: estado XMM e YMM habilitado */
        __cpuidex(r, 7, 0);
        avx2 = (r[1] >> 5) & 1; /* CPUID hoja 7, EBX bit 5 = AVX2 */
    }
    return avx2 ? NIVEL_AVX2 : (sse2 ? NIVEL_SSE2 : NIVEL_ESCALAR);
#else
    /* gcc/clang: __builtin_cpu_supports consulta CPUID (y que el SO habilite los registros YMM) */
    __builtin_cpu_init();
    if (__builtin_cpu_supports("avx2")) return NIVEL_AVX2;
    if (__builtin_cpu_supports("sse2")) return NIVEL_SSE2;
    return NIVEL_ESCALAR;
#endif
}

static int nivel_cpu = -1; /* lo que soporta la CPU (se detecta una vez) */
static int nivel_max = 2;  /* tope elegido con hg_forzar_nivel */

static int nivel_actual(void) {
    if (nivel_cpu < 0) nivel_cpu = detectar_nivel();
    return nivel_cpu < nivel_max ? nivel_cpu : nivel_max;
}

HG_EXPORTAR int hg_nivel_detectado(void) {
    if (nivel_cpu < 0) nivel_cpu = detectar_nivel();
    return nivel_cpu;
}

HG_EXPORTAR int hg_nivel(void) { return nivel_actual(); }

HG_EXPORTAR int hg_forzar_nivel(int k) {
    nivel_max = (k < 0 || k > NIVEL_AVX2) ? NIVEL_AVX2 : k;
    return nivel_actual();
}

/* ------------------------------------------------------------------------ */
/* Funciones públicas: eligen la mejor versión disponible                   */
/* ------------------------------------------------------------------------ */

HG_EXPORTAR void hg_xor(const uint8_t *a, const uint8_t *b, uint8_t *s, size_t n) {
#if HG_X86
    switch (nivel_actual()) {
    case NIVEL_AVX2: xor_avx2(a, b, s, n); return;
    case NIVEL_SSE2: xor_sse2(a, b, s, n); return;
    }
#endif
    xor_escalar(a, b, s, n);
}

HG_EXPORTAR void hg_and(const uint8_t *a, const uint8_t *b, uint8_t *s, size_t n) {
#if HG_X86
    switch (nivel_actual()) {
    case NIVEL_AVX2: and_avx2(a, b, s, n); return;
    case NIVEL_SSE2: and_sse2(a, b, s, n); return;
    }
#endif
    and_escalar(a, b, s, n);
}

HG_EXPORTAR void hg_xor_and(const uint8_t *a, const uint8_t *b, const uint8_t *m, uint8_t *s, size_t n) {
#if HG_X86
    switch (nivel_actual()) {
    case NIVEL_AVX2: xor_and_avx2(a, b, m, s, n); return;
    case NIVEL_SSE2: xor_and_sse2(a, b, m, s, n); return;
    }
#endif
    xor_and_escalar(a, b, m, s, n);
}
