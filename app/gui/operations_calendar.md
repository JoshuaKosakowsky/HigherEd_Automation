# Bursar Office Calendar (0.18.0)

Only active application administrators can open or edit this calendar. All
administrators share the same calendar; assigning a staff member or role to an
item does not grant them calendar access. The calendar is a visual planning
aid, with no Started/In progress/Complete statuses and no external notifications.

## Group related items with independent dates

Use **Groups…** on the calendar to create a heading such as **Annual PCI Cycle**,
**Fall Fee Assessment**, or **Fall Payment Deadline**. Select existing items and
Save to organize the entries you have already made. Their dates, date approvals,
recurrence, affected roles/people, and reminders are preserved. Categories remain
separate filter labels; a group can contain items from different categories.

For example, Annual PCI Cycle can contain three ordinary calendar items:

- Review/update materials, with its own start date and duration.
- Send the announcement, with its own date.
- Quiz completion window, with its own start date and duration.

Changing PCI Review to one day does not move the announcement or quiz window.
Each part repeats according to its own schedule. There are no group-level
dependencies, completion statuses, or dates that control other members.

In **Add item** or **Edit schedule**, use **Group (optional)** to choose an
existing group or **No group**. For bulk organization, Groups… lists all existing
schedules, including those outside the currently displayed dates or filters.
Checking an item already in another group moves it to the selected group.
Switching groups in that dialog retains pending membership edits; Save commits
them together and Cancel discards them. Membership applies to the entire recurring
schedule; future-only schedule editing retains its normal scope.

The chart shows an **Expand / Collapse** button beside each group's compact
timeline. Click anywhere on the button once, or focus it with Tab and
press Space. The button stays visible as the group opens or closes.
Collapsing changes only the chart display;
reminders remain visible. Search includes group names, and reminders include
their group name. The group timeline shows each matching deadline as a diamond
and each actual work/coverage period as its own bar, including when collapsed.
It does not fill the gaps between independent activities. Overlapping or closely
spaced marks use separate lanes so one cannot hide another; narrow views may
therefore make a group heading taller. Hover over the group timeline for dates,
semester labels, affected staff, and review information; expand it to edit an
individual item. **Collapse groups** and **Expand groups** change all group
headings together. Groups with
no matching items in the selected view are hidden.

Rename groups in Groups…. Removing a group detaches its members while preserving
every calendar item and its dates. To remove an individual calendar item, select
that item's row rather than the group heading.

**Linked coverage** is different: its offsets still move with its parent event.
Use that option when coverage should follow a deadline. Keep email coverage and
counter coverage as separate grouped items when their dates should be edited
independently; you can place your existing entries in the same group.

Existing calendar files load without being rewritten or requiring data re-entry.
The first explicit save uses format 5 and keeps the previous file in the existing
backup. Update all calendar users to app 0.18.0 or newer before editing the shared
calendar: older versions cannot read the semester format. Files in formats 1–4
remain readable by the updated app. Opening, filtering, and collapsing groups
never save or rewrite the calendar. No production calendar
entries are prefilled, moved, or grouped automatically.

## Semester colors

Choose **Semester (optional)** in **Add item** or **Edit schedule**. This identifies
the semester the work belongs to, independently of the date on which it occurs.
For example, a Spring balance's collections deadline in September is still Spring.
The choice applies to the recurring schedule and its linked coverage. Existing
entries start as **Not assigned**; titles, dates, and group names are never used
to guess a semester. **General / no semester** is an explicit choice, separate
from an entry that has not yet been classified.

| Semester | Mines color | Hex |
|---|---|---|
| Fall | Colorado Red | `#CC4628` |
| Spring | Blaster Blue | `#09396C` |
| Summer | Muted Blue | `#57A2BD` |
| General / no semester | Silver | `#81848A` |

These are owner-selected calendar meanings using the
[Mines digital palette](https://brand.mines.edu/fonts/), not institution-wide
semester conventions. The legend and item labels identify each semester;
unassigned entries retain the earlier blue deadline/light-blue coverage colors.
Filled marks still mean scheduled/reviewed; outlined marks still need date review.
Coverage bars are thinner than event bars. The red vertical line still marks today.
Changing only a semester retains existing date approvals, exceptions, reminder
lead times, recurrence, and staffing assignments. **Semester** filtering applies
to group summaries, detail rows, and the reminder list without changing data.

## Choose affected roles or people

Each item applies to **Everyone**, whole staff roles, or specific people beneath
those roles. In **Affects**, select **Admin** for the group, or expand it and
select a name to assign **Admin — Josh**, for example. Staff Accountant works
the same way. You can select several people or roles for one item.

The roles
are the **View** assignments already maintained in **Staff access → Edit profile**;
they are separate from a user's descriptive job title. For example, an item
assigned to **Staff Accountant** applies to whoever currently has that view.
Whole-role selections apply to everyone currently in that role. Selecting an
individual applies only to that person within that role; it does not create a
new permission view or require completion tracking.

Adding, replacing, or revoking users updates role staffing when the calendar is
reopened or reloaded. A role without active users remains on its calendar items
with **no active staff**, so admins can cover or delegate it. Calendar role
assignments do not grant calendar access; the page remains Admin-only.
Named selections use the existing user's login, so display-name edits update
their calendar labels. If that user is revoked, removed, or moved to another
role, the selection stays visible as **unassigned**; edit the item to choose a
replacement person or its whole role. Individual selections are not silently
transferred to another user.
If a role is renamed or removed, edit the affected items to select its current
name; the previous assignment remains visible rather than being dropped.

## Add events and coverage

Choose **Add item** and enter a title, category, normal date, duration, reminder
lead time, affected roles/people or **Everyone**, and optional notes.
Assign a category in **Add item** or **Edit schedule**, using the **Category**
field. Choose an existing label, type a new one, or click **New category…** beside
the field and enter its name. Save the item to make that category available in
other item editors and the chart filter. The four starter suggestions are not a
limit; new categories are shared with the other admins through the saved calendar.
Categories describe events, such as Tuition, Payment Deadline, or Billing.
The **Affects** field separately selects roles or the people beneath them.
Billing details are comma-separated labels, such as **Late Fees, Holds**.

Repeat **One time**, **Every year**, or **Every month (selected months)**.
Optional recurrence end dates are inclusive. Future years populate when viewed;
there is no annual copy step. Monthly recurrence uses the original day each
month: the 31st clamps to February's last day and returns to the 31st in March.
An annual February 29 schedule returns to February 29 in leap years.

For billing on the 12th, select monthly recurrence and the applicable months.
Use separate schedules for month groups with different Late Fee/Hold rules,
or change labels and notes for just one occurrence using **Review / edit date**.
No institution billing or semester dates are prefilled or inferred.

Use **Add coverage** for periods around an event. Offsets are calendar days
relative to the actual event date, with both endpoints included. For example,
email coverage from **-21 to +7** and counter coverage from **-14 to 0** can have
different affected roles. Moving the deadline moves both linked periods.
Labels describe coverage demand; the app does not calculate staff availability
or construct employee shifts.

## Proposed dates and editing

Each schedule has its own weekend rule:

- **Propose next Monday** (default).
- **Keep college / normal date**, useful for externally set deadlines.
- **Propose previous Friday**.

Weekend adjustments show **Proposed — adjusted from a weekend; admin review
needed**. Routine dates follow the saved schedule without requiring an approval
for every month or year. **Keep college / normal date** also preserves weekend
dates without requesting an adjustment review. Holiday adjustments are manual;
no holiday calendar is assumed.

Select a row and choose **Review / edit date**, or double-click a timeline or
reminder row. Set the actual date and check **Date reviewed by an admin** to
approve it. Changing the date or duration clears that checkbox until reviewed
again. Dates always remain editable. Reviewing a date acknowledges the date,
not completion of the event or its related work.

**Edit schedule** changes the entire schedule or this occurrence and future
dates. Future-only changes preserve earlier occurrences and exceptions but
reset exceptions and approvals for the replaced future schedule. Entire-schedule
date-rule changes preserve exceptions that still belong to the pattern, clear
their date approvals, and remove exceptions outside the new pattern. Labels
and notes alone do not reset date approvals. Use occurrence editing when only
one year's date should change.

**Remove item** can omit one occurrence (including linked coverage), or remove
its entire schedule. Both require confirmation. Add the schedule again or
restore a backup if an item was removed by mistake.

## Read the chart and reminders

Use **Calendar view** to choose a full year or a three-month window, and filter
by category, role/person, or search text. **Sep–Nov (3 months)** shows September through November of the selected
year. **Nov–Jan (3 months)** begins in November of that year and ends in January
of the following year. **Full year** shows January through December. These are
display ranges and do not change event dates or recurrence. Everyone items
appear in every role/person filter. A person's filter also includes their whole
role's items, while a role filter includes its individually assigned items.
Each event and
linked coverage period has a row on a common date axis; bars at the same dates
show overlapping demand. One-day events use diamonds. Filled marks indicate
scheduled or reviewed dates, outlined marks indicate proposals needing review,
and the red line marks today.
Hover over a row for dates, affected people, labels, notes, and review details.

The home page shows an admin-only reminder summary. The calendar's reminders
show dates within each schedule's configured lead time, active coverage, dates
passed within the last seven days, date review needs, and unassigned roles or
people. Reminders follow role/person/category/search filters but are independent
of the chart's selected year. A passed date is not a claim that work is overdue
or incomplete. Reopen the page or use **Reload** to refresh dates and staff changes.

## Storage and synchronization

`operations_calendar.json` lives beside the shared `gui_access.json` in the
existing hidden Bursar OneDrive folder. Local/Mac review uses the same filename
beside the selected review policy. Calendar files, backups, and locks are
ignored by Git because they contain office planning information. No live calendar data
is created by installing this feature; the first save creates the file.

Reads and writes check the current administrator policy. Saves validate data,
reject locally visible stale changes, use a local exclusive save lock, write
through a temporary file, and keep the previous version in
`.operations_calendar.backup.json`. The backup is not loaded automatically.

OneDrive synchronization is asynchronous; the local lock and digest check are
not a distributed lock across different computers. Synchronize before editing,
avoid simultaneous/offline edits, and Reload after a conflict. Resolve OneDrive
conflict copies before continuing. If a save was interrupted and no admin is
saving, an admin can remove the leftover `operations_calendar.lock` and reload.
Department folder permissions remain the storage access boundary; app Admin
checks do not replace OneDrive permissions.

To restore a backup, close the calendar on other computers, copy the backup
over `operations_calendar.json`, allow OneDrive to synchronize, and reopen or
Reload. Restoring a backup replaces the current calendar with the preceding
saved version.

Earlier calendars with position assignments are read without changing the
source file. Positions convert to their assigned user's existing role, including
revoked users' retained profiles. A former position with no known user/role stays
visible as **Former position: … — no active staff**; edit the item or coverage to
choose a current role. The next explicit save writes the simpler role-based
format and backs up the earlier file, preserving schedules and date exceptions.
