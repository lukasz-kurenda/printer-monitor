# -*- coding: utf-8 -*-
import argparse
import getpass
import os
from cryptography.fernet import Fernet

KEY_FILE = 'secret.key'

def generate_key():
    """Generate and save an encryption key to a file."""
    if os.path.exists(KEY_FILE):
        print(f"Error: key file '{KEY_FILE}' already exists. Remove it to generate a new one.")
        return
    key = Fernet.generate_key()
    with open(KEY_FILE, 'wb') as key_file:
        key_file.write(key)
    print(f"New key generated and saved to: {KEY_FILE}")
    print("!!! IMPORTANT: treat this file like a password. Store it securely and do not share it with anyone.")

def encrypt_password():
    """Encrypt a password provided by the user using an existing key."""
    try:
        with open(KEY_FILE, 'rb') as key_file:
            key = key_file.read()
    except FileNotFoundError:
        print(f"Error: key file '{KEY_FILE}' not found.")
        print("First generate a key using: python encrypt_util.py --generate-key")
        return

    f = Fernet(key)
    
    # Use getpass so the password is not visible on screen
    password = getpass.getpass("Enter the password to encrypt: ")
    
    encrypted_password = f.encrypt(password.encode('utf-8'))
    
    print("\nYour encrypted password:")
    print("--------------------------------------------------")
    print(encrypted_password.decode('utf-8'))
    print("--------------------------------------------------")
    print("\nCopy the string above and paste it into config.ini as the current password.")

def main():
    parser = argparse.ArgumentParser(description="SMTP password encryption tool.")
    parser.add_argument('--generate-key', action='store_true', help='Generates a new encryption key.')
    parser.add_argument('--encrypt', action='store_true', help='Encrypts a password using the existing key.')
    args = parser.parse_args()

    if args.generate_key:
        generate_key()
    elif args.encrypt:
        encrypt_password()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()