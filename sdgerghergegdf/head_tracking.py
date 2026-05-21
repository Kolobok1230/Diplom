import cv2
import mediapipe as mp
import pyautogui
import numpy as np
import threading
import time
import ctypes

pyautogui.PAUSE = 0
pyautogui.FAILSAFE = False

class HeadTracker:
    def __init__(self, camera_source=0, **kwargs):
        self.camera_source = camera_source
        self.invert_x = kwargs.get('invert_x', True)
        self.swap_eyes = kwargs.get('swap_eyes', True)
        self.sensitivity_x = kwargs.get('sensitivity_x', 10.0) / 7.0
        self.sensitivity_y = kwargs.get('sensitivity_y', 12.0) / 7.0
        
        # Настройки точности (Безопасная зона)
        self.precision_interval_ms = kwargs.get('precision_interval_ms', 150)
        self.last_micro_move_time = 0
        
        # Настройки сброса
        self.reset_blinks_needed = kwargs.get('reset_blinks', 2)
        self.reset_time_window = kwargs.get('reset_time', 2.0)
        self.both_blink_timestamps = []

        # Состояния
        self.cursor_x, self.cursor_y = pyautogui.position()
        self.base_nose_x, self.base_nose_y = None, None
        self.running = False
        self.cap = None

        self.start_blink_l = 0
        self.start_blink_r = 0
        self.is_held_l = False
        self.is_held_r = False
        
        self.blink_limit = 0.22
        self.dead_zone = 0.008       
        self.precision_zone = 0.025   

        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(refine_landmarks=True)

    def update_settings(self, settings):
        self.sensitivity_x = settings.get('sx', 10) / 7.0
        self.sensitivity_y = settings.get('sy', 12) / 7.0
        self.invert_x = settings.get('inv_x', self.invert_x)
        self.swap_eyes = settings.get('swap', self.swap_eyes)
        self.precision_interval_ms = settings.get('ms', self.precision_interval_ms)
        self.reset_blinks_needed = settings.get('reset_blinks', self.reset_blinks_needed)
        self.reset_time_window = settings.get('reset_time', self.reset_time_window)
        self.camera_source = settings.get('cam', self.camera_source)

    def _get_ear(self, lm, eye_type='left'):
        # Используем конкретные индексы для точности
        if (eye_type == 'left' and not self.swap_eyes) or (eye_type == 'right' and self.swap_eyes):
            p1, p2, p3, p4 = lm[33], lm[133], lm[159], lm[145]
        else:
            p1, p2, p3, p4 = lm[362], lm[263], lm[386], lm[374]
        w = ((p1.x - p2.x)**2 + (p1.y - p2.y)**2)**0.5
        h = ((p3.x - p4.x)**2 + (p3.y - p4.y)**2)**0.5
        return h / (w + 1e-6)

    def _track_loop(self):
        self.cap = cv2.VideoCapture(self.camera_source)
        screen_w, screen_h = pyautogui.size()
        both_blink_active = False

        while self.running:
            ret, frame = self.cap.read()
            if not ret: continue
            
            now_ts = time.time()
            now_ms = now_ts * 1000
            
            rgb = cv2.cvtColor(cv2.flip(frame, 1), cv2.COLOR_BGR2RGB)
            results = self.face_mesh.process(rgb)
            
            if results.multi_face_landmarks:
                # ВАЖНО: берем .landmark[0] для конкретного лица
                lm = results.multi_face_landmarks[0].landmark
                ear_l, ear_r = self._get_ear(lm, 'left'), self._get_ear(lm, 'right')

                # --- ЛОГИКА КЛИКОВ ---
                if ear_l < self.blink_limit and ear_r < self.blink_limit:
                    if not both_blink_active:
                        self.both_blink_timestamps.append(now_ts)
                        self.both_blink_timestamps = [t for t in self.both_blink_timestamps if now_ts - t <= self.reset_time_window]
                        if len(self.both_blink_timestamps) >= self.reset_blinks_needed:
                            # ФИКС ОШИБКИ: nose теперь точка lm[1]
                            self.base_nose_x, self.base_nose_y = lm[1].x, lm[1].y
                            self.both_blink_timestamps = []
                        both_blink_active = True
                    self.start_blink_l = self.start_blink_r = 0
                else:
                    both_blink_active = False
                    # Левый глаз
                    if ear_l < self.blink_limit:
                        if self.start_blink_l == 0: self.start_blink_l = now_ms
                        if (now_ms - self.start_blink_l) > 500 and not self.is_held_l:
                            ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                            self.is_held_l = True
                    else:
                        if self.start_blink_l > 0:
                            if (now_ms - self.start_blink_l) < 400 and not self.is_held_l:
                                ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                            if self.is_held_l:
                                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                                self.is_held_l = False
                            self.start_blink_l = 0
                    # Правый глаз
                    if ear_r < self.blink_limit:
                        if self.start_blink_r == 0: self.start_blink_r = now_ms
                        if (now_ms - self.start_blink_r) > 500 and not self.is_held_r:
                            ctypes.windll.user32.mouse_event(0x0008, 0, 0, 0, 0)
                            self.is_held_r = True
                    else:
                        if self.start_blink_r > 0:
                            if (now_ms - self.start_blink_r) < 400 and not self.is_held_r:
                                ctypes.windll.user32.mouse_event(0x0008, 0, 0, 0, 0)
                                ctypes.windll.user32.mouse_event(0x0010, 0, 0, 0, 0)
                            if self.is_held_r:
                                ctypes.windll.user32.mouse_event(0x0010, 0, 0, 0, 0)
                                self.is_held_r = False
                            self.start_blink_r = 0

                # --- ЛОГИКА ДВИЖЕНИЯ ---
                nose = lm[1] # Кончик носа
                if self.base_nose_x is None:
                    self.base_nose_x, self.base_nose_y = nose.x, nose.y
                
                dx, dy = (nose.x - self.base_nose_x), (nose.y - self.base_nose_y)
                if self.invert_x: dx = -dx
                dist = (dx**2 + dy**2)**0.5

                # 1. ЗОНА ТОЧНОСТИ (Шаг 2 пикселя)
                if self.dead_zone < dist <= self.precision_zone:
                    if now_ms - self.last_micro_move_time > self.precision_interval_ms:
                        step = 2 # Увеличили шаг для удобства
                        if abs(dx) > abs(dy): self.cursor_x += step if dx > 0 else -step
                        else: self.cursor_y += step if dy > 0 else -step
                        self.last_micro_move_time = now_ms
                        pyautogui.moveTo(int(self.cursor_x), int(self.cursor_y))
                
                # 2. ЗОНА ДЖОЙСТИКА
                elif dist > self.precision_zone:
                    self.cursor_x += dx * self.sensitivity_x * 45
                    self.cursor_y += dy * self.sensitivity_y * 45
                    self.cursor_x = max(0, min(screen_w-1, self.cursor_x))
                    self.cursor_y = max(0, min(screen_h-1, self.cursor_y))
                    pyautogui.moveTo(int(self.cursor_x), int(self.cursor_y))
                
                # 3. ПОКОЙ
                else:
                    curr = pyautogui.position()
                    self.cursor_x, self.cursor_y = curr.x, curr.y

        self.cap.release()

    def start(self):
        self.running = True
        threading.Thread(target=self._track_loop, daemon=True).start()

    def stop(self): self.running = False
