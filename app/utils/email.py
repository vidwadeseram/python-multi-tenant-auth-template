import aiosmtplib

from app.config import get_settings


async def send_email(recipient: str, subject: str, body: str) -> None:
    settings = get_settings()
    message = (
        f"From: {settings.smtp_sender}\r\n"
        f"To: {recipient}\r\n"
        f"Subject: {subject}\r\n\r\n"
        f"{body}"
    )
    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        sender=settings.smtp_sender,
        recipients=[recipient],
    )
