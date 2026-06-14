from django.conf import settings
from django.db import migrations, models


def fk_to_m2m(apps, schema_editor):
    Task = apps.get_model('admin_api', 'Task')
    for task in Task.objects.using(schema_editor.connection.alias).all():
        if task.assigned_to_old_id:
            task.assigned_to_new.add(task.assigned_to_old_id)


class Migration(migrations.Migration):

    dependencies = [
        ('admin_api', '0015_remove_task_task_completion_requires_timestamp_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. Rename old FK so we can free up the name 'assigned_to'
        migrations.RenameField(
            model_name='task',
            old_name='assigned_to',
            new_name='assigned_to_old',
        ),

        # 2. Add new M2M under a temporary name
        migrations.AddField(
            model_name='task',
            name='assigned_to_new',
            field=models.ManyToManyField(
                blank=True,
                related_name='assigned_tasks_new',
                to=settings.AUTH_USER_MODEL,
            ),
        ),

        # 3. Copy FK data into M2M
        migrations.RunPython(fk_to_m2m, migrations.RunPython.noop),

        # 4. Drop old FK
        migrations.RemoveField(
            model_name='task',
            name='assigned_to_old',
        ),

        # 5. Rename M2M to final name
        migrations.RenameField(
            model_name='task',
            old_name='assigned_to_new',
            new_name='assigned_to',
        ),

        # 6. Drop old indexes that referenced the FK column
        migrations.DeleteModel(name='__fake__') if False else migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    "DROP INDEX IF EXISTS task_assigned_to_idx;",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    "DROP INDEX IF EXISTS task_assigned_status_idx;",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[],
        ),
    ]
