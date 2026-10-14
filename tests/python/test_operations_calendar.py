"""Synthetic calendar dates, staffing, and persistence; no live shared writes."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from app.gui.services.operations_calendar import (
    Audience, CalendarConflictError, CalendarData, CalendarError, CalendarEvent,
    CalendarStore, CalendarGroup, Coverage, DateOverride, RolePerson, adjust_weekend,
    audience_labels, audience_matches, nominal_dates, occurrences, reminder_entries, replace_event, replace_future,
    replace_override, timeline_rows, unassigned_roles, unassigned_targets, assign_group, remove_group,
)


def synthetic_access_payload():
    return {
        "schemaVersion": 3, "metadata": {"ownerLogin": "ADMIN"}, "ownerProtection": None,
        "users": {
            "ADMIN": {"displayName": "Example Admin", "jobTitle": "Manager", "view": "administrator"},
            "STAFF": {"displayName": "Example Staff", "jobTitle": "Cashier", "view": "cashier"},
            "NEW": {"displayName": "Example Replacement", "jobTitle": "Cashier", "view": "cashier"},
        },
        "views": {"administrator": {"workflows": ["*"]}, "cashier": {"workflows": []}},
    }


class RecurrenceTests(unittest.TestCase):
    def event(self, **changes):
        return replace(CalendarEvent("billing", "Monthly billing", "Billing", date(2026, 1, 12),
                                     recurrence="monthly"), **changes)

    def test_monthly_billing_moves_weekend_to_monday_and_requires_review(self):
        data = CalendarData(events=(self.event(),))
        actual = occurrences(data, date(2026, 9, 1), date(2026, 9, 30))[0]
        self.assertEqual(actual.nominal, date(2026, 9, 12))
        self.assertEqual(actual.actual, date(2026, 9, 14))
        self.assertFalse(actual.approved)
        self.assertIn("adjusted from a weekend", actual.review_reason)

    def test_weekend_rules_are_per_event(self):
        weekend = date(2026, 9, 12)
        self.assertEqual(adjust_weekend(weekend, "keep"), weekend)
        self.assertEqual(adjust_weekend(weekend, "friday"), date(2026, 9, 11))
        self.assertEqual(adjust_weekend(date(2026, 9, 13), "monday"), date(2026, 9, 14))
        self.assertEqual(adjust_weekend(date(2026, 9, 14), "monday"), date(2026, 9, 14))

    def test_routine_recurrence_does_not_require_review_each_month(self):
        event = self.event()
        october = occurrences(CalendarData(events=(event,)), date(2026, 10, 1), date(2026, 10, 31))[0]
        self.assertFalse(october.needs_review)
        self.assertFalse(october.approved)
        self.assertIn("follows the normal date", october.review_reason)
        college = self.event(anchor=date(2026, 9, 12), recurrence="annual", weekend="keep")
        fixed = occurrences(CalendarData(events=(college,)), date(2026, 9, 1), date(2026, 9, 30))[0]
        self.assertFalse(fixed.needs_review)
        self.assertEqual(fixed.actual, college.anchor)

    def test_editing_only_occurrence_notes_does_not_add_date_review(self):
        event = self.event()
        data = CalendarData(events=(event,), overrides=(DateOverride(
            event.id, date(2026, 10, 12), date(2026, 10, 12), notes="Holds this month", tags=("Holds",)),))
        october = occurrences(data, date(2026, 10, 1), date(2026, 10, 31))[0]
        self.assertFalse(october.needs_review)
        self.assertEqual(october.tags, ("Holds",))

    def test_month_end_clamp_does_not_drift(self):
        dates = nominal_dates(self.event(anchor=date(2027, 1, 31)), date(2027, 1, 1), date(2027, 4, 30))
        self.assertEqual(dates, (date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31), date(2027, 4, 30)))

    def test_annual_leap_day_recovers_in_next_leap_year(self):
        dates = nominal_dates(self.event(anchor=date(2024, 2, 29), recurrence="annual"),
                              date(2025, 1, 1), date(2028, 12, 31))
        self.assertEqual(dates, (date(2025, 2, 28), date(2026, 2, 28), date(2027, 2, 28), date(2028, 2, 29)))

    def test_selected_months_and_until_define_billing_population(self):
        event = self.event(months=(2, 4, 8), until=date(2026, 4, 12), tags=("Late Fees", "Holds"))
        dates = nominal_dates(event, date(2025, 1, 1), date(2030, 12, 31))
        self.assertEqual(dates, (date(2026, 2, 12), date(2026, 4, 12)))

    def test_approved_override_moves_coverage_and_keeps_next_year_pattern(self):
        coverage = Coverage("counter", "Dual counter coverage", -14, 0)
        event = self.event(recurrence="annual", anchor=date(2026, 9, 12), coverage=(coverage,))
        data = replace_override(CalendarData(events=(event,)), DateOverride(
            event.id, date(2026, 9, 12), date(2026, 9, 16), True, tags=("Late Fees",)))
        actual = occurrences(data, date(2026, 9, 1), date(2026, 9, 30))[0]
        self.assertTrue(actual.approved)
        self.assertEqual(timeline_rows(actual)[1].start, date(2026, 9, 2))
        self.assertEqual(timeline_rows(actual)[1].end, date(2026, 9, 16))
        future = occurrences(data, date(2027, 9, 1), date(2027, 9, 30))[0]
        self.assertEqual(future.nominal, date(2027, 9, 12))
        self.assertFalse(future.approved)

    def test_coverage_spanning_year_boundary_is_included(self):
        event = self.event(recurrence="annual", anchor=date(2026, 1, 12),
                           coverage=(Coverage("email", "Extra email coverage", -21, 7),))
        actual = occurrences(CalendarData(events=(event,)), date(2025, 12, 1), date(2025, 12, 31))
        self.assertEqual(len(actual), 1)
        self.assertEqual(timeline_rows(actual[0])[1].start, date(2025, 12, 22))

    def test_override_moved_into_a_different_year_is_not_lost(self):
        event = self.event(anchor=date(2026, 1, 12), recurrence="annual")
        data = CalendarData(events=(event,), overrides=(DateOverride(
            event.id, date(2026, 1, 12), date(2025, 12, 30), True),))
        result = occurrences(data, date(2025, 12, 1), date(2025, 12, 31))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].actual, date(2025, 12, 30))

    def test_skip_one_occurrence_preserves_following_dates(self):
        event = self.event()
        data = CalendarData(events=(event,), overrides=(DateOverride(
            event.id, date(2026, 2, 12), date(2026, 2, 12), hidden=True),))
        result = occurrences(data, date(2026, 1, 1), date(2026, 3, 31))
        self.assertEqual([o.nominal.month for o in result], [1, 3])

    def test_edit_future_preserves_past_exception(self):
        event = self.event()
        data = CalendarData(events=(event,), overrides=(
            DateOverride(event.id, date(2026, 1, 12), date(2026, 1, 13), True),
            DateOverride(event.id, date(2026, 3, 12), date(2026, 3, 17), True),
        ))
        february = occurrences(data, date(2026, 2, 1), date(2026, 2, 28))[0]
        new = replace(event, id="new", anchor=date(2026, 2, 15))
        result = replace_future(data, february, new)
        dates = occurrences(result, date(2026, 1, 1), date(2026, 3, 31))
        self.assertEqual([o.nominal for o in dates], [date(2026, 1, 12), date(2026, 2, 15), date(2026, 3, 15)])
        self.assertEqual(result.overrides, data.overrides[:1])
        self.assertTrue(dates[0].approved)

    def test_series_edit_removes_exceptions_outside_new_pattern(self):
        event = self.event()
        data = CalendarData(events=(event,), overrides=(DateOverride(
            event.id, date(2026, 2, 12), date(2026, 2, 13), True),))
        result = replace_event(data, replace(event, months=(1, 3)))
        self.assertEqual(result.overrides, ())

    def test_future_edit_from_first_date_resets_exceptions(self):
        event = self.event()
        data = CalendarData(events=(event,), overrides=(DateOverride(
            event.id, event.anchor, date(2026, 1, 13), True),))
        first = occurrences(data, date(2026, 1, 1), date(2026, 1, 31))[0]
        updated = replace_future(data, first, replace(event, id="new", anchor=date(2026, 1, 15)))
        self.assertEqual(len(updated.events), 1)
        self.assertEqual(updated.overrides, ())

    def test_date_rule_change_resets_review_but_notes_change_preserves_it(self):
        event = self.event()
        data = CalendarData(events=(event,), overrides=(DateOverride(
            event.id, event.anchor, date(2026, 1, 13), True),))
        notes = replace_event(data, replace(event, notes="New planning note"))
        self.assertTrue(notes.overrides[0].approved)
        rule = replace_event(data, replace(event, weekend="keep"))
        self.assertFalse(rule.overrides[0].approved)
        self.assertEqual(rule.overrides[0].actual, date(2026, 1, 13))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.access_path = self.root / "gui_access.json"
        self.policy = synthetic_access_payload()
        self.write_policy()
        self.store = CalendarStore(self.access_path, "ADMIN")

    def write_policy(self):
        self.access_path.write_text(json.dumps(self.policy), encoding="utf-8")

    def data(self):
        audience = Audience(False, ("cashier",))
        return CalendarData(
            events=(CalendarEvent("deadline", "Payment deadline", "Tuition", date(2026, 9, 12),
                                  recurrence="annual", audience=audience,
                                  coverage=(Coverage("extra", "Dual coverage", -14, 7, audience),)),),
        )

    def test_first_load_is_empty_without_creating_file(self):
        self.assertEqual(self.store.load(), CalendarData())
        self.assertFalse(self.store.path.exists())

    def test_round_trip_metadata_and_backup(self):
        saved = self.store.save(self.data())
        self.assertEqual(saved.events, self.data().events)
        self.assertEqual(saved.updated_by, "ADMIN")
        self.assertIsNotNone(saved.source_digest)
        old = self.store.path.read_bytes()
        self.store.save(replace(saved, events=(replace(saved.events[0], notes="Updated note"),)))
        self.assertEqual((self.root / ".operations_calendar.backup.json").read_bytes(), old)
        self.assertFalse(self.store.path.with_suffix(".lock").exists())
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_stale_admin_edits_are_rejected(self):
        saved = self.store.save(self.data())
        self.store.save(replace(saved, events=(replace(saved.events[0], notes="Updated note"),)))
        before = self.store.path.read_bytes()
        with self.assertRaises(CalendarConflictError):
            self.store.save(saved)
        self.assertEqual(before, self.store.path.read_bytes())

    def test_concurrent_initial_creation_rejected(self):
        empty = self.store.load()
        self.store.save(self.data())
        with self.assertRaises(CalendarConflictError):
            self.store.save(empty)

    def test_existing_local_lock_rejected_without_removing_lock(self):
        lock = self.store.path.with_suffix(".lock")
        lock.write_text("", encoding="utf-8")
        with self.assertRaises(CalendarConflictError):
            self.store.save(self.data())
        self.assertTrue(lock.exists())

    def test_non_admin_cannot_read_or_write(self):
        staff = CalendarStore(self.access_path, "STAFF")
        with self.assertRaisesRegex(CalendarError, "active administrator"):
            staff.load()
        with self.assertRaises(CalendarError):
            staff.save(self.data())
        self.assertFalse(self.store.path.exists())

    def test_revocation_after_page_loaded_prevents_save(self):
        saved = self.store.save(self.data())
        self.policy["users"]["SECOND"] = dict(self.policy["users"]["ADMIN"])
        self.policy["users"]["ADMIN"]["active"] = False
        self.write_policy()
        with self.assertRaises(CalendarError):
            self.store.save(saved)

    def test_role_assignments_follow_current_staff_without_editing_calendar(self):
        saved = self.store.save(self.data())
        audience = saved.events[0].audience
        self.assertEqual(audience_labels(audience, self.store.access()), ("Cashier",))
        self.policy["users"]["STAFF"]["active"] = False
        self.write_policy()
        self.assertEqual(unassigned_roles(audience, self.store.access()), ())
        self.policy["users"]["NEW"]["active"] = False
        self.write_policy()
        self.assertEqual(unassigned_roles(audience, self.store.access()), ("cashier",))
        self.assertEqual(audience_labels(audience, self.store.access()), ("Cashier — no active staff",))
        self.policy["users"]["NEW"]["active"] = True
        self.write_policy()
        self.assertEqual(unassigned_roles(audience, self.store.access()), ())
        self.assertEqual(self.store.load().events, saved.events)
        del self.policy["users"]["NEW"]
        self.write_policy()
        self.assertEqual(unassigned_roles(audience, self.store.access()), ("cashier",))

    def test_invalid_configuration_never_overwrites_valid_data(self):
        saved = self.store.save(self.data())
        invalid = (
            replace(saved, events=(replace(saved.events[0], duration=0),)),
            replace(saved, events=(replace(saved.events[0], audience=Audience(False)),)),
            replace(saved, events=(replace(saved.events[0], audience=Audience(False, ("cashier", "cashier"))),)),
            replace(saved, events=(replace(saved.events[0], coverage=(Coverage("bad", "Bad", 5, -5),)),)),
            replace(saved, events=(replace(saved.events[0], recurrence="weekly"),)),
            replace(saved, overrides=(DateOverride("missing", date(2026, 1, 1), date(2026, 1, 1)),)),
        )
        before = self.store.path.read_bytes()
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(CalendarError):
                self.store.save(data)
            self.assertEqual(before, self.store.path.read_bytes())

    def test_malformed_file_is_not_replaced_with_empty_calendar(self):
        self.store.path.write_text("broken JSON", encoding="utf-8")
        with self.assertRaises(CalendarError):
            self.store.load()
        with self.assertRaises(CalendarError):
            self.store.save(self.data())
        self.assertEqual(self.store.path.read_text(), "broken JSON")

    def test_reminders_are_date_based_without_completion_statuses(self):
        data = self.data()
        access = self.store.access()
        entries = reminder_entries(data, access, date(2026, 9, 15))
        deadline = next(message for row, message in entries if not row.coverage)
        self.assertIn("Date passed", deadline)
        self.assertNotIn("overdue", deadline.casefold())
        self.assertFalse(any(not row.coverage for row, _ in
                             reminder_entries(data, access, date(2026, 9, 22))))
        self.assertTrue(any(row.coverage for row, _ in entries))

    def test_reminder_lead_time_is_applied_to_coverage_start(self):
        data = self.data()
        entries = reminder_entries(data, self.store.access(), date(2026, 8, 10))
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0][0].coverage)
        self.assertIn("Upcoming in 21 day(s)", entries[0][1])

    def legacy_calendar(self, *, login="staff"):
        self.store.save(replace_override(self.data(), DateOverride(
            "deadline", date(2026, 9, 12), date(2026, 9, 14), True, tags=("Reviewed date",))))
        payload = json.loads(self.store.path.read_text())
        payload["schemaVersion"] = 1
        payload["positions"] = [{"id": "counter", "name": "Counter lead", "login": login}]
        event = payload["events"][0]
        event["audience"] = {"everyone": False, "positions": ["counter"], "views": []}
        event["coverage"][0]["audience"] = event["audience"].copy()
        self.store.path.write_text(json.dumps(payload), encoding="utf-8")
        return self.store.path.read_bytes()

    def test_earlier_calendar_positions_migrate_to_assigned_users_roles(self):
        original = self.legacy_calendar()
        data = self.store.load()
        self.assertEqual(data.events[0].audience, Audience(False, ("cashier",)))
        self.assertEqual(data.events[0].coverage[0].audience, Audience(False, ("cashier",)))
        self.assertTrue(data.overrides[0].approved)
        self.assertEqual(data.overrides[0].actual, date(2026, 9, 14))
        self.assertEqual(self.store.path.read_bytes(), original)
        self.store.save(data)
        payload = json.loads(self.store.path.read_text())
        self.assertEqual(payload["schemaVersion"], 4)
        self.assertNotIn("positions", payload)
        self.assertEqual((self.root / ".operations_calendar.backup.json").read_bytes(), original)

    def test_earlier_vacant_positions_remain_visible_without_guessing_role(self):
        self.legacy_calendar(login=None)
        data = self.store.load()
        audience = data.events[0].audience
        self.assertFalse(audience.everyone)
        self.assertEqual(audience.views, ("Former position: Counter lead",))
        self.assertEqual(unassigned_roles(audience, self.store.access()), audience.views)
        self.store.save(data)
        self.assertEqual(self.store.load().events, data.events)

    def test_unknown_role_is_retained_as_unstaffed_after_role_removal(self):
        saved = self.store.save(self.data())
        self.policy["users"]["STAFF"]["view"] = "administrator"
        self.policy["users"]["NEW"]["view"] = "administrator"
        del self.policy["views"]["cashier"]
        self.write_policy()
        self.assertEqual(unassigned_roles(saved.events[0].audience, self.store.access()), ("cashier",))
        self.assertEqual(self.store.load().events, saved.events)

    def test_person_assignment_round_trip_and_filters(self):
        data = self.data()
        audience = Audience(False, people=(RolePerson("cashier", "staff"),))
        saved = self.store.save(replace(data, events=(replace(data.events[0], audience=audience),)))
        self.assertEqual(saved.events[0].audience, audience)
        self.assertEqual(audience_labels(audience, self.store.access()), ("Cashier — Example Staff",))
        self.assertTrue(audience_matches(audience, "cashier"))
        self.assertTrue(audience_matches(audience, "cashier", "STAFF"))
        self.assertFalse(audience_matches(audience, "cashier", "new"))
        self.assertTrue(audience_matches(Audience(False, ("cashier",)), "cashier", "new"))
        self.assertTrue(audience_matches(Audience(), "administrator", "admin"))

    def test_person_name_updates_and_role_changes_leave_assignment_visible(self):
        audience = Audience(False, people=(RolePerson("cashier", "staff"),))
        self.policy["users"]["STAFF"]["displayName"] = "Example Renamed"
        self.write_policy()
        self.assertEqual(audience_labels(audience, self.store.access()), ("Cashier — Example Renamed",))
        self.policy["users"]["STAFF"]["view"] = "administrator"
        self.write_policy()
        self.assertEqual(unassigned_targets(audience, self.store.access()), ("Cashier — Example Renamed",))
        self.assertIn("unassigned", audience_labels(audience, self.store.access())[0])
        del self.policy["users"]["STAFF"]
        self.write_policy()
        self.assertEqual(unassigned_targets(audience, self.store.access()), ("Cashier — staff",))

    def test_revoked_person_stays_unassigned_even_when_role_has_other_staff(self):
        audience = Audience(False, people=(RolePerson("cashier", "staff"),))
        self.policy["users"]["STAFF"]["active"] = False
        self.write_policy()
        self.assertEqual(unassigned_roles(audience, self.store.access()), ())
        self.assertEqual(unassigned_targets(audience, self.store.access()), ("Cashier — Example Staff",))

    def test_invalid_person_selections_are_rejected_without_overwriting(self):
        saved = self.store.save(self.data())
        before = self.store.path.read_bytes()
        person = RolePerson("cashier", "staff")
        for audience in (Audience(True, people=(person,)),
                         Audience(False, ("cashier",), (person,)),
                         Audience(False, people=(person, person)),
                         Audience(False, people=(RolePerson("cashier", ""),))):
            with self.subTest(audience=audience), self.assertRaises(CalendarError):
                self.store.save(replace(saved, events=(replace(saved.events[0], audience=audience),)))
            self.assertEqual(self.store.path.read_bytes(), before)

    def test_role_only_format_is_read_without_rewriting_or_adding_people(self):
        saved = self.store.save(self.data())
        payload = json.loads(self.store.path.read_text())
        payload["schemaVersion"] = 2
        for event in payload["events"]:
            for item in (event, *event["coverage"]):
                item["audience"].pop("people")
        self.store.path.write_text(json.dumps(payload))
        before = self.store.path.read_bytes()
        loaded = self.store.load()
        self.assertEqual(loaded.events, saved.events)
        self.assertEqual(self.store.path.read_bytes(), before)

    def pci_data(self):
        return CalendarData(events=(
            CalendarEvent("review", "Review PCI Materials", "PCI", date(2026, 3, 1), recurrence="annual", duration=7),
            CalendarEvent("email", "PCI Announcement", "PCI", date(2026, 3, 15), recurrence="annual"),
            CalendarEvent("quiz", "PCI Quiz Window", "PCI", date(2026, 4, 1), recurrence="annual", duration=30),
        ), groups=(CalendarGroup("pci", "Annual PCI Cycle"),))

    def test_grouping_existing_items_preserves_dates_recurrence_and_exceptions(self):
        data = self.pci_data()
        data = replace_override(data, DateOverride("quiz", date(2026, 4, 1), date(2026, 4, 2), True, duration=30))
        grouped = assign_group(data, "pci", frozenset(e.id for e in data.events))
        self.assertEqual(tuple(replace(e, group_id=None) for e in grouped.events), data.events)
        self.assertEqual(grouped.overrides, data.overrides)
        saved = self.store.save(grouped)
        self.assertEqual(saved.events, grouped.events)
        self.assertEqual(saved.groups, grouped.groups)

    def test_shortening_and_moving_review_leaves_quiz_and_other_dates_unchanged(self):
        data = assign_group(self.pci_data(), "pci", frozenset({"review", "email", "quiz"}))
        before = occurrences(data, date(2026, 1, 1), date(2027, 12, 31))
        changed = replace_event(data, replace(data.events[0], anchor=date(2026, 3, 10), duration=1))
        after = occurrences(changed, date(2026, 1, 1), date(2027, 12, 31))
        self.assertEqual([o for o in before if o.event.id != "review"],
                         [o for o in after if o.event.id != "review"])
        self.assertEqual([entry for entry in reminder_entries(data, self.store.access(), date(2026, 4, 1))
                          if entry[0].occurrence.event.id != "review"],
                         [entry for entry in reminder_entries(changed, self.store.access(), date(2026, 4, 1))
                          if entry[0].occurrence.event.id != "review"])
        review = next(o for o in after if o.event.id == "review")
        self.assertEqual(review.end, review.actual)

    def test_review_date_exception_does_not_move_other_group_members(self):
        data = assign_group(self.pci_data(), "pci", frozenset({"review", "email", "quiz"}))
        changed = replace_override(data, DateOverride("review", date(2026, 3, 1), date(2026, 3, 25), True))
        before = occurrences(data, date(2026, 1, 1), date(2026, 12, 31))
        after = occurrences(changed, date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual([o for o in before if o.event.id != "review"],
                         [o for o in after if o.event.id != "review"])

    def test_removing_or_renaming_group_preserves_events_and_approvals(self):
        data = assign_group(self.pci_data(), "pci", frozenset({"review", "quiz"}))
        data = replace_override(data, DateOverride("quiz", date(2026, 4, 1), date(2026, 4, 2), True, duration=30))
        renamed = replace(data, groups=(CalendarGroup("pci", "PCI Training"),))
        saved = self.store.save(renamed)
        self.assertEqual(saved.events, data.events)
        self.assertEqual(saved.overrides, data.overrides)
        removed = remove_group(data, "pci")
        self.assertEqual(removed.groups, ())
        self.assertEqual(removed.events, self.pci_data().events)
        self.assertEqual(removed.overrides, data.overrides)

    def test_invalid_groups_never_overwrite_valid_calendar(self):
        saved = self.store.save(self.pci_data())
        before = self.store.path.read_bytes()
        for invalid in (replace(saved, groups=saved.groups * 2),
                        replace(saved, groups=(*saved.groups, CalendarGroup("other", "ANNUAL PCI CYCLE"))),
                        replace(saved, groups=(CalendarGroup("pci", ""),)),
                        replace(saved, events=(replace(saved.events[0], group_id="missing"),))):
            with self.subTest(data=invalid), self.assertRaises(CalendarError):
                self.store.save(invalid)
            self.assertEqual(self.store.path.read_bytes(), before)
        with self.assertRaises(CalendarError):
            assign_group(saved, "missing", frozenset({"review"}))
        with self.assertRaises(CalendarError):
            assign_group(saved, "pci", frozenset({"missing"}))

    def test_current_work_pc_format_loads_without_rewriting_and_keeps_backup_on_save(self):
        saved = self.store.save(self.data())
        payload = json.loads(self.store.path.read_text())
        payload["schemaVersion"] = 3
        payload.pop("groups")
        for event in payload["events"]:
            event.pop("group_id")
        self.store.path.write_text(json.dumps(payload), encoding="utf-8")
        before = self.store.path.read_bytes()
        loaded = self.store.load()
        self.assertEqual(loaded.events, saved.events)
        self.assertEqual(loaded.groups, ())
        self.assertEqual(self.store.path.read_bytes(), before)
        new = replace(loaded, groups=(CalendarGroup("fall", "Fall Payment Deadline"),))
        self.store.save(assign_group(new, "fall", frozenset(e.id for e in new.events)))
        self.assertEqual((self.root / ".operations_calendar.backup.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
