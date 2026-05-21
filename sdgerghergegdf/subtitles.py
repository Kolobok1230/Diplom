import threading
import queue
import json
import time
import numpy as np
from vosk import KaldiRecognizer
import pyaudiowpatch as pyaudio

class SubtitlesEngine:
    def __init__(self, model, callback=None, level_callback=None):
        self.model = model
        self.callback = callback
        self.level_callback = level_callback
        self.audio_queue = queue.Queue()
        self.is_running = False
        self.recognizer = None
        self.audio_stream = None
        self.p = None
        self.current_device = None
        self.thread = None
        self.last_text = ""

    def load_model(self):
        try:
            self.recognizer = KaldiRecognizer(self.model, 16000)
            self.recognizer.SetWords(True)
            return True
        except Exception as e:
            print(f"[Subtitles] Ошибка загрузки модели Vosk: {e}")
            return False

    def set_device(self, device_index):
        self.current_device = None
        p = pyaudio.PyAudio()
        try:
            dev = p.get_device_info_by_index(device_index)
            if dev['maxInputChannels'] > 0:
                sample_rate = int(dev['defaultSampleRate'])
                self.current_device = (device_index,
                                       dev['maxInputChannels'],
                                       sample_rate)
        except Exception as e:
            print(f"[Subtitles] Ошибка установки устройства: {e}")
        finally:
            p.terminate()
        return self.current_device is not None

    def audio_callback(self, in_data, frame_count, time_info, status):
        if self.is_running:
            self.audio_queue.put(in_data)
        return (None, pyaudio.paContinue)

    def convert_to_mono_16k(self, audio_bytes, input_channels, input_rate):
        audio = np.frombuffer(audio_bytes, dtype=np.int16)
        if self.level_callback:
            rms = np.sqrt(np.mean(audio.astype(np.float32)**2))
            level = min(100, int(rms / 32768 * 100))
            self.level_callback(level)
        if input_channels > 1:
            audio = audio.reshape(-1, input_channels).mean(axis=1).astype(np.int16)
        if input_rate != 16000:
            old_len = len(audio)
            new_len = int(old_len * 16000 / input_rate)
            indices = np.linspace(0, old_len - 1, new_len)
            audio = np.interp(indices, np.arange(old_len), audio).astype(np.int16)
        return audio.tobytes()

    def process_loop(self):
        # Храним список последних завершенных фраз (например, последние 3)
        history = []
        max_history_lines = 3
        
        # ТОЧНОЕ ВОССТАНОВЛЕНИЕ ТВОИХ ОРИГИНАЛЬНЫХ ИНДЕКСОВ
        channels, rate = self.current_device[1], self.current_device[2]
        
        # Переменная для очистки экрана после долгого молчания
        last_speech_time = time.time()
        
        # Переменные для фиксации прошлых состояний (Фикс KAN-14 от наложений текста)
        last_sent_display = ""
        part_text = ""
        
        while self.is_running:
            try:
                data = self.audio_queue.get(timeout=0.5)
                converted = self.convert_to_mono_16k(data, channels, rate)
                
                if self.recognizer.AcceptWaveform(converted):
                    # ФИНАЛЬНЫЙ РЕЗУЛЬТАТ (фраза закончена)
                    res = json.loads(self.recognizer.Result())
                    text = res.get("text", "").strip()
                    
                    if text:
                        # Добавляем в историю и держим её в пределах 3 строк
                        history.append(text)
                        if len(history) > max_history_lines:
                            history.pop(0)
                        
                        full_display = "\n".join(history)
                        
                        # Фикс KAN-14: Передаем в callback только если текст РЕАЛЬНО изменился
                        if full_display != last_sent_display and self.callback:
                            self.callback(full_display, False)
                            last_sent_display = full_display
                            
                        last_speech_time = time.time()
                else:
                    # ПРОМЕЖУТОЧНЫЙ РЕЗУЛЬТАТ (черновик фразы)
                    partial = json.loads(self.recognizer.PartialResult())
                    part_text = partial.get("partial", "").strip()
                    
                    if part_text:
                        # Показываем историю + текущий "черновик" внизу
                        current_display = "\n".join(history + [part_text])
                        
                        # Фикс KAN-14: Защита от лишнего флуда перерисовки UI
                        if current_display != last_sent_display and self.callback:
                            self.callback(current_display, True)
                            last_sent_display = current_display
                            
                        last_speech_time = time.time()
                
                # АВТО-ОЧИСТКА: если молчим больше 5 секунд, очищаем экран
                if time.time() - last_speech_time > 5.0 and (history or part_text):
                    history = []
                    part_text = ""
                    last_sent_display = ""
                    if self.callback:
                        self.callback("", False)

            except queue.Empty:
                # Даже если данных нет, проверяем таймер очистки
                if time.time() - last_speech_time > 5.0 and history:
                    history = []
                    last_sent_display = ""
                    if self.callback: 
                        self.callback("", False)
                continue
            except Exception as e:
                print(f"Subtitles error: {e}")

    def start(self):
        if self.is_running or self.audio_stream:
            return True
            
        if not self.recognizer and not self.load_model():
            return False
        if not self.current_device:
            return False
            
        self.is_running = True
        self.p = pyaudio.PyAudio()
        try:
            dev_idx, channels, rate = self.current_device[0], self.current_device[1], self.current_device[2]
            self.audio_stream = self.p.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=dev_idx,
                frames_per_buffer=1024,
                stream_callback=self.audio_callback
            )
            self.audio_stream.start_stream()
            
            # Перед стартом полностью очищаем очередь от старого мусора в памяти
            with self.audio_queue.mutex:
                self.audio_queue.queue.clear()
                
            self.thread = threading.Thread(target=self.process_loop, daemon=True)
            self.thread.start()
            return True
        except Exception as e:
            self.stop()
            return False

    def stop(self):
        self.is_running = False
        
        if self.audio_stream:
            try:
                self.audio_stream.stop_stream()
                self.audio_stream.close()
            except:
                pass
            self.audio_stream = None
            
        if self.p:
            try:
                self.p.terminate()
            except:
                pass
            self.p = None
            
        # Защита KAN-3: Ожидаем физического закрытия потока, чтобы не ловить Race Condition
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=0.2)
            
        self.thread = None
        self.last_text = ""
        
        # Полностью очищаем буфер аудио-очереди
        with self.audio_queue.mutex:
            self.audio_queue.queue.clear()

    def get_loopback_devices(self):
        p = pyaudio.PyAudio()
        devices = []
        for i in range(p.get_device_count()):
            dev = p.get_device_info_by_index(i)
            if dev['maxInputChannels'] > 0 and 'loopback' in dev['name'].lower():
                devices.append((i, dev['name']))
        p.terminate()
        return devices
