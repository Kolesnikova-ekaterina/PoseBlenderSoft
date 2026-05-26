#!/usr/bin/env python3
"""
Автоматическая установка зависимостей для Pose Server
"""
import subprocess
import sys
import os
import urllib.request
from pathlib import Path

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
MODEL_FILE = "pose_landmarker_lite.task"

def print_step(msg):
    print(f"\n{'='*60}")
    print(f"▶ {msg}")
    print('='*60)

def check_python():
    """Проверка версии Python"""
    print_step("Проверка Python")
    version = sys.version_info
    print(f"Python {version.major}.{version.minor}.{version.micro}")
    
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print("Требуется Python 3.8+")
        sys.exit(1)
    
    print("OK")

def install_pip_packages():
    """Установка pip пакетов"""
    print_step("Установка Python пакетов")
    
    # Обновляем pip
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    
    # Устанавливаем из requirements.txt
    req_file = Path(__file__).parent / "requirements.txt"
    if req_file.exists():
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(req_file)])
    else:
        # Fallback - установка напрямую
        packages = [
            "fastapi",
            "uvicorn[standard]",
            "python-multipart",
            "mediapipe",
            "opencv-python",
            "numpy"
        ]
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + packages)
    
    print("Пакеты установлены")

def download_model():
    """Скачивание модели MediaPipe"""
    print_step("Загрузка модели MediaPipe")
    
    model_path = Path(__file__).parent / MODEL_FILE
    
    if model_path.exists():
        size_mb = model_path.stat().st_size / (1024 * 1024)
        print(f"Модель уже существует ({size_mb:.1f} MB)")
        return
    
    print(f"Загрузка из {MODEL_URL}")
    print("Это может занять несколько минут...")
    
    try:
        def progress_hook(block_num, block_size, total_size):
            downloaded = block_num * block_size
            if total_size > 0:
                percent = downloaded / total_size * 100
                print(f"\rПрогресс: {percent:.1f}%", end='', flush=True)
        
        urllib.request.urlretrieve(MODEL_URL, str(model_path), progress_hook)
        print("\nМодель загружена")
        
    except Exception as e:
        print(f"\n Ошибка загрузки: {e}")
        print("Скачайте модель вручную:")
        print(f"  {MODEL_URL}")
        print(f"  и сохраните как '{MODEL_FILE}' в папке сервера")
        sys.exit(1)

def check_model():
    """Проверка наличия модели"""
    print_step("Проверка модели")
    
    model_path = Path(__file__).parent / MODEL_FILE
    if model_path.exists():
        size_mb = model_path.stat().st_size / (1024 * 1024)
        print(f"Модель: {MODEL_FILE} ({size_mb:.1f} MB)")
    else:
        print("Модель не найдена!")
        return False
    
    return True

def main():
    print("="*60)
    print("  POSE SERVER - Установка и настройка")
    print("="*60)
    
    check_python()
    install_pip_packages()
    download_model()
    
    print_step("Проверка установки")
    
    # Проверяем импорты
    try:
        import fastapi
        import uvicorn
        import mediapipe as mp
        import cv2
        import numpy as np
        print("Все зависимости установлены")
    except ImportError as e:
        print(f"Ошибка импорта: {e}")
        sys.exit(1)
    
    if not check_model():
        sys.exit(1)
    
    print("\n" + "="*60)
    print("  УСТАНОВКА ЗАВЕРШЕНА!")
    print("="*60)
    print("\nДля запуска сервера выполните:")
    print("  python pose_server.py")
    print("\n  Сервер будет доступен по адресу:")
    print("  http://127.0.0.1:5000")
    print("  Документация: http://127.0.0.1:5000/docs")

if __name__ == "__main__":
    main()