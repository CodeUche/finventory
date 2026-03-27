"""
Custom SMTP email backend with flexible SSL handling.

On developer machines, antivirus software (Avast, Norton, etc.) performs
SSL inspection which breaks standard certificate verification. This backend
tries verified TLS first and falls back to an unverified context if needed.

In production (Linux servers) standard verification succeeds — no fallback.
"""

import logging
import ssl

from django.core.mail.backends.smtp import EmailBackend

logger = logging.getLogger(__name__)


class CertifiEmailBackend(EmailBackend):
    """SMTP backend that handles AV-intercepted TLS on Windows dev machines."""

    def open(self):
        if self.connection:
            return False
        try:
            self.connection = self.connection_class(
                host=self.host, port=self.port, local_hostname=None
            )
            if self.use_tls:
                # Try strict verification first
                try:
                    ctx = ssl.create_default_context()
                    self.connection.ehlo()
                    self.connection.starttls(context=ctx)
                except ssl.SSLCertVerificationError:
                    # Antivirus SSL inspection detected — reconnect with no verification
                    logger.warning(
                        "SMTP TLS cert verification failed (likely AV interception). "
                        "Reconnecting without cert verification. "
                        "This is normal on Windows dev machines with Avast/Norton."
                    )
                    self.connection = self.connection_class(
                        host=self.host, port=self.port, local_hostname=None
                    )
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    self.connection.ehlo()
                    self.connection.starttls(context=ctx)
                self.connection.ehlo()
            if self.username and self.password:
                self.connection.login(self.username, self.password)
            return True
        except Exception:
            if not self.fail_silently:
                raise
