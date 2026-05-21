import threading
import speech_recognition as sr
import tkinter as tk
from tkinter import ttk, messagebox
import ttkbootstrap as tb
import time
import ctypes

# Константы для низкоуровневого WinAPI keybd_event
KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_KEYUP = 0x0002

# Виртуальные коды клавиш для Windows
VK_CODES = {
    'backspace': 0x08, 'tab': 0x09, 'enter': 0x0D, 'shift': 0x10, 'ctrl': 0x11, 'alt': 0x12,
    'capslock': 0x14, 'esc': 0x1B, 'space': 0x20, 'pageup': 0x21, 'pagedown': 0x22,
    'end': 0x23, 'home': 0x24, 'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28,
    'printscreen': 0x2C, 'insert': 0x2D, 'delete': 0x2E,
    'win': 0x5B, 'apps': 0x5D,
}

# Автоматическое наполнение F1-F24, цифр и букв
for i in range(1, 25):
    VK_CODES[f'f{i}'] = 0x70 + i - 1
for c in '0123456789':
    VK_CODES[c] = ord(c)
for c in 'abcdefghijklmnopqrstuvwxyz':
    VK_CODES[c] = ord(c.upper())

def get_vk_code(key):
    """Возвращает виртуальный код клавиши Windows."""
    key_lower = key.lower()
    if key_lower in VK_CODES:
        return VK_CODES[key_lower]
    if len(key) == 1 and key.isalnum():
        return ord(key.upper())
    raise ValueError(f"Неизвестная клавиша: {key}")

# Словарь аппаратных перегрузок системных комбинаций.
# Позволяет выполнять заблокированные системой хоткеи напрямую через WinAPI.
SYSTEM_API_OVERRIDES = {
    "win+l": lambda: ctypes.windll.user32.LockWorkStation(),
    # Сюда можно будет дописывать другие защищенные комбинации Windows, если они найдутся
}

def send_hotkey(combo):
    """
    Эмулирует нажатие комбинации клавиш.
    Если комбинация защищена Windows, вызывает ее через прямой системный API.
    """
    normalized_combo = combo.lower().strip()
    
    # ПРОВЕРКА ОВЕРРАЙДОВ: Если комбинация требует вызова функции Windows напрямую
    if normalized_combo in SYSTEM_API_OVERRIDES:
        try:
            SYSTEM_API_OVERRIDES[normalized_combo]()
            print(f"[WinAPI Override] Комбинация '{combo}' успешно выполнена через системный метод.")
            return
        except Exception as e:
            print(f"[WinAPI Override] Ошибка вызова системного метода для '{combo}': {e}")
            # Если прямой вызов почему-то упал, падаем в дефолтный keybd_event ниже

    # ДЕФОЛТНЫЙ КЛИКЕР: Стандартная эмуляция через keybd_event
    keys = normalized_combo.split('+')
    if not keys:
        return
        
    main_key = keys[-1]
    modifiers = keys[:-1]
    
    user32 = ctypes.windll.user32
    
    # Зажимаем модификаторы
    for mod in modifiers:
        vk = get_vk_code(mod)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYDOWN, 0)
        time.sleep(0.01)
        
    # Нажимаем и отпускаем основную клавишу
    vk_main = get_vk_code(main_key)
    user32.keybd_event(vk_main, 0, KEYEVENTF_KEYDOWN, 0)
    time.sleep(0.02)
    user32.keybd_event(vk_main, 0, KEYEVENTF_KEYUP, 0)
    
    # Отпускаем модификаторы в обратном порядке
    for mod in reversed(modifiers):
        vk = get_vk_code(mod)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.01)


class VoiceCommandsManager:
    def __init__(self, parent):
        self.parent = parent
        self.commands = parent.settings.get("voice_commands", {})
        self.listening = False
        
        # Настройки фильтрации и активационного слова
        self.use_wake_word = False
        self.WAKE_WORD = "компьютер"
        self.STOP_WORDS = ["блядь", "блять", "сука", "черт", "капец", "хуй"]
        
        self._migrate_old_commands()

    def _migrate_old_commands(self):
        migrated = False
        for phrase, value in list(self.commands.items()):
            if isinstance(value, str):
                self.commands[phrase] = {"type": "builtin", "value": value}
                migrated = True
        if migrated:
            self.parent.settings["voice_commands"] = self.commands
            self.parent.save_settings()

    def start_listening(self):
        if self.listening:
            return
        try:
            with sr.Microphone() as source:
                pass
        except Exception as e:
            print(f"[voice_commands] Микрофон недоступен: {e}")
            return
        self.listening = True
        threading.Thread(target=self._listen, daemon=True).start()
        print("[voice_commands] Слушатель голосовых команд запущен")

    def stop_listening(self):
        self.listening = False

    def _listen(self):
        recognizer = sr.Recognizer()
        try:
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=1)
                while self.listening:
                    try:
                        audio = recognizer.listen(source, timeout=3, phrase_time_limit=3)
                        try:
                            raw_text = recognizer.recognize_google(audio, language="ru-RU").lower().strip()
                            if not raw_text:
                                continue
                                
                            print(f"[voice_commands] Распознано: {raw_text}")

                            # Фильтрация мата и шума
                            if any(stop_word in raw_text for stop_word in self.STOP_WORDS):
                                print("[voice_commands] Фраза проигнорирована (обнаружено стоп-слово)")
                                continue

                            # Обработка активационного слова
                            text = raw_text
                            if self.use_wake_word:
                                if raw_text.startswith(self.WAKE_WORD):
                                    text = raw_text[len(self.WAKE_WORD):].strip()
                                else:
                                    continue

                            # Поиск наиболее точного совпадения подстроки (защита от дубликатов)
                            matched_action = None
                            max_len = 0

                            # Проверка внутренних команд
                            for phrase, data in self.commands.items():
                                if phrase in text and len(phrase) > max_len:
                                    max_len = len(phrase)
                                    if data["type"] == "builtin":
                                        matched_action = lambda d=data: self._execute_builtin(d["value"])
                                    elif data["type"] == "script":
                                        script_name = data["value"]
                                        if script_name in self.parent.script_launcher.buttons:
                                            matched_action = lambda s=script_name: self.parent.script_launcher.run_script(s)

                            # Проверка внешних хоткеев из соседнего модуля
                            for phrase, combo in self.parent.hotkey_cmd.get_commands().items():
                                if phrase in text and len(phrase) > max_len:
                                    max_len = len(phrase)
                                    matched_action = lambda c=combo: self._safe_send_hotkey(c)

                            # Выполнение строго одной лучшей команды
                            if matched_action:
                                matched_action()

                        except sr.UnknownValueError:
                            pass
                        except sr.RequestError as e:
                            print(f"[voice_commands] Ошибка соединения с Google: {e}")
                        except Exception as e:
                            print(f"[voice_commands] Ошибка обработки текста: {e}")
                    except sr.WaitTimeoutError:
                        pass
                    except Exception as e:
                        print(f"[voice_commands] Ошибка при получении аудио: {e}")
        except Exception as e:
            print(f"[voice_commands] Критическая ошибка микрофона: {e}")
            self.listening = False

    def _safe_send_hotkey(self, combo):
        """Асинхронная отправка клавиш, исключающая фризы потока распознавания."""
        def run():
            try:
                send_hotkey(combo)
                print(f"[voice_commands] Отправлена комбинация: {combo} через keybd_event")
            except Exception as e:
                print(f"Ошибка отправки {combo}: {e}")
        threading.Thread(target=run, daemon=True).start()

    def _execute_builtin(self, action):
        if action == "Включить субтитры":
            self.parent.subtitles_var.set(True)
            self.parent.start_subtitles()
        elif action == "Выключить субтитры":
            self.parent.subtitles_var.set(False)
            self.parent.stop_subtitles()
        elif action == "Включить голосовой ввод":
            self.parent.voice_typing_var.set(True)
            self.parent.start_voice_typing()
        elif action == "Выключить голосовой ввод":
            self.parent.voice_typing_var.set(False)
            self.parent.stop_voice_typing()
        elif action == "Включить трекинг головы":
            self.parent.head_control_var.set(True)
            self.parent.start_head_tracking()
        elif action == "Выключить трекинг головы":
            self.parent.head_control_var.set(False)
            self.parent.stop_head_tracking()
        elif action == "Включить цветокоррекцию":
            self.parent.color_correction_var.set(True)
            self.parent.start_color_correction()
        elif action == "Выключить цветокоррекцию":
            self.parent.color_correction_var.set(False)
            self.parent.stop_color_correction()
        elif action == "Открыть профиль":
            self.parent.show_profile()
        elif action == "Выйти из аккаунта":
            self.parent.logout()
        elif action == "Открыть настройки программы":
            self.parent.open_program_settings()
        elif action == "Открыть настройки субтитров":
            self.parent.open_subtitle_settings()
        elif action == "Открыть настройки голосового ввода":
            self.parent.open_voice_settings()
        elif action == "Открыть настройки трекинга головы":
            self.parent.open_head_settings()
        elif action == "Открыть настройки цветокоррекции":
            self.parent.open_color_correction_settings()
        elif action == "Открыть боковое меню":
            self.parent.open_menu()
        elif action == "Закрыть боковое меню":
            self.parent.close_menu()
        elif action == "Открыть инструкцию":
            self.parent.open_instructions_window()
        elif action == "Управление голосовыми командами":
            self.show_settings_window()
        elif action == "Управление комбинациями клавиш":
            self.parent.hotkey_cmd.show_settings_window()
        elif action == "Управление кнопками запуска":
            self.parent.script_launcher.show_settings_window()

    def show_settings_window(self):
        win = tb.Toplevel(self.parent)
        win.title("Голосовые команды")
        win.geometry("550x650")
        win.resizable(False, False)
        win.transient(self.parent)
        win.grab_set()

        builtin_actions = [
            "Включить субтитры", "Выключить субтитры", "Включить голосовой ввод", "Выключить голосовой ввод",
            "Включить трекинг головы", "Выключить трекинг головы", "Включить цветокоррекцию", "Выключить цветокоррекцию",
            "Открыть профиль", "Выйти из аккаунта", "Открыть настройки программы", "Открыть настройки субтитров",
            "Открыть настройки голосового ввода", "Открыть настройки трекинга головы", "Открыть настройки цветокоррекции",
            "Открыть боковое меню", "Закрыть боковое меню", "Открыть инструкцию", "Управление голосовыми командами",
            "Управление комбинациями клавиш", "Управление кнопками запуска"
        ]

        frame = tb.Frame(win, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        # Панель параметров фильтрации (ОШИБКА ИСПРАВЛЕНА: padding удален из конструктора)
        settings_lf = tb.LabelFrame(frame, text=" Параметры фильтрации ")
        settings_lf.pack(fill=tk.X, pady=(0, 10), padx=5, ipady=5, ipadx=5)

        wake_var = tk.BooleanVar(value=self.use_wake_word)
        def toggle_wake(): self.use_wake_word = wake_var.get()
        wake_chk = tb.Checkbutton(settings_lf, text="Использовать активационное слово ('компьютер')", 
                                  variable=wake_var, command=toggle_wake)
        wake_chk.pack(anchor=tk.W, pady=5, padx=5)

        # Поле ввода фразы
        tb.Label(frame, text="Фраза для распознавания:").pack(anchor=tk.W, pady=(0,5))
        phrase_frame = tb.Frame(frame)
        phrase_frame.pack(fill=tk.X, pady=2)
        phrase_entry = tb.Entry(phrase_frame)
        phrase_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))

        def voice_input_phrase():
            def listen():
                recognizer = sr.Recognizer()
                with sr.Microphone() as source:
                    try:
                        recognizer.adjust_for_ambient_noise(source)
                        win.after(0, lambda: messagebox.showinfo("Голосовой ввод", "Говорите фразу...", parent=win))
                        audio = recognizer.listen(source, timeout=5, phrase_time_limit=5)
                        text = recognizer.recognize_google(audio, language="ru-RU").lower()
                        win.after(0, lambda: phrase_entry.delete(0, tk.END))
                        win.after(0, lambda: phrase_entry.insert(0, text))
                    except Exception as e:
                        win.after(0, lambda: messagebox.showerror("Ошибка", f"Не удалось распознать: {e}", parent=win))
            threading.Thread(target=listen, daemon=True).start()

        mic_btn = tb.Button(phrase_frame, text="🎤", width=3, command=voice_input_phrase)
        mic_btn.pack(side=tk.RIGHT)

        # Выбор действия
        tb.Label(frame, text="Выберите действие:").pack(anchor=tk.W, pady=(10,0))
        def get_actions():
            buttons = list(self.parent.script_launcher.buttons.keys())
            return builtin_actions + buttons

        action_combo = ttk.Combobox(frame, values=get_actions(), state="readonly")
        action_combo.pack(fill=tk.X, pady=5)

        # Список команд (Listbox с изоляцией ключей)
        listbox_keys = []
        listbox_frame = tb.Frame(frame)
        listbox_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        listbox = tk.Listbox(listbox_frame, font=("Courier New", 10))
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scroll = tb.Scrollbar(listbox_frame, orient=tk.VERTICAL, command=listbox.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.configure(yscrollcommand=scroll.set)

        def refresh():
            listbox.delete(0, tk.END)
            listbox_keys.clear()
            for phrase, data in self.commands.items():
                listbox_keys.append(phrase)
                if data["type"] == "builtin":
                    listbox.insert(tk.END, f"🗣 {phrase:<22} ➔  ⚙️ {data['value']}")
                else:
                    listbox.insert(tk.END, f"🗣 {phrase:<22} ➔  📜 [Сценарий] {data['value']}")

        def add():
            phrase = phrase_entry.get().strip().lower()
            action = action_combo.get()
            if not phrase or not action:
                messagebox.showwarning("Ошибка", "Заполните оба поля", parent=win)
                return
            if action in builtin_actions:
                self.commands[phrase] = {"type": "builtin", "value": action}
            else:
                self.commands[phrase] = {"type": "script", "value": action}
            self.parent.settings["voice_commands"] = self.commands
            self.parent.save_settings()
            refresh()
            phrase_entry.delete(0, tk.END)
            action_combo.set('')

        def delete():
            sel = listbox.curselection()
            if sel:
                index = sel[0]
                phrase = listbox_keys[index]
                if phrase in self.commands:
                    del self.commands[phrase]
                    self.parent.settings["voice_commands"] = self.commands
                    self.parent.save_settings()
                    refresh()
            else:
                messagebox.showwarning("Внимание", "Выберите команду для удаления", parent=win)

        btn_add = tb.Button(frame, text="Добавить команду", bootstyle="success", command=add)
        btn_add.pack(fill=tk.X, pady=3)

        btn_del = tb.Button(frame, text="Удалить выбранное", bootstyle="danger", command=delete)
        btn_del.pack(fill=tk.X, pady=3)

        refresh()
