import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

# Load the key from your .env file
try:
    key = os.getenv("SECRET_KEY").encode()
    cipher_suite = Fernet(key)
except Exception as e:
    print("FATAL ERROR: No SECRET_KEY found in .env file. Please generate one.")
    cipher_suite = None

def encrypt_data(data: str) -> bytes:
    """Encrypts a string and returns bytes."""
    if cipher_suite is None:
        raise ValueError("Encryption is not configured. Missing SECRET_KEY.")
    
    return cipher_suite.encrypt(data.encode('utf-8'))

def decrypt_data(data: bytes) -> str:
    """Decrypts bytes and returns a string."""
    if cipher_suite is None:
        raise ValueError("Encryption is not configured. Missing SECRET_KEY.")
    
    return cipher_suite.decrypt(data).decode('utf-8')