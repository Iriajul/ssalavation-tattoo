# Salvation Tattoo — Admin API Reference

Reference for the frontend team. Each endpoint below shows, in one place:
its **method**, **who can call it**, **request body**, **query params/filters**,
and a **sample JSON response**.

## Base URL

All admin endpoints are prefixed with:

```
https://api.salvationhq.com/api/admin/
```

So `GET users/` means `GET https://api.salvationhq.com/api/admin/users/`.

| Role | Base URL |
|------|----------|
| `super_admin` | `https://api.salvationhq.com/api/admin/` |
| `district_manager` | `https://api.salvationhq.com/api/admin/` |
| `branch_manager` | `https://api.salvationhq.com/api/admin/` |
| `clock_in_user` | `https://api.salvationhq.com/api/admin/` (only `clock-in/qr/`) |
| `staff` / `tattoo_artist` / `body_piercer` (mobile app) | `https://api.salvationhq.com/api/users/` (separate app API — not in this doc) |

## Conventions

- **Auth header** on every endpoint except the Auth group:
  `Authorization: Bearer <access_token>`
- **`403`** = your role can't call this endpoint. **`401`** = missing/expired token.
- Validation errors → `400` with `{ "field": ["message"] }` or `{ "error": "message" }`.
- **Pagination:** list endpoints return **15 per page**, wrapped as:
  ```json
  { "count": 40, "next": "…?page=2", "previous": null, "results": [ … ] }
  ```
  `count` is the total across **all** pages, not the current page size.
- **Task approval is shared:** a submission can be approved/rejected by the branch
  manager, district manager, or super admin — once one approves, it's approved for all.

## Role summary

| Role | Scope | Summary |
|------|-------|---------|
| `super_admin` | All locations | Manages the whole org — users, locations, org tasks, content. |
| `district_manager` | All locations | Oversight across every location; verifies & assigns tasks; manages instructions & locations. Cannot manage users, FAQs, or fire. |
| `branch_manager` | Own location only | Runs one shop — its staff, tasks, QR, verifications. |
| `clock_in_user` | Kiosk | Display-only — shows the attendance QR. |

## Contents
- [Auth (all roles)](#auth-all-roles)
- [Super Admin](#super-admin)
- [District Manager](#district-manager)
- [Branch Manager](#branch-manager)
- [Clock-In User](#clock-in-user)
- [Permission summary matrix](#permission-summary-matrix)

---
this is the thing that we need

# Auth (all roles)

No auth header required for this group.

## POST `login/`
**Body**
```json
{ "email": "admin@salvationhq.com", "password": "secret" }
```
**200**
```json
{
  "message": "Login successful.",
  "user": { "id": 1, "email": "admin@salvationhq.com", "role": "super_admin", "full_name": "Zubaer Ahmed" },
  "tokens": { "access": "<jwt>", "refresh": "<jwt>" }
}
```
**400** → `{ "error": "Invalid email or password." }`

## POST `forgot-password/`
**Body** `{ "email": "admin@salvationhq.com" }`
**200** `{ "message": "Reset code sent to your email.", "temp_token": "<jwt>" }`

## POST `verify-otp/`
**Body** `{ "temp_token": "<jwt>", "otp": "12345" }`
**200** `{ "message": "OTP verified.", "temp_token": "<jwt>" }`

## POST `reset-password/`
**Body** `{ "temp_token": "<jwt>", "new_password": "newpass123", "confirm_password": "newpass123" }`
**200** `{ "message": "Password reset successfully." }`

---

# Super Admin

Role `super_admin`. Full control of the whole organization.

## Users

### GET `users/`
List all users. *(also allowed for `district_manager`)*
**Query params**

| Param | Type | Notes |
|-------|------|-------|
| `search` | string | first name, last name, username, email, role |
| `role` | string | e.g. `staff` |
| `location` | int | location id |
| `page` | int | page number (15/page) |

**200**
```json
{
  "count": 45, "next": "…/users/?page=2", "previous": null,
  "results": [
    {
      "id": 32, "first_name": "Ramona", "last_name": "Smith", "username": "ramona",
      "email": "ramona@ex.com", "role": "staff", "role_display": "Staff",
      "location": 1, "location_name": "Pembroke Pines",
      "is_active": true, "is_suspended": false, "user_status": "active",
      "joined": "January 2026",
      "work_schedules": [
        { "id": 5, "day": "mon", "is_active": true, "start_time": "10:00:00", "end_time": "18:00:00" }
      ]
    }
  ]
}
```

### POST `users/`
Create a user.
**Body**
```json
{
  "first_name": "Ramona", "last_name": "Smith", "username": "ramona",
  "email": "ramona@ex.com", "password": "secret123", "role": "staff",
  "location": 1, "phone": "+100000000",
  "work_schedules": [
    { "day": "mon", "is_active": true, "start_time": "10:00", "end_time": "18:00" },
    { "day": "tue", "is_active": true, "start_time": "10:00", "end_time": "18:00" }
  ]
}
```
- `role` ∈ `super_admin | district_manager | branch_manager | tattoo_artist | body_piercer | staff | clock_in_user`
- `password` ≥ 8 chars. `work_schedules` required only for employee roles.

**201** → the created user (detail shape). **400** on duplicate email/username.

### GET `users/{id}/`
Single user — same fields as the list row plus `phone`, `profile_photo`. *(also `district_manager`)*

### PATCH `users/{id}/`
Edit a user. Any subset of the create body, plus `status`.
**Body**
```json
{ "first_name": "Ramona", "status": "suspended", "password": "newpass123" }
```
`status` ∈ `active | inactive | suspended`. `work_schedules` **replace** the existing set.
**200** → updated user.

### DELETE `users/{id}/`
**204** No Content.

### POST `users/{id}/suspend/`
No body. **200** `{ "message": "User suspended." }`

### POST `users/{id}/activate/`
No body. **200** `{ "message": "User activated." }`

## Locations
*(read: all admins · write: `super_admin` + `district_manager`)*

### GET `locations/`
No params.
**200**
```json
[
  {
    "id": 1, "name": "Pembroke Pines", "street_address": "123 Main St",
    "city_state": "Pembroke Pines, FL", "status": "active",
    "staff_count": 12, "created_at": "2026-01-01T10:00:00Z", "updated_at": "2026-01-01T10:00:00Z"
  }
]
```

### POST `locations/`
**Body**
```json
{ "name": "Coral Springs", "street_address": "456 Oak Ave", "city_state": "Coral Springs, FL", "status": "active" }
```
`status` ∈ `active | inactive`. **201** → created location.

### GET `locations/{id}/`
Single location (same fields as list).

### PATCH `locations/{id}/`
Any subset of the create body. **200** → updated location.

### DELETE `locations/{id}/`
**204** on success.
**400** → `{ "error": "Cannot delete: active employees are assigned to this location." }`

### GET `locations/{id}/employees/`
**200**
```json
[
  {
    "id": 32, "name": "Ramona Smith", "role": "Staff", "profile_photo": null,
    "work_schedules": [ { "day": "mon", "is_active": true, "start_time": "10:00:00", "end_time": "18:00:00" } ]
  }
]
```

## Tasks
*(`super_admin` only — district managers use `district-manager/tasks/`, branch managers use `manager/tasks/`)*

### GET `tasks/`
**Query params:** `search` (title/description), `location` (int), `status`, `page`.
**200**
```json
{
  "stats": { "total": 40, "pending": 30, "approved": 6, "rejected": 4 },
  "count": 40, "next": "…?page=2", "previous": null,
  "results": [
    {
      "task_id": 12, "template_id": 3, "title": "Clean stations",
      "description": "…", "location": 1, "location_name": "Pembroke Pines",
      "due_date": "2026-04-10", "next_due_date": "2026-04-11",
      "is_recurring": true, "frequency": "daily",
      "recurrence": { "frequency": "daily", "interval": 1, "weekdays": [], "day_of_month": null },
      "total_occurrences": 30, "requires_photo": true,
      "created_by": "Zubaer Ahmed", "created_at": "2026-04-01T09:00:00Z",
      "assignments": [
        { "id": 55, "employee_id": 32, "employee_name": "Ramona Smith", "status": "pending",
          "photo_url": null, "completed_at": null, "approved_by": null, "rejected_by": null }
      ],
      "status_counts": { "pending": 1, "awaiting_review": 0, "approved": 0, "rejected": 0 }
    }
  ]
}
```

### POST `tasks/` — one-time task
**Body**
```json
{
  "title": "Deep clean", "description": "…",
  "location": 1, "assigned_to": [32, 27],
  "due_date": "2026-05-01", "requires_photo": true, "is_recurring": false
}
```

### POST `tasks/` — recurring task
**Body**
```json
{
  "title": "Daily open checklist", "location": 1, "assigned_to": [32],
  "is_recurring": true, "start_date": "2026-05-01", "requires_photo": false,
  "recurrence": {
    "frequency": "weekly",            // daily | weekly | monthly | yearly
    "interval": 1,                     // every N periods
    "weekdays": ["mon","wed","fri"],  // weekly only
    "day_of_month": null               // monthly only, 1–31
  }
}
```
- One-time requires `due_date`, rejects `start_date`/`recurrence`.
- Recurring requires `start_date` + `recurrence`, rejects `due_date`.

**201** → created task.

### GET `tasks/{id}/`
Single task detail (full assignment list).

### PATCH `tasks/{id}/`
Any subset of: `title`, `description`, `location`, `due_date`, `start_date`, `recurrence`, `requires_photo`, `assigned_to`.
- `assigned_to` **replaces** the assignee list. Changing `location` requires new `assigned_to`.
- Editing a recurring task updates the template + regenerates future, not-yet-started occurrences.

### DELETE `tasks/{id}/`
Deletes the task; for a recurring series, keeps completed/acted-on history and removes untouched future occurrences. **204**.

### POST `tasks/{id}/approve/`
**Body** `{ "assignment_id": 55 }` → **200** `{ "message": "Task approved." }`

### POST `tasks/{id}/reject/`
**Body** `{ "assignment_id": 55, "rejection_reason": "Photo unclear" }` (min 5 chars) → **200** `{ "message": "Task rejected." }`

### GET `tasks/{id}/fire-info/`
Returns the assignment + employee info to pre-fill the fire dialog.

### POST `tasks/{id}/fire-user/`
**Body** `{ "assignment_id": 55, "fire_reason": "Repeated no-shows." }`
Deactivates the employee, sends the termination email. **200** `{ "message": "Employee terminated." }`

## Instructions
*(CRUD: `super_admin` + `district_manager`)*

### GET `instructions/`
**Query params:** `search` (title/description), `role` (`all` or a role slug).
Always returns the grouped structure regardless of filter.
**200**
```json
{
  "stats": { "total": 4, "employee": 2, "manager": 1, "district": 1 },
  "grouped": [
    { "section": "Employees Instructions",        "document_count": 2, "instructions": [ /* … */ ] },
    { "section": "Managers Instructions",          "document_count": 1, "instructions": [ /* … */ ] },
    { "section": "District Managers Instructions", "document_count": 1, "instructions": [ /* … */ ] }
  ]
}
```
Each instruction object:
```json
{ "id": 3, "title": "Safety rules", "description": "…",
  "pdf_url": "https://…/file.pdf", "pdf_filename": "safety.pdf",
  "role_visibility": ["staff","tattoo_artist"],
  "created_at": "2026-01-01T…", "updated_at": "2026-01-01T…" }
```

### POST `instructions/` *(multipart/form-data)*
| Field | Type | Notes |
|-------|------|-------|
| `title` | string | required |
| `description` | string | optional |
| `role_visibility` | list | required, e.g. `["staff","branch_manager"]` |
| `pdf_file` | file | optional PDF |

**201** → created instruction.

### GET / PATCH / DELETE `instructions/{id}/`
Detail / edit / delete.

## QR
*(`super_admin` + `district_manager` + `branch_manager`)*

### GET `qr/`
Current active session.
**200**
```json
{ "id": 9, "token": "abc123", "location": 1, "location_name": "Pembroke Pines",
  "is_active": true, "duration_seconds": 180, "duration_display": "3m 0s",
  "expires_at": "2026-04-10T10:03:00Z", "created_at": "2026-04-10T10:00:00Z" }
```

### POST `qr/`
Generate a session.
**Body** `{ "location": 1, "duration_minutes": 3, "duration_seconds": 0 }`
Lifetime = minutes×60 + seconds. **201** → the QR session (same shape as GET).

### GET `qr/{id}/details/`
Single QR session detail.

## Notifications
*(all admin roles)*

### GET `notifications/`
**Query params:** `tab` = `all | unread`, `page`.
**200**
```json
{ "count": 20, "next": "…?page=2", "previous": null, "unread_count": 3,
  "results": [
    { "id": 7, "type": "task_assigned", "title": "New task", "message": "…",
      "is_read": false, "image_url": null, "created_at": "2026-04-10T…", "time_ago": "2h ago" }
  ] }
```

### POST `notifications/` *(JSON or multipart)*
**Body** `{ "recipients": [32, 27, 5], "message": "Team meeting at 5pm", "image": null }`
`recipients` = user ids. `image` optional file. **201**.

### GET `notifications/sent/`
Paginated list of notifications you sent.

### GET `notifications/recipients/`
Available recipients for the send screen (respects the sender's role/location).

## Dashboard & Analytics

### GET `dashboard/`
**Query param:** `location` (int) filters `employee_breakdown`.
**200**
```json
{
  "stats": { "total_employees": 45, "total_locations": 5, "pending_tasks": 579, "today_attendance": 32 },
  "attendance_overview": [ { "date": "Jul 07", "present": 3, "late": 1, "absent": 0 } ],
  "task_status": { "total": 591, "pending": 579, "approved": 6, "rejected": 5 },
  "task_by_location": [ { "location_id": 1, "location_name": "MidTown", "pending": 2, "approved": 2, "rejected": 2 } ],
  "recent_activity": [ { "id": 1, "action": "task_completed", "message": "…", "time_ago": "5m ago" } ],
  "employee_breakdown": {
    "count": 45, "next": "…?page=2", "previous": null,
    "results": [ { "id": 32, "name": "Ramona Smith", "role_display": "Staff", "location_name": "Pembroke Pines", "today_status": "absent" } ]
  }
}
```

### GET `performance/`
**Query param:** `period` = `daily | weekly | monthly` (aliases like `week` accepted). Completion/attendance analytics.

### GET `reports/`
**Query param:** `period`. Report analytics (task completion, attendance trends).

## Attendance

### GET `users-attendance/`
*(also `district_manager`)* Org-wide yearly attendance totals per employee.
**Query params:** `search`, `location` (int), `year` (default current), `page`.
**200**
```json
{
  "year": 2026,
  "employees": [
    { "id": 32, "name": "Ramona Smith", "role": "Staff",
      "location_name": "Pembroke Pines", "location_id": 1,
      "present": 4, "late": 1, "absent": 0 }
  ],
  "employees_meta": { "count": 40, "next": "…?page=2", "previous": null }
}
```

### GET `district-manager/attendance/{employee_id}/`
*(also `district_manager`)* Per-employee attendance detail.
**Query params:** `month` = `YYYY-MM` (day grid) **or** `year` = `YYYY` (12-month summary).

`?month=2026-04` →
```json
{
  "employee": { "id": 32, "name": "Ramona Smith", "role": "Staff", "location": "Pembroke Pines" },
  "mode": "daily", "month": "2026-04", "month_label": "April 2026",
  "summary": { "present": 12, "late": 2, "absent": 1 },
  "records": [
    { "date": "2026-04-01", "day": 1, "weekday": "Wed", "is_work_day": true,
      "status": "present", "clock_in": "10:03:00", "clock_out": "18:00:00" }
  ]
}
```

`?year=2026` →
```json
{
  "employee": { "id": 32, "name": "Ramona Smith", "role": "Staff", "location": "Pembroke Pines" },
  "mode": "monthly", "year": 2026,
  "summary": { "present": 120, "late": 10, "absent": 5 },
  "records": [ { "month": 1, "month_label": "Jan", "month_key": "2026-01", "present": 15, "late": 1, "absent": 0 } ]
}
```

## Profile

### GET `profile/`
**200**
```json
{ "id": 1, "first_name": "Zubaer", "last_name": "Ahmed", "email": "…", "phone": "…",
  "role": "super_admin", "role_display": "Super Admin", "profile_photo": null }
```

### PATCH `profile/` *(multipart for photo)*
Any of `first_name`, `last_name`, `phone`, `profile_photo`. **200** → updated profile.

### POST `profile/password/`
**Body** `{ "current_password": "old", "new_password": "newpass123", "confirm_password": "newpass123" }`
**200** `{ "message": "Password changed." }`. **400** if current wrong or new ≠ confirm.

## App content / FAQs
*(`super_admin` only, except splash-screen which is public)*

### GET `app-content/splash-screen/` *(public)*
Returns splash content.

### GET `app-content/faqs/`
**200** `[ { "id": 1, "question": "…", "answer": "…", "order": 1, "is_active": true } ]`

### POST `app-content/faqs/`
**Body** `{ "question": "How do I clock in?", "answer": "Scan the QR at reception.", "order": 1, "is_active": true }`
**201** → created FAQ.

### GET / PATCH / DELETE `app-content/faqs/{id}/`
Detail / edit / delete.

---

# District Manager

Role `district_manager`. Cross-location oversight across **all** locations.
**Shared with super admin:** `users/` (read only), `locations/` (read + write),
`instructions/`, `qr/`, `users-attendance/`, `notifications/`,
`district-manager/attendance/{id}/`. Those are documented once under
[Super Admin](#super-admin); the district-only endpoints are below.

## Employees & locations

### GET `district-manager/employees/`
All employees, every location.
**Query params:** `search`, `location` (int), `page`.
**200**
```json
{ "count": 45, "next": "…?page=2", "previous": null,
  "results": [ { "id": 32, "name": "Ramona Smith", "role": "Staff", "location_name": "Pembroke Pines", "location_id": 1 } ] }
```

### GET `district-manager/locations/`
*(also `super_admin`)* All active locations, **read-only**, with `staff_count`.
**200**
```json
[ { "id": 1, "name": "Pembroke Pines", "street_address": "123 Main St", "city_state": "Pembroke Pines, FL", "status": "active", "staff_count": 12 } ]
```

### GET `district-manager/locations/{id}/employees/`
Employees at one location (same shape as `locations/{id}/employees/`).

## Tasks

### GET `district-manager/tasks/`
Same response shape as [`GET tasks/`](#get-tasks).
**Query params:** `search`, `location`, `status`, `page`.

### POST `district-manager/tasks/`
Same body as [`POST tasks/`](#post-tasks--one-time-task) (one-time or recurring). **201** → created task.

### GET `district-manager/tasks/{id}/`
Single task detail.

### PATCH `district-manager/tasks/{id}/`
Same edit rules as [`PATCH tasks/{id}/`](#patch-tasksid).

### DELETE `district-manager/tasks/{id}/`
Delete task or series. **204**.

## Verifications

### GET `district-manager/verifications/`
Submissions awaiting review (all locations).
**200**
```json
{ "count": 8, "next": null, "previous": null,
  "results": [
    { "assignment_id": 55, "task_id": 12, "task_title": "Clean stations",
      "employee_id": 32, "employee_name": "Ramona Smith", "location_name": "Pembroke Pines",
      "photo_url": "https://…/photo.jpg", "completed_at": "2026-04-10T14:00:00Z", "status": "awaiting_review" }
  ] }
```

### POST `district-manager/verifications/{task_id}/{action}/`
> ⚠️ The URL segment is the **TASK id**, not the assignment id. The assignment id
> goes in the **body**. Same convention as super-admin/branch approve & reject.

`{action}` = `approve` or `reject`.
**Approve body** `{ "assignment_id": 55 }`
**Reject body** `{ "assignment_id": 55, "rejection_reason": "Photo is blurry" }` (min 5 chars)
**200** → `{ "message": "Task approved successfully." }` / `{ "message": "Task rejected." }`
**404** `{ "error": "Task not found." }` if the URL id isn't a task at an active location.

## Dashboard / analytics

### GET `district-manager/dashboard/`
**200**
```json
{ "stats": { "active_locations": 5, "task_completion": 19, "task_completion_detail": "6/32 tasks done",
    "avg_attendance": 90, "avg_attendance_label": "Across all locations", "overdue_tasks": 3 },
  "attendance_overview": [ { "date": "Jul 07", "present": 3, "late": 1, "absent": 0 } ],
  "task_status": { "total": 32, "pending": 20, "approved": 6, "rejected": 6 } }
```

### GET `district-manager/performance/`
**Query param:** `period`. Performance dashboard.

### GET `district-manager/reports/employee-performance/`
**Query params:** `period`, `location`. Employee performance report.

### GET `district/reports/`
**Query param:** `period`. District reports.

### GET `district-manager/users-attendance/`
*(also `super_admin`)* Same as [`users-attendance/`](#get-users-attendance).

## Profile

### GET / PATCH `district-manager/profile/`
Same shapes as [`profile/`](#get-profile).

### POST `district-manager/profile/password/`
Same body as [`profile/password/`](#post-profilepassword).

---

# Branch Manager

Role `branch_manager`. Everything is auto-scoped to the manager's own location —
**no location param needed**, the API restricts server-side.

## Employees

### GET `manager/employees/`
Employees at the manager's location (same shape as `locations/{id}/employees/`).

## Tasks

### GET `manager/tasks/`
Their location's tasks. Same response shape as [`GET tasks/`](#get-tasks).
**Query params:** `search`, `status`, `page`.

### POST `manager/tasks/`
Same body as [`POST tasks/`](#post-tasks--one-time-task) — `location` is fixed to the manager's own. **201**.

### GET `manager/tasks/{id}/`
Single task detail.

### DELETE `manager/tasks/{id}/`
Delete task/series. **204**.

### POST `manager/tasks/{id}/approve/`
**Body** `{ "assignment_id": 55 }` → `{ "message": "Task approved." }`

### POST `manager/tasks/{id}/reject/`
**Body** `{ "assignment_id": 55, "rejection_reason": "…" }` (min 5 chars) → `{ "message": "Task rejected." }`

## Verifications

### GET `manager/verifications/`
Submissions awaiting review (own location). Approve/reject via `manager/tasks/{id}/approve|reject/` above.
**200**
```json
{ "count": 3, "next": null, "previous": null,
  "results": [
    { "assignment_id": 55, "task_id": 12, "task_title": "Clean stations",
      "employee_id": 32, "employee_name": "Ramona Smith",
      "photo_url": "https://…/photo.jpg", "completed_at": "2026-04-10T14:00:00Z", "status": "awaiting_review" }
  ] }
```

## Attendance
Same screens as the district/super-admin Users Attendance, but scoped to the
manager's **own location only** — no `location` param (it's fixed server-side).

### GET `manager/users-attendance/`
Yearly attendance totals for the manager's own-location employees.
**Query params:** `search`, `year` (default current), `page`.
**200**
```json
{
  "year": 2026,
  "employees": [
    { "id": 32, "name": "Ramona Smith", "role": "Staff",
      "location_name": "Pembroke Pines", "location_id": 1,
      "present": 4, "late": 1, "absent": 0 }
  ],
  "employees_meta": { "count": 3, "next": null, "previous": null }
}
```

### GET `manager/attendance/{employee_id}/`
Per-employee attendance detail. Returns **404** if the employee isn't at the manager's location.
**Query params:** `month` = `YYYY-MM` (day grid) **or** `year` = `YYYY` (12-month summary).

`?month=2026-04` →
```json
{
  "employee": { "id": 32, "name": "Ramona Smith", "role": "Staff", "location": "Pembroke Pines" },
  "mode": "daily", "month": "2026-04", "month_label": "April 2026",
  "summary": { "present": 12, "late": 2, "absent": 1 },
  "records": [
    { "date": "2026-04-01", "day": 1, "weekday": "Wed", "is_work_day": true,
      "status": "present", "clock_in": "10:03:00", "clock_out": "18:00:00" }
  ]
}
```

`?year=2026` →
```json
{
  "employee": { "id": 32, "name": "Ramona Smith", "role": "Staff", "location": "Pembroke Pines" },
  "mode": "monthly", "year": 2026,
  "summary": { "present": 120, "late": 10, "absent": 5 },
  "records": [ { "month": 1, "month_label": "Jan", "month_key": "2026-01", "present": 15, "late": 1, "absent": 0 } ]
}
```

## QR
Same endpoints as [Super Admin → QR](#qr) (`qr/`, `qr/{id}/details/`) — scoped to the manager's location.

## Locations

### GET `locations/`
Read-only — returns only the manager's own location (same shape as [`GET locations/`](#get-locations)).

## Dashboard / reports

### GET `branch-manager/dashboard/`
**200**
```json
{ "stats": { "total_employees": 3, "pending_verifications": 3,
    "today_attendance": { "total": 3, "present": 3, "late": 0, "absent": 0 } },
  "attendance_overview": [ { "date": "Jul 07", "present": 3, "late": 0, "absent": 0 } ],
  "task_status": { "total": 10, "pending": 7, "approved": 2, "rejected": 1 } }
```

### GET `branch-manager/reports/`
**Query param:** `period`. Location reports.

## Profile

### GET / PATCH `branch-manager/profile/`
Same shapes as [`profile/`](#get-profile).

### POST `branch-manager/profile/password/`
Same body as [`profile/password/`](#post-profilepassword).

## Notifications
Same endpoints as [Super Admin → Notifications](#notifications), but can only **send to employees at their own location**.

---

# Clock-In User

Role `clock_in_user`. Kiosk/display account with exactly one endpoint.

### GET `clock-in/qr/`
Show the current attendance QR code for scanning.
**200**
```json
{ "id": 9, "token": "abc123", "location": 1, "location_name": "Pembroke Pines",
  "is_active": true, "duration_seconds": 180, "expires_at": "2026-04-10T10:03:00Z" }
```

---

# Permission summary matrix

| Capability | super_admin | district_manager | branch_manager |
|------------|:-----------:|:----------------:|:--------------:|
| Manage users (create/edit/delete) | ✅ | ❌ | ❌ |
| Read users list | ✅ | ✅ | ❌ |
| Suspend / activate users | ✅ | ❌ | ❌ |
| Create/edit/delete locations | ✅ | ✅ | ❌ |
| Read locations | ✅ (all) | ✅ (all) | ✅ (own only) |
| Create/manage tasks | ✅ (`tasks/`) | ✅ (`district-manager/tasks/`) | ✅ (`manager/tasks/`, own loc) |
| Approve / reject submissions | ✅ | ✅ | ✅ (own loc) |
| Fire an employee | ✅ | ❌ | ❌ |
| Manage instructions | ✅ | ✅ | ❌ |
| Manage FAQs / app content | ✅ | ❌ | ❌ |
| Generate QR codes | ✅ | ✅ | ✅ (own loc) |
| View attendance | ✅ (all) | ✅ (all) | ✅ (own loc only) |
| Global dashboard / reports | ✅ | ✅ (district) | ✅ (own loc) |
| Send notifications | ✅ (anyone) | ✅ (anyone) | ✅ (own-loc employees) |

## Notes for the frontend
1. **403 = wrong role.** Don't render an action a role can't call.
2. **District managers use `district-manager/*` task endpoints**, not `tasks/` (super-admin only). Same feature, different URL.
3. **Branch managers are auto location-scoped** — no location filter needed.
4. **`count` in paginated responses is the grand total across all pages**, not the current page size.

---

*Response fields come from the serializers in `apps/admin_api/serializers.py` and
the view payloads in `apps/admin_api/views.py` / `district_views.py`. Some sample
values (ids, timestamps) are illustrative; field names and structure are accurate.*
