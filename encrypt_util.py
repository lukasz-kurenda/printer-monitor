# -*- coding: utf-8 -*-
import argparse
import getpass
import os
from cryptography.fernet import Fernet

KEY_FILE = 'secret.key'

def generate_key():
    """Generuje i zapisuje klucz szyfrujący do pliku."""
    if os.path.exists(KEY_FILE):
        print(f"Błąd: Plik klucza '{KEY_FILE}' już istnieje. Usuń go, jeśli chcesz wygenerować nowy.")
        return
    key = Fernet.generate_key()
    with open(KEY_FILE, 'wb') as key_file:
        key_file.write(key)
    print(f"Wygenerowano nowy klucz i zapisano w pliku: {KEY_FILE}")
    print("!!! WAŻNE: Traktuj ten plik jak hasło. Przechowuj go w bezpiecznym miejscu i nie udostępniaj nikomu.")

def encrypt_password():
    """Szyfruje hasło podane przez użytkownika przy użyciu istniejącego klucza."""
    try:
        with open(KEY_FILE, 'rb') as key_file:
            key = key_file.read()
    except FileNotFoundError:
        print(f"Błąd: Nie znaleziono pliku klucza '{KEY_FILE}'.")
        print("Najpierw wygeneruj klucz, używając polecenia: python encrypt_util.py --generate-key")
        return

    f = Fernet(key)
    
    # Użyj getpass, aby hasło nie było widoczne na ekranie
    password = getpass.getpass("Podaj hasło do zaszyfrowania: ")
    
    encrypted_password = f.encrypt(password.encode('utf-8'))
    
    print("\nTwoje zaszyfrowane hasło:")
    print("--------------------------------------------------")
    print(encrypted_password.decode('utf-8'))
    print("--------------------------------------------------")
    print("\nSkopiuj powyższy ciąg znaków i wklej go do pliku config.ini w miejsce dotychczasowego hasła.")

def main():
    parser = argparse.ArgumentParser(description="Narzędzie do szyfrowania hasła SMTP.")
    parser.add_argument('--generate-key', action='store_true', help='Generuje nowy klucz szyfrujący.')
    parser.add_argument('--encrypt', action='store_true', help='Szyfruje hasło przy użyciu istniejącego klucza.')
    args = parser.parse_args()

    if args.generate_key:
        generate_key()
    elif args.encrypt:
        encrypt_password()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()