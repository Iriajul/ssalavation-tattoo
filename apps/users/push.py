"""
Firebase Cloud Messaging (FCM) push helper.

Sends push notifications to a user's registered device tokens. Designed to be
safe: if firebase-admin isn't installed or FIREBASE_CREDENTIALS_PATH isn't set,
every call is a silent no-op — in-app notifications keep working regardless.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_app   = None
_tried = False


def _get_app():
    """Lazily initialize the Firebase app once. Returns None if unavailable."""
    global _app, _tried
    if _tried:
        return _app
    _tried = True

    path = getattr(settings, 'FIREBASE_CREDENTIALS_PATH', '') or ''
    if not path:
        return None

    try:
        import os
        import firebase_admin
        from firebase_admin import credentials

        if not os.path.exists(path):
            logger.warning('Firebase credentials file not found: %s', path)
            return None

        if firebase_admin._apps:
            _app = firebase_admin.get_app()
        else:
            _app = firebase_admin.initialize_app(credentials.Certificate(path))
    except Exception as exc:  # ImportError, bad creds, etc.
        logger.warning('Firebase init failed: %s', exc)
        _app = None
    return _app


def send_push(user, title, body, data=None, image_url=None):
    """Send an FCM push to all of `user`'s device tokens. No-op if unconfigured."""
    if _get_app() is None:
        return
    try:
        from firebase_admin import messaging
    except ImportError:
        return

    from .models import DeviceToken

    tokens = list(DeviceToken.objects.filter(user=user).values_list('token', flat=True))
    if not tokens:
        return

    payload = {k: str(v) for k, v in (data or {}).items()}
    for tk in tokens:
        try:
            messaging.send(messaging.Message(
                notification=messaging.Notification(title=title, body=body, image=image_url),
                data=payload,
                token=tk,
            ))
        except Exception as exc:
            msg = str(exc).lower()
            # Stale / unregistered token → remove it so we stop trying.
            if any(w in msg for w in ('not found', 'unregistered', 'invalid', 'not a valid')):
                DeviceToken.objects.filter(token=tk).delete()
            else:
                logger.warning('Push send failed: %s', exc)


def send_push_to_users(users, title, body, data=None, image_url=None):
    """Send the same push to multiple users."""
    for user in users:
        send_push(user, title, body, data, image_url)
