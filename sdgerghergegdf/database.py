import os
import json
import random
import string
import hashlib
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

def hash_password(password: str) -> str:
    """Возвращает хеш пароля (SHA-256). Соль не используется."""
    return hashlib.sha256(password.encode()).hexdigest()


class Database:
    def __init__(self, dbname="Assistant", user="postgres", password=None, host="localhost", port=5432):
        self.conn_params = {
            "dbname": dbname,
            "user": user,
            "password": str(password) if password is not None else os.environ.get("DB_PASSWORD", ""),
            "host": host,
            "port": port
        }
        self.connection = None
        self._temp_codes = {}

    def connect(self):
        if self.connection is None or self.connection.closed:
            self.connection = psycopg2.connect(**self.conn_params)
        return self.connection

    def close(self):
        if self.connection and not self.connection.closed:
            self.connection.close()
            self.connection = None

    def authenticate(self, identifier, password):
        """Проверяет пару логин/пароль. Пароль хешируется и сравнивается с БД."""
        conn = self.connect()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        hashed_input = hash_password(password)
        cur.execute("""
            SELECT a.id, a."NickName", a.email, a.token, s.config as settings
            FROM accounts a
            LEFT JOIN "Settings" s ON a.id = s.id_account
            WHERE (a.email = %s OR a."NickName" = %s) AND a.password = %s
        """, (identifier, identifier, hashed_input))
        user = cur.fetchone()
        cur.close()
        if user and not user.get('settings'):
            default_settings = self.get_default_settings_json()
            self.update_user_settings(user['id'], default_settings)
            user['settings'] = default_settings
        return user

    def user_exists(self, nickname, email):
        conn = self.connect()
        cur = conn.cursor()
        cur.execute("""SELECT 1 FROM accounts WHERE "NickName" = %s OR email = %s""", (nickname, email))
        exists = cur.fetchone() is not None
        cur.close()
        return exists

    def generate_token(self, length=25):
        symbols = string.ascii_letters + string.digits
        return ''.join(random.choice(symbols) for _ in range(length))

    def update_user_token(self, user_id, token):
        conn = self.connect()
        cur = conn.cursor()
        try:
            cur.execute("UPDATE accounts SET token = %s WHERE id = %s", (token, user_id))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            print(f"Ошибка обновления токена: {e}")
            return False
        finally:
            cur.close()

    def get_user_by_token(self, token):
        conn = self.connect()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT a.id, a."NickName", a.email, s.config as settings
            FROM accounts a
            LEFT JOIN "Settings" s ON a.id = s.id_account
            WHERE a.token = %s
        """, (token,))
        user = cur.fetchone()
        cur.close()
        if user and not user.get('settings'):
            default_settings = self.get_default_settings_json()
            self.update_user_settings(user['id'], default_settings)
            user['settings'] = default_settings
        return user

    def get_default_settings_json(self):
        default = {
            "app": {"theme": "darkly"},
            "subtitles": {"alpha": 0.8, "font_family": "Segoe UI", "font_size": 14, "device_index": None},
            "voice_input": {"device_index": 0},
            "head_tracking": {
                "camera_index": 1, "sensitivity_x": 10.0, "sensitivity_y": 12.0,
                "invert_x": True, "swap_eyes": True, "precision_interval_ms": 100,
                "reset_blinks": 2, "reset_time": 2.0
            },
            "color_correction": {"type": "deuteranomaly", "intensity": 0.7, "gain": 0.7}
        }
        return json.dumps(default, ensure_ascii=False)

    def update_user_settings(self, user_id, settings_json):
        conn = self.connect()
        cur = conn.cursor()
        try:
            cur.execute('SELECT 1 FROM "Settings" WHERE id_account = %s', (user_id,))
            exists = cur.fetchone()
            if exists:
                cur.execute('UPDATE "Settings" SET config = %s WHERE id_account = %s', (settings_json, user_id))
            else:
                cur.execute('INSERT INTO "Settings" (id_account, config) VALUES (%s, %s)', (user_id, settings_json))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            print(f"Ошибка обновления настроек: {e}")
            return False
        finally:
            cur.close()

    def register_user(self, nickname, email, password):
        """Регистрирует нового пользователя. Пароль хешируется."""
        if self.user_exists(nickname, email):
            return None
        token = self.generate_token()
        default_settings = self.get_default_settings_json()
        hashed_pwd = hash_password(password)
        conn = self.connect()
        cur = conn.cursor()
        try:
            cur.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM accounts")
            next_id = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO accounts (id, "NickName", email, password, token)
                VALUES (%s, %s, %s, %s, %s)
            """, (next_id, nickname, email, hashed_pwd, token))
            cur.execute("""
                INSERT INTO "Settings" (id_account, config)
                VALUES (%s, %s)
            """, (next_id, default_settings))
            conn.commit()
            return next_id
        except Exception as e:
            conn.rollback()
            print(f"Ошибка регистрации: {e}")
            return None
        finally:
            cur.close()

    # ----- Верификация email (заглушка) -----
    def generate_verification_code(self, length=6):
        return ''.join(random.choices(string.digits, k=length))

    def store_verification_code(self, email, code):
        self._temp_codes[email] = code

    def send_verification_email(self, email, code):
        print(f"[ТЕСТ] Код подтверждения для {email}: {code}")
        return True

    def verify_user_email(self, email, code):
        expected = self._temp_codes.get(email)
        if expected and expected == code:
            del self._temp_codes[email]
            return True
        return False