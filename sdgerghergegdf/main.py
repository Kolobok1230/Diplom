import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import ttkbootstrap as tb
from ttkbootstrap.constants import *
import json
import os
import threading
import sys
import urllib.request
import zipfile
import shutil
import tempfile
import random
import time
import string
import webbrowser
import subprocess
import winreg
from PIL import Image, ImageTk
from pygrabber.dshow_graph import FilterGraph
from head_tracking import HeadTracker
from subtitles import SubtitlesEngine
from voice_input import VoiceInputEngine
from color_correction import ColorCorrectionOverlay
from database import Database
from vosk import Model
import keyboard as kb
import pystray
from pystray import MenuItem as item
from voice_commands import VoiceCommandsManager
from hotkey_commands import HotkeyCommandsManager
from script_launcher import ScriptLauncherManager

class AssistiveSuite(tb.Window):
    def __init__(self):
        self.db = Database(password="123")
        self.current_user = None
        self.is_authenticated = False
        self.settings_file = "settings.json"
        self.settings = self.load_settings()
        self.token_file = "autorization_token.json"

        super().__init__(themename="darkly")
        self.title("Инклюзивный ассистент")
        self.geometry("800x700")
        self.minsize(800, 700)

        self.color_correction_var = tk.BooleanVar(value=False)
        self.subtitles_var = tk.BooleanVar(value=False)
        self.voice_typing_var = tk.BooleanVar(value=False)
        self.head_control_var = tk.BooleanVar(value=False)

        self.menu_open = False
        self.menu_on_hover_var = tk.BooleanVar(value=True)
        self.menu_frame = None
        self.hover_detector = None
        self.menu_canvas = None
        self.menu_scrollbar = None
        self.menu_inner = None

        self.engine = None
        self.overlay_sub = None
        self.subtitle_alpha = 0.8
        self.selected_device_index = None
        self.model_loaded = False
        self.model_loading = False
        self.font_family = "Segoe UI"
        self.font_size = 14
        self.subtitle_history = []
        self.subtitles_active = False
        self.partial_text = ""

        self.voice_engine = None
        self.voice_active = False
        self.voice_paused = False
        self.selected_voice_device = self.settings.get("voice_input", {}).get("device_index", -1)
        if hasattr(self, 'voice_input') and self.voice_input:
            self.voice_input.set_device(self.selected_voice_device)

        self.voice_level = 0
        self.shared_model = None
        self.voice_engine = VoiceInputEngine(None)

        self.color_correction_type = "protanomaly"
        self.color_intensity = 0.7
        self.color_gain = 0.7
        self.color_correction_overlay = ColorCorrectionOverlay(
            correction_type=self.color_correction_type,
            intensity=self.color_intensity,
            gain=self.color_gain
        )

        self.head_tracker = None
        self.head_invert_x = True
        self.head_swap_eyes = True
        self.head_ear_threshold = 0.21
        self.head_click_duration = 0.2
        self.head_long_press_duration = 0.8
        self.head_sensitivity_x = 10.0
        self.head_sensitivity_y = 12.0
        self.head_precision_ms = 100
        self.head_camera_index = 1
        self.head_reset_blinks = 2
        self.head_reset_time = 2.0
        self.last_blink_time_l = 0
        self.is_held_l = False
        self.blink_count_l = 0
        self.last_single_blink_time_l = 0
        self.blink_counter_l = 0
        self.blink_counter_r = 0

        self.voice_cmd = VoiceCommandsManager(self)
        self.hotkey_cmd = HotkeyCommandsManager(self)
        self.script_launcher = ScriptLauncherManager(self)

        self.last_subtitle_toggle_time = 0
        self.status_frame = tb.Frame(self, height=30)
        self.status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_label_main = tb.Label(self.status_frame, text="Загрузка модели...", font=("Segoe UI", 9))
        self.status_label_main.pack(side=tk.LEFT, padx=10)
        self.progressbar_main = ttk.Progressbar(self.status_frame, mode='indeterminate', length=150)
        self.progressbar_main.pack(side=tk.RIGHT, padx=10)

        self.main_container = tb.Frame(self)
        self.main_container.pack(fill=tk.BOTH, expand=True)

        self.auth_frame = tb.Frame(self.main_container)
        self.auth_frame.pack(fill=tk.X, padx=(70, 20), pady=(20, 0))

        self.content_frame = tb.Frame(self.main_container)
        self.content_frame.pack(fill=tk.BOTH, expand=True, padx=(70, 20), pady=(15, 20))

        self.btn_show_menu = tk.Button(
            self.main_container, text="<", font=("Segoe UI", 16),
            bg="#2d2d2d", fg="white", relief="flat", bd=0,
            command=self.toggle_menu
        )
        self.btn_show_menu.place(x=5, rely=0.5, anchor="w", width=30, height=60)

        self.create_function_cards()
        self.create_side_menu()
        self.create_hover_detector()
        self.bind_hover_events()
        self.disable_switches_until_model_loaded()
        self.color_correction_overlay.start()

        self.start_model_loading()
        self.apply_settings()
        self.after_idle(self.load_token_and_authenticate)
        self.after_idle(self.update_auth_display)

        self.voice_cmd.start_listening()

    def load_settings(self):
        default = {
            "app": {"theme": "darkly"},
            "subtitles": {"alpha": 0.8, "font_family": "Segoe UI", "font_size": 14, "device_index": None},
            "voice_input": {"device_index": 0},
            "head_tracking": {
                "camera_index": 1, "sensitivity_x": 10.0, "sensitivity_y": 12.0,
                "invert_x": True, "swap_eyes": True, "precision_interval_ms": 100,
                "reset_blinks": 2, "reset_time": 2.0
            },
            "color_correction": {"type": "deuteranomaly", "intensity": 0.7, "gain": 0.7},
            "voice_commands": {},
            "hotkey_commands": {},
            "script_buttons": {},
            "minimize_to_tray": False
        }
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                def update_dict(d, u):
                    for k, v in u.items():
                        if isinstance(v, dict):
                            d[k] = update_dict(d.get(k, {}), v)
                        else:
                            d[k] = v
                    return d
                update_dict(default, loaded)
                return default
            except Exception as e:
                print(f"Ошибка загрузки настроек: {e}")
                return default
        else:
            self.save_settings(default)
            return default

    def save_settings(self, settings=None):
        if settings is None:
            settings = self.settings
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка сохранения настроек: {e}")

    def apply_settings(self):
        s = self.settings
        theme = s["app"]["theme"]
        if self.style.theme.name != theme:
            self.style.theme_use(theme)
        self.subtitle_alpha = s["subtitles"]["alpha"]
        self.font_family = s["subtitles"]["font_family"]
        self.font_size = s["subtitles"]["font_size"]
        self.selected_device_index = s["subtitles"]["device_index"]
        self.selected_voice_device = s["voice_input"]["device_index"]
        ht = s["head_tracking"]
        self.head_camera_index = ht["camera_index"]
        self.head_sensitivity_x = ht["sensitivity_x"]
        self.head_sensitivity_y = ht["sensitivity_y"]
        self.head_invert_x = ht["invert_x"]
        self.head_swap_eyes = ht["swap_eyes"]
        self.head_precision_ms = ht["precision_interval_ms"]
        self.head_reset_blinks = ht["reset_blinks"]
        self.head_reset_time = ht["reset_time"]
        cc = s["color_correction"]
        self.color_correction_type = cc["type"]
        self.color_intensity = cc["intensity"]
        self.color_gain = cc["gain"]
        if hasattr(self, 'color_correction_overlay'):
            self.color_correction_overlay.set_correction_type(self.color_correction_type)
            self.color_correction_overlay.set_intensity(self.color_intensity)
            self.color_correction_overlay.set_gain(self.color_gain)

    def save_token(self, token):
        try:
            with open(self.token_file, 'w', encoding='utf-8') as f:
                json.dump({"token": token}, f)
        except Exception as e:
            print(f"Ошибка сохранения токена: {e}")

    def clear_token(self):
        if os.path.exists(self.token_file):
            os.remove(self.token_file)

    def load_token_and_authenticate(self):
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    token = data.get("token")
                if token:
                    user = self.db.get_user_by_token(token)
                    if user:
                        self.current_user = user
                        self.is_authenticated = True
                        self.update_auth_display()
                        return
                    else:
                        self.clear_token()
            except Exception as e:
                print(f"Ошибка загрузки токена: {e}")
        self.update_auth_display()

    def update_auth_display(self):
        for widget in self.auth_frame.winfo_children():
            widget.destroy()
        if self.is_authenticated and self.current_user:
            nickname = self.current_user.get('NickName', 'Пользователь')
            btn_nick = tb.Button(self.auth_frame, text=nickname, bootstyle="light-outline", width=12,
                                 command=self.show_user_menu)
            btn_nick.pack(side=tk.RIGHT)
        else:
            btn_login = tb.Button(self.auth_frame, text="🔐 Вход", bootstyle="primary", width=12,
                                  command=self.login)
            btn_login.pack(side=tk.RIGHT, padx=(5, 5))
            btn_register = tb.Button(self.auth_frame, text="📝 Регистрация", bootstyle="primary", width=14,
                                     command=self.register)
            btn_register.pack(side=tk.RIGHT, padx=(0, 5))

    def show_user_menu(self):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="👤 Профиль", command=self.show_profile)
        menu.add_separator()
        menu.add_command(label="🚪 Выйти", command=self.logout)
        try:
            for child in self.auth_frame.winfo_children():
                if isinstance(child, tb.Button) and child.cget('text') == self.current_user.get('NickName', ''):
                    x = child.winfo_rootx()
                    y = child.winfo_rooty() + child.winfo_height()
                    menu.post(x, y)
                    return
            menu.post(self.winfo_pointerx(), self.winfo_pointery())
        except:
            menu.post(self.winfo_pointerx(), self.winfo_pointery())

    def show_profile(self):
        if not self.current_user:
            return
        prof_win = tb.Toplevel(self)
        prof_win.title("Профиль пользователя")
        prof_win.geometry("450x500")
        prof_win.resizable(False, False)
        prof_win.transient(self)
        prof_win.grab_set()
        x = self.winfo_x() + (self.winfo_width() // 2) - 225
        y = self.winfo_y() + (self.winfo_height() // 2) - 250
        prof_win.geometry(f"+{x}+{y}")
        main_frame = tb.Frame(prof_win, padding=25)
        main_frame.pack(fill=tk.BOTH, expand=True)
        tb.Label(main_frame, text="Редактирование профиля", font=("Segoe UI", 16, "bold")).pack(pady=(0, 20))
        tb.Label(main_frame, text="Никнейм", anchor=tk.W).pack(fill=tk.X, pady=(0, 5))
        nick_var = tk.StringVar(value=self.current_user['NickName'])
        entry_nick = tb.Entry(main_frame, textvariable=nick_var, font=("Segoe UI", 10))
        entry_nick.pack(fill=tk.X, pady=(0, 15))
        tb.Label(main_frame, text="Электронная почта", anchor=tk.W).pack(fill=tk.X, pady=(0, 5))
        lbl_email = tb.Label(main_frame, text=self.current_user['email'], font=("Segoe UI", 10), anchor=tk.W)
        lbl_email.pack(fill=tk.X, pady=(0, 15))

        def change_password():
            pwd_win = tb.Toplevel(prof_win)
            pwd_win.title("Смена пароля")
            pwd_win.geometry("400x300")
            pwd_win.resizable(False, False)
            pwd_win.transient(prof_win)
            pwd_win.grab_set()
            frame = tb.Frame(pwd_win, padding=20)
            frame.pack(fill=tk.BOTH, expand=True)
            tb.Label(frame, text="Смена пароля", font=("Segoe UI", 14, "bold")).pack(pady=(0, 15))
            tb.Label(frame, text="Текущий пароль", anchor=tk.W).pack(fill=tk.X)
            old_pass = tb.Entry(frame, show="*")
            old_pass.pack(fill=tk.X, pady=(0, 10))
            tb.Label(frame, text="Новый пароль", anchor=tk.W).pack(fill=tk.X)
            new_pass = tb.Entry(frame, show="*")
            new_pass.pack(fill=tk.X, pady=(0, 10))
            tb.Label(frame, text="Подтверждение", anchor=tk.W).pack(fill=tk.X)
            confirm_pass = tb.Entry(frame, show="*")
            confirm_pass.pack(fill=tk.X, pady=(0, 15))

            def do_change():
                old = old_pass.get().strip()
                new = new_pass.get().strip()
                confirm = confirm_pass.get().strip()
                if not old or not new:
                    messagebox.showwarning("Ошибка", "Заполните все поля")
                    return
                if new != confirm:
                    messagebox.showerror("Ошибка", "Новый пароль и подтверждение не совпадают")
                    return
                if len(new) < 4:
                    messagebox.showerror("Ошибка", "Пароль должен содержать не менее 4 символов")
                    return
                if self.db.authenticate(self.current_user['email'], old) is None:
                    messagebox.showerror("Ошибка", "Неверный текущий пароль")
                    return
                from database import hash_password
                hashed_new = hash_password(new)
                conn = self.db.connect()
                cur = conn.cursor()
                try:
                    cur.execute("UPDATE accounts SET password = %s WHERE id = %s", (hashed_new, self.current_user['id']))
                    conn.commit()
                    messagebox.showinfo("Успех", "Пароль успешно изменён.")
                    pwd_win.destroy()
                except Exception as e:
                    conn.rollback()
                    messagebox.showerror("Ошибка", f"Не удалось изменить пароль: {e}")
                finally:
                    cur.close()

            tb.Button(frame, text="Изменить пароль", bootstyle="primary", command=do_change).pack(fill=tk.X, pady=10)
            tb.Button(frame, text="Отмена", bootstyle="secondary", command=pwd_win.destroy).pack(fill=tk.X)

        tb.Button(main_frame, text="Сменить пароль", bootstyle="outline-info", command=change_password).pack(fill=tk.X, pady=(0, 10))

        def refresh_token():
            new_token = self.db.generate_token()
            if self.db.update_user_token(self.current_user['id'], new_token):
                self.save_token(new_token)
                messagebox.showinfo("Токен обновлён", "Токен авторизации успешно обновлён.\nВы останетесь в системе.")
            else:
                messagebox.showerror("Ошибка", "Не удалось обновить токен на сервере")

        tb.Button(main_frame, text="Обновить токен", bootstyle="outline-warning", command=refresh_token).pack(fill=tk.X, pady=(0, 20))

        def save_profile():
            new_nick = nick_var.get().strip()
            if not new_nick:
                messagebox.showwarning("Ошибка", "Никнейм не может быть пустым")
                return
            if new_nick != self.current_user['NickName']:
                if self.db.user_exists(new_nick, ""):
                    messagebox.showerror("Ошибка", "Пользователь с таким ником уже существует")
                    return
                conn = self.db.connect()
                cur = conn.cursor()
                try:
                    cur.execute('UPDATE accounts SET "NickName" = %s WHERE id = %s', (new_nick, self.current_user['id']))
                    conn.commit()
                    self.current_user['NickName'] = new_nick
                    self.update_auth_display()
                    messagebox.showinfo("Успех", "Никнейм обновлён")
                except Exception as e:
                    conn.rollback()
                    messagebox.showerror("Ошибка", f"Не удалось обновить ник: {e}")
                finally:
                    cur.close()
            prof_win.destroy()

        bottom_frame = tb.Frame(main_frame)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(20, 0))
        tb.Button(bottom_frame, text="Сохранить изменения", bootstyle="success", command=save_profile).pack(side=tk.LEFT, padx=5, expand=True)
        tb.Button(bottom_frame, text="Закрыть", bootstyle="secondary", command=prof_win.destroy).pack(side=tk.LEFT, padx=5, expand=True)

    def logout(self):
        self.is_authenticated = False
        self.current_user = None
        self.clear_token()
        self.update_auth_display()

    def login(self):
        login_win = tb.Toplevel(self)
        login_win.title("Авторизация")
        login_win.geometry("360x420")
        login_win.resizable(False, False)
        login_win.transient(self)
        login_win.grab_set()
        login_win.attributes("-topmost", True)
        x = self.winfo_x() + (self.winfo_width() // 2) - 180
        y = self.winfo_y() + (self.winfo_height() // 2) - 210
        login_win.geometry(f"+{x}+{y}")
        container = tb.Frame(login_win, padding=25)
        container.pack(fill=tk.BOTH, expand=True)
        tb.Label(container, text="🔐 Вход в аккаунт", font=("Segoe UI", 16, "bold")).pack(pady=(0, 20))
        tb.Label(container, text="Электронная почта или логин", anchor=tk.W).pack(fill=tk.X, pady=(0, 5))
        entry_identifier = tb.Entry(container, font=("Segoe UI", 10))
        entry_identifier.pack(fill=tk.X, pady=(0, 15))
        tb.Label(container, text="Пароль", anchor=tk.W).pack(fill=tk.X, pady=(0, 5))
        entry_password = tb.Entry(container, font=("Segoe UI", 10), show="*")
        entry_password.pack(fill=tk.X, pady=(0, 20))

        def do_login():
            identifier = entry_identifier.get().strip()
            password = entry_password.get().strip()
            if not identifier or not password:
                messagebox.showwarning("Ошибка", "Заполните все поля!")
                return
            user = self.db.authenticate(identifier, password)
            if user:
                new_token = self.db.generate_token()
                if self.db.update_user_token(user['id'], new_token):
                    self.save_token(new_token)
                self.current_user = user
                self.is_authenticated = True
                self.sync_settings_with_server()
                self.update_auth_display()
                login_win.destroy()
                messagebox.showinfo("Успех", f"Добро пожаловать, {user['NickName']}!")
            else:
                messagebox.showerror("Ошибка", "Неверный email/логин или пароль")

        tb.Button(container, text="Войти", bootstyle="primary", command=do_login).pack(fill=tk.X, pady=(0, 15))
        sep_frame = tb.Frame(container)
        sep_frame.pack(fill=tk.X, pady=10)
        tb.Separator(sep_frame, orient="horizontal").pack(side=tk.LEFT, fill=tk.X, expand=True)
        tb.Label(sep_frame, text=" или ", font=("Segoe UI", 9), foreground="gray").pack(side=tk.LEFT, padx=10)
        tb.Separator(sep_frame, orient="horizontal").pack(side=tk.LEFT, fill=tk.X, expand=True)
        tb.Button(container, text="Войти через Google", bootstyle="outline-secondary",
                  command=lambda: messagebox.showinfo("Google вход", "Функция в разработке")).pack(fill=tk.X, pady=(5, 10))
        reg_frame = tb.Frame(container)
        reg_frame.pack(fill=tk.X, pady=10)
        tb.Label(reg_frame, text="Нет аккаунта? ", font=("Segoe UI", 9)).pack(side=tk.LEFT)
        lbl_reg = tb.Label(reg_frame, text="Зарегистрироваться", font=("Segoe UI", 9, "underline"),
                           foreground=self.style.colors.success, cursor="hand2")
        lbl_reg.pack(side=tk.LEFT)
        lbl_reg.bind("<Button-1>", lambda e: (login_win.destroy(), self.register()))
        entry_identifier.focus_set()

    def register(self):
        reg_win = tb.Toplevel(self)
        reg_win.title("Регистрация")
        reg_win.geometry("400x500")
        reg_win.resizable(False, False)
        reg_win.transient(self)
        reg_win.grab_set()
        reg_win.attributes("-topmost", True)
        x = self.winfo_x() + (self.winfo_width() // 2) - 200
        y = self.winfo_y() + (self.winfo_height() // 2) - 250
        reg_win.geometry(f"+{x}+{y}")
        container = tb.Frame(reg_win, padding=25)
        container.pack(fill=tk.BOTH, expand=True)
        tb.Label(container, text="📝 Регистрация", font=("Segoe UI", 16, "bold")).pack(pady=(0, 15))
        tb.Label(container, text="Никнейм", anchor=tk.W).pack(fill=tk.X, pady=(0, 5))
        entry_nick = tb.Entry(container, font=("Segoe UI", 10))
        entry_nick.pack(fill=tk.X, pady=(0, 10))
        tb.Label(container, text="Электронная почта", anchor=tk.W).pack(fill=tk.X, pady=(0, 5))
        entry_email = tb.Entry(container, font=("Segoe UI", 10))
        entry_email.pack(fill=tk.X, pady=(0, 10))
        tb.Label(container, text="Пароль", anchor=tk.W).pack(fill=tk.X, pady=(0, 5))
        entry_pass = tb.Entry(container, font=("Segoe UI", 10), show="*")
        entry_pass.pack(fill=tk.X, pady=(0, 10))
        tb.Label(container, text="Подтвердите пароль", anchor=tk.W).pack(fill=tk.X, pady=(0, 5))
        entry_pass2 = tb.Entry(container, font=("Segoe UI", 10), show="*")
        entry_pass2.pack(fill=tk.X, pady=(0, 15))

        def final_register():
            nickname = entry_nick.get().strip()
            email = entry_email.get().strip()
            password = entry_pass.get().strip()
            password2 = entry_pass2.get().strip()
            if not nickname or not email or not password:
                messagebox.showwarning("Ошибка", "Заполните все поля")
                return
            if password != password2:
                messagebox.showerror("Ошибка", "Пароли не совпадают")
                return
            if len(password) < 4:
                messagebox.showerror("Ошибка", "Пароль не менее 4 символов")
                return
            if self.db.user_exists(nickname, email):
                messagebox.showerror("Ошибка", "Никнейм или email уже заняты")
                return
            user_id = self.db.register_user(nickname, email, password)
            if user_id:
                messagebox.showinfo("Успех", "Регистрация завершена! Теперь войдите.")
                reg_win.destroy()
            else:
                messagebox.showerror("Ошибка", "Не удалось зарегистрировать пользователя")

        tb.Button(container, text="Завершить регистрацию", bootstyle="info", command=final_register).pack(fill=tk.X, pady=15)

    def sync_settings_with_server(self):
        if not self.is_authenticated or not self.current_user:
            return
        server_settings_json = self.current_user.get('settings')
        if not server_settings_json:
            return
        try:
            server_settings = json.loads(server_settings_json)
        except json.JSONDecodeError:
            return
        if self.settings == server_settings:
            return
        pref = self.settings.get("sync_preference")
        if pref == "server":
            self.settings = server_settings
            self.save_settings()
            self.apply_settings()
            return
        elif pref == "local":
            local_json = json.dumps(self.settings, ensure_ascii=False)
            if self.db.update_user_settings(self.current_user['id'], local_json):
                self.current_user['settings'] = local_json
            return
        elif pref == "skip":
            return

        dialog = tk.Toplevel(self)
        dialog.title("Конфликт настроек")
        dialog.geometry("500x320")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.attributes("-topmost", True)
        x = self.winfo_x() + (self.winfo_width() // 2) - 250
        y = self.winfo_y() + (self.winfo_height() // 2) - 160
        dialog.geometry(f"+{x}+{y}")
        tb.Label(dialog, text="Конфликт настроек", font=("Segoe UI", 14, "bold")).pack(pady=(20, 10))
        tb.Label(dialog, text="Настройки на этом компьютере отличаются от облачных.\nЧто сделать?",
                 font=("Segoe UI", 10)).pack(pady=(0, 15))
        q_frame = tb.Frame(dialog)
        q_frame.pack(pady=5)
        tb.Label(q_frame, text="Загрузить настройки с облачного хранилища?", font=("Segoe UI", 11, "bold")).pack()
        btn_frame = tb.Frame(dialog)
        btn_frame.pack(pady=15)
        no_cloud_change_var = tk.BooleanVar(value=False)
        remember_var = tk.BooleanVar(value=False)

        def do_action(action):
            if action == "yes":
                self.settings = server_settings
                self.save_settings()
                self.apply_settings()
                if remember_var.get():
                    self.settings["sync_preference"] = "server"
                    self.save_settings()
            elif action == "no":
                if not no_cloud_change_var.get():
                    local_json = json.dumps(self.settings, ensure_ascii=False)
                    if self.db.update_user_settings(self.current_user['id'], local_json):
                        self.current_user['settings'] = local_json
                if remember_var.get():
                    if no_cloud_change_var.get():
                        self.settings["sync_preference"] = "skip"
                    else:
                        self.settings["sync_preference"] = "local"
                    self.save_settings()
            dialog.destroy()

        tb.Button(btn_frame, text="Да", bootstyle="primary", width=12,
                  command=lambda: do_action("yes")).pack(side=tk.LEFT, padx=10)
        tb.Button(btn_frame, text="Нет", bootstyle="secondary", width=12,
                  command=lambda: do_action("no")).pack(side=tk.LEFT, padx=10)
        cb_no_cloud = tb.Checkbutton(dialog, text="Не менять настройки в облаке",
                                     variable=no_cloud_change_var, bootstyle="round-toggle")
        cb_no_cloud.pack(pady=(10, 5))
        cb_remember = tb.Checkbutton(dialog, text="Запомнить выбор (больше не спрашивать)",
                                     variable=remember_var, bootstyle="round-toggle")
        cb_remember.pack(pady=5)
        dialog.protocol("WM_DELETE_WINDOW", lambda: do_action("no"))

    def start_model_loading(self):
        def get_model_path():
            temp_dir = os.environ.get('TEMP', 'C:\\Temp')
            return os.path.join(temp_dir, 'vosk_model_ru')

        def is_model_valid(model_path):
            if not os.path.exists(model_path):
                return False
            am_path = os.path.join(model_path, "am")
            if not os.path.exists(am_path):
                return False
            final_mdl = os.path.join(am_path, "final.mdl")
            if not os.path.exists(final_mdl) or os.path.getsize(final_mdl) < 1000:
                return False
            return True

        def download_and_extract(target_path):
            model_url = "https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip"
            zip_path = target_path + ".zip"
            try:
                if os.path.exists(target_path):
                    shutil.rmtree(target_path)
                if os.path.exists(zip_path):
                    os.remove(zip_path)
                self.after(0, lambda: self.status_label_main.config(text="Скачивание модели (45 МБ)..."))
                self.after(0, lambda: self.progressbar_main.start())
                def report(block, block_size, total):
                    if total > 0:
                        percent = int(block * block_size * 100 / total)
                        self.after(0, lambda: self.status_label_main.config(text=f"Скачивание: {percent}%"))
                urllib.request.urlretrieve(model_url, zip_path, report)
                self.after(0, lambda: self.status_label_main.config(text="Распаковка модели..."))
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(os.path.dirname(target_path))
                extracted = os.path.join(os.path.dirname(target_path), "vosk-model-ru-0.42")
                if os.path.exists(extracted) and extracted != target_path:
                    os.rename(extracted, target_path)
                os.remove(zip_path)
                return True
            except Exception as e:
                print(f"Ошибка установки: {e}")
                return False

        def load():
            model_path = get_model_path()
            if not is_model_valid(model_path):
                print("Модель не найдена, скачиваем...")
                if not download_and_extract(model_path):
                    self.after(0, lambda: self.status_label_main.config(text="Model error"))
                    self.after(0, lambda: self.progressbar_main.stop())
                    return
            try:
                self.shared_model = Model(model_path)
                self.model_loaded = True
                self.model_loading = False
                self.after(0, self.enable_switches)
                self.after(0, lambda: self.status_label_main.config(text="Model ready"))
                self.after(0, lambda: self.progressbar_main.stop())
                self.after(0, lambda: self.progressbar_main.config(mode='determinate', value=100))
            except Exception as e:
                self.model_loaded = False
                self.model_loading = False
                self.after(0, lambda: self.status_label_main.config(text=f"Model error: {str(e)[:50]}"))
                self.after(0, lambda: self.progressbar_main.stop())
        threading.Thread(target=load, daemon=True).start()

    def enable_switches(self):
        for child in self.content_frame.winfo_children():
            for subchild in child.winfo_children():
                if isinstance(subchild, tb.Checkbutton):
                    parent = subchild.master
                    if parent.winfo_children():
                        text = parent.winfo_children()[0].cget("text")
                        if text in ("Субтитры из звука", "Голосовой ввод текста", "Коррекция цвета для экрана"):
                            subchild.configure(state="normal")

    def disable_switches_until_model_loaded(self):
        for child in self.content_frame.winfo_children():
            for subchild in child.winfo_children():
                if isinstance(subchild, tb.Checkbutton):
                    parent = subchild.master
                    if parent.winfo_children():
                        text = parent.winfo_children()[0].cget("text")
                        if text in ("Субтитры из звука", "Голосовой ввод текста", "Коррекция цвета для экрана"):
                            subchild.configure(state="disabled")

    def create_function_cards(self):
        functions = [
            ("Управление мышью при помощи головы", "Перемещение курсора поворотом головы", self.head_control_var),
            ("Коррекция цвета для экрана", "Адаптация цветов для дальтоников", self.color_correction_var),
            ("Субтитры из звука", "Преобразование речи в текст в реальном времени", self.subtitles_var),
            ("Голосовой ввод текста", "Голос -> текст в активное поле", self.voice_typing_var)
        ]
        for title, desc, var in functions:
            card = tb.Frame(self.content_frame)
            card.pack(fill=tk.X, pady=15)
            top_line = tb.Frame(card)
            top_line.pack(fill=tk.X)
            lbl_title = tb.Label(top_line, text=title, font=("Segoe UI", 14, "bold"))
            lbl_title.pack(side=tk.LEFT)
            right_box = tb.Frame(top_line)
            right_box.pack(side=tk.RIGHT)
            btn_settings = tb.Button(right_box, text="⚙️", bootstyle="outline-secondary",
                                     command=lambda t=title: self.open_feature_settings(t))
            btn_settings.pack(side=tk.LEFT, padx=(0, 15))
            switch = tb.Checkbutton(right_box, variable=var, bootstyle="primary-round-toggle",
                                    command=lambda t=title: self.on_switch_toggle(t))
            switch.pack(side=tk.LEFT)
            lbl_desc = tb.Label(card, text=desc, font=("Segoe UI", 10), foreground="gray")
            lbl_desc.pack(anchor=tk.W, pady=(2, 0))

    def on_switch_toggle( self, func_name):
        if func_name == "Субтитры из звука":
            if self.model_loading:
                messagebox. showwarning("Загрузка модели", "Модель ещё загружается.")
                self. subtitles_var. set( False)
                return
            if not self.model_loaded:
                messagebox. showerror("Ошибка", "Модель не загружена.")
                self. subtitles_var. set( False)
                return

            current_time = time.time()
            if current_time - self.last_subtitle_toggle_time < 0.6:
                print("[Anti-Crash] Слишком быстрый клик! Сигнал проигнорирован.")
                self.subtitles_var.set(not self.subtitles_var.get())
                return
            self.last_subtitle_toggle_time = current_time

            if self. subtitles_var. get():
                self. start_subtitles()
            else:
                self. stop_subtitles()
        elif func_name == "Голосовой ввод текста":
            if self.model_loading:
                messagebox.showwarning("Загрузка модели", "Модель ещё загружается.")
                self.voice_typing_var.set(False)
                return
            if not self.model_loaded:
                messagebox.showerror("Ошибка", "Модель не загружена.")
                self.voice_typing_var.set(False)
                return
            if self.voice_typing_var.get():
                self.start_voice_typing()
            else:
                self.stop_voice_typing()
        elif func_name == "Коррекция цвета для экрана":
            if self.color_correction_var.get():
                self.start_color_correction()
            else:
                self.stop_color_correction()
        elif func_name == "Управление мышью при помощи головы":
            if self.head_control_var.get():
                self.start_head_tracking()
            else:
                self.stop_head_tracking()

    def start_subtitles(self):
        if self.subtitles_active:
            return
        if self.selected_device_index is None:
            messagebox.showwarning("Нет устройства", "Сначала выберите устройство захвата в настройках (⚙️).")
            self.subtitles_var.set(False)
            self.open_feature_settings("Субтитры из звука")
            return
        self.overlay_sub = tk.Toplevel(self)
        self.overlay_sub.title("")
        self.overlay_sub.geometry("800x200+100+100")
        self.overlay_sub.overrideredirect(True)
        self.overlay_sub.attributes("-topmost", True)
        self.overlay_sub.attributes("-alpha", self.subtitle_alpha)
        self.overlay_sub.configure(bg="black")
        top_bar = tk.Frame(self.overlay_sub, bg="#333", height=28)
        top_bar.pack(fill=tk.X)
        fullscreen_btn = tk.Button(top_bar, text="⛶", font=("Segoe UI", 10), bg="#333", fg="white", relief="flat",
                                   command=self.toggle_fullscreen)
        fullscreen_btn.pack(side=tk.LEFT, padx=5)
        drag_label = tk.Label(top_bar, text="     СУБТИТРЫ (перетащите)     ", bg="#333", fg="white", font=("Segoe UI", 9))
        drag_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        close_btn = tk.Button(top_bar, text="✕", font=("Segoe UI", 10), bg="#333", fg="white", relief="flat",
                              command=self.stop_subtitles)
        close_btn.pack(side=tk.RIGHT, padx=5)
        drag_label.bind("<Button-1>", self.start_move)
        drag_label.bind("<B1-Motion>", self.on_move)
        self.text_widget = tk.Text(self.overlay_sub, wrap=tk.WORD, font=(self.font_family, self.font_size),
                                   bg="black", fg="white", bd=0, highlightthickness=0)
        self.text_widget.tag_configure("center", justify="center")
        self.text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.overlay_sub.text_widget = self.text_widget
        self.subtitle_history.clear()
        self.partial_text = ""
        self.text_widget.insert(tk.END, "Ожидание аудио...")
        self.text_widget.tag_add("center", "1.0", "end")
        self.subtitles_active = True
        self.overlay_fullscreen = False
        self.overlay_normal_geometry = None
        threading.Thread(target=self._run_subtitle_engine, daemon=True).start()

    def _run_subtitle_engine(self):
        try:
            if self.engine is None:
                self.engine = SubtitlesEngine(self.shared_model)
                if not self.engine.load_model():
                    raise Exception("Не удалось инициализировать распознаватель")
            self.engine.set_device(self.selected_device_index)
            self.engine.callback = self.update_subtitle_text
            if not self.engine.start():
                raise Exception("Не удалось запустить захват звука")
        except Exception as e:
            self.after(0, lambda: self._on_subtitle_error(str(e)))

    def _on_subtitle_error(self, err_msg):
        if self.overlay_sub and self.overlay_sub.winfo_exists():
            self.overlay_sub.destroy()
        self.overlay_sub = None
        self.subtitles_active = False
        self.subtitles_var.set(False)
        messagebox.showerror("Ошибка субтитров", err_msg)

    def update_subtitle_text(self, text, is_partial=False):
        # Определяем цвет: промежуточный черновик — серый, готовая фраза — белая
        color = "gray" if is_partial else "white"
        
        # Проверяем, существует ли виджет метки в интерфейсе
        if hasattr(self, 'subtitle_label') and self.subtitle_label:
            try:
                # Безопасно обновляем конфигурацию текста и цвета
                self.subtitle_label.config(text=text, fg=color)
                
                # ФИКС KAN-14: Принудительно заставляем графический движок Tkinter
                # мгновенно очистить старый слой пикселей перед отрисовкой новых букв
                self.subtitle_label.update_idletasks()
                
            except Exception as e:
                print(f"[Subtitles UI Фикс] Ошибка обновления интерфейса: {e}")


    def _get_display_text(self, include_partial=False):
        history_text = "\n".join(self.subtitle_history[-3:])
        if include_partial and self.partial_text:
            return history_text + ("" if not history_text else "\n") + self.partial_text
        return history_text

    def _update_text_widget(self, text, is_partial):
        widget = self.overlay_sub.text_widget
        widget.delete(1.0, tk.END)
        widget.insert(tk.END, text if text else "Ожидание аудио...")
        widget.tag_add("center", "1.0", "end")
        if is_partial and self.partial_text:
            widget.tag_add("partial", "1.0", "end")
            widget.tag_config("partial", foreground="#aaaaaa")
        else:
            widget.tag_remove("partial", "1.0", "end")

    def stop_subtitles(self):
        self.subtitles_active = False
        if self.engine:
            self.engine.stop()
        if self.overlay_sub and self.overlay_sub.winfo_exists():
            self.overlay_sub.destroy()
        self.overlay_sub = None
        self.subtitles_var.set(False)

    def toggle_fullscreen(self):
        if not hasattr(self, 'overlay_fullscreen'):
            self.overlay_fullscreen = False
            self.overlay_normal_geometry = None
        if not self.overlay_fullscreen:
            self.overlay_normal_geometry = self.overlay_sub.geometry()
            w = self.overlay_sub.winfo_screenwidth()
            h = self.overlay_sub.winfo_screenheight()
            self.overlay_sub.geometry(f"{w}x{h}+0+0")
            self.overlay_fullscreen = True
        else:
            self.overlay_sub.geometry(self.overlay_normal_geometry)
            self.overlay_fullscreen = False

    def start_move(self, event):
        self._drag_x = event.x_root - self.overlay_sub.winfo_x()
        self._drag_y = event.y_root - self.overlay_sub.winfo_y()

    def on_move(self, event):
        if hasattr(self, 'overlay_fullscreen') and not self.overlay_fullscreen:
            x = event.x_root - self._drag_x
            y = event.y_root - self._drag_y
            self.overlay_sub.geometry(f"+{x}+{y}")

    def show_voice_control_panel(self):
        if hasattr(self, 'voice_win') and self.voice_win.winfo_exists():
            self.voice_win.lift()
            return
        self.voice_win = tb.Toplevel(self)
        self.voice_win.title("Голосовой ввод")
        self.voice_win.geometry("400x230")
        self.voice_win.attributes("-topmost", True)
        container = tb.Frame(self.voice_win, padding=25)
        container.pack(fill=tk.BOTH, expand=True)
        btn_frame = tb.Frame(container)
        btn_frame.pack(pady=10)
        tb.Button(btn_frame, text="▶", bootstyle="success", width=5,
                  command=lambda: setattr(self.voice_engine, 'is_paused', False)).pack(side=tk.LEFT, padx=2)
        tb.Button(btn_frame, text="⏸", bootstyle="warning", width=5,
                  command=lambda: setattr(self.voice_engine, 'is_paused', True)).pack(side=tk.LEFT, padx=2)
        tb.Button(btn_frame, text="⏹", bootstyle="danger", width=5,
                  command=self.stop_voice_typing).pack(side=tk.LEFT, padx=2)
        self.m_progress = tb.Progressbar(container, bootstyle="info", maximum=100, mode='determinate')
        self.m_progress.pack(fill=tk.X, pady=(5, 10))
        if hasattr(self, 'voice_engine') and self.voice_engine:
            self.voice_engine.level_callback = self.update_voice_level

    def start_voice_typing(self):
     if not self.model_loaded:
         messagebox.showwarning("Модель не загружена", "Подождите загрузки речевой модели.")
         self.voice_typing_var.set(False)
         return
         
     # Жестко проверяем и выставляем дефолт, если переменная пустая или равна None
     if not hasattr(self, 'selected_voice_device') or self.selected_voice_device is None:
         self.selected_voice_device = -1
     elif isinstance(self.selected_voice_device, str):
         # На случай, если в переменной остался текст из комбобокса, переводим в чистый инт
         try:
             self.selected_voice_device = int(self.selected_voice_device)
         except:
             self.selected_voice_device = -1

     self.voice_engine.model = self.shared_model
     
     # Передаем индекс в движок
     self.voice_engine.set_device(self.selected_voice_device)
     
     # Запускаем захват звука
     if self.voice_engine.start():
         self.voice_active = True
         self.show_voice_control_panel() # Твое окно панели управления теперь железно откроется!
     else:
         messagebox.showerror("Ошибка", "Не удалось запустить захват звука. Проверьте настройки микрофона.")
         self.voice_typing_var.set(False)

    def stop_voice_typing(self):
        if self.voice_engine:
            self.voice_engine.stop()
        self.voice_active = False
        if hasattr(self, 'voice_win') and self.voice_win.winfo_exists():
            self.voice_win.destroy()
        self.voice_typing_var.set(False)

    def update_voice_level(self, level):
        if hasattr(self, 'm_progress') and self.m_progress.winfo_exists():
            self.m_progress['value'] = level

    def stop_color_correction(self):
        if self.color_correction_overlay:
            self.color_correction_overlay.stop()

    def start_color_correction(self):
        if self.color_correction_overlay:
            self.color_correction_overlay.start()

    def start_head_tracking(self):
        if self.head_tracker is None:
            self.head_tracker = HeadTracker(
                camera_source=self.head_camera_index,
                sensitivity_x=self.head_sensitivity_x,
                sensitivity_y=self.head_sensitivity_y,
                invert_x=self.head_invert_x,
                swap_eyes=self.head_swap_eyes,
                precision_interval_ms=self.head_precision_ms
            )
        self.head_tracker.start()

    def stop_head_tracking(self):
        if self.head_tracker:
            self.head_tracker.stop()

    def handle_head_event(self, event):
        print(f"Событие: {event}")

    def open_feature_settings(self, feature_name):
        if feature_name == "Субтитры из звука":
            self.open_subtitle_settings()
        elif feature_name == "Голосовой ввод текста":
            self.open_voice_settings()
        elif feature_name == "Коррекция цвета для экрана":
            self.open_color_correction_settings()
        elif feature_name == "Управление мышью при помощи головы":
            self.open_head_settings()

    def open_head_settings(self):
        win = tb.Toplevel(title="Настройки управления головой", size=(600, 525))
        win.resizable(False, False)
        container = tb.Frame(win, padding=20)
        container.pack(fill=tk.BOTH, expand=True)
        tb.Label(container, text="Настройки управления", font=("Segoe UI", 14, "bold")).pack(pady=(0, 20))
        current_sx = self.head_sensitivity_x
        current_sy = self.head_sensitivity_y
        current_ms = self.head_precision_ms
        current_inv = self.head_invert_x
        current_swap = self.head_swap_eyes
        current_cam = self.head_camera_index
        tb.Label(container, text="Выберите камеру:", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        graph = FilterGraph()
        device_names = graph.get_input_devices()
        cam_list = [f"{i}: {name}" for i, name in enumerate(device_names)]
        cam_var = tk.StringVar()
        cam_combo = ttk.Combobox(container, textvariable=cam_var, values=cam_list, state="readonly")
        cam_combo.pack(fill=tk.X, pady=(5, 15))
        if cam_list:
            cam_combo.set(cam_list[current_cam] if current_cam < len(cam_list) else cam_list[0])
        tb.Label(container, text="Чувствительность мыши:", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        frame_x = tb.Frame(container)
        frame_x.pack(fill=tk.X, pady=5)
        tb.Label(frame_x, text="По горизонтали (X):", width=20).pack(side=tk.LEFT)
        sx_var = tk.DoubleVar(value=current_sx)
        tb.Scale(frame_x, from_=1.0, to=30.0, variable=sx_var, orient=tk.HORIZONTAL).pack(side=tk.LEFT, fill=tk.X, expand=True)
        frame_y = tb.Frame(container)
        frame_y.pack(fill=tk.X, pady=5)
        tb.Label(frame_y, text="По вертикали (Y):", width=20).pack(side=tk.LEFT)
        sy_var = tk.DoubleVar(value=current_sy)
        tb.Scale(frame_y, from_=1.0, to=30.0, variable=sy_var, orient=tk.HORIZONTAL).pack(side=tk.LEFT, fill=tk.X, expand=True)
        inv_x_var = tk.BooleanVar(value=current_inv)
        tb.Checkbutton(container, text="Отзеркалить движения по горизонтали (Инверсия X)",
                       variable=inv_x_var, bootstyle="primary-round-toggle").pack(anchor=tk.W, pady=15)
        swap_eyes_var = tk.BooleanVar(value=current_swap)
        tb.Checkbutton(container, text="Инверсия кнопок глаз (Левый <-> Правый)",
                       variable=swap_eyes_var, bootstyle="primary-round-toggle").pack(anchor=tk.W, pady=15)
        tb.Label(container, text="Сброс центра (калибровка):", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(10, 0))
        reset_frame = tb.Frame(container)
        reset_frame.pack(fill=tk.X, pady=5)
        tb.Label(reset_frame, text="Кол-во морганий:").pack(side=tk.LEFT)
        blink_count_var = tk.IntVar(value=self.head_reset_blinks)
        tb.Entry(reset_frame, textvariable=blink_count_var, width=5).pack(side=tk.LEFT, padx=5)
        tb.Label(reset_frame, text="За время (сек):").pack(side=tk.LEFT, padx=(15, 0))
        blink_time_var = tk.DoubleVar(value=self.head_reset_time)
        tb.Entry(reset_frame, textvariable=blink_time_var, width=5).pack(side=tk.LEFT, padx=5)
        tb.Label(container, text="Интервал точного перемещения (мс):", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        ms_frame = tb.Frame(container)
        ms_frame.pack(fill=tk.X, pady=5)
        ms_var = tk.IntVar(value=current_ms)
        tb.Entry(ms_frame, textvariable=ms_var, width=10).pack(side=tk.LEFT)
        tb.Label(ms_frame, text=" мс (время перемещения на 1 пиксель)").pack(side=tk.LEFT, padx=10)

        def apply():
            try:
                selected_cam_text = cam_var.get()
                new_cam_idx = int(selected_cam_text.split(":")[0]) if selected_cam_text else 0
                self.head_sensitivity_x = sx_var.get()
                self.head_sensitivity_y = sy_var.get()
                self.head_invert_x = inv_x_var.get()
                self.head_swap_eyes = swap_eyes_var.get()
                self.head_precision_ms = int(ms_var.get())
                self.head_camera_index = new_cam_idx
                self.head_reset_blinks = int(blink_count_var.get())
                self.head_reset_time = float(blink_time_var.get())
                self.settings["head_tracking"].update({
                    "camera_index": self.head_camera_index,
                    "sensitivity_x": self.head_sensitivity_x,
                    "sensitivity_y": self.head_sensitivity_y,
                    "invert_x": self.head_invert_x,
                    "swap_eyes": self.head_swap_eyes,
                    "precision_interval_ms": self.head_precision_ms,
                    "reset_blinks": self.head_reset_blinks,
                    "reset_time": self.head_reset_time
                })
                self.save_settings()
                settings = {
                    'cam': self.head_camera_index,
                    'sx': self.head_sensitivity_x,
                    'sy': self.head_sensitivity_y,
                    'inv_x': self.head_invert_x,
                    'swap': self.head_swap_eyes,
                    'ms': self.head_precision_ms,
                    'reset_blinks': self.head_reset_blinks,
                    'reset_time': self.head_reset_time
                }
                if self.head_tracker:
                    if self.head_tracker.camera_source != new_cam_idx:
                        self.head_tracker.stop()
                        self.head_tracker.camera_source = new_cam_idx
                        self.head_tracker.update_settings(settings)
                        if self.head_control_var.get():
                            self.head_tracker.start()
                    else:
                        self.head_tracker.update_settings(settings)
                win.destroy()
                messagebox.showinfo("Успех", "Настройки головы сохранены")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

        tb.Button(container, text="Применить настройки", bootstyle="success", command=apply).pack(pady=15, fill=tk.X)

    def open_subtitle_settings(self):
        win = tb.Toplevel(title="Настройки субтитров", size=(620, 420))
        win.resizable(False, False)
        tb.Label(win, text="Настройка субтитров", font=("Segoe UI", 14, "bold")).pack(pady=15)
        dev_frame = tb.Frame(win)
        dev_frame.pack(fill=tk.X, padx=20, pady=10)
        tb.Label(dev_frame, text="Устройство захвата (loopback):").pack(side=tk.LEFT, padx=(0, 10))
        tmp = SubtitlesEngine(self.shared_model)
        devices = tmp.get_loopback_devices()
        device_names = [f"{idx}: {name}" for idx, name in devices]
        self.device_var = tk.StringVar()
        device_combo = ttk.Combobox(dev_frame, textvariable=self.device_var, values=device_names, state="readonly", width=50)
        device_combo.pack(side=tk.LEFT)
        if self.selected_device_index is not None:
            for idx, name in devices:
                if idx == self.selected_device_index:
                    device_combo.set(f"{idx}: {name}")
                    break
        if not device_combo.get() and devices:
            device_combo.set(device_names[0])
        self.device_combo = device_combo
        alpha_frame = tb.Frame(win)
        alpha_frame.pack(fill=tk.X, padx=20, pady=10)
        tb.Label(alpha_frame, text="Прозрачность окна:").pack(side=tk.LEFT, padx=(0, 10))
        alpha_slider = tb.Scale(alpha_frame, from_=0.2, to=1.0, value=self.subtitle_alpha, orient=tk.HORIZONTAL, length=200)
        alpha_slider.pack(side=tk.LEFT, padx=10)
        alpha_label = tb.Label(alpha_frame, text=f"{int(self.subtitle_alpha * 100)}%")
        alpha_label.pack(side=tk.LEFT)

        def update_alpha(val):
            self.subtitle_alpha = float(val)
            alpha_label.config(text=f"{int(self.subtitle_alpha * 100)}%")
            if self.overlay_sub and self.overlay_sub.winfo_exists():
                self.overlay_sub.attributes("-alpha", self.subtitle_alpha)
            self.settings["subtitles"]["alpha"] = self.subtitle_alpha
            self.save_settings()
        alpha_slider.configure(command=update_alpha)

        font_frame = tb.Frame(win)
        font_frame.pack(fill=tk.X, padx=20, pady=10)
        tb.Label(font_frame, text="Шрифт:").pack(side=tk.LEFT, padx=(0, 10))
        font_combo = ttk.Combobox(font_frame, values=["Segoe UI", "Arial", "Times New Roman", "Courier New"], state="readonly")
        font_combo.set(self.font_family)
        font_combo.pack(side=tk.LEFT, padx=5)
        tb.Label(font_frame, text="Размер:").pack(side=tk.LEFT, padx=(10, 5))
        size_slider = tb.Scale(font_frame, from_=10, to=30, value=self.font_size, orient=tk.HORIZONTAL, length=100)
        size_slider.pack(side=tk.LEFT, padx=5)
        size_label = tb.Label(font_frame, text=f"{self.font_size}px")
        size_label.pack(side=tk.LEFT)

        def update_font(*args):
            self.font_family = font_combo.get()
            self.font_size = int(size_slider.get())
            size_label.config(text=f"{self.font_size}px")
            if self.overlay_sub and self.overlay_sub.winfo_exists():
                self.overlay_sub.text_widget.configure(font=(self.font_family, self.font_size))
            self.settings["subtitles"]["font_family"] = self.font_family
            self.settings["subtitles"]["font_size"] = self.font_size
            self.save_settings()
        font_combo.bind("<<ComboboxSelected>>", update_font)
        size_slider.configure(command=lambda v: update_font())

        def save():
            sel = self.device_combo.get()
            if sel:
                self.selected_device_index = int(sel.split(":")[0])
            self.settings["subtitles"]["device_index"] = self.selected_device_index
            self.save_settings()
            was_active = self.subtitles_active
            win.destroy()
            if was_active:
                self.stop_subtitles()
                self.after(300, self.start_subtitles)
        tb.Button(win, text="Сохранить", bootstyle="success", command=save).pack(pady=20)

    def open_voice_settings(self):
        # Внутри метода перед каждой строчкой должно быть по 8 пробелов!
        win_voice = tb.Toplevel(title="Настройки голосового ввода", size=(450, 320))
        win_voice.resizable(False, False)
        win_voice.transient(self)
        win_voice.grab_set()

        frame_voice = tb.Frame(win_voice, padding=20)
        frame_voice.pack(fill=tk.BOTH, expand=True)

        tb.Label(frame_voice, text="Выберите микрофон для ввода текста:", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(0, 5))

                # Прямой сбор устройств через PyAudio прямо внутри интерфейса
                # Прямой сбор устройств через PyAudio с фильтрацией дубликатов по имени
        import pyaudiowpatch as pa
        devices = []
        seen_names = set() # Множество для отслеживания уже добавленных имен
        
        try:
            p_temp = pa.PyAudio()
            for i in range(p_temp.get_device_count()):
                try:
                    dev_info = p_temp.get_device_info_by_index(i)
                    if dev_info.get('maxInputChannels', 0) > 0:
                        name = dev_info.get('name', f"Микрофон {i}").strip()
                        if isinstance(name, bytes):
                            name = name.decode('utf-8', errors='ignore')

                        ignore_keywords = ["динамик", "наушник", "speaker", "headphone", "loopback", "output"]
                        
                        # Проверяем, нужно ли игнорировать устройство
                        should_ignore = any(keyword in name.lower() for keyword in ignore_keywords)

                        # Добавляем устройство только если его имя уникально и это не динамики/наушники
                        if name not in seen_names and not should_ignore:
                            seen_names.add(name)
                            devices.append((i, name))

                except:
                    continue
            p_temp.terminate()
        except Exception as e:
            print(f"[UI Audio Debug] Ошибка PortAudio: {e}")

        device_list = ["-1: Системное устройство (По умолчанию)"] + [f"{i}: {name}" for i, name in devices]
        
        # Убираем textvariable=device_var, оставляя только values
        device_combo = ttk.Combobox(frame_voice, values=device_list, state="readonly")
        device_combo.pack(fill=tk.X, pady=(0, 15))

        # Жёстко и принудительно выставляем текст по умолчанию в комбобокс
        current_dev = -1
        if hasattr(self, 'settings') and self.settings:
            current_dev = self.settings.get("voice_input", {}).get("device_index", -1)
            
        # Находим нужную строчку в списке или собираем её на лету
        target_value = next((item for item in device_list if item.startswith(f"{current_dev}:")), None)
        if not target_value:
            if current_dev == -1:
                target_value = "-1: Системное устройство (По умолчанию)"
            else:
                target_value = f"{current_dev}: Настроенное устройство записи"
                
        # Принудительно вбиваем текст в комбобокс
        device_combo.set(target_value)

        def save_voice_config():
            selected = device_combo.get()
            if selected:
                try:
                    idx = int(selected.split(":")[0])
                    if "voice_input" not in self.settings:
                        self.settings["voice_input"] = {}
                    self.settings["voice_input"]["device_index"] = idx
                    self.selected_voice_device = idx
                    
                    if hasattr(self, 'voice_input') and self.voice_input:
                        self.voice_input.set_device(idx)
                        
                    self.save_settings()
                    messagebox.showinfo("Успех", "Настройки микрофона успешно сохранены.", parent=win_voice)
                    win_voice.destroy()
                except Exception as e:
                    messagebox.showerror("Ошибка", f"Не удалось сохранить настройки: {e}", parent=win_voice)
            else:
                win_voice.destroy()

        def internal_open_replacements():
            win_repl = tb.Toplevel(win_voice)
            win_repl.title("Настройка голосовых замен")
            win_repl.geometry("600x550")
            win_repl.resizable(False, False)
            win_repl.transient(win_voice)
            win_repl.grab_set()

            if "voice_replacements" not in self.settings:
                self.settings["voice_replacements"] = {
                    "знак запятая": ",", 
                    "знак точка": ".", 
                    "знак вопрос": "?",
                    "знак восклицания": "!"
                }
            replacements = self.settings["voice_replacements"]

            frame_repl = tb.Frame(win_repl, padding=15)
            frame_repl.pack(fill=tk.BOTH, expand=True)

            tb.Label(frame_repl, text="Добавить новую замену:", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, pady=(0,10))
            tb.Label(frame_repl, text="Что говорить (голосовая команда):").pack(anchor=tk.W)
            
            cmd_frame = tb.Frame(frame_repl)
            cmd_frame.pack(fill=tk.X, pady=(2, 10))
            entry_cmd = tb.Entry(cmd_frame)
            entry_cmd.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

            def record_phrase():
                def listen():
                    import speech_recognition as sr
                    recognizer = sr.Recognizer()
                    with sr.Microphone() as source:
                        try:
                            recognizer.adjust_for_ambient_noise(source, duration=0.5)
                            win_repl.after(0, lambda: messagebox.showinfo("Запись", "Говорите команду...", parent=win_repl))
                            audio = recognizer.listen(source, timeout=4, phrase_time_limit=4)
                            text = recognizer.recognize_google(audio, language="ru-RU").lower().strip()
                            win_repl.after(0, lambda: entry_cmd.delete(0, tk.END))
                            win_repl.after(0, lambda: entry_cmd.insert(0, text))
                        except Exception as e:
                            win_repl.after(0, lambda: messagebox.showerror("Ошибка", f"Не удалось записать: {e}", parent=win_repl))
                threading.Thread(target=listen, daemon=True).start()

            tb.Button(cmd_frame, text="🎤", width=4, bootstyle="outline-secondary", command=record_phrase).pack(side=tk.RIGHT)

            tb.Label(frame_repl, text="На какой символ или слово заменять:").pack(anchor=tk.W)
            sym_frame = tb.Frame(frame_repl)
            sym_frame.pack(fill=tk.X, pady=(2, 15))
            entry_sym = tb.Entry(sym_frame)
            entry_sym.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

            tb.Button(sym_frame, text="⌨️ Клавиатура", bootstyle="outline-info", 
                      command=lambda: os.system("start osk.exe")).pack(side=tk.RIGHT)

            list_container = tb.Frame(frame_repl)
            list_container.pack(fill=tk.BOTH, expand=True, pady=5)
            listbox = tk.Listbox(list_container, font=("Courier New", 10))
            listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scroll = tb.Scrollbar(list_container, orient=tk.VERTICAL, command=listbox.yview)
            scroll.pack(side=tk.RIGHT, fill=tk.Y)
            listbox.configure(yscrollcommand=scroll.set)

            listbox_keys = []

            def refresh():
                listbox.delete(0, tk.END)
                listbox_keys.clear()
                for cmd, sym in replacements.items():
                    listbox_keys.append(cmd)
                    listbox.insert(tk.END, f" 🗣 '{cmd}'  ➔  🎹 '{sym}'")

            def add():
                cmd_text = entry_cmd.get().strip().lower()
                sym_text = entry_sym.get().strip()
                if not cmd_text or not sym_text:
                    messagebox.showwarning("Ошибка", "Заполните оба поля!", parent=win_repl)
                    return
                replacements[cmd_text] = sym_text
                self.settings["voice_replacements"] = replacements
                self.save_settings()
                refresh()
                entry_cmd.delete(0, tk.END)
                entry_sym.delete(0, tk.END)

            def delete():
                sel = listbox.curselection()
                if sel:
                    index = sel[0]
                    cmd_to_del = listbox_keys[index]
                    if cmd_to_del in replacements:
                        del replacements[cmd_to_del]
                        self.settings["voice_replacements"] = replacements
                        self.save_settings()
                        refresh()

            tb.Button(frame_repl, text="Добавить замену", bootstyle="success", command=add).pack(fill=tk.X, pady=3)
            tb.Button(frame_repl, text="Удалить выбранное", bootstyle="danger-outline", command=delete).pack(fill=tk.X, pady=3)
            refresh()

        tb.Button(frame_voice, text="🔣 Настройка голосовых замен и знаков", 
                  bootstyle="info-outline", command=internal_open_replacements).pack(fill=tk.X, pady=(0, 20))

        actions_frame = tb.Frame(frame_voice)
        actions_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))

        tb.Button(actions_frame, text="Сохранить микрофон", bootstyle="success", command=save_voice_config).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        tb.Button(actions_frame, text="Отмена", bootstyle="secondary", command=win_voice.destroy).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))


    def open_color_correction_settings(self):
        if hasattr(self, '_color_settings_win') and self._color_settings_win is not None:
            try:
                self._color_settings_win.destroy()
            except:
                pass
            self._color_settings_win = None
        win = tb.Toplevel(title="Настройки цветокоррекции", size=(550, 450))
        win.resizable(False, False)
        self._color_settings_win = win

        def on_close():
            self._color_settings_win = None
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", on_close)
        tb.Label(win, text="Коррекция цвета для дальтоников", font=("Segoe UI", 14, "bold")).pack(pady=15)
        type_frame = tb.Frame(win)
        type_frame.pack(fill=tk.X, padx=20, pady=10)
        tb.Label(type_frame, text="Тип коррекции:").pack(side=tk.LEFT, padx=(0, 10))
        temp_type = tk.StringVar(value=self.color_correction_type)
        types = [("Протанопия (красный)", "protanomaly"), ("Дейтеранопия (зелёный)", "deuteranomaly"), ("Тританопия (синий)", "tritanomaly")]
        for text, val in types:
            tb.Radiobutton(type_frame, text=text, variable=temp_type, value=val).pack(anchor=tk.W)
        int_frame = tb.Frame(win)
        int_frame.pack(fill=tk.X, padx=20, pady=10)
        tb.Label(int_frame, text="Интенсивность:").pack(side=tk.LEFT, padx=(0, 10))
        temp_intensity = tk.DoubleVar(value=self.color_intensity)
        int_slider = tb.Scale(int_frame, from_=0.0, to=1.0, variable=temp_intensity, orient=tk.HORIZONTAL, length=200)
        int_slider.pack(side=tk.LEFT, padx=10)
        int_label = tb.Label(int_frame, text=f"{int(temp_intensity.get() * 100)}%")
        int_label.pack(side=tk.LEFT)
        def update_int_label(*args):
            int_label.config(text=f"{int(temp_intensity.get() * 100)}%")
        temp_intensity.trace_add('write', update_int_label)
        gain_frame = tb.Frame(win)
        gain_frame.pack(fill=tk.X, padx=20, pady=10)
        tb.Label(gain_frame, text="Усиление цвета:").pack(side=tk.LEFT, padx=(0, 10))
        temp_gain = tk.DoubleVar(value=self.color_gain)
        gain_slider = tb.Scale(gain_frame, from_=0.0, to=1.0, variable=temp_gain, orient=tk.HORIZONTAL, length=200)
        gain_slider.pack(side=tk.LEFT, padx=10)
        gain_label = tb.Label(gain_frame, text=f"{int(temp_gain.get() * 100)}%")
        gain_label.pack(side=tk.LEFT)
        def update_gain_label(*args):
            gain_label.config(text=f"{int(temp_gain.get() * 100)}%")
        temp_gain.trace_add('write', update_gain_label)
        btn_frame = tb.Frame(win)
        btn_frame.pack(pady=20)

        def apply_changes():
            self.color_correction_type = temp_type.get()
            self.color_intensity = temp_intensity.get()
            self.color_gain = temp_gain.get()
            self.settings["color_correction"] = {"type": self.color_correction_type, "intensity": self.color_intensity, "gain": self.color_gain}
            self.save_settings()
            self.color_correction_overlay.set_correction_type(self.color_correction_type)
            self.color_correction_overlay.set_intensity(self.color_intensity)
            self.color_correction_overlay.set_gain(self.color_gain)
            if self.color_correction_var.get():
                self.stop_color_correction()
                self.start_color_correction()
            messagebox.showinfo("Успех", "Настройки цветокоррекции сохранены")
        def close_window():
            if self._color_settings_win:
                self._color_settings_win.destroy()
                self._color_settings_win = None
        tb.Button(btn_frame, text="Применить", bootstyle="success", command=apply_changes).pack(side=tk.LEFT, padx=10)
        tb.Button(btn_frame, text="Закрыть", bootstyle="secondary", command=close_window).pack(side=tk.LEFT, padx=10)

    def create_side_menu(self):
        self.menu_frame = tk.Frame(
            self.main_container,
            width=230,
            bg=self.style.colors.bg,
            bd=0,
            highlightthickness=0,
            padx=0,
            pady=0
        )
        self.menu_frame.place(x=-250, y=0, width=230, relheight=1.0)
        self.menu_frame.pack_propagate(False)

        # Контейнер для содержимого
        self.menu_content = tk.Frame(self.menu_frame, bg=self.style.colors.bg)
        self.menu_content.pack(fill=tk.BOTH, expand=True)

        # Акцентная полоска (Canvas)
        self.accent_canvas = tk.Canvas(self.menu_frame, width=4, bg=self.style.colors.bg, highlightthickness=0)
        self.accent_canvas.place(relx=1.0, x=-4, y=0, width=4, relheight=1.0)
        self.accent_canvas.create_line(2, 0, 2, 10000, fill='#28a745', width=3)

        self.refresh_menu_content()

    def refresh_menu_content(self):
        for widget in self.menu_content.winfo_children():
            widget.destroy()

        bg_color = self.style.colors.bg
        fg_color = self.style.colors.fg
        accent = '#28a745'
        hover_bg = self.style.colors.inputbg
        btn_style = {
            "bg": bg_color, "fg": fg_color,
            "activebackground": hover_bg, "activeforeground": accent,
            "relief": "flat", "bd": 0, "font": ("Segoe UI", 10, "bold"),
            "anchor": "w", "padx": 15
        }

        tk.Label(self.menu_content, text="МЕНЮ", font=("Segoe UI", 16, "bold"),
                 bg=bg_color, fg=accent, bd=0, highlightthickness=0).pack(pady=(40, 30))

        tk.Button(self.menu_content, text="📖 Инструкция", **btn_style,
                  command=self.open_instructions_window).pack(fill="x", pady=5, padx=(0, 10))
        tk.Button(self.menu_content, text="⚙️ Настройки программы", **btn_style,
                  command=self.open_program_settings).pack(fill="x", pady=5, padx=(0, 10))

        tk.Frame(self.menu_content, bg=self.style.colors.border, height=1, bd=0, highlightthickness=0).pack(fill="x", padx=20, pady=20)

        tk.Button(self.menu_content, text="🎤 Голосовые команды", **btn_style,
                  command=self.voice_cmd.show_settings_window).pack(fill="x", pady=5, padx=(0, 10))
        tk.Button(self.menu_content, text="⌨️ Комбинации клавиш", **btn_style,
                  command=self.hotkey_cmd.show_settings_window).pack(fill="x", pady=5, padx=(0, 10))
        tk.Button(self.menu_content, text="⚡ Запуск по кнопке", **btn_style,
                  command=self.script_launcher.show_main_window).pack(fill="x", pady=5, padx=(0, 10))

        if self.script_launcher.buttons:
            tk.Frame(self.menu_content, bg=self.style.colors.border, height=1, bd=0, highlightthickness=0).pack(fill="x", padx=20, pady=10)
            for name in list(self.script_launcher.buttons.keys()):
                btn = tk.Button(self.menu_content, text=f"▶ {name}", **btn_style,
                                command=lambda n=name: self.script_launcher.run_script(n))
                btn.pack(fill="x", pady=5, padx=(0, 10))

        tk.Frame(self.menu_content, bg=self.style.colors.border, height=1, bd=0, highlightthickness=0).pack(fill="x", padx=20, pady=20)
        frame_sw = tk.Frame(self.menu_content, bg=bg_color, bd=0, highlightthickness=0)
        frame_sw.pack(fill="x", padx=(20, 15), pady=5)
        tk.Label(frame_sw, text="Авто-меню", bg=bg_color, fg="gray", font=("Segoe UI", 9), bd=0, highlightthickness=0).pack(side="left")
        tb.Checkbutton(frame_sw, variable=self.menu_on_hover_var, bootstyle="success-round-toggle").pack(side="right")

        btn_close = tk.Button(self.menu_content, text="✕ ЗАКРЫТЬ", **btn_style, command=self.close_menu)
        btn_close.pack(side="bottom", fill="x", pady=30, padx=(0, 10))

    def open_instructions_window(self):
        win = tb.Toplevel(title="Центр помощи", size=(600, 500))
        win.resizable(False, False)
        main_frame = tb.Frame(win, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        tb.Label(main_frame, text="📖 Руководство пользователя", font=("Segoe UI", 16, "bold"), bootstyle="success").pack(pady=(0, 20))
        btn_container = tb.Frame(main_frame)
        btn_container.pack(fill=tk.X, pady=10)
        menu_items = [
            ("Управление головой", "👁️", self.show_eye_instruction),
            ("Цветокоррекция", "🎨", self.show_color_instruction),
            ("Субтитры", "📝", self.show_subtitles_instruction),
            ("Голосовой ввод", "🎤", self.show_voice_instruction)
        ]
        for text, icon, cmd in menu_items:
            btn = tb.Button(btn_container, text=f"{icon} {text}", bootstyle="outline-secondary", command=cmd, width=25)
            btn.pack(pady=5, fill=tk.X)
        tb.Separator(main_frame).pack(pady=20)
        tb.Button(main_frame, text="Понятно", bootstyle="success", command=win.destroy).pack(side=tk.BOTTOM, pady=10)

    def create_hover_detector(self):
        self.hover_detector = tk.Frame(self.main_container, bg="", width=15)
        self.hover_detector.place(x=0, y=0, width=15, relheight=1.0)
        self.hover_detector.lower()
        self.bind_hover_events()

    def bind_hover_events(self):
        def on_enter_hitbox(e):
            if self.menu_on_hover_var.get() and not self.menu_open:
                self.open_menu()
        self.hover_detector.bind("<Enter>", on_enter_hitbox)

        def is_mouse_over_menu():
            x, y = self.winfo_pointerxy()
            widget = self.winfo_containing(x, y)
            while widget:
                if widget == self.menu_frame:
                    return True
                widget = widget.master
            return False

        def on_mouse_move(e):
            if self.menu_on_hover_var.get() and self.menu_open:
                if not is_mouse_over_menu():
                    self.close_menu()
        self.bind("<Motion>", on_mouse_move)

    def toggle_menu(self):
        if self.menu_open:
            self.close_menu()
        else:
            self.open_menu()

    def open_menu(self):
        if not self.menu_open:
            self.menu_frame.place(x=0, y=0)
            self.menu_frame.lift()
            self.menu_open = True

    def close_menu(self):
        if self.menu_open:
            self.menu_frame.place(x=-240, y=0)
            self.menu_open = False

    def open_program_settings(self):
        win = tb.Toplevel(title="Настройки программы", size=(450, 450))
        win.resizable(False, False)
        container = tb.Frame(win, padding=20)
        container.pack(fill=tk.BOTH, expand=True)
        tb.Label(container, text="⚙️ Общие настройки", font=("Segoe UI", 14, "bold")).pack(pady=(0, 20))
        themes_dict = {"darkly": "Тёмная классика", "flatly": "Светлая классика", "superhero": "Супергерой",
                       "cyborg": "Киборг", "vapor": "Киберпанк", "solar": "Солнечная"}
        rev_themes = {v: k for k, v in themes_dict.items()}
        theme_frame = tb.Frame(container)
        theme_frame.pack(fill=tk.X, pady=10)
        tb.Label(theme_frame, text="Выберите оформление:").pack(anchor=tk.W, pady=5)
        theme_combo = ttk.Combobox(theme_frame, values=list(themes_dict.values()), state="readonly")
        current_tech = self.style.theme.name
        theme_combo.set(themes_dict.get(current_tech, "Тёмная классика"))
        theme_combo.pack(fill=tk.X)
        def on_theme_change(event):
            rus_name = theme_combo.get()
            tech_name = rev_themes.get(rus_name, "darkly")
            self.style.theme_use(tech_name)
            self.settings["app"]["theme"] = tech_name
            self.save_settings()
            self.update()
            if hasattr(self, 'menu_frame'):
                self.refresh_menu_content()
        theme_combo.bind("<<ComboboxSelected>>", on_theme_change)
        tb.Separator(container).pack(pady=20)

        def set_autorun(enable):
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS) as key:
                    if enable:
                        winreg.SetValueEx(key, "AssistiveSuite", 0, winreg.REG_SZ, sys.executable + " " + os.path.abspath(__file__))
                    else:
                        try:
                            winreg.DeleteValue(key, "AssistiveSuite")
                        except:
                            pass
            except Exception as e:
                print("Ошибка автозапуска", e)

        def check_autorun():
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
                    winreg.QueryValueEx(key, "AssistiveSuite")
                    return True
            except:
                return False

        autorun_var = tk.BooleanVar(value=check_autorun())
        cb_autorun = tb.Checkbutton(container, text="Запускать при старте Windows",
                                    bootstyle="success-square-toggle",
                                    command=lambda: set_autorun(autorun_var.get()),
                                    variable=autorun_var)
        cb_autorun.pack(anchor=tk.W, pady=5)

        tray_var = tk.BooleanVar(value=self.settings.get("minimize_to_tray", False))
        def set_tray(enable):
            self.settings["minimize_to_tray"] = enable
            self.save_settings()
        cb_tray = tb.Checkbutton(container, text="Сворачивать в трей при закрытии",
                                 bootstyle="success-square-toggle",
                                 command=lambda: set_tray(tray_var.get()),
                                 variable=tray_var)
        cb_tray.pack(anchor=tk.W, pady=5)

        tb.Separator(container).pack(pady=15)
        tb.Button(container, text="Закрыть", bootstyle="secondary", command=win.destroy).pack(side=tk.BOTTOM, fill=tk.X, pady=10)

    def _create_styled_info_window(self, title, icon, subtitle, steps):
        info_win = tb.Toplevel(title=title, size=(550, 550))
        info_win.resizable(False, False)
        container = tb.Frame(info_win, padding=25)
        container.pack(fill=tk.BOTH, expand=True)
        header_frame = tb.Frame(container)
        header_frame.pack(fill=tk.X, pady=(0, 15))
        tb.Label(header_frame, text=icon, font=("Segoe UI", 24)).pack(side=tk.LEFT, padx=(0, 15))
        tb.Label(header_frame, text=title, font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT)
        tb.Label(container, text=subtitle, font=("Segoe UI", 10, "italic"),
                 wraplength=480, justify=tk.LEFT, foreground="gray").pack(anchor=tk.W, pady=(0, 20))
        text_area = tb.Canvas(container, highlightthickness=0)
        text_area.pack(fill=tk.BOTH, expand=True)
        inner_text = tb.Frame(text_area)
        inner_text.pack(fill=tk.BOTH, expand=True)
        for i, step in enumerate(steps, 1):
            step_frame = tb.Frame(inner_text)
            step_frame.pack(fill=tk.X, pady=5)
            tb.Label(step_frame, text=f"{i}.", font=("Segoe UI", 10, "bold"),
                     bootstyle="success").pack(side=tk.LEFT, anchor=tk.N, padx=(0, 10))
            tb.Label(step_frame, text=step, font=("Segoe UI", 10),
                     wraplength=440, justify=tk.LEFT).pack(side=tk.LEFT, anchor=tk.W)
        tb.Button(container, text="Закрыть", bootstyle="outline-success", command=info_win.destroy).pack(pady=(20, 0))

    def show_voice_instruction(self):
        steps = ["Убедитесь, что микрофон подключен в настройках (⚙️).", "Нажмите кнопку 🎤 на панели управления для старта.",
                 "Говорите четко. Текст будет печататься в активное окно.", "Используйте кнопку паузы, если нужно прерваться.",
                 "Для завершения нажмите кнопку Стоп (квадрат)."]
        self._create_styled_info_window("Голосовой ввод", "🎤", "Превращает вашу речь в печатный текст в любом приложении.", steps)

    def show_subtitles_instruction(self):
        steps = ["Выберите устройство Loopback в настройках.", "Включите функцию: появится прозрачное окно.",
                 "Окно можно перетаскивать и менять его прозрачность.", "Двойное моргание двумя глазами (если настроено) сбросит центр.",
                 "Текст очищается автоматически каждые несколько секунд."]
        self._create_styled_info_window("Субтитры", "📝", "Отображает системные звуки и речь в виде текста поверх всех окон.", steps)

    def show_color_instruction(self):
        steps = ["Выберите ваш тип цветовой слепоты в настройках.", "Настройте интенсивность фильтра ползунком.",
                 "Фильтр применяется ко всей области экрана мгновенно.", "Если цвета не изменились, попробуйте перезапустить функцию."]
        self._create_styled_info_window("Коррекция цвета", "🎨", "Адаптирует палитру монитора для лучшего различения цветов.", steps)

    def show_eye_instruction(self):
        steps = ["Замрите перед камерой в центре экрана при включении.", "Поворот головы — мышь плавно едет (режим джойстика).",
                 "Левый глаз — клик ЛКМ, Правый глаз — ПКМ.", "Долгое закрытие глаза — зажатие кнопки (Drag & Drop).",
                 "Моргните обоими глазами 2 раза для быстрого сброса центра."]
        self._create_styled_info_window("Управление головой", "👁️", "Полный контроль мыши без помощи рук при помощи веб-камеры.", steps)

    def on_closing(self):
        if self.settings.get("minimize_to_tray", False):
            self.withdraw()
            if not hasattr(self, 'tray_icon') or self.tray_icon is None:
                image = Image.new('RGB', (64, 64), color='blue')
                menu = (item('Показать', lambda: self.deiconify()), item('Выйти', lambda: self.destroy()))
                self.tray_icon = pystray.Icon("assistive", image, "Инклюзивный ассистент", menu)
                threading.Thread(target=self.tray_icon.run, daemon=True).start()
        else:
            self.stop_subtitles()
            self.stop_voice_typing()
            self.stop_color_correction()
            self.stop_head_tracking()
            if hasattr(self, 'db'):
                self.db.close()
            self.save_settings()
            self.destroy()

        def open_voice_replacements_window(self):
            """Окно настройки голосовых замен знаков препинания и символов (KAN-12)"""
            win = tb.Toplevel(self)
            win.title("Настройка голосовых замен")
            win.geometry("600x550")
            win.resizable(False, False)
            win.transient(self)
            win.grab_set()

            # Создаем словарь в общих настройках, если его там нет
            if "voice_replacements" not in self.settings:
                self.settings["voice_replacements"] = {
                    "знак запятая": ",", 
                    "знак точка": ".", 
                    "знак вопрос": "?",
                    "знак восклицания": "!"
                }
            replacements = self.settings["voice_replacements"]

            frame = tb.Frame(win, padding=15)
            frame.pack(fill=tk.BOTH, expand=True)

            tb.Label(frame, text="Добавить новую замену:", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, pady=(0,10))
            tb.Label(frame, text="Что говорить (голосовая команда):").pack(anchor=tk.W)
        
            cmd_frame = tb.Frame(frame)
            cmd_frame.pack(fill=tk.X, pady=(2, 10))
            entry_cmd = tb.Entry(cmd_frame)
            entry_cmd.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

            def record_phrase():
                def listen():
                    import speech_recognition as sr
                    recognizer = sr.Recognizer()
                    with sr.Microphone() as source:
                        try:
                            recognizer.adjust_for_ambient_noise(source, duration=0.5)
                            win.after(0, lambda: messagebox.showinfo("Запись", "Говорите команду...", parent=win))
                            audio = recognizer.listen(source, timeout=4, phrase_time_limit=4)
                            text = recognizer.recognize_google(audio, language="ru-RU").lower().strip()
                            win.after(0, lambda: entry_cmd.delete(0, tk.END))
                            win.after(0, lambda: entry_cmd.insert(0, text))
                        except Exception as e:
                            win.after(0, lambda: messagebox.showerror("Ошибка", f"Не удалось записать: {e}", parent=win))
                threading.Thread(target=listen, daemon=True).start()

            tb.Button(cmd_frame, text="🎤", width=4, bootstyle="outline-secondary", command=record_phrase).pack(side=tk.RIGHT)

            tb.Label(frame, text="На какой символ или слово заменять:").pack(anchor=tk.W)
            sym_frame = tb.Frame(frame)
            sym_frame.pack(fill=tk.X, pady=(2, 15))
            entry_sym = tb.Entry(sym_frame)
            entry_sym.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

            tb.Button(sym_frame, text="⌨️ Клавиатура", bootstyle="outline-info", 
                      command=lambda: os.system("start osk.exe")).pack(side=tk.RIGHT)

            list_container = tb.Frame(frame)
            list_container.pack(fill=tk.BOTH, expand=True, pady=5)
            listbox = tk.Listbox(list_container, font=("Courier New", 10))
            listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scroll = tb.Scrollbar(list_container, orient=tk.VERTICAL, command=listbox.yview)
            scroll.pack(side=tk.RIGHT, fill=tk.Y)
            listbox.configure(yscrollcommand=scroll.set)

            listbox_keys = []

            def refresh():
                listbox.delete(0, tk.END)
                listbox_keys.clear()
                for cmd, sym in replacements.items():
                    listbox_keys.append(cmd)
                    listbox.insert(tk.END, f" 🗣 '{cmd}'  ➔  🎹 '{sym}'")

            def add():
                cmd_text = entry_cmd.get().strip().lower()
                sym_text = entry_sym.get().strip()
                if not cmd_text or not sym_text:
                    messagebox.showwarning("Ошибка", "Заполните оба поля!", parent=win)
                    return
                replacements[cmd_text] = sym_text
                self.settings["voice_replacements"] = replacements
                self.save_settings()
                refresh()
                entry_cmd.delete(0, tk.END)
                entry_sym.delete(0, tk.END)

            def delete():
                sel = listbox.curselection()
                if sel:
                    index = sel[0]  # Исправлено извлечение индекса
                    cmd_to_del = listbox_keys[index]
                    if cmd_to_del in replacements:
                        del replacements[cmd_to_del]
                        self.settings["voice_replacements"] = replacements
                        self.save_settings()
                        refresh()

            tb.Button(frame, text="Добавить замену", bootstyle="success", command=add).pack(fill=tk.X, pady=3)
            tb.Button(frame, text="Удалить выбранное", bootstyle="danger-outline", command=delete).pack(fill=tk.X, pady=3)
            refresh()

if __name__ == "__main__":
    app = AssistiveSuite()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()