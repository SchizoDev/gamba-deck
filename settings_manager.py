import os
import base64
from cryptography.fernet import Fernet

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), ".gamba_deck_settings")
KEY_FILE = os.path.join(os.path.dirname(__file__), ".gamba_deck_key")

def generate_key():
    key = Fernet.generate_key()
    with open(KEY_FILE, 'wb') as f:
        f.write(key)
    return key

def get_key():
    if not os.path.exists(KEY_FILE):
        return generate_key()
    with open(KEY_FILE, 'rb') as f:
        return f.read()

def save_api_key(api_key):
    key = get_key()
    f = Fernet(key)
    token = f.encrypt(api_key.encode())
    with open(SETTINGS_FILE, 'wb') as fset:
        fset.write(token)

def load_api_key():
    if not os.path.exists(SETTINGS_FILE):
        return ''
    key = get_key()
    f = Fernet(key)
    with open(SETTINGS_FILE, 'rb') as fset:
        token = fset.read()
    try:
        return f.decrypt(token).decode()
    except Exception:
        return ''
