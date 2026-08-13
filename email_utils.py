# -*- coding: utf-8 -*-
"""SMTP e-mail notifications (Fernet-encrypted password)."""

import logging
import os
import smtplib
import socket
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from cryptography.fernet import Fernet

from reports import PANDAS_AVAILABLE

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def send_email_notification(subject, html_body, config, recipient_key, attachment_path=None, priority=None):
    logging.info(f"Attempting to send e-mail notification (key: {recipient_key}, priority: {priority})")
    smtp_config = config['SMTP']
    sender_email = smtp_config.get('sender_email')
    receiver_emails_str = config['EMAILS'].get(recipient_key)

    if not receiver_emails_str:
        logging.warning(f"No recipients for key '{recipient_key}'. E-mail will not be sent.")
        return False

    receiver_emails = [email.strip() for email in receiver_emails_str.split(',')]
    logging.info(f"Recipients: {', '.join(receiver_emails)}")

    message = MIMEMultipart("alternative")
    message["From"] = sender_email
    message["To"] = ", ".join(receiver_emails)
    message["Subject"] = subject

    if priority == 'high':
        message['X-Priority'] = '1 (Highest)'
        message['X-MSMail-Priority'] = 'High'
        message['Importance'] = 'High'

    message.attach(MIMEText(html_body, 'html', 'utf-8'))

    if attachment_path and PANDAS_AVAILABLE:
        try:
            with open(attachment_path, "rb") as attachment:
                part = MIMEApplication(attachment.read(), Name=os.path.basename(attachment_path))
            part['Content-Disposition'] = f'attachment; filename="{os.path.basename(attachment_path)}"'
            message.attach(part)
            logging.info(f"Attached file: {attachment_path}")
        except Exception as e:
            logging.error(f"Failed to attach file: {e}")
            return False

    try:
        # Read the key from the file
        with open(os.path.join(BASE_DIR, 'secret.key'), 'rb') as key_file:
            key = key_file.read()

        f = Fernet(key)

        # Read the encrypted password from config.ini
        encrypted_password = smtp_config.get('password')
        if not encrypted_password:
            raise ValueError("No password in the configuration file.")

        # Decrypt the password
        decrypted_password = f.decrypt(encrypted_password.encode('utf-8')).decode('utf-8')

    except FileNotFoundError:
        logging.critical("CRITICAL ERROR: key file 'secret.key' not found! Cannot send e-mail.")
        return False
    except Exception as e:
        logging.critical("CRITICAL ERROR: failed to decrypt the password. Error: %s. "
                         "Check the key and password in config.ini.", e)
        return False

    try:
        server_address = smtp_config.get('server')
        port = int(smtp_config.get('port'))
        logging.info(f"Connecting to SMTP server: {server_address}:{port}")

        server = smtplib.SMTP(server_address, port, timeout=15)

        if smtp_config.getboolean('use_tls', fallback=False):
            server.starttls()

        if smtp_config.get('user') and decrypted_password:
            server.login(smtp_config.get('user'), decrypted_password)

        server.send_message(message)
        server.quit()
        logging.info(f"E-mail '{subject}' sent successfully.")
        return True
    except socket.timeout:
        logging.error("Timeout while connecting to the SMTP server.")
    except Exception as e:
        logging.error(f"Error while sending e-mail: {e}", exc_info=True)
    return False
