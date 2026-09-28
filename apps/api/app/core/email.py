import asyncio
import smtplib
from email.message import EmailMessage

from app.core.config import settings


class EmailDeliveryError(RuntimeError):
    pass


def _send_sync(recipient: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
            server.ehlo()
            if settings.SMTP_USE_STARTTLS:
                server.starttls()
                server.ehlo()
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.send_message(message)
    except Exception as exc:
        raise EmailDeliveryError("Email delivery failed") from exc


async def send_account_link(recipient: str, purpose: str, token: str) -> None:
    if purpose == "verify_email":
        subject = "Verify your Agent V account"
        url = f"{settings.FRONTEND_URL.rstrip('/')}/?verify_email={token}"
        action = "verify your email address"
        ttl = settings.AUTH_TOKEN_TTL_MINUTES
    elif purpose == "password_reset":
        subject = "Reset your Agent V password"
        url = f"{settings.FRONTEND_URL.rstrip('/')}/?reset_password={token}"
        action = "reset your password"
        ttl = settings.PASSWORD_RESET_TTL_MINUTES
    else:
        raise ValueError("Unsupported account email purpose")

    body = (
        f"Use this link to {action}:\n\n{url}\n\n"
        f"This link expires in {ttl} minutes and can only be used once. "
        "If you did not request this, you can ignore this email."
    )
    await asyncio.to_thread(_send_sync, recipient, subject, body)
