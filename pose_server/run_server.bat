@echo off
chcp 65001 >nul
title Pose Server
setlocal enabledelayedexpansion

echo   POSE SERVER v2.4
echo.

set PYTHON_CMD=
set BEST_VERSION=0
set BEST_PYTHON=

echo Поиск Python 3.9+...
echo.

:: Ищем Python во всех стандартных местах
for %%d in (
    "%LOCALAPPDATA%\Programs\Python"
    "C:\Program Files"
    "C:\"
) do (
    if exist "%%~d\Python3*" (
        for /d %%p in ("%%~d\Python3*") do (
            if exist "%%p\python.exe" (
                call :check_version "%%p\python.exe"
            )
        )
    )
)

:: Если ничего не нашли - пробуем where
:: очень нужен Python выше 3.8 иначе медиапайп не заведется(
if not defined BEST_PYTHON (
    for %%v in (python3.13 python3.12 python3.11 python3.10 python3.9 python3) do (
        for /f "delims=" %%p in ('where %%v 2^>nul') do (
            if exist "%%p" (
                call :check_version "%%p"
            )
        )
    )
)

if defined BEST_PYTHON (
    set PYTHON_CMD=!BEST_PYTHON!
    echo.
    echo [OK] Выбран Python !BEST_VERSION!
    echo [OK] Путь: !BEST_PYTHON!
    goto :found
)

echo [ERROR] Python 3.9+ не найден
echo Установите с https://python.org/downloads/
pause
exit /b 1

:check_version
set "TEST_PATH=%~1"
if not exist "!TEST_PATH!" goto :eof

for /f "tokens=2" %%v in ('"!TEST_PATH!" --version 2^>^&1') do (
    for /f "tokens=1,2 delims=." %%a in ("%%v") do (
        if %%a EQU 3 (
            if %%b GEQ 9 (
                if %%b GTR !BEST_VERSION! (
                    set BEST_VERSION=%%b
                    set BEST_PYTHON=!TEST_PATH!
                    echo   Python %%v: !TEST_PATH!
                )
            )
        )
    )
)
goto :eof

:found
echo.

if not exist ".deps_ok" (
    echo   УСТАНОВКА ЗАВИСИМОСТЕЙ
    echo.
    
    echo Установка пакетов...
    "!PYTHON_CMD!" -m pip install --upgrade pip --quiet
    "!PYTHON_CMD!" -m pip install fastapi uvicorn python-multipart mediapipe opencv-python numpy
    
    if errorlevel 1 (
        echo [ERROR] Ошибка установки
        pause
        exit /b 1
    )
    
    echo. > .deps_ok
    echo [OK] Готово
    echo.
)

if not exist "pose_landmarker_lite.task" (
    echo   ЗАГРУЗКА МОДЕЛИ
    echo.
    
    "!PYTHON_CMD!" -c "import urllib.request; urllib.request.urlretrieve('https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task', 'pose_landmarker_lite.task'); print('OK')"
    
    if errorlevel 1 (
        echo [ERROR] Не удалось загрузить модель
        pause
        exit /b 1
    )
    
    echo [OK] Модель загружена
    echo.
)

echo   СЕРВЕР ЗАПУЩЕН
echo.
echo   http://127.0.0.1:5000
echo   http://127.0.0.1:5000/docs
echo.
echo   Ctrl+C для остановки
echo.

"!PYTHON_CMD!" pose_server.py

pause