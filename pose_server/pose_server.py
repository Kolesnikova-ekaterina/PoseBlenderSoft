#!/usr/bin/env python3
"""
Pose Server - MediaPipe + FastAPI
Автоматическая установка зависимостей при первом запуске
"""

import sys
import os
import subprocess
from pathlib import Path

def ensure_dependencies():
    """Проверяет и устанавливает зависимости при необходимости"""
    required = {
        'fastapi': 'fastapi',
        'uvicorn': 'uvicorn',
        'mediapipe': 'mediapipe',
        'cv2': 'opencv-python',
        'numpy': 'numpy',
    }
    
    missing = []
    for module, package in required.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    
    if missing:
        print("="*60)
        print("  УСТАНОВКА ЗАВИСИМОСТЕЙ...")
        print("="*60)
        print(f"  Пакеты: {', '.join(missing)}")
        print()
        
        try:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", "--upgrade", "pip"
            ])
            subprocess.check_call([
                sys.executable, "-m", "pip", "install"
            ] + missing + ['python-multipart'])
            print("\nЗависимости установлены!")
            print("Перезапустите сервер...\n")
            
            os.execv(sys.executable, [sys.executable] + sys.argv)
            
        except subprocess.CalledProcessError as e:
            print(f"\nОшибка установки: {e}")
            print("\nУстановите зависимости вручную:")
            print(f"  pip install {' '.join(missing)} python-multipart")
            sys.exit(1)

# Проверяем зависимости перед импортом
if __name__ != "__main__":
    ensure_dependencies()

# ИМПОРТЫ
import json
import cv2
import zipfile
import io
import os
import tempfile
import traceback
import numpy as np
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Form, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import mediapipe as mp

import json
import cv2
import zipfile
import io
import os
import tempfile
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import mediapipe as mp

app = FastAPI(title="Pose Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SERVER_DIR = Path(__file__).parent.absolute()
MODEL_PATH = str(SERVER_DIR / "pose_landmarker_lite.task")


def create_pose_landmarker():
    """Создает PoseLandmarker"""
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(
            f"Скачайте {MODEL_PATH}:\n"
            f"https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
        )

    BaseOptions = python.BaseOptions
    PoseLandmarker = vision.PoseLandmarker
    PoseLandmarkerOptions = vision.PoseLandmarkerOptions
    VisionRunningMode = mp.tasks.vision.RunningMode

    options = PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(Path(MODEL_PATH).absolute())),
        running_mode=VisionRunningMode.IMAGE,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5
    )
    return PoseLandmarker.create_from_options(options)


# Глобальный landmarker
try:
    pose_landmarker = create_pose_landmarker()
    print("PoseLandmarker готов!")
except Exception as e:
    print(f"Ошибка: {e}")
    pose_landmarker = None


def extract_pose(image_path: str):
    """Извлекает позу (33 landmarks + копчик)"""
    if not pose_landmarker:
        raise ValueError("PoseLandmarker не инициализирован")

    # Загружаем изображение
    mp_image = mp.Image.create_from_file(image_path)

    # Детектим позу
    detection_result = pose_landmarker.detect(mp_image)

    if not detection_result.pose_landmarks or len(detection_result.pose_landmarks) == 0:
        raise ValueError("Поза не найдена на фото")

    landmarks = detection_result.pose_world_landmarks[0]
    pose_points = []
    # Преобразует координаты в пространство Blender
    for lmk in landmarks:
        pose_points.append({
            'x': float(lmk.x),
            'y': float(lmk.z),
            'z': float(-lmk.y)
        })

    # копчик (индекс 33)
    if len(pose_points) >= 12:
        mid_hip = {
            'x': (pose_points[11]['x'] + pose_points[12]['x']) / 2.0,
            'y': (pose_points[11]['y'] + pose_points[12]['y']) / 2.0,
            'z': (pose_points[11]['z'] + pose_points[12]['z']) / 2.0
        }
        pose_points.append(mid_hip)

    return pose_points

def convert_mediapipe_to_blender(landmarks_3d):
    """
    Конвертирует координаты MediaPipe в систему координат Blender.
    """
    converted = []
    for lmk in landmarks_3d:
        converted.append({
            'x': float(lmk.x),
            'y': float(lmk.z),
            'z': float(-lmk.y),
            'visibility': float(lmk.visibility)
        })

    # Добавляем копчик (индекс 33)
    if len(converted) >= 12:
        mid_hip = {
            'x': (converted[11]['x'] + converted[12]['x']) / 2.0,
            'y': (converted[11]['y'] + converted[12]['y']) / 2.0,
            'z': (converted[11]['z'] + converted[12]['z']) / 2.0,
            'visibility': min(converted[11]['visibility'], converted[12]['visibility'])
        }
        converted.append(mid_hip)

    return converted

def get_video_info_and_frames(video_path: str, fragments_count: int):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError("Не удалось открыть видео")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    if total_frames <= 0 or not fps or fps <= 0:
        cap.release()
        raise ValueError("Не удалось определить параметры видео")

    fragments_count = max(1, min(fragments_count, total_frames))

    duration_sec = total_frames / fps
    fragment_duration_sec = duration_sec / fragments_count

    result = []
    # читает фрагменты с равным шагом
    for fragment_index in range(fragments_count):
        start_frame = int(fragment_index * total_frames / fragments_count)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        ok, frame = cap.read()
        if not ok:
            continue

        timestamp_sec = fragment_index * fragment_duration_sec
        result.append((round(timestamp_sec, 3), frame))

    cap.release()
    return result

def extract_pose_from_frame(frame):
    """Извлекает позу из кадра OpenCV"""
    if not pose_landmarker:
        raise ValueError("PoseLandmarker не инициализирован")

    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)

    detection_result = pose_landmarker.detect(mp_image)

    if not detection_result.pose_landmarks or len(detection_result.pose_landmarks) == 0:
        raise ValueError("Поза не найдена на кадре")

    landmarks = detection_result.pose_landmarks[0]
    pose_points = []
    for lmk in landmarks:
        pose_points.append({
            'x': float(lmk.x),
            'y': float(lmk.z),
            'z': float(-lmk.y)
        })

    if len(pose_points) >= 12:
        mid_hip = {
            'x': (pose_points[11]['x'] + pose_points[12]['x']) / 2.0,
            'y': (pose_points[11]['y'] + pose_points[12]['y']) / 2.0,
            'z': (pose_points[11]['z'] + pose_points[12]['z']) / 2.0
        }
        pose_points.append(mid_hip)

    return pose_points



def rotate_pose_raw(pose_raw, angle_degrees):
    """
    Поворачивает СЫРУЮ позу (в системе MediaPipe) вокруг вертикальной оси Y
    """
    angle_rad = np.radians(angle_degrees)
    cos_a = np.cos(angle_rad)
    sin_a = np.sin(angle_rad)

    rotated = []
    for point in pose_raw:
        x, y, z = point['x'], point['y'], point['z']

        # Поворот вокруг Y
        x_new = x * cos_a - z * sin_a
        z_new = x * sin_a + z * cos_a

        rotated.append({
            'x': float(x_new),
            'y': float(y),
            'z': float(z_new)
        })

    return rotated


def convert_to_blender_format(pose_raw):
    """
    Преобразует из сырой системы MediaPipe в формат для Blender
    """
    blender_pose = []
    for p in pose_raw:
        blender_pose.append({
            'x': p['x'],
            'y': p['z'],  
            'z': -p['y']  
        })
    return blender_pose

def extract_pose_raw(image_path: str):
    """Извлекает сырую позу без преобразований координат"""
    if not pose_landmarker:
        raise ValueError("PoseLandmarker не инициализирован")

    mp_image = mp.Image.create_from_file(image_path)
    detection_result = pose_landmarker.detect(mp_image)

    if not detection_result.pose_landmarks or len(detection_result.pose_landmarks) == 0:
        raise ValueError("Поза не найдена на фото")

    landmarks = detection_result.pose_landmarks[0] 
    pose_points = []
    for lmk in landmarks:
        pose_points.append({
            'x': float(lmk.x),     
            'y': float(lmk.y),     
            'z': float(lmk.z)     
        })

    # Добавляем копчик
    if len(pose_points) >= 12:
        mid_hip = {
            'x': (pose_points[11]['x'] + pose_points[12]['x']) / 2.0,
            'y': (pose_points[11]['y'] + pose_points[12]['y']) / 2.0,
            'z': (pose_points[11]['z'] + pose_points[12]['z']) / 2.0
        }
        pose_points.append(mid_hip)

    return pose_points
def convert_back_to_raw(pose_from_extract):
    """
    Преобразует позу из формата extract_pose обратно в сырые координаты MediaPipe
    """
    raw = []
    for p in pose_from_extract:
        raw.append({
            'x': p['x'],        
            'y': -p['z'],       
            'z': p['y']         
        })
    return raw





@app.post("/process_pose")
async def process_pose(file: UploadFile = File(...)):
    """
    Одиночное фото >> поза
    Возвращает JSON с позой
    """
    if not file.content_type or not file.content_type.startswith('image/'):
        raise HTTPException(400, "Только изображения")

    with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
        content = await file.read()
        tmp_file.write(content)
        target_path = tmp_file.name

    try:
        pose_points = extract_pose(target_path)

        #базовая поза deprecated
        pose_points_diff = None
        if os.path.exists('base_pose.jpg'):
            try:
                pose_points_base = extract_pose('base_pose.jpg')
                pose_points_diff = []
                max_len = max(len(pose_points), len(pose_points_base))
                for i in range(max_len):
                    px = pose_points[i] if i < len(pose_points) else {'x': 0, 'y': 0, 'z': 0}
                    bx = pose_points_base[i] if i < len(pose_points_base) else {'x': 0, 'y': 0, 'z': 0}
                    pose_points_diff.append({
                        'x': px['x'] - bx['x'],
                        'y': px['y'] - bx['y'],
                        'z': px['z'] - bx['z']
                    })
            except:
                pass

        result = {
            "status": "success",
            "pose": pose_points,
            "landmarks_count": len(pose_points)
        }
        
        if pose_points_diff:
            result["diff"] = pose_points_diff

        return JSONResponse(content=result)

    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, str(e))
    finally:
        if os.path.exists(target_path):
            os.unlink(target_path)


@app.post("/process_dual_pose_final")
async def process_dual_pose_final(
    front_image: UploadFile = File(...),
    side_image: UploadFile = File(...),
    angle_between_cameras: float = Form(90),
    write_debug: bool = Form(True)
):
    """
    Два фото >> поза с глубиной
    Возвращает JSON с позами
    """
    if not front_image.content_type or not front_image.content_type.startswith('image/'):
        raise HTTPException(400, "front_image должен быть изображением")
    if not side_image.content_type or not side_image.content_type.startswith('image/'):
        raise HTTPException(400, "side_image должен быть изображением")

    temp_files = []
    
    try:
        for img, suffix in [(front_image, 'front'), (side_image, 'side')]:
            content = await img.read()
            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
                tmp.write(content)
                temp_files.append((suffix, tmp.name))
            await img.seek(0)

        # Получаем позы в blender-формате
        front_blender = extract_pose(temp_files[0][1])
        side_blender = extract_pose(temp_files[1][1])
        
        # Конвертируем в сырые координаты
        front_raw = convert_back_to_raw(front_blender)
        side_raw = convert_back_to_raw(side_blender)
        
        # Поворачиваем боковую
        side_raw_rotated = rotate_pose_raw(side_raw, angle_between_cameras)
        
        # Конвертируем обратно в blender-формат
        side_blender_rotated = convert_to_blender_format(side_raw_rotated)
        
        # Триангуляция
        combined = []
        for i in range(min(len(front_blender), len(side_blender_rotated))):
            fb = front_blender[i]
            sb = side_blender_rotated[i]
            combined.append({
                'x': fb['x'],
                'y': fb['y'],
                'z': sb['z']
            })
        
        result = {
            "status": "success",
            "landmarks_count": len(combined),
            "combined_pose": combined,
            "front_pose": front_blender,
            "side_rotated": side_blender_rotated,
            "calibration": {
                "angle_between_cameras": angle_between_cameras,
                "method": "X,Y from front, Z from rotated side"
            }
        }
        
        if write_debug:
            result["debug"] = {
                "front_raw": front_raw,
                "side_raw": side_raw,
                "side_raw_rotated": side_raw_rotated
            }

        return JSONResponse(content=result)

    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, str(e))
    finally:
        for _, filepath in temp_files:
            if os.path.exists(filepath):
                os.unlink(filepath)


@app.post("/process_animation")
async def process_animation(
    file: UploadFile = File(...),
    fragments_count: int = Form(12)
):
    """
    Видео  >> анимация
    Возвращает JSON с позами по временным меткам
    """
    if not file.content_type or not file.content_type.startswith("video/"):
        raise HTTPException(400, "Только видео!")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_file:
        tmp_file.write(await file.read())
        target_path = tmp_file.name

    try:
        frames = get_video_info_and_frames(target_path, fragments_count)
        pose_by_timestamp = {}

        for timestamp, frame in frames:
            try:
                pose_points = extract_pose_from_frame(frame)
                pose_by_timestamp[str(timestamp)] = pose_points
            except Exception as e:
                pose_by_timestamp[str(timestamp)] = {"error": str(e)}

        result = {
            "status": "success",
            "fragments_count": len(frames),
            "poses": pose_by_timestamp
        }

        return JSONResponse(content=result)

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, str(e))
    finally:
        if os.path.exists(target_path):
            os.unlink(target_path)

@app.post("/process_frame")
async def process_frame(
        frame: UploadFile = File(...),
        session_id: str = Form(...)
):
    """
    Обрабатывает ОДИН кадр для реал-тайма
    """
    try:
        if not pose_landmarker:
            return JSONResponse(status_code=500, content={'error': 'PoseLandmarker not initialized'})

        frame_data = await frame.read()
        nparr = np.frombuffer(frame_data, np.uint8)
        frame_cv = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame_cv is None:
            return JSONResponse(status_code=400, content={'error': 'Failed to decode frame'})

        frame_rgb = cv2.cvtColor(frame_cv, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
        detection_result = pose_landmarker.detect(mp_image)

        if not detection_result.pose_landmarks:
            return JSONResponse(content={'pose_found': False, 'error': 'No pose detected'})

        landmarks_3d = []
        if detection_result.pose_world_landmarks:
            landmarks_3d = convert_mediapipe_to_blender(detection_result.pose_world_landmarks[0])
        else:
            landmarks_3d = convert_mediapipe_to_blender(detection_result.pose_landmarks[0])

        return JSONResponse(content={
            'session_id': session_id,
            'pose_found': True,
            'landmarks_count': len(landmarks_3d),
            'landmarks_3d': landmarks_3d,
            'method': 'monocular'
        })

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={'error': str(e)})

@app.post("/process_dual_animation")
async def process_dual_animation(
    front_video: UploadFile = File(...),
    side_video: UploadFile = File(...),
    fragments_count: int = Form(12),
    angle_between_cameras: float = Form(90.0),
    write_debug: bool = Form(False)
):
    """
    Два видео >> анимация с глубиной.
    Обрабатывает кадры из обоих видео, комбинирует X,Y из фронтального,
    Z из бокового (после поворота на угол между камерами).
    Возвращает JSON с позами по временным меткам.
    по сути повторяет process_animation но использует два видео и на каждом шаге вместо обычной extract_pose берет комбинированную из двух
    """
    if not front_video.content_type or not front_video.content_type.startswith("video/"):
        raise HTTPException(400, "front_video должен быть видео")
    if not side_video.content_type or not side_video.content_type.startswith("video/"):
        raise HTTPException(400, "side_video должен быть видео")

    temp_files = []
    
    try:
        # Сохраняем оба видео
        for video, suffix in [(front_video, 'front'), (side_video, 'side')]:
            content = await video.read()
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp:
                tmp.write(content)
                temp_files.append((suffix, tmp.name))
            await video.seek(0)

        front_path = temp_files[0][1]
        side_path = temp_files[1][1]

        # Получаем кадры из обоих видео
        front_frames = get_video_info_and_frames(front_path, fragments_count)
        side_frames = get_video_info_and_frames(side_path, fragments_count)

        # Берём минимальное количество кадров
        min_frames = min(len(front_frames), len(side_frames))
        pose_by_timestamp = {}

        for i in range(min_frames):
            ts_front, frame_front = front_frames[i]
            ts_side, frame_side = side_frames[i]
            
            # Используем timestamp из фронтального видео
            timestamp = round(ts_front, 3)
            
            try:
                # Извлекаем позы в blender-формате
                front_blender = extract_pose_from_frame(frame_front)
                side_blender = extract_pose_from_frame(frame_side)
                
                # Конвертируем в сырые координаты
                front_raw = convert_back_to_raw(front_blender)
                side_raw = convert_back_to_raw(side_blender)
                
                # Поворачиваем боковую
                side_raw_rotated = rotate_pose_raw(side_raw, angle_between_cameras)
                
                # Конвертируем обратно в blender-формат
                side_blender_rotated = convert_to_blender_format(side_raw_rotated)
                
                # Триангуляция: X,Y из фронта, Z из повёрнутого бока
                combined = []
                max_len = max(len(front_blender), len(side_blender_rotated))
                for j in range(max_len):
                    fb = front_blender[j] if j < len(front_blender) else {'x': 0, 'y': 0, 'z': 0}
                    sb = side_blender_rotated[j] if j < len(side_blender_rotated) else {'x': 0, 'y': 0, 'z': 0}
                    combined.append({
                        'x': fb['x'],
                        'y': fb['y'],
                        'z': sb['z']
                    })
                
                pose_by_timestamp[str(timestamp)] = combined
                
            except Exception as e:
                pose_by_timestamp[str(timestamp)] = {"error": str(e)}

        result = {
            "status": "success",
            "fragments_count": min_frames,
            "angle_between_cameras": angle_between_cameras,
            "method": "X,Y from front video, Z from rotated side video",
            "poses": pose_by_timestamp
        }

        if write_debug:
            result["debug_info"] = {
                "front_frames_count": len(front_frames),
                "side_frames_count": len(side_frames),
                "used_frames": min_frames
            }

        return JSONResponse(content=result)

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, str(e))
    finally:
        for _, filepath in temp_files:
            if os.path.exists(filepath):
                os.unlink(filepath)

@app.get("/")
async def root():
    return {
        "status": "MediaPipe работает!",
        "model": "pose_landmarker_lite.task" if os.path.exists(MODEL_PATH) else "НЕ НАЙДЕН",
        "base_pose": os.path.exists('base_pose.jpg'),
        "docs": "/docs"
    }


if __name__ == "__main__":
    import uvicorn
    
    # Проверяем наличие модели
    MODEL_PATH = "pose_landmarker_lite.task"
    if not os.path.exists(MODEL_PATH):
        print("="*60)
        print("  МОДЕЛЬ НЕ НАЙДЕНА!")
        print("="*60)
        print(f"\nСкачайте модель и сохраните как '{MODEL_PATH}':")
        print("  https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task")
        print("\nИли запустите установку:")
        print("  python setup.py")
        sys.exit(1)
    
    print("="*60)
    print("  POSE SERVER v2.0")
    print("="*60)
    print(f"  Модель: {MODEL_PATH}")
    print(f"  Сервер: http://127.0.0.1:5000")
    print(f"  Доки:   http://127.0.0.1:5000/docs")
    print("="*60)
    
    uvicorn.run(app, host="127.0.0.1", port=5000)