@echo off
rem Compila nativo\bitwise_simd.c como bitwise_simd.dll y genera el ensamblador (bitwise_simd.s / .asm).
rem Usa MinGW gcc si esta en el PATH; si no, MSVC cl (abrir "x64 Native Tools Command Prompt for VS").
rem La DLL tiene que ser de 64 bits, igual que Python.
setlocal
cd /d "%~dp0"

where gcc >nul 2>nul
if %errorlevel%==0 goto gcc
where cl >nul 2>nul
if %errorlevel%==0 goto msvc

echo No se encontro gcc ni cl.
echo Instala MSYS2 (https://www.msys2.org), y en la terminal "MSYS2 UCRT64":
echo     pacman -S mingw-w64-ucrt-x86_64-gcc
echo Despues agrega C:\msys64\ucrt64\bin al PATH y volve a ejecutar este archivo.
exit /b 1

:gcc
echo Compilando con gcc...
gcc -O2 -shared -o bitwise_simd.dll bitwise_simd.c || exit /b 1
rem -S: solo traduce a ensamblador (sintaxis Intel, mas parecida a la de clase)
gcc -O2 -S -masm=intel -fno-asynchronous-unwind-tables -o bitwise_simd.s bitwise_simd.c || exit /b 1
goto fin

:msvc
echo Compilando con MSVC cl...
rem /FA genera el listado de ensamblador bitwise_simd.asm
cl /nologo /O2 /LD /FA /Fabitwise_simd.asm bitwise_simd.c /Febitwise_simd.dll || exit /b 1
del /q bitwise_simd.obj bitwise_simd.lib bitwise_simd.exp 2>nul
goto fin

:fin
echo Listo: nativo\bitwise_simd.dll
echo Probar: .venv\Scripts\python -m pytest tests\test_nativo.py -q
echo Medir:  .venv\Scripts\python -m homeguard.preproceso.benchmark
endlocal
