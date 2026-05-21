import threading
import speech_recognition as sr
import tkinter as tk
from tkinter import ttk, messagebox
import ttkbootstrap as tb

class HotkeyCommandsManager:
    def __init__(self, parent):
        self.parent = parent
        self.commands = parent.settings.get("hotkey_commands", {})
        self._recording = False
        self._virtual_keys = []

    def get_commands(self):
        return self.commands

    def record_combination(self, entry_widget, parent_win):
        if self._recording:
            return
        self._recording = True
        entry_widget.config(state="normal")
        entry_widget.delete(0, tk.END)
        entry_widget.insert(0, "Используйте виртуальную клавиатуру...")
        entry_widget.config(state="readonly")
        self._start_virtual_keyboard(entry_widget, parent_win)

    def _start_virtual_keyboard(self, entry_widget, parent_win):
        self._virtual_keys = []
        kb_win = tb.Toplevel(parent_win)
        kb_win.title("Виртуальная клавиатура")
        kb_win.geometry("1000x500")
        kb_win.resizable(False, False)
        kb_win.transient(parent_win)
        kb_win.grab_set()

        def on_close():
            self._recording = False
            kb_win.destroy()
        kb_win.protocol("WM_DELETE_WINDOW", on_close)

        display_var = tk.StringVar(value="")
        display_entry = tb.Entry(kb_win, textvariable=display_var, state="readonly", font=("Segoe UI", 12))
        display_entry.pack(pady=10, padx=10, fill=tk.X)

        main_frame = tb.Frame(kb_win)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        rows = [
            ['F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12'],
            ['`', '1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-', '=', 'Backspace'],
            ['Tab', 'q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p', '[', ']', '\\'],
            ['Caps', 'a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', ';', "'", 'Enter'],
            ['Shift', 'z', 'x', 'c', 'v', 'b', 'n', 'm', ',', '.', '/', 'Shift'],
            ['Ctrl', 'Win', 'Alt', 'Space', 'Alt', 'Win', 'Ctrl'],
            ['Up', 'Down', 'Left', 'Right', 'Home', 'End', 'PageUp', 'PageDown', 'Insert', 'Delete']
        ]

        key_map = {
            'Space': 'space', 'Enter': 'enter', 'Tab': 'tab', 'Backspace': 'backspace',
            'Caps': 'caps lock', 'Shift': 'shift', 'Ctrl': 'ctrl', 'Alt': 'alt', 'Win': 'win',
            'Up': 'up', 'Down': 'down', 'Left': 'left', 'Right': 'right',
            'Home': 'home', 'End': 'end', 'PageUp': 'page up', 'PageDown': 'page down',
            'Insert': 'insert', 'Delete': 'delete'
        }
        for i in range(1, 13):
            key_map[f'F{i}'] = f'f{i}'

        def add_key(key):
            normalized = key_map.get(key, key.lower())
            self._virtual_keys.append(normalized)
            display_var.set('+'.join(self._virtual_keys))

        def clear_keys():
            self._virtual_keys.clear()
            display_var.set('')

        def confirm():
            if not self._virtual_keys:
                messagebox.showwarning("Ошибка", "Не выбрана ни одна клавиша", parent=kb_win)
                return
            combo = '+'.join(self._virtual_keys)
            self._recording = False
            entry_widget.config(state="normal")
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, combo)
            entry_widget.config(state="readonly")
            kb_win.destroy()

        def cancel():
            self._recording = False
            kb_win.destroy()

        for r_idx, row in enumerate(rows):
            row_frame = tb.Frame(main_frame)
            row_frame.pack(pady=2, fill=tk.X)
            cols = len(row)
            for c_idx, key in enumerate(row):
                width = 6
                if key in ['Backspace', 'Enter', 'Shift', 'Caps']:
                    width = 8
                elif key == 'Space':
                    width = 30
                btn = tb.Button(row_frame, text=key, width=width, command=lambda k=key: add_key(k))
                btn.grid(row=0, column=c_idx, padx=1, sticky='ew')
            for c_idx in range(cols):
                row_frame.columnconfigure(c_idx, weight=1)

        ctrl_frame = tb.Frame(main_frame)
        ctrl_frame.pack(pady=10)
        tb.Button(ctrl_frame, text="Очистить", bootstyle="warning", command=clear_keys).pack(side=tk.LEFT, padx=5)
        tb.Button(ctrl_frame, text="Подтвердить", bootstyle="success", command=confirm).pack(side=tk.LEFT, padx=5)
        tb.Button(ctrl_frame, text="Отмена", bootstyle="secondary", command=cancel).pack(side=tk.LEFT, padx=5)

    def show_settings_window(self):
        win = tb.Toplevel(self.parent)
        win.title("Голосовые комбинации клавиш")
        win.geometry("600x550")
        win.resizable(False, False)
        win.transient(self.parent)
        win.grab_set()

        frame = tb.Frame(win, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        # Поле ввода голосовой фразы
        tb.Label(frame, text="Фраза для активации:").pack(anchor=tk.W, pady=(0,5))
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

        # Поле ввода комбинации клавиш
        tb.Label(frame, text="Комбинация клавиш:").pack(anchor=tk.W, pady=(10,0))
        hotkey_frame = tb.Frame(frame)
        hotkey_frame.pack(fill=tk.X, pady=2)
        hotkey_entry = tb.Entry(hotkey_frame, state="readonly")
        hotkey_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        
        btn_virtual = tb.Button(hotkey_frame, text="⌨️ Вирт. клав.", bootstyle="outline-secondary", 
                                command=lambda: self.record_combination(hotkey_entry, win))
        btn_virtual.pack(side=tk.LEFT, padx=2)

        # Контейнер для списка команд
        listbox_keys = []
        list_frame = tb.Frame(frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        listbox = tk.Listbox(list_frame, font=("Courier New", 10))
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scroll = tb.Scrollbar(list_frame, orient=tk.VERTICAL, command=listbox.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.configure(yscrollcommand=scroll.set)

        def refresh():
            listbox.delete(0, tk.END)
            listbox_keys.clear()
            for phrase, combo in self.commands.items():
                listbox_keys.append(phrase)
                listbox.insert(tk.END, f"🗣 {phrase:<22} ➔  ⌨️ {combo}")

        def add():
            phrase = phrase_entry.get().strip().lower()
            combo = hotkey_entry.get()
            if not phrase or not combo or combo == "Используйте виртуальную клавиатуру...":
                messagebox.showwarning("Ошибка", "Заполните фразу и комбинацию", parent=win)
                return
            
            self.commands[phrase] = combo
            self.parent.settings["hotkey_commands"] = self.commands
            self.parent.save_settings()
            refresh()
            
            phrase_entry.delete(0, tk.END)
            hotkey_entry.config(state="normal")
            hotkey_entry.delete(0, tk.END)
            hotkey_entry.config(state="readonly")

        def delete():
            sel = listbox.curselection()
            if sel:
                index = sel[0]
                phrase = listbox_keys[index]
                if phrase in self.commands:
                    del self.commands[phrase]
                    self.parent.settings["hotkey_commands"] = self.commands
                    self.parent.save_settings()
                    refresh()
            else:
                messagebox.showwarning("Внимание", "Выберите комбинацию для удаления", parent=win)

        btn_add = tb.Button(frame, text="Добавить комбинацию", bootstyle="success", command=add)
        btn_add.pack(fill=tk.X, pady=3)

        btn_del = tb.Button(frame, text="Удалить выбранное", bootstyle="danger", command=delete)
        btn_del.pack(fill=tk.X, pady=3)

        refresh()
