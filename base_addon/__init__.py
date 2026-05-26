bl_info = {
    "name": "Pose from Photo v2",
    "author": "Ekaterina",
    "version": (2, 3, 0),
    "blender": (4, 0, 0),
    "location": "View3D > N-Panel > Pose Tool",
    "description": "аддон для автоматического позирования и анимации",
    "category": "Animation",
}

import bpy
import bpy.types
import json
import os
import urllib.request
import datetime
from mathutils import Vector, Quaternion
from math import atan2

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

PROCESS_POSE_ROUTE = "http://127.0.0.1:5000/process_pose"
PROCESS_DUAL_POSE_ROUTE = "http://127.0.0.1:5000/process_dual_pose_final"
PROCESS_ANIMATION_ROUTE = "http://127.0.0.1:5000/process_animation"
PROCESS_DUAL_ANIMATION_ROUTE = "http://127.0.0.1:5000/process_dual_animation"


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def get_addon_dir():
    return os.path.dirname(os.path.abspath(__file__))


def send_multipart(url, files_dict, data_dict=None, timeout=60):
    """Отправляет multipart/form-data запрос и возвращает распарсенный JSON"""
    boundary = f'----blender-{os.urandom(8).hex()}'

    body_parts = []

    for field_name, (filename, file_data, content_type) in files_dict.items():
        body_parts.extend([
            f'--{boundary}'.encode('utf-8'),
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"'.encode('utf-8'),
            f'Content-Type: {content_type}'.encode('utf-8'),
            b'',
            file_data,
        ])

    if data_dict:
        for key, value in data_dict.items():
            body_parts.extend([
                f'--{boundary}'.encode('utf-8'),
                f'Content-Disposition: form-data; name="{key}"'.encode('utf-8'),
                b'',
                str(value).encode('utf-8'),
            ])

    body_parts.append(f'--{boundary}--'.encode('utf-8'))
    body = b'\r\n'.join(body_parts)

    req = urllib.request.Request(url, data=body, method='POST')
    req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
    req.add_header('Accept', 'application/json')
    req.add_header('Content-Length', str(len(body)))

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        response_text = resp.read().decode('utf-8')
        return json.loads(response_text)


# ============================================================
# СВОЙСТВА
# ============================================================

def register_properties():
    # Одиночное фото
    bpy.types.Scene.pose_single_image = bpy.props.StringProperty(
        name="Single Image", default="", subtype='FILE_PATH'
    )

    # Двойное фото
    bpy.types.Scene.pose_front_image = bpy.props.StringProperty(
        name="Front Image", default="", subtype='FILE_PATH'
    )
    bpy.types.Scene.pose_side_image = bpy.props.StringProperty(
        name="Side Image", default="", subtype='FILE_PATH'
    )

    # Одиночное видео
    bpy.types.Scene.pose_selected_video = bpy.props.StringProperty(
        name="Selected Video", default="", subtype='FILE_PATH'
    )

    # Двойное видео
    bpy.types.Scene.pose_front_video = bpy.props.StringProperty(
        name="Front Video", default="", subtype='FILE_PATH'
    )
    bpy.types.Scene.pose_side_video = bpy.props.StringProperty(
        name="Side Video", default="", subtype='FILE_PATH'
    )

    # Модель
    bpy.types.Scene.pose_selected_model = bpy.props.StringProperty(
        name="Selected Model", default=""
    )

    # Хранилище данных в памяти
    bpy.types.Scene.pose_data_json = bpy.props.StringProperty(
        name="Pose Data JSON", default="",
        description="JSON-строка с данными позы (хранится в памяти)"
    )
    bpy.types.Scene.pose_animation_json = bpy.props.StringProperty(
        name="Animation Data JSON", default="",
        description="JSON-строка с данными анимации (хранится в памяти)"
    )

    # Настройки
    bpy.types.Scene.pose_fragments_count = bpy.props.IntProperty(
        name="Fragments Count", default=12, min=1, max=1000
    )
    bpy.types.Scene.pose_camera_angle = bpy.props.FloatProperty(
        name="Camera Angle", default=90.0, min=-180.0, max=180.0
    )
    bpy.types.Scene.pose_side_position = bpy.props.EnumProperty(
        name="Side Camera",
        items=[
            ('right', "Справа (90°)", ""),
            ('left', "Слева (-90°)", ""),
            ('custom', "Свой угол", ""),
        ],
        default='right',
    )
    bpy.types.Scene.pose_video_camera_angle = bpy.props.FloatProperty(
        name="Camera Angle (Video)", default=90.0, min=-180.0, max=180.0
    )
    bpy.types.Scene.pose_video_side_position = bpy.props.EnumProperty(
        name="Side Camera (Video)",
        items=[
            ('right', "Справа (90°)", ""),
            ('left', "Слева (-90°)", ""),
            ('custom', "Свой угол", ""),
        ],
        default='right',
    )


def unregister_properties():
    del bpy.types.Scene.pose_single_image
    del bpy.types.Scene.pose_front_image
    del bpy.types.Scene.pose_side_image
    del bpy.types.Scene.pose_selected_video
    del bpy.types.Scene.pose_front_video
    del bpy.types.Scene.pose_side_video
    del bpy.types.Scene.pose_selected_model
    del bpy.types.Scene.pose_data_json
    del bpy.types.Scene.pose_animation_json
    del bpy.types.Scene.pose_fragments_count
    del bpy.types.Scene.pose_camera_angle
    del bpy.types.Scene.pose_side_position
    del bpy.types.Scene.pose_video_camera_angle
    del bpy.types.Scene.pose_video_side_position


class POSE_OT_select_single_image(bpy.types.Operator):
    bl_idname = "pose.select_single_image"
    bl_label = "Выбрать фото"
    bl_options = {'REGISTER', 'UNDO'}
    filepath: bpy.props.StringProperty(subtype='FILE_PATH', default="")

    def execute(self, context):
        context.scene.pose_single_image = self.filepath
        self.report({'INFO'}, f"{os.path.basename(self.filepath)}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class POSE_OT_select_front_image(bpy.types.Operator):
    bl_idname = "pose.select_front_image"
    bl_label = "Выбрать фронт"
    bl_options = {'REGISTER', 'UNDO'}
    filepath: bpy.props.StringProperty(subtype='FILE_PATH', default="")

    def execute(self, context):
        context.scene.pose_front_image = self.filepath
        self.report({'INFO'}, f"Фронт: {os.path.basename(self.filepath)}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class POSE_OT_select_side_image(bpy.types.Operator):
    bl_idname = "pose.select_side_image"
    bl_label = "Выбрать бок"
    bl_options = {'REGISTER', 'UNDO'}
    filepath: bpy.props.StringProperty(subtype='FILE_PATH', default="")

    def execute(self, context):
        context.scene.pose_side_image = self.filepath
        self.report({'INFO'}, f"Бок: {os.path.basename(self.filepath)}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class POSE_OT_select_video(bpy.types.Operator):
    bl_idname = "pose.select_video"
    bl_label = "Выбрать видео"
    bl_options = {'REGISTER', 'UNDO'}
    filepath: bpy.props.StringProperty(subtype='FILE_PATH', default="")

    def execute(self, context):
        context.scene.pose_selected_video = self.filepath
        self.report({'INFO'}, f"Видео: {os.path.basename(self.filepath)}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class POSE_OT_select_front_video(bpy.types.Operator):
    bl_idname = "pose.select_front_video"
    bl_label = "Выбрать фронт видео"
    bl_options = {'REGISTER', 'UNDO'}
    filepath: bpy.props.StringProperty(subtype='FILE_PATH', default="")

    def execute(self, context):
        context.scene.pose_front_video = self.filepath
        self.report({'INFO'}, f"Фронт видео: {os.path.basename(self.filepath)}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class POSE_OT_select_side_video(bpy.types.Operator):
    bl_idname = "pose.select_side_video"
    bl_label = "Выбрать бок видео"
    bl_options = {'REGISTER', 'UNDO'}
    filepath: bpy.props.StringProperty(subtype='FILE_PATH', default="")

    def execute(self, context):
        context.scene.pose_side_video = self.filepath
        self.report({'INFO'}, f"Бок видео: {os.path.basename(self.filepath)}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class POSE_OT_load_model(bpy.types.Operator):
    bl_idname = "pose.load_model"
    bl_label = "Загрузить модель"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        addon_dir = get_addon_dir()
        candidates = [
            os.path.join(addon_dir, "model.fbx"),
        ]
        model_path = None
        for p in candidates:
            if os.path.exists(p):
                model_path = p
                break
        if not model_path:
            self.report({'ERROR'}, "Модель не найдена")
            return {'CANCELLED'}
        try:
            ext = os.path.splitext(model_path)[1].lower()
            if ext in {".glb", ".gltf"}:
                bpy.ops.import_scene.gltf(filepath=model_path)
            elif ext == ".fbx":
                bpy.ops.import_scene.fbx(filepath=model_path)
            elif ext == ".obj":
                bpy.ops.import_scene.obj(filepath=model_path)
            context.scene.pose_selected_model = model_path
            self.report({'INFO'}, f"{os.path.basename(model_path)}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"{e}")
            return {'CANCELLED'}


class POSE_OT_send_single(bpy.types.Operator):
    bl_idname = "pose.send_single"
    bl_label = "Отправить на сервер"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        img_path = bpy.path.abspath(scene.pose_single_image)
        if not os.path.exists(img_path):
            self.report({'ERROR'}, "Выбери фото!")
            return {'CANCELLED'}
        self.report({'INFO'}, "Отправка...")
        try:
            with open(img_path, 'rb') as f:
                file_data = f.read()
            files = {'file': (os.path.basename(img_path), file_data, 'image/jpeg')}
            result = send_multipart(PROCESS_POSE_ROUTE, files, timeout=60)

            # Извлекаем позу
            if isinstance(result, list):
                pose_data = result
            elif isinstance(result, dict):
                pose_data = result.get('pose') or result.get('combined_pose') or result
            else:
                pose_data = result

            # Сохраняем в свойство сцены
            scene.pose_data_json = json.dumps(pose_data)
            self.report({'INFO'}, f"Поза получена! {len(pose_data) if isinstance(pose_data, list) else '?'} точек")

        except Exception as e:
            self.report({'ERROR'}, f"{str(e)}")
            return {'CANCELLED'}
        return {'FINISHED'}


class POSE_OT_send_dual(bpy.types.Operator):
    bl_idname = "pose.send_dual"
    bl_label = "Отправить на сервер"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        front_path = bpy.path.abspath(scene.pose_front_image)
        side_path = bpy.path.abspath(scene.pose_side_image)
        if not os.path.exists(front_path):
            self.report({'ERROR'}, "Выбери фронт!")
            return {'CANCELLED'}
        if not os.path.exists(side_path):
            self.report({'ERROR'}, "Выбери бок!")
            return {'CANCELLED'}

        angle = {'right': 90.0, 'left': -90.0}.get(scene.pose_side_position, scene.pose_camera_angle)
        self.report({'INFO'}, f"Отправка (угол={angle}°)...")

        try:
            with open(front_path, 'rb') as f1, open(side_path, 'rb') as f2:
                files = {
                    'front_image': (os.path.basename(front_path), f1.read(), 'image/jpeg'),
                    'side_image': (os.path.basename(side_path), f2.read(), 'image/jpeg'),
                }
            data = {'angle_between_cameras': str(angle), 'write_debug': 'true'}
            result = send_multipart(PROCESS_DUAL_POSE_ROUTE, files, data, timeout=60)

            if isinstance(result, dict) and 'combined_pose' in result:
                scene.pose_data_json = json.dumps(result['combined_pose'])
                self.report({'INFO'}, f"Поза получена! {result.get('landmarks_count', '?')} точек")
            else:
                self.report({'ERROR'}, "Нет combined_pose в ответе")
                return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"{str(e)}")
            return {'CANCELLED'}
        return {'FINISHED'}


class POSE_OT_create_animation(bpy.types.Operator):
    bl_idname = "pose.create_animation"
    bl_label = "Создать анимацию"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        video_path = bpy.path.abspath(scene.pose_selected_video)
        if not os.path.exists(video_path):
            self.report({'ERROR'}, "Выбери видео!")
            return {'CANCELLED'}
        self.report({'INFO'}, "Отправка видео...")
        try:
            with open(video_path, 'rb') as f:
                file_data = f.read()
            files = {'file': (os.path.basename(video_path), file_data, 'video/mp4')}
            data = {'fragments_count': str(scene.pose_fragments_count)}
            result = send_multipart(PROCESS_ANIMATION_ROUTE, files, data, timeout=120)

            scene.pose_animation_json = json.dumps(result)
            self.report({'INFO'}, f"Анимация получена!")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"{str(e)}")
            return {'CANCELLED'}


class POSE_OT_create_dual_animation(bpy.types.Operator):
    bl_idname = "pose.create_dual_animation"
    bl_label = "Создать анимацию (два видео)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        front_path = bpy.path.abspath(scene.pose_front_video)
        side_path = bpy.path.abspath(scene.pose_side_video)
        if not os.path.exists(front_path):
            self.report({'ERROR'}, "Выбери фронт видео!")
            return {'CANCELLED'}
        if not os.path.exists(side_path):
            self.report({'ERROR'}, "Выбери бок видео!")
            return {'CANCELLED'}

        angle = {'right': 90.0, 'left': -90.0}.get(scene.pose_video_side_position, scene.pose_video_camera_angle)
        self.report({'INFO'}, f"Отправка двух видео (угол={angle}°)...")

        try:
            with open(front_path, 'rb') as f1, open(side_path, 'rb') as f2:
                files = {
                    'front_video': (os.path.basename(front_path), f1.read(), 'video/mp4'),
                    'side_video': (os.path.basename(side_path), f2.read(), 'video/mp4'),
                }
            data = {
                'fragments_count': str(scene.pose_fragments_count),
                'angle_between_cameras': str(angle),
                'write_debug': 'true'
            }
            result = send_multipart(PROCESS_DUAL_ANIMATION_ROUTE, files, data, timeout=120)

            scene.pose_animation_json = json.dumps(result)
            self.report({'INFO'}, f"Dual анимация получена! Фрагментов: {result.get('fragments_count', '?')}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f" {str(e)}")
            return {'CANCELLED'}



def apply_pose_from_points(context, armature, pose_target_points):
    """Применяет позу к арматуре"""
    bone_to_connection = {
        'clavicle_R': (33, 12), 'clavicle_L': (33, 11),
        'thigh_R': (24, 26), 'thigh_L': (23, 25),
        'upperarm_R': (12, 14), 'upperarm_L': (11, 13),
        'calf_R': (26, 28), 'calf_L': (25, 27),
        'foot_R': (28, 32), 'foot_L': (27, 31),
        'lowerarm_R': (14, 16), 'lowerarm_L': (13, 15)
    }

    left_hip = Vector((pose_target_points[23]['x'], pose_target_points[23]['y'], pose_target_points[23]['z']))
    right_hip = Vector((pose_target_points[24]['x'], pose_target_points[24]['y'], pose_target_points[24]['z']))
    left_shoulder = Vector((pose_target_points[11]['x'], pose_target_points[11]['y'], pose_target_points[11]['z']))
    right_shoulder = Vector((pose_target_points[12]['x'], pose_target_points[12]['y'], pose_target_points[12]['z']))

    hip_mid = (left_hip + right_hip) * 0.5
    shoulder_mid = (left_shoulder + right_shoulder) * 0.5

    hips_to_shoulders = shoulder_mid - hip_mid
    if hips_to_shoulders.length < 1e-8:
        hips_to_shoulders = Vector((0, 0, 1))
    hips_to_shoulders.normalize()

    hips_line = - right_hip + left_hip
    if hips_line.length < 1e-8:
        hips_line = Vector((1, 0, 0))
    hips_line.normalize()

    shoulders_line = - right_shoulder + left_shoulder
    if shoulders_line.length < 1e-8:
        shoulders_line = Vector((1, 0, 0))
    shoulders_line.normalize()

    # PELVIS
    pelvis_bone = armature.pose.bones.get("pelvis")
    if pelvis_bone is not None:
        pelvis_forward = hips_line.cross(hips_to_shoulders)
        if pelvis_forward.length < 1e-8:
            pelvis_forward = Vector((0, 0, 1))
        pelvis_forward.normalize()
        if pelvis_forward.z < 0:
            pelvis_forward.negate()

        align_quat = Vector((0, 1, 0)).rotation_difference(hips_to_shoulders)

        reference_hips = align_quat @ Vector((-1, 0, 0))
        reference_hips = reference_hips - hips_to_shoulders * reference_hips.dot(hips_to_shoulders)
        if reference_hips.length > 1e-8:
            reference_hips.normalize()
        else:
            reference_hips = Vector((-1, 0, 0))

        hips_proj = (-hips_line) - hips_to_shoulders * (-hips_line).dot(hips_to_shoulders)
        if hips_proj.length > 1e-8:
            hips_proj.normalize()
        else:
            hips_proj = Vector((-1, 0, 0))

        twist_angle = atan2(
            reference_hips.cross(hips_proj).dot(hips_to_shoulders),
            reference_hips.dot(hips_proj)
        )
        twist_quat = Quaternion(hips_to_shoulders, twist_angle)
        final_quat = twist_quat @ align_quat

        if pelvis_bone.parent:
            parent_quat = pelvis_bone.parent.matrix.to_quaternion()
            local_quat = parent_quat.inverted() @ final_quat
        else:
            local_quat = final_quat

        pelvis_bone.rotation_mode = 'QUATERNION'
        pelvis_bone.rotation_quaternion = local_quat
        pelvis_bone.keyframe_insert(data_path="rotation_quaternion", frame=context.scene.frame_current)
        context.view_layer.update()

    # SPINE
    spine01_bone = armature.pose.bones.get("spine01")
    spine02_bone = armature.pose.bones.get("spine02")

    if spine02_bone is not None:
        spine_forward = shoulders_line.cross(hips_to_shoulders)
        if spine_forward.length < 1e-8:
            spine_forward = Vector((0, 0, 1))
        spine_forward.normalize()
        if spine_forward.z < 0:
            spine_forward.negate()

        align_quat_spine02 = Vector((0, 1, 0)).rotation_difference(hips_to_shoulders)

        reference_shoulders = align_quat_spine02 @ Vector((1, 0, 0))
        reference_shoulders = reference_shoulders - hips_to_shoulders * reference_shoulders.dot(hips_to_shoulders)
        if reference_shoulders.length > 1e-8:
            reference_shoulders.normalize()
        else:
            reference_shoulders = Vector((1, 0, 0))

        shoulders_proj = shoulders_line - hips_to_shoulders * shoulders_line.dot(hips_to_shoulders)
        if shoulders_proj.length > 1e-8:
            shoulders_proj.normalize()
        else:
            shoulders_proj = Vector((1, 0, 0))

        twist_angle_spine02 = atan2(
            reference_shoulders.cross(shoulders_proj).dot(hips_to_shoulders),
            reference_shoulders.dot(shoulders_proj)
        )
        twist_quat_spine02 = Quaternion(hips_to_shoulders, twist_angle_spine02)
        target_quat_spine02 = twist_quat_spine02 @ align_quat_spine02

        if spine01_bone is not None and pelvis_bone is not None:
            if pelvis_bone.parent:
                parent_quat = pelvis_bone.parent.matrix.to_quaternion()
                pelvis_quat = parent_quat @ pelvis_bone.rotation_quaternion
            else:
                pelvis_quat = pelvis_bone.rotation_quaternion

            delta_quat = pelvis_quat.inverted() @ target_quat_spine02
            half_delta = Quaternion().slerp(delta_quat, 0.5)

            spine01_target = pelvis_quat @ half_delta
            spine02_target = spine01_target @ half_delta

            if spine01_bone.parent:
                parent_q = spine01_bone.parent.matrix.to_quaternion()
                local_spine01 = parent_q.inverted() @ spine01_target
            else:
                local_spine01 = spine01_target

            spine01_bone.rotation_mode = 'QUATERNION'
            spine01_bone.rotation_quaternion = local_spine01
            spine01_bone.keyframe_insert(data_path="rotation_quaternion", frame=context.scene.frame_current)
            context.view_layer.update()

            if spine02_bone.parent:
                parent_q = spine02_bone.parent.matrix.to_quaternion()
                local_spine02 = parent_q.inverted() @ spine02_target
            else:
                local_spine02 = spine02_target

            spine02_bone.rotation_mode = 'QUATERNION'
            spine02_bone.rotation_quaternion = local_spine02
            spine02_bone.keyframe_insert(data_path="rotation_quaternion", frame=context.scene.frame_current)
            context.view_layer.update()
        else:
            if spine02_bone.parent:
                parent_quat = spine02_bone.parent.matrix.to_quaternion()
                local_quat = parent_quat.inverted() @ target_quat_spine02
            else:
                local_quat = target_quat_spine02

            spine02_bone.rotation_mode = 'QUATERNION'
            spine02_bone.rotation_quaternion = local_quat
            spine02_bone.keyframe_insert(data_path="rotation_quaternion", frame=context.scene.frame_current)
            context.view_layer.update()

    # КОНЕЧНОСТИ
    for bone_name, (start_id, end_id) in bone_to_connection.items():
        pose_bone = armature.pose.bones.get(bone_name)
        if pose_bone is None:
            continue

        target_start = Vector((
            pose_target_points[start_id]['x'],
            pose_target_points[start_id]['y'],
            pose_target_points[start_id]['z']
        ))
        target_end = Vector((
            pose_target_points[end_id]['x'],
            pose_target_points[end_id]['y'],
            pose_target_points[end_id]['z']
        ))
        vec = target_end - target_start
        if vec.length < 1e-8:
            continue
        vec.normalize()

        if pose_bone.parent:
            parent_rot = pose_bone.parent.matrix.to_quaternion()
        else:
            parent_rot = armature.matrix_world.to_quaternion()

        local_vec = parent_rot.inverted() @ vec
        quat = Vector((0, 1, 0)).rotation_difference(local_vec)

        pose_bone.rotation_mode = 'QUATERNION'
        pose_bone.rotation_quaternion = quat
        pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=context.scene.frame_current)
        context.view_layer.update()


class POSE_OT_apply_pose(bpy.types.Operator):
    bl_idname = "pose.apply_pose"
    bl_label = "Применить позу"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        if not scene.pose_data_json:
            self.report({'ERROR'}, "Сначала отправьте фото на сервер!")
            return {'CANCELLED'}
        try:
            pose_data = json.loads(scene.pose_data_json)
            armature = None
            for obj in context.scene.objects:
                if obj.type == 'ARMATURE':
                    armature = obj
                    break
            if not armature:
                self.report({'ERROR'}, "Скелет не найден!")
                return {'CANCELLED'}
            context.view_layer.objects.active = armature
            bpy.ops.object.mode_set(mode='POSE')
            apply_pose_from_points(context, armature, pose_data)
            bpy.ops.object.mode_set(mode='OBJECT')
            self.report({'INFO'}, "Поза применена!")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"{str(e)}")
            return {'CANCELLED'}


class POSE_OT_bake_animation(bpy.types.Operator):
    bl_idname = "pose.bake_animation"
    bl_label = "Запечь анимацию"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        if not scene.pose_animation_json:
            self.report({'ERROR'}, "Сначала создайте анимацию!")
            return {'CANCELLED'}
        try:
            data = json.loads(scene.pose_animation_json)
            armature = None
            for obj in context.scene.objects:
                if obj.type == 'ARMATURE':
                    armature = obj
                    break
            if not armature:
                self.report({'ERROR'}, "Скелет не найден!")
                return {'CANCELLED'}

            poses_dict = data.get('poses', {k: v for k, v in data.items() if k not in (
            'status', 'fragments_count', 'angle_between_cameras', 'method', 'debug_info')})

            items = []
            for ts, points in poses_dict.items():
                try:
                    if isinstance(points, dict) and 'error' not in points:
                        items.append((float(ts), points))
                except:
                    continue
            items.sort(key=lambda x: x[0])

            if not items:
                self.report({'ERROR'}, "Нет поз в анимации")
                return {'CANCELLED'}

            fps = context.scene.render.fps / context.scene.render.fps_base
            context.view_layer.objects.active = armature
            bpy.ops.object.mode_set(mode='POSE')

            if armature.animation_data is None:
                armature.animation_data_create()

            action_name = "PoseAnim_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            new_action = bpy.data.actions.new(name=action_name)
            armature.animation_data.action = new_action
            new_action.use_fake_user = True

            for ts, points in items:
                frame = int(round(ts * fps))
                context.scene.frame_set(frame)
                apply_pose_from_points(context, armature, points)

            bpy.ops.object.mode_set(mode='OBJECT')
            self.report({'INFO'}, f"{action_name}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"{str(e)}")
            return {'CANCELLED'}


class POSE_PT_single_panel(bpy.types.Panel):
    bl_label = "Одиночное фото"
    bl_idname = "POSE_PT_single_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Pose Tool"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        box = layout.box()
        img_path = bpy.path.abspath(scene.pose_single_image)
        if img_path and os.path.exists(img_path):
            box.label(text=f"{os.path.basename(img_path)}", icon='FILE_IMAGE')
        else:
            box.label(text="Выбери фото", icon='ERROR')
        box.operator("pose.select_single_image", icon='FILE_IMAGE')
        box.operator("pose.send_single", icon='EXPORT')
        if scene.pose_data_json:
            box.label(text="Данные в памяти", icon='CHECKMARK')


class POSE_PT_dual_panel(bpy.types.Panel):
    bl_label = "Двойное фото"
    bl_idname = "POSE_PT_dual_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Pose Tool"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        box = layout.box()
        for prop, label in [('pose_front_image', 'Фронт'), ('pose_side_image', 'Бок')]:
            path = bpy.path.abspath(getattr(scene, prop))
            if path and os.path.exists(path):
                box.label(text=f"{label}: {os.path.basename(path)}", icon='FILE_IMAGE')
            else:
                box.label(text=f"{label}", icon='ERROR')
        box.operator("pose.select_front_image", icon='FILE_IMAGE')
        box.operator("pose.select_side_image", icon='FILE_IMAGE')
        box.separator()
        box.prop(scene, "pose_side_position")
        if scene.pose_side_position == 'custom':
            box.prop(scene, "pose_camera_angle")
        box.operator("pose.send_dual", icon='EXPORT')
        if scene.pose_data_json:
            box.label(text="Данные в памяти", icon='CHECKMARK')


class POSE_PT_animation_panel(bpy.types.Panel):
    bl_label = "Одно видео"
    bl_idname = "POSE_PT_animation_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Pose Tool"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        box = layout.box()
        path = bpy.path.abspath(scene.pose_selected_video)
        if path and os.path.exists(path):
            box.label(text=f"{os.path.basename(path)}", icon='FILE_MOVIE')
        else:
            box.label(text="Выбери видео", icon='ERROR')
        box.prop(scene, "pose_fragments_count")
        box.operator("pose.select_video", icon='FILE_MOVIE')
        box.operator("pose.create_animation", icon='ACTION')
        if scene.pose_animation_json:
            box.label(text="Анимация в памяти", icon='CHECKMARK')


class POSE_PT_dual_animation_panel(bpy.types.Panel):
    bl_label = "Два видео"
    bl_idname = "POSE_PT_dual_animation_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Pose Tool"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        box = layout.box()
        for prop, label in [('pose_front_video', 'Фронт'), ('pose_side_video', 'Бок')]:
            path = bpy.path.abspath(getattr(scene, prop))
            if path and os.path.exists(path):
                box.label(text=f"{label}: {os.path.basename(path)}", icon='FILE_MOVIE')
            else:
                box.label(text=f"{label}", icon='ERROR')
        box.operator("pose.select_front_video", icon='FILE_MOVIE')
        box.operator("pose.select_side_video", icon='FILE_MOVIE')
        box.separator()
        box.prop(scene, "pose_fragments_count")
        box.prop(scene, "pose_video_side_position")
        if scene.pose_video_side_position == 'custom':
            box.prop(scene, "pose_video_camera_angle")
        box.operator("pose.create_dual_animation", icon='ACTION')
        if scene.pose_animation_json:
            box.label(text="Анимация в памяти", icon='CHECKMARK')


class POSE_PT_common_panel(bpy.types.Panel):
    bl_label = "Применение"
    bl_idname = "POSE_PT_common_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Pose Tool"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        box = layout.box()
        box.label(text="Модель", icon='MESH_CUBE')
        box.operator("pose.load_model", icon='IMPORT')
        if scene.pose_selected_model:
            box.label(text=os.path.basename(scene.pose_selected_model), icon='CHECKMARK')
        layout.separator()
        box = layout.box()
        box.operator("pose.apply_pose", icon='ARMATURE_DATA')
        box.operator("pose.bake_animation", icon='REC')


classes = (
    POSE_PT_single_panel,
    POSE_PT_dual_panel,
    POSE_PT_animation_panel,
    POSE_PT_dual_animation_panel,
    POSE_PT_common_panel,
    POSE_OT_select_single_image,
    POSE_OT_select_front_image,
    POSE_OT_select_side_image,
    POSE_OT_select_video,
    POSE_OT_select_front_video,
    POSE_OT_select_side_video,
    POSE_OT_load_model,
    POSE_OT_send_single,
    POSE_OT_send_dual,
    POSE_OT_apply_pose,
    POSE_OT_create_animation,
    POSE_OT_create_dual_animation,
    POSE_OT_bake_animation,
)


def register():
    register_properties()
    for cls in classes:
        bpy.utils.register_class(cls)
    print("Pose Tool установлен!")


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    unregister_properties()
    print("Pose Tool удален")


if __name__ == "__main__":
    register()