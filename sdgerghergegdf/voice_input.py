import threading, queue, json, numpy as np, time, keyboard, pyaudio
from vosk import KaldiRecognizer

class VoiceInputEngine:
    def __init__(self, model, level_callback=None):
        self.model = model
        self.level_callback = level_callback
        self.audio_queue = queue.Queue()
        self.is_running = False
        self.is_paused = False
        self.recognizer = None
        self.audio_stream = None
        self.p = None
        self.current_device = None 

    def load_model(self):
        if not self.model: return False
        try:
            self.recognizer = KaldiRecognizer(self.model, 16000)
            return True
        except: return False

    def set_device(self, index):
        p = pyaudio.PyAudio()
        try:
            dev = p.get_device_info_by_index(index)
            self.current_device = (index, int(dev['maxInputChannels']), int(dev['defaultSampleRate']))
            return True
        except: return False
        finally: p.terminate()

    def get_input_devices(self):
        p = pyaudio.PyAudio(); devs = []
        for i in range(p.get_device_count()):
            d = p.get_device_info_by_index(i)
            if d.get('maxInputChannels', 0) > 0: devs.append((i, d.get('name')))
        p.terminate(); return devs

    def audio_callback(self, in_data, frame_count, time_info, status):
        if self.is_running: self.audio_queue.put(in_data)
        return (None, pyaudio.paContinue)

    def process_loop(self):
        idx, ch, rate = self.current_device
        while self.is_running:
            try:
                data = self.audio_queue.get(timeout=0.2)
                # Конвертация и уровень звука
                audio = np.frombuffer(data, dtype=np.int16)
                if self.level_callback:
                    rms = np.sqrt(np.mean(audio.astype(np.float32)**2))
                    self.level_callback(min(100, int(rms / 32768 * 500)))

                if self.is_paused or not self.recognizer: continue

                # Ресемплинг в 16к для Vosk
                if rate != 16000:
                    new_len = int(len(audio) * 16000 / rate)
                    audio = np.interp(np.linspace(0, len(audio)-1, new_len), np.arange(len(audio)), audio).astype(np.int16)
                
                if self.recognizer.AcceptWaveform(audio.tobytes()):
                    res = json.loads(self.recognizer.Result())
                    text = res.get("text", "")
                    if text:
                        keyboard.write(text + ' ')
            except: continue

    def start(self):
        self.load_model()
        self.is_running = True
        self.p = pyaudio.PyAudio()
        try:
            idx, ch, rate = self.current_device
            self.audio_stream = self.p.open(format=pyaudio.paInt16, channels=ch, rate=rate,
                                          input=True, input_device_index=idx, stream_callback=self.audio_callback)
            threading.Thread(target=self.process_loop, daemon=True).start()
            return True
        except: return False

    def stop(self):
        self.is_running = False
        if self.audio_stream: self.audio_stream.stop_stream(); self.audio_stream.close()
        if self.p: self.p.terminate()
        self.recognizer = None
