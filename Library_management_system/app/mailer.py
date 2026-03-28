import os
import smtplib
from email.message import EmailMessage


def send_verification_email(recipient_email: str, token: str) -> None:
    smtp_host = os.getenv("SMTP_HOST")
    if not smtp_host:
        raise ValueError("SMTP_HOST is not configured")

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    sender_email = os.getenv("SMTP_FROM", smtp_user or "no-reply@lms.local")

    verify_url_base = os.getenv(
        "VERIFY_URL_BASE",
        "http://localhost:8000/auth/verify-email",
    )
    verification_link = f"{verify_url_base}?token={token}"

    message = EmailMessage()
    message["Subject"] = "Verify your LMS account"
    message["From"] = sender_email
    message["To"] = recipient_email
    message.set_content(
        "Welcome to LMS.\n\n"
        "Use the token below to verify your account:\n"
        f"{token}\n\n"
        "Or click this verification link:\n"
        f"{verification_link}\n"
    )


    with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
        server.ehlo()
        if smtp_use_tls:
            server.starttls()
            server.ehlo()

        if smtp_user and smtp_password:
            server.login(smtp_user, smtp_password)

        server.send_message(message)



def send_password_reset_email(recipient_email: str, token: str) -> None:
    smtp_host = os.getenv("SMTP_HOST")
    if not smtp_host:
        raise ValueError("SMTP_HOST is not configured")

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    sender_email = os.getenv("SMTP_FROM", smtp_user or "no-reply@lms.local")

    reset_url_base = os.getenv(
        "PASSWORD_RESET_URL_BASE",
        "http://localhost:8000/auth/reset-password",
    )
    reset_link = f"{reset_url_base}?token={token}"

    message = EmailMessage()
    message["Subject"] = "Reset your LMS password"
    message["From"] = sender_email
    message["To"] = recipient_email
    message.set_content(
        "We received a password reset request for your LMS account.\n\n"
        "Use the token below to reset your password:\n"
        f"{token}\n\n"
        "Or click this reset link:\n"
        f"{reset_link}\n"
        "If you did not request this, you can ignore this email.\n"
    )

    with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
        server.ehlo()
        if smtp_use_tls:
            server.starttls()
            server.ehlo()

        if smtp_user and smtp_password:
            server.login(smtp_user, smtp_password)

        server.send_message(message)


def send_notification_email(recipient_email: str, subject: str, message_body: str) -> None:
    smtp_host = os.getenv("SMTP_HOST")
    if not smtp_host:
        raise ValueError("SMTP_HOST is not configured")

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    sender_email = os.getenv("SMTP_FROM", smtp_user or "no-reply@lms.local")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender_email
    message["To"] = recipient_email
    message.set_content(message_body)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
        server.ehlo()
        if smtp_use_tls:
            server.starttls()
            server.ehlo()

        if smtp_user and smtp_password:
            server.login(smtp_user, smtp_password)

        server.send_message(message)
