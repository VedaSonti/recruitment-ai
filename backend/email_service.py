"""Environment-configured SMTP delivery for Talent iSOFT."""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Protocol


class EmailService(Protocol):
    def send_html(self, to_address: str, subject: str, html_body: str) -> bool: ...


class SMTPEmailService:
    def __init__(self) -> None:
        self.host = os.getenv("SMTP_HOST", "").strip()
        self.port = int(os.getenv("SMTP_PORT", "0"))
        self.username = os.getenv("SMTP_USER", "").strip()
        self.password = os.getenv("SMTP_PASSWORD", "")
        self.from_address = os.getenv("EMAIL_FROM", "").strip() or self.username
        self.from_name = os.getenv("EMAIL_FROM_NAME", "Talent iSOFT").strip() or "Talent iSOFT"

    def send_html(self, to_address: str, subject: str, html_body: str) -> bool:
        if not self.host or not self.port or not self.username or not self.password:
            print("[email] SMTP configuration is incomplete")
            return False

        try:
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = f"{self.from_name} <{self.from_address}>"
            message["To"] = to_address
            message.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP(self.host, self.port) as server:
                server.ehlo()
                server.starttls()
                server.login(self.username, self.password)
                server.sendmail(self.from_address, to_address, message.as_string())
            return True
        except Exception as exc:
            print(f"[email] SMTP delivery failed ({type(exc).__name__})")
            return False


def get_email_service() -> EmailService:
    return SMTPEmailService()


def send_email(to_address: str, subject: str, html_body: str) -> bool:
    """Stable application interface; a future provider only replaces the factory."""
    return get_email_service().send_html(to_address, subject, html_body)
