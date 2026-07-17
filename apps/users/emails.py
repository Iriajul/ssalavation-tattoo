"""
Central place for outgoing email. Every sender in the project goes through
send_html_email so branding and failure handling stay consistent.

Emails are sent as multipart: an HTML part plus a plaintext fallback for clients
that block HTML. Sending never raises — a failed email must not break the
request that triggered it (an OTP response, a task action, etc.).
"""
import logging
import re

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def _html_to_text(html):
    """Readable plaintext fallback — strip_tags alone leaves ragged whitespace."""
    text = strip_tags(html)
    text = re.sub(r'[ \t]+', ' ', text)              # collapse runs of spaces
    text = '\n'.join(line.strip() for line in text.splitlines())
    text = re.sub(r'\n{3,}', '\n\n', text)           # cap consecutive blank lines
    return text.strip()


def send_html_email(subject, template, context, to, fail_silently=True):
    """
    Render `template` with `context` and send it to `to` (str or list).

    Returns True if the message was handed to the SMTP backend, else False.
    """
    recipients = [to] if isinstance(to, str) else list(to)
    recipients = [r for r in recipients if r]
    if not recipients:
        return False

    try:
        html_body = render_to_string(template, context)
        text_body = _html_to_text(html_body)

        message = EmailMultiAlternatives(
            subject     = subject,
            body        = text_body,
            from_email  = settings.DEFAULT_FROM_EMAIL,
            to          = recipients,
        )
        message.attach_alternative(html_body, "text/html")
        message.send(fail_silently=False)
        return True

    except Exception as exc:
        logger.exception("Email send failed (subject=%r, to=%s): %s", subject, recipients, exc)
        if not fail_silently:
            raise
        return False


def send_otp_email(email, otp, *, heading, intro, subject,
                   full_name=None, code_label="Verification code", expiry_minutes=10):
    """Branded OTP email — used for app login, app reset and admin reset."""
    return send_html_email(
        subject  = subject,
        template = "emails/otp.html",
        context  = {
            'otp':            otp,
            'heading':        heading,
            'intro':          intro,
            'full_name':      full_name,
            'code_label':     code_label,
            'expiry_minutes': expiry_minutes,
        },
        to = email,
    )
