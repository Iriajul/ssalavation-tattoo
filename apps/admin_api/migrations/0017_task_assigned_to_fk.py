from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def m2m_to_fk(apps, schema_editor):
    Task = apps.get_model('admin_api', 'Task')
    db   = schema_editor.connection.alias

    for task in Task.objects.using(db).prefetch_related('assigned_to').all():
        assignees = list(task.assigned_to.all())
        if not assignees:
            continue

        # First assignee keeps the original task
        task.assigned_to_fk_id = assignees[0].pk
        task.save(using=db, update_fields=['assigned_to_fk_id'])

        # Extra assignees get a task copy each
        for extra in assignees[1:]:
            Task.objects.using(db).create(
                title            = task.title,
                description      = task.description,
                location_id      = task.location_id,
                assigned_to_fk_id = extra.pk,
                created_by_id    = task.created_by_id,
                due_date         = task.due_date,
                status           = task.status,
                is_fired         = task.is_fired,
                is_recurring     = task.is_recurring,
                frequency        = task.frequency,
                requires_photo   = task.requires_photo,
                photo_url        = task.photo_url,
                completed_by_id  = task.completed_by_id,
                completed_at     = task.completed_at,
                approved_by_id   = task.approved_by_id,
                approved_at      = task.approved_at,
                rejection_reason = task.rejection_reason,
                rejected_by_id   = task.rejected_by_id,
                rejected_at      = task.rejected_at,
            )


class Migration(migrations.Migration):

    dependencies = [
        ('admin_api', '0016_task_assigned_to_m2m'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. Add new FK column (nullable so data migration can fill it)
        migrations.AddField(
            model_name='task',
            name='assigned_to_fk',
            field=models.ForeignKey(
                null=True, blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='assigned_tasks_fk',
                to=settings.AUTH_USER_MODEL,
            ),
        ),

        # 2. Copy M2M → FK
        migrations.RunPython(m2m_to_fk, migrations.RunPython.noop),

        # 3. Remove M2M field
        migrations.RemoveField(
            model_name='task',
            name='assigned_to',
        ),

        # 4. Rename FK to assigned_to
        migrations.RenameField(
            model_name='task',
            old_name='assigned_to_fk',
            new_name='assigned_to',
        ),

        # 5. Update related_name to match model
        migrations.AlterField(
            model_name='task',
            name='assigned_to',
            field=models.ForeignKey(
                null=True, blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='assigned_tasks',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
