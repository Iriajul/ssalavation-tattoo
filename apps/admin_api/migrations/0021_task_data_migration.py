from django.db import migrations
from itertools import groupby


def migrate_to_task_assignments(apps, schema_editor):
    Task = apps.get_model('admin_api', 'Task')
    TaskAssignment = apps.get_model('admin_api', 'TaskAssignment')

    all_tasks = list(
        Task.objects.all()
        .order_by('title', 'location_id', 'due_date', 'created_by_id', 'id')
    )

    def group_key(t):
        return (t.title, t.location_id, str(t.due_date), t.created_by_id)

    tasks_to_delete = []
    assignments_to_create = []
    seen_pairs = set()

    for key, group_iter in groupby(all_tasks, key=group_key):
        group_list = list(group_iter)
        canonical = group_list[0]  # keep lowest id as the real task

        for task in group_list:
            if task.assigned_to_id:
                pair = (canonical.id, task.assigned_to_id)
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    assignments_to_create.append(TaskAssignment(
                        task_id          = canonical.id,
                        employee_id      = task.assigned_to_id,
                        status           = task.status,
                        is_fired         = task.is_fired,
                        photo_url        = task.photo_url or None,
                        completed_at     = task.completed_at,
                        approved_by_id   = task.approved_by_id,
                        approved_at      = task.approved_at,
                        rejection_reason = task.rejection_reason,
                        rejected_by_id   = task.rejected_by_id,
                        rejected_at      = task.rejected_at,
                    ))

            if task.id != canonical.id:
                tasks_to_delete.append(task.id)

    TaskAssignment.objects.bulk_create(assignments_to_create, ignore_conflicts=True)
    Task.objects.filter(id__in=tasks_to_delete).delete()


def reverse_migrate(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('admin_api', '0020_task_assignment'),
    ]

    operations = [
        migrations.RunPython(migrate_to_task_assignments, reverse_migrate),
    ]
