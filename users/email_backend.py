"""Email delivery through Brevo's HTTP API.

Django's SMTP backend cannot be used in production: the application runs on
Vercel, which blocks outbound SMTP from serverless functions. SMTP would work
on a developer machine and then fail silently once deployed, so mail goes out
over HTTPS instead.

httpx is used rather than a dedicated Brevo library because the whole
integration is one POST — see https://developers.brevo.com/reference/sendtransacemail
"""

from email.utils import parseaddr

import httpx
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

API_URL = "https://api.brevo.com/v3/smtp/email"

# Serverless request handlers are killed by the platform long before a socket
# would time out on its own, so the send gets an explicit deadline.
TIMEOUT_SECONDS = 15


class BrevoEmailBackend(BaseEmailBackend):
    """Send Django EmailMessages via Brevo's transactional endpoint."""

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        api_key = getattr(settings, "BREVO_API_KEY", "")
        if not api_key:
            # A missing key is a deployment mistake, not a per-message failure:
            # surface it rather than dropping verification mail on the floor.
            if not self.fail_silently:
                raise ValueError(
                    "BREVO_API_KEY is not set — cannot send email. "
                    "Set it in .env locally and in the Vercel environment."
                )
            return 0

        sent = 0
        headers = {"api-key": api_key, "content-type": "application/json"}

        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            for message in email_messages:
                try:
                    response = client.post(
                        API_URL, json=self._payload(message), headers=headers
                    )
                    response.raise_for_status()
                except Exception:
                    if not self.fail_silently:
                        raise
                else:
                    sent += 1
        return sent

    def _payload(self, message):
        """One Django message as Brevo's JSON body."""
        from_name, from_email = parseaddr(message.from_email or settings.DEFAULT_FROM_EMAIL)

        payload = {
            "sender": {"email": from_email},
            "to": [{"email": address} for address in message.to],
            "subject": message.subject,
            "textContent": message.body,
        }
        if from_name:
            payload["sender"]["name"] = from_name
        if message.cc:
            payload["cc"] = [{"email": address} for address in message.cc]
        if message.bcc:
            payload["bcc"] = [{"email": address} for address in message.bcc]
        if message.reply_to:
            _, reply_email = parseaddr(message.reply_to[0])
            payload["replyTo"] = {"email": reply_email}

        # EmailMultiAlternatives carries the HTML part; a plain EmailMessage
        # has no alternatives at all.
        for content, mimetype in getattr(message, "alternatives", []):
            if mimetype == "text/html":
                payload["htmlContent"] = content
                break

        return payload
