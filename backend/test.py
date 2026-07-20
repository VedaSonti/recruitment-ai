import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import os

load_dotenv()

SMTP_USER     = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
TO            = SMTP_USER   # send to yourself

msg = MIMEMultipart("alternative")
msg["Subject"] = "iSOFT Recruitment — email test"
msg["From"]    = f"iSOFT Recruitment <{SMTP_USER}>"
msg["To"]      = TO
msg.attach(MIMEText(
    "<h2>Email works!</h2><p>Gmail SMTP is configured correctly.</p>",
    "html"
))

with smtplib.SMTP("smtp.gmail.com", 587) as server:
    server.ehlo()
    server.starttls()
    server.login(SMTP_USER, SMTP_PASSWORD)
    server.sendmail(SMTP_USER, TO, msg.as_string())

print("Sent successfully — check your inbox")