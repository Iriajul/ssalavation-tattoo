from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('admin_api', '0021_task_data_migration'),
    ]

    operations = [
        migrations.RemoveField(model_name='task', name='assigned_to'),
        migrations.RemoveField(model_name='task', name='status'),
        migrations.RemoveField(model_name='task', name='is_fired'),
        migrations.RemoveField(model_name='task', name='photo_url'),
        migrations.RemoveField(model_name='task', name='completed_by'),
        migrations.RemoveField(model_name='task', name='completed_at'),
        migrations.RemoveField(model_name='task', name='approved_by'),
        migrations.RemoveField(model_name='task', name='approved_at'),
        migrations.RemoveField(model_name='task', name='rejection_reason'),
        migrations.RemoveField(model_name='task', name='rejected_by'),
        migrations.RemoveField(model_name='task', name='rejected_at'),
    ]
