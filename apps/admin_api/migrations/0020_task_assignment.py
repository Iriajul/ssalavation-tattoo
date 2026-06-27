from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('admin_api', '0019_admin_notification_m2m'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Remove constraints that reference fields we'll drop later
        migrations.RemoveConstraint(model_name='task', name='task_completion_requires_data'),
        migrations.RemoveConstraint(model_name='task', name='task_rejection_requires_reason'),

        # Remove status-related indexes (status field will be removed)
        migrations.RemoveIndex(model_name='task', name='task_status_idx'),
        migrations.RemoveIndex(model_name='task', name='task_location_status_idx'),
        migrations.RemoveIndex(model_name='task', name='task_status_created_idx'),

        # Create TaskAssignment table
        migrations.CreateModel(
            name='TaskAssignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Pending'),
                        ('awaiting_review', 'Awaiting Review'),
                        ('approved', 'Approved'),
                        ('rejected', 'Rejected'),
                        ('overdue', 'Overdue'),
                    ],
                    default='pending',
                    max_length=20,
                )),
                ('is_fired', models.BooleanField(default=False)),
                ('photo_url', models.URLField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('rejection_reason', models.TextField(blank=True, null=True)),
                ('rejected_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('task', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='assignments',
                    to='admin_api.task',
                )),
                ('employee', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='task_assignments',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('approved_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='approved_assignments',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('rejected_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='rejected_assignments',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'db_table': 'task_assignments',
                'ordering': ['created_at'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='taskassignment',
            unique_together={('task', 'employee')},
        ),
        migrations.AddIndex(
            model_name='taskassignment',
            index=models.Index(fields=['status'], name='ta_status_idx'),
        ),
        migrations.AddIndex(
            model_name='taskassignment',
            index=models.Index(fields=['task', 'status'], name='ta_task_status_idx'),
        ),
        migrations.AddIndex(
            model_name='taskassignment',
            index=models.Index(fields=['employee', 'status'], name='ta_emp_status_idx'),
        ),
    ]
