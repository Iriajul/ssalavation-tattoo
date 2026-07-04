"""
Auto-send an FCM push whenever an in-app notification is created.

This covers every AppNotification made via .create() (task assigned / approved /
rejected / due-soon / system). Bulk-created notifications (e.g. admin broadcasts
using bulk_create) bypass signals and push explicitly in the view instead.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import AppNotification


@receiver(post_save, sender=AppNotification)
def _push_on_app_notification(sender, instance, created, **kwargs):
    if not created:
        return
    from .push import send_push
    send_push(
        instance.recipient,
        instance.title,
        instance.message,
        data={
            'notif_type': instance.notif_type,
            'task_id':    str(instance.task_id or ''),
        },
    )
