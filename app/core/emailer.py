import logging
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def send_otp_email(email: str, otp: str, subject: str, intro: str) -> None:
    settings = get_settings()
    sender = settings.smtp_from_email or settings.smtp_username

    if not sender:
        logger.warning("SMTP sender missing; OTP for %s is %s", email, otp)
        return

    if not settings.smtp_host:
        logger.warning("SMTP host missing; OTP for %s is %s", email, otp)
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = email
    msg.set_content(
        f"{intro}\n\n"
        f"Your OTP is: {otp}\n"
        f"This code expires in {settings.otp_expire_minutes} minutes.\n"
        "If you did not request this, you can ignore this email."
    )

    if settings.smtp_port == 465:
        # Port 465 expects implicit SSL/TLS.
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            if settings.smtp_username and settings.smtp_password:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)
    else:
        # Port 587 typically uses explicit STARTTLS.
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            if settings.smtp_use_tls:
                server.starttls()
            if settings.smtp_username and settings.smtp_password:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)
