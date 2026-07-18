# Roles & Permissions — Admin API

Reference for the frontend team.

## Base URLs

There are **two** API bases:

| Base URL | Used by | Covered here |
|----------|---------|--------------|
| `https://api.salvationhq.com/api/admin/` | Admin dashboard — super admin, district manager, branch manager | ✅ This document |
| `https://api.salvationhq.com/api/users/` | Employee mobile app — tattoo artist, body piercer, staff | (separate app API) |

> **Every endpoint in this document is prefixed with the admin base:**
> ```
> https://api.salvationhq.com/api/admin/
> ```
> e.g. the table row `GET  users/` means `GET https://api.salvationhq.com/api/admin/users/`.

### Which base URL does each role use?

| Role | Base URL to build every request on |
|------|------------------------------------|
| `super_admin` | `https://api.salvationhq.com/api/admin/` |
| `district_manager` | `https://api.salvationhq.com/api/admin/` |
| `branch_manager` | `https://api.salvationhq.com/api/admin/` |
| `clock_in_user` | `https://api.salvationhq.com/api/admin/`  (only calls `clock-in/qr/`) |
| `staff` / `tattoo_artist` / `body_piercer` (mobile app) | `https://api.salvationhq.com/api/users/` |

All three admin roles **and** the clock-in user share the **same admin base**
(`/api/admin/`) — what they may call differs by `role`, not by base URL. Only the
employee mobile app uses a different base (`/api/users/`), documented separately.

**Full-URL examples**

```
super_admin       GET  https://api.salvationhq.com/api/admin/dashboard/
district_manager  GET  https://api.salvationhq.com/api/admin/district-manager/dashboard/
branch_manager    GET  https://api.salvationhq.com/api/admin/branch-manager/dashboard/
clock_in_user     GET  https://api.salvationhq.com/api/admin/clock-in/qr/
staff (app)       POST https://api.salvationhq.com/api/users/auth/login/
```

There are **three admin roles**. A request is authorized purely by the logged-in
user's `role` (sent as the JWT `access` token). If a role calls an endpoint it
isn't allowed to, the API returns **403 Forbidden**.

| Role | Scope | One-line summary |
|------|-------|------------------|
| `super_admin` | All locations | Manages the whole organization (users, locations, org tasks, content). |
| `district_manager` | All locations | Oversees & directs across every location, but does **not** manage the org. |
| `branch_manager` | **Own location only** | Runs a single shop (its staff, tasks, QR, verifications). |
| `clock_in_user` | Kiosk | Display-only account — shows the attendance QR. Only calls `clock-in/qr/`. |

> **Shared-status note:** A task submission can be approved/rejected by the
> branch manager **and** the district manager **and** the super admin. Approval
> status is shared — once one manager approves, it's approved for everyone.

---

## Auth (all roles — no permission required)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `login/` | Log in → returns JWT `access` + `refresh`. |
| POST | `forgot-password/` | Send reset OTP to email. |
| POST | `verify-otp/` | Verify the reset OTP. |
| POST | `reset-password/` | Set a new password. |
| GET | `app-content/splash-screen/` | Public splash-screen content. |

---

# 1. Super Admin — `super_admin`

**Can do everything.** The only role that manages users, locations, org-wide
tasks, and app content.

### Users — full CRUD
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET | `users/` | List all users (paginated). |
| POST | `users/` | Create a user (any role). |
| GET | `users/{id}/` | User detail. |
| PATCH | `users/{id}/` | Edit a user. |
| DELETE | `users/{id}/` | Delete a user. |
| POST | `users/{id}/suspend/` | Suspend a user. |
| POST | `users/{id}/activate/` | Re-activate a user. |

> Shared with district manager: `GET users/` list/detail are also allowed for
> district managers (read). **Create/edit/delete/suspend/activate are super-admin only.**

### Locations — full CRUD
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET | `locations/` | List locations (all admins can read). |
| GET | `locations/{id}/` | Location detail. |
| POST | `locations/` | Create a location. |
| PATCH | `locations/{id}/` | Edit a location. |
| DELETE | `locations/{id}/` | Delete a location (blocked if active staff are assigned). |
| GET | `locations/{id}/employees/` | Employees at a location. |

> Write actions (POST/PATCH/DELETE) are **super_admin + district_manager**.
> Read (list/retrieve) is **all three admin roles**.

### Tasks — full CRUD (org-wide) `super_admin only`
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET | `tasks/` | List tasks (recurring collapsed to one row). |
| POST | `tasks/` | Create a task (one-time or recurring). |
| GET | `tasks/{id}/` | Task detail. |
| PATCH | `tasks/{id}/` | Edit / edit series. |
| DELETE | `tasks/{id}/` | Delete task or series. |
| POST | `tasks/{id}/approve/` | Approve a submission. |
| POST | `tasks/{id}/reject/` | Reject a submission. |
| GET | `tasks/{id}/fire-info/` | Pre-fire info for an employee. |
| POST | `tasks/{id}/fire-user/` | Terminate an employee (sends email, deactivates). |

### Instructions — full CRUD
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET | `instructions/` | List (grouped by role section). |
| POST | `instructions/` | Create. |
| GET/PATCH/DELETE | `instructions/{id}/` | Detail / edit / delete. |

> Shared with district manager (both can manage instructions).

### App content / FAQs — `super_admin only`
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET/POST | `app-content/faqs/` | List / create FAQs. |
| GET/PATCH/DELETE | `app-content/faqs/{id}/` | Detail / edit / delete. |

### QR (attendance codes)
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET | `qr/` | Current/active QR session. |
| POST | `qr/` | Generate a QR session (custom minutes + seconds). |
| GET | `qr/{id}/details/` | QR session detail. |

> Shared with district manager.

### Dashboard / analytics / attendance (global)
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET | `dashboard/` | Global dashboard (all locations). |
| GET | `performance/` | Performance analytics. |
| GET | `reports/` | Reports analytics. |
| GET | `users-attendance/` | Org-wide attendance list. |

> `users-attendance/` is shared with district manager.

### Profile & notifications
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET/PATCH | `profile/` | Own profile. |
| POST | `profile/password/` | Change own password. |
| GET | `notifications/` | Received notifications (paginated 15/page). |
| POST | `notifications/` | Send a notification. |
| GET | `notifications/sent/` | Sent notifications. |
| GET | `notifications/recipients/` | Available recipients (full mesh). |

---

# 2. District Manager — `district_manager`

**Cross-location oversight.** Sees and directs across **all** locations, verifies
tasks, and manages instructions — but **cannot** create/edit users, create/edit
locations, or touch the super-admin task API.

### Employees & locations (read across all locations)
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET | `district-manager/employees/` | All employees, every location. |
| GET | `district-manager/locations/` | All active locations (**read-only**). |
| GET | `district-manager/locations/{id}/employees/` | Employees at one location. |
| GET | `users/` , `users/{id}/` | Read users (shared with super admin). |
| GET | `locations/` , `locations/{id}/` , `locations/{id}/employees/` | Read locations. |
| POST/PATCH/DELETE | `locations/…` | ✅ **Allowed** — location writes are super_admin + district_manager. |

### Tasks (district task API — separate from super admin's `tasks/`)
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET | `district-manager/tasks/` | List tasks (same shape as `tasks/`). |
| POST | `district-manager/tasks/` | Create a task (one-time or recurring). |
| GET | `district-manager/tasks/{id}/` | Task detail. |
| PATCH | `district-manager/tasks/{id}/` | Edit / edit series. |
| DELETE | `district-manager/tasks/{id}/` | Delete task or series. |

> ❌ District managers **cannot** call the super-admin `tasks/` viewset — they use
> the `district-manager/tasks/` endpoints above.

### Task verification (approve / reject)
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET | `district-manager/verifications/` | Submissions awaiting review. |
| POST | `district-manager/verifications/{id}/{action}/` | `action` = `approve` or `reject`. |

### Instructions (shared with super admin)
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET/POST | `instructions/` | List / create. |
| GET/PATCH/DELETE | `instructions/{id}/` | Detail / edit / delete. |

### QR (shared with super admin)
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET/POST | `qr/` | Read / generate QR session. |
| GET | `qr/{id}/details/` | QR detail. |

### Dashboard / analytics / attendance (all locations)
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET | `district-manager/dashboard/` | District dashboard. |
| GET | `district-manager/performance/` | Performance dashboard. |
| GET | `district-manager/reports/employee-performance/` | Employee performance report. |
| GET | `district/reports/` | District reports. |
| GET | `district-manager/users-attendance/` | Attendance list (paginated). |
| GET | `district-manager/attendance/{employee_id}/` | Per-employee attendance detail (`?month=YYYY-MM` or `?year=YYYY`). |
| GET | `users-attendance/` | Org-wide attendance (shared with super admin). |

### Profile & notifications
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET/PATCH | `district-manager/profile/` | Own profile. |
| POST | `district-manager/profile/password/` | Change own password. |
| GET/POST | `notifications/` … | Notifications (full mesh, same as super admin). |

### ❌ District manager CANNOT
- Create / edit / delete / suspend / activate **users**
- Create / edit / delete **tasks via the super-admin `tasks/` API** (uses district task API instead)
- Manage **FAQs / app content**
- Fire an employee (`tasks/{id}/fire-user/` is super-admin only)

---

# 3. Branch Manager — `branch_manager`

**Runs a single shop.** Everything is scoped to **the manager's own location** —
they cannot see or affect other locations.

### Employees (own location)
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET | `manager/employees/` | Employees at the manager's location. |

### Tasks (own location)
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET | `manager/tasks/` | List their location's tasks. |
| POST | `manager/tasks/` | Create a task for their location. |
| GET | `manager/tasks/{id}/` | Task detail. |
| DELETE | `manager/tasks/{id}/` | Delete task/series. |
| POST | `manager/tasks/{id}/approve/` | Approve a submission. |
| POST | `manager/tasks/{id}/reject/` | Reject a submission. |

### Verifications
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET | `manager/verifications/` | Submissions awaiting review (own location). |

> Approve/reject is done through `manager/tasks/{id}/approve|reject/` above.

### QR codes (own location attendance)
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET/POST | `qr/` | Generate / read QR for their location. |
| GET | `qr/{id}/details/` | QR detail. |

> QR endpoints require `super_admin`, `district_manager`, **or** `branch_manager`.

### Locations (read-only, own location)
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET | `locations/` | Reads — returns only the manager's own location. |

### Dashboard / reports (own location)
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET | `branch-manager/dashboard/` | Location dashboard. |
| GET | `branch-manager/reports/` | Location reports. |

### Profile & notifications
| Method | Endpoint | Ability |
|--------|----------|---------|
| GET/PATCH | `branch-manager/profile/` | Own profile. |
| POST | `branch-manager/profile/password/` | Change own password. |
| GET/POST | `notifications/` … | Notifications — but can only **send to employees at their own location**. |

### ❌ Branch manager CANNOT
- See or manage **other locations** or their staff
- Create / edit / delete **users** or **locations**
- Manage **instructions**, **FAQs**, or **app content**
- Access any **district-manager** or **super-admin** endpoint
- Fire an employee

---

# 4. Clock-In User — `clock_in_user`

A **kiosk / display-only** account (e.g. a tablet at the shop entrance). It has
access to exactly one endpoint and cannot do anything else.

| Method | Endpoint | Ability |
|--------|----------|---------|
| GET | `clock-in/qr/` | Show the current attendance QR code for scanning. |

Base URL: `https://api.salvationhq.com/api/admin/` (same base as the admin roles).

---

# 5. Employee mobile app — `staff` / `tattoo_artist` / `body_piercer`

These roles do **not** use the admin API at all. They use the **mobile app API**:

```
https://api.salvationhq.com/api/users/
```

This is a separate frontend (the phone app) with its own endpoints — login,
tasks, attendance check-in/out, notifications, profile, device-token, delete
account. It is **out of scope for this admin document** and has its own reference.

---

## Permission summary matrix

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
| View attendance (all locations) | ✅ | ✅ | ❌ (own loc only) |
| Global dashboard / reports | ✅ | ✅ (district) | ✅ (own loc) |
| Send notifications | ✅ (anyone) | ✅ (anyone) | ✅ (own-loc employees) |

---

## Notes for the frontend

1. **403 = wrong role.** If an endpoint returns 403, the logged-in role isn't
   permitted — don't render that action for that role.
2. **District managers use `district-manager/*` task endpoints**, not the plain
   `tasks/` endpoints (those are super-admin only). Same feature, different URL.
3. **Branch managers are always location-scoped** server-side — you don't need to
   pass a location filter; the API restricts to their location automatically.
4. **Pagination:** list endpoints (users, notifications, attendance) return 15
   items per page with `count` / `next` / `previous`. `count` is the **grand
   total across all pages**, not the number on the current page.
