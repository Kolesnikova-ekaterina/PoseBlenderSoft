bl_info = {
    "name": "Camera Pose REAL TIME",
    "author": "Your Name",
    "version": (6, 1),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Webcam",
    "description": "Fast pose capture ",
    "category": "Animation",
}

import bpy
import json
import time
import threading
import subprocess
import os
import sys
import numpy as np
from pathlib import Path
from mathutils import Vector, Quaternion
from math import atan2, pi
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import (
    StringProperty, FloatProperty, IntProperty,
    PointerProperty, BoolProperty, EnumProperty,
)
from datetime import datetime


class Logger:
    _logs = []

    @classmethod
    def log(cls, msg, level='INFO'):
        ts = datetime.now().strftime('%H:%M:%S')
        cls._logs.append({'ts': ts, 'msg': str(msg)})
        if len(cls._logs) > 200:
            cls._logs = cls._logs[-200:]
        print(f"[{ts}] {msg}")

    @classmethod
    def info(cls, msg): cls.log(msg)

    @classmethod
    def warn(cls, msg): cls.log(msg, 'WARN')

    @classmethod
    def error(cls, msg): cls.log(msg, 'ERROR')

    @classmethod
    def get_logs(cls, n=30): return cls._logs[-n:]

    @classmethod
    def clear(cls): cls._logs.clear()


log = Logger()

BLENDER_PYTHON = sys.executable
FRONT_IMAGE = "FrontCam"
SIDE_IMAGE = "SideCam"
W, H = 320, 240

realtime_running = False
latest_pose_data = None  # Храню сырые данные позы
pose_ready = threading.Event()  # Сигнал "новая поза готова" - надо чтобы потоки коммуницировали
cv2 = None

stats = {
    'fps_capture': 0,
    'fps_pose': 0,
    'status': 'idle',
    'method': 'none',
    'errors': 0
}


class PoseFilter:

    def __init__(self, window=3):
        self.history = []
        self.window = window
        self.prev = None

    def filter(self, landmarks):
        if not landmarks:
            return None

        # Если нет предыдущей - возвращаем как есть
        if self.prev is None or len(self.prev) != len(landmarks):
            self.prev = landmarks
            self.history = [landmarks]
            return landmarks

        # Простое среднее с предыдущим кадром
        result = []
        alpha = 0.4  # Фактор сглаживания 
        for i, (p, c) in enumerate(zip(self.prev, landmarks)):
            if i < len(landmarks):
                # Проверка на скачок
                dx = c.get('x', 0) - p.get('x', 0)
                dy = c.get('y', 0) - p.get('y', 0)
                dz = c.get('z', 0) - p.get('z', 0)
                dist = (dx * dx + dy * dy + dz * dz) ** 0.5

                if dist < 0.3:  # Не больше 30см скачок
                    result.append({
                        'x': alpha * c['x'] + (1 - alpha) * p['x'],
                        'y': alpha * c['y'] + (1 - alpha) * p['y'],
                        'z': alpha * c['z'] + (1 - alpha) * p['z'],
                        'visibility': c.get('visibility', 1.0)
                    })
                else:
                    result.append(p.copy())
            else:
                result.append(p.copy())

        self.prev = result
        return result


pose_filter = PoseFilter(window=3)


def apply_pose_fast(context, armature, points):
    if len(points) < 25:
        return False

    # повороты позвоночника опускаю чтобы не перегружать блендер
    bone_map = {
        'thigh_R': (24, 26), 'thigh_L': (23, 25),
        'calf_R': (26, 28), 'calf_L': (25, 27),
        'upperarm_R': (12, 14), 'upperarm_L': (11, 13),
        'lowerarm_R': (14, 16), 'lowerarm_L': (13, 15),
    }

    def vec(i):
        p = points[i]
        return Vector((p['x'], p['y'], p['z']))

    try:
        for bone_name, (a, b) in bone_map.items():
            bone = armature.pose.bones.get(bone_name)
            if not bone or a >= len(points) or b >= len(points):
                continue

            # Проверка видимости
            if points[a].get('visibility', 0) < 0.3 or points[b].get('visibility', 0) < 0.3:
                continue

            va = vec(a)
            vb = vec(b)
            v = (vb - va)
            if v.length < 0.01:
                continue
            v.normalize()

            pm = bone.parent.matrix if bone.parent else armature.matrix_world
            pr = pm.to_quaternion().inverted()
            q = Vector((0, 1, 0)).rotation_difference(pr @ v)

            bone.rotation_mode = 'QUATERNION'
            bone.rotation_quaternion = q

        context.view_layer.update()
        return True
    except:
        return False


def capture_thread():
    global realtime_running, latest_pose_data, pose_ready, stats, cv2

    import requests as req

    props = bpy.context.scene.bridge_props

    # Открываем камеру
    cam_idx = int(props.front_camera) if props.front_camera.isdigit() else 0

    cap = None
    for backend in [cv2.CAP_DSHOW, cv2.CAP_ANY]:
        cap = cv2.VideoCapture(cam_idx, backend)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, W)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
            cap.set(cv2.CAP_PROP_FPS, 30)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Минимальный буфер!
            ret, _ = cap.read()
            if ret:
                break
            cap.release()
            cap = None

    if cap is None:
        log.error(f"Cannot open camera {cam_idx}")
        stats['status'] = 'error'
        return

    log.info(f"Camera {cam_idx} opened ({W}x{H})")
    stats['status'] = 'running'

    session = f"b_{int(time.time())}"
    frame_count = 0
    last_fps_time = time.time()
    fps_frames = 0

    img = None
    try:
        img = bpy.data.images.get(FRONT_IMAGE)
        if img is None:
            img = bpy.data.images.new(FRONT_IMAGE, W, H, alpha=False, float_buffer=True)
    except:
        pass

    try:
        while realtime_running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.001)
                continue

            frame_count += 1
            fps_frames += 1

            # FPS счетчик
            now = time.time()
            if now - last_fps_time >= 1.0:
                stats['fps_capture'] = fps_frames
                fps_frames = 0
                last_fps_time = now

            # Обрабатываем каждый 2-й кадр
            if frame_count % 2 != 0:
                continue

            # Сжимаем в JPEG
            _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])

            # Отправляем на сервер
            try:
                resp = req.post(
                    f'{props.server_url}/process_frame',
                    files={'frame': ('f.jpg', buf.tobytes(), 'image/jpeg')},
                    data={
                        'session_id': session,
                        'front_distance': props.front_distance,
                        'front_height': props.front_height
                    },
                    timeout=1.5  # Короткий таймаут - чтобы не оказаться в бесконечном цикле навсегда
                )

                if resp.status_code == 200:
                    data = resp.json()
                    if data.get('pose_found'):
                        # Сохраняем позу в глобальную переменную
                        latest_pose_data = data.get('landmarks_3d', [])
                        pose_ready.set()  # Сигнализируем что поза готова
                        stats['fps_pose'] += 1
                        stats['method'] = 'mono'

            except:
                stats['errors'] += 1

            # Небольшая задержка для стабильности
            time.sleep(0.01)

    except Exception as e:
        log.error(f"Capture error: {e}")
    finally:
        cap.release()
        stats['status'] = 'idle'


class BRIDGE_OT_start(Operator):
    bl_idname = 'bridge.start'
    bl_label = 'Start'

    _timer = None

    def modal(self, context, event):
        if event.type == 'TIMER':
            self.process_pose(context)

        if not realtime_running:
            self.cleanup(context)
            return {'CANCELLED'}

        return {'PASS_THROUGH'}

    def process_pose(self, context):
        """Обрабатывает позу только когда она готова"""
        global latest_pose_data, pose_ready

        props = context.scene.bridge_props
        if not props.apply_pose:
            return

        # Проверяем есть ли новая поза
        if not pose_ready.is_set():
            return

        pose_ready.clear()

        if latest_pose_data is None:
            return

        landmarks = list(latest_pose_data)  # Копируем

        # Фильтруем
        landmarks = pose_filter.filter(landmarks)
        if landmarks is None:
            return

        # Находим арматуру
        armature = None
        for obj in bpy.data.objects:
            if obj.type == 'ARMATURE':
                armature = obj
                break

        if armature is None:
            return

        #  применяем позу
        try:
            mode = context.mode
            if mode != 'POSE':
                bpy.context.view_layer.objects.active = armature
                bpy.ops.object.mode_set(mode='POSE')

            apply_pose_fast(context, armature, landmarks)

            if mode != 'POSE':
                bpy.ops.object.mode_set(mode='OBJECT')
        except:
            pass

    def execute(self, context):
        global realtime_running, cv2, stats

        if realtime_running:
            return {'CANCELLED'}

        # Проверяем cv2
        try:
            import cv2 as cv
            cv2 = cv
        except ImportError:
            self.report({'ERROR'}, 'OpenCV not installed!')
            return {'CANCELLED'}

        props = context.scene.bridge_props

        log.info(f"Starting capture...")

        # Создаем изображение
        try:
            img = bpy.data.images.get(FRONT_IMAGE)
            if img is None:
                bpy.data.images.new(FRONT_IMAGE, W, H, alpha=False, float_buffer=True)
        except:
            pass

        stats = {'fps_capture': 0, 'fps_pose': 0, 'status': 'starting', 'method': 'none', 'errors': 0}
        realtime_running = True

        # Запускаем поток захвата
        t = threading.Thread(target=capture_thread, daemon=True)
        t.start()

        # Таймер с большим интервалом (не нагружает UI)
        wm = context.window_manager
        self._timer = wm.event_timer_add(1.0 / 15.0, window=context.window)  # 15 FPS для UI
        wm.modal_handler_add(self)

        self.report({'INFO'}, 'Streaming started')
        return {'RUNNING_MODAL'}

    def cleanup(self, context):
        global realtime_running
        realtime_running = False
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
        stats['status'] = 'idle'

    def cancel(self, context):
        self.cleanup(context)


class BRIDGE_OT_stop(Operator):
    bl_idname = 'bridge.stop'
    bl_label = 'Stop'

    def execute(self, context):
        global realtime_running
        realtime_running = False
        return {'FINISHED'}


class BRIDGE_OT_install(Operator):
    bl_idname = 'bridge.install'
    bl_label = 'Install OpenCV'

    def execute(self, context):
        site = os.path.join(os.path.dirname(BLENDER_PYTHON), 'Lib', 'site-packages')
        cmd = f'"{BLENDER_PYTHON}" -s -m pip install --target "{site}" opencv-python numpy requests'
        log.info(f"Running: {cmd}")
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
            if r.returncode == 0:
                self.report({'INFO'}, 'Installed! Restart Blender.')
            else:
                self.report({'ERROR'}, f'Failed: {r.stderr[:100]}')
        except Exception as e:
            self.report({'ERROR'}, str(e))
        return {'FINISHED'}


class BridgeProps(PropertyGroup):
    server_url: StringProperty(default='http://127.0.0.1:5000')
    front_camera: StringProperty(default='0', description='Camera index')
    front_distance: FloatProperty(default=1.5, min=0.1)
    front_height: FloatProperty(default=1.2, min=0.0)
    update_rate: FloatProperty(default=15.0, min=5.0, max=30.0)
    apply_pose: BoolProperty(default=True)
    armature_name: StringProperty(default='Armature')


class BRIDGE_PT_panel(Panel):
    bl_label = 'Pose REAL TIME'
    bl_idname = 'BRIDGE_PT_panel'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Webcam'

    def draw(self, context):
        layout = self.layout
        props = context.scene.bridge_props

        # OpenCV статус
        try:
            import cv2
            layout.label(text="OpenCV Ready", icon='CHECKMARK')
        except ImportError:
            layout.label(text="OpenCV Missing", icon='ERROR')
            layout.operator('bridge.install', text='Install OpenCV', icon='PACKAGE')
            return

        layout.separator()

        # Настройки
        col = layout.column(align=True)
        col.prop(props, 'server_url', text='Server')
        col.prop(props, 'front_camera', text='Camera')
        col.prop(props, 'front_distance', text='Distance')
        col.prop(props, 'front_height', text='Height')

        col.separator()
        col.prop(props, 'armature_name', text='Armature')
        col.prop(props, 'apply_pose', text='Apply')
        col.prop(props, 'update_rate', text='FPS')

        layout.separator()

        # Кнопки
        row = layout.row(align=True)
        if not realtime_running:
            row.operator('bridge.start', text='▶ Start', icon='PLAY')
        else:
            row.operator('bridge.stop', text='⏹ Stop', icon='PAUSE')

        # Статус
        layout.separator()
        box = layout.box()
        box.label(text=f"Status: {stats['status']}")
        box.label(text=f"Capture FPS: {stats['fps_capture']}")
        box.label(text=f"Pose FPS: {stats['fps_pose']}")
        box.label(text=f"Method: {stats['method']}")
        box.label(text=f"Errors: {stats['errors']}")


classes = (
    BridgeProps,
    BRIDGE_OT_start,
    BRIDGE_OT_stop,
    BRIDGE_OT_install,
    BRIDGE_PT_panel,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.bridge_props = PointerProperty(type=BridgeProps)


def unregister():
    global realtime_running
    realtime_running = False
    del bpy.types.Scene.bridge_props
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == '__main__':
    register()
