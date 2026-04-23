"""SMTP email delivery — HTML body with PDF attachment."""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
import structlog
from config.settings import settings

logger = structlog.get_logger()


def send_report_email(
    to_emails: list[str],
    cc_emails: list[str],
    subject: str,
    html_content: str,
    pdf_path: str | None,
    run_date: str,
    org_short: str = "MediaIntel",
    dry_run: bool = False,
    bcc_emails: list[str] | None = None,
) -> None:
    """Send the daily intelligence briefing via SMTP.

    Raises RuntimeError if dry_run=True to prevent accidental delivery.
    Callers should check dry_run before calling this function; this guard
    is a last-resort safety net.
    """
    if dry_run:
        raise RuntimeError("send_report_email called with dry_run=True — email delivery is disabled")
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = f"{org_short} Media Intelligence <{settings.smtp_user}>"
    msg["To"] = ", ".join(to_emails)
    if cc_emails:
        msg["Cc"] = ", ".join(cc_emails)
    bcc_emails = bcc_emails or []

    # Attach HTML body
    alternative = MIMEMultipart("alternative")
    html_part = MIMEText(html_content, "html", "utf-8")
    alternative.attach(html_part)
    msg.attach(alternative)

    # Attach PDF if available
    if pdf_path and Path(pdf_path).exists():
        with open(pdf_path, "rb") as f:
            pdf_data = f.read()
        attachment = MIMEBase("application", "pdf")
        attachment.set_payload(pdf_data)
        encoders.encode_base64(attachment)
        attachment.add_header(
            "Content-Disposition",
            "attachment",
            filename=f"{org_short}_Briefing_{run_date}.pdf",
        )
        msg.attach(attachment)

    all_recipients = to_emails + cc_emails + bcc_emails

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.sendmail(settings.smtp_user, all_recipients, msg.as_string())

    logger.info("email_sent", to=to_emails, cc=cc_emails, bcc=bcc_emails, subject=subject)
