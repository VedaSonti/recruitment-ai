from dotenv import load_dotenv
import os

from email_service import send_email

load_dotenv()

to_address = os.getenv("EMAIL_TEST_RECIPIENT", "").strip() or os.getenv("EMAIL_FROM", "").strip() or os.getenv("SMTP_USER", "").strip()
if not to_address:
    raise SystemExit("Set EMAIL_TEST_RECIPIENT, EMAIL_FROM, or SMTP_USER before sending a test email.")

if not send_email(
    to_address,
    "Talent iSOFT — email test",
    "<h2>Email works!</h2><p>Talent iSOFT SMTP is configured correctly.</p>",
):
    raise SystemExit("Email was not sent. Check the SMTP environment variables.")

print("Sent successfully — check the configured test inbox")
