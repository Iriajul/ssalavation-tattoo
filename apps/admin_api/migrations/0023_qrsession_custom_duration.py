from django.db import migrations, models


def copy_interval_to_seconds(apps, schema_editor):
    QRSession = apps.get_model('admin_api', 'QRSession')
    for session in QRSession.objects.all():
        # old refresh_interval was in minutes
        session.duration_seconds = (session.refresh_interval or 3) * 60
        session.save(update_fields=['duration_seconds'])


def reverse_seconds_to_interval(apps, schema_editor):
    QRSession = apps.get_model('admin_api', 'QRSession')
    for session in QRSession.objects.all():
        session.refresh_interval = max(1, round((session.duration_seconds or 180) / 60))
        session.save(update_fields=['refresh_interval'])


class Migration(migrations.Migration):

    dependencies = [
        ('admin_api', '0022_remove_task_old_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='qrsession',
            name='duration_seconds',
            field=models.PositiveIntegerField(default=180),
        ),
        migrations.RunPython(copy_interval_to_seconds, reverse_seconds_to_interval),
        migrations.RemoveField(
            model_name='qrsession',
            name='refresh_interval',
        ),
    ]
