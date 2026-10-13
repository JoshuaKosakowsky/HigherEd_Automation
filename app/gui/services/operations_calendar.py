"""Admin Bursar Office Calendar, recurrence, coverage, and shared persistence.

Nominal dates identify occurrences. Actual dates and approvals are exceptions,
so moving a deadline also moves coverage without changing next year's pattern.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.gui.services.access import AccessConfiguration, load_access_configuration
from shared.mines_paths import ensure_hidden_directory


class CalendarError(ValueError):
    """Invalid calendar data or unauthorized operation."""


class CalendarConflictError(CalendarError):
    """An administrator must reload before saving again."""


@dataclass(frozen=True)
class RolePerson:
    view: str
    login: str


@dataclass(frozen=True)
class Audience:
    everyone: bool = True
    views: tuple[str, ...] = ()
    people: tuple[RolePerson, ...] = ()


@dataclass(frozen=True)
class Coverage:
    id: str
    title: str
    start_offset: int
    end_offset: int
    audience: Audience = Audience()


@dataclass(frozen=True)
class CalendarEvent:
    id: str
    title: str
    category: str
    anchor: date
    recurrence: str = "once"
    months: tuple[int, ...] = tuple(range(1, 13))
    until: date | None = None
    weekend: str = "monday"
    duration: int = 1
    reminder_days: int = 21
    audience: Audience = Audience()
    tags: tuple[str, ...] = ()
    notes: str = ""
    coverage: tuple[Coverage, ...] = ()


@dataclass(frozen=True)
class DateOverride:
    event_id: str
    nominal: date
    actual: date
    approved: bool = False
    duration: int = 1
    tags: tuple[str, ...] = ()
    notes: str = ""
    hidden: bool = False


@dataclass(frozen=True)
class CalendarData:
    events: tuple[CalendarEvent, ...] = ()
    overrides: tuple[DateOverride, ...] = ()
    source_digest: str | None = None
    updated_by: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class Occurrence:
    event: CalendarEvent
    nominal: date
    actual: date
    end: date
    approved: bool
    needs_review: bool
    tags: tuple[str, ...]
    notes: str

    @property
    def review_reason(self) -> str:
        if self.approved:
            return "Date reviewed"
        if not self.needs_review:
            return "Scheduled — follows the normal date"
        if self.actual != self.nominal and self.nominal.weekday() >= 5:
            return "Proposed — adjusted from a weekend; admin review needed"
        return "Proposed — admin date review needed"


@dataclass(frozen=True)
class TimelineRow:
    occurrence: Occurrence
    title: str
    start: date
    end: date
    audience: Audience
    coverage: bool = False


def calendar_path(access_path: Path) -> Path:
    return access_path.with_name("operations_calendar.json")


def _text(value: object, name: str, *, empty: bool = False, limit: int = 200) -> str:
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise CalendarError(f"Invalid {name}.")
    return value.strip()


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise CalendarError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise CalendarError(f"Invalid {name}.")
    return value


def _date(value: object) -> date:
    try:
        day = date.fromisoformat(value)
    except (ValueError, TypeError) as error:
        raise CalendarError("Invalid calendar date.") from error
    if not 1900 <= day.year <= 2199:
        raise CalendarError("Calendar dates must be between 1900 and 2199.")
    return day


def _list(value: object) -> list:
    if not isinstance(value, list):
        raise CalendarError("Expected a calendar list.")
    return value


def _strings(value: object, name: str) -> tuple[str, ...]:
    result = tuple(_text(item, name) for item in _list(value))
    if len(set(result)) != len(result):
        raise CalendarError(f"Duplicate {name}.")
    return result


def _audience(value: object) -> Audience:
    if not isinstance(value, dict):
        raise CalendarError("Invalid affected staff.")
    audience = Audience(
        _boolean(value.get("everyone", True), "Everyone selection"),
        _strings(value.get("views", []), "view"),
        tuple(RolePerson(_text(item["view"], "person's role"),
                         _text(item["login"], "person's login").casefold())
              for item in _list(value.get("people", []))),
    )
    if len(set(audience.people)) != len(audience.people):
        raise CalendarError("Duplicate role/person selection.")
    if any(person.view in audience.views for person in audience.people):
        raise CalendarError("Choose a whole role or individual people within it, rather than both.")
    if not audience.everyone and not (audience.views or audience.people):
        raise CalendarError("Choose Everyone, a role, or a person within a role.")
    if audience.everyone and (audience.views or audience.people):
        raise CalendarError("Everyone cannot be combined with selected roles or people.")
    return audience


def _migrate_positions(payload: dict, access: AccessConfiguration) -> dict:
    """Preserve earlier calendars while converting staff positions to roles.

    A vacancy with no known role stays explicitly unresolved. Never broaden a
    specific assignment to Everyone merely because its former user is gone.
    """
    payload = json.loads(json.dumps(payload))
    positions = {}
    for item in _list(payload.get("positions", [])):
        key = _text(item["id"], "position ID")
        name = _text(item["name"], "position name")
        login = _text(item["login"], "login") if item.get("login") else None
        profile = access.raw_profile_for_login(login)
        if key in positions:
            raise CalendarError("Duplicate position ID in the earlier calendar.")
        positions[key] = profile.view if profile else f"Former position: {name[:175]}"
    for event in _list(payload.get("events", [])):
        for owner in [event, *_list(event.get("coverage", []))]:
            audience = owner["audience"]
            old = _strings(audience.pop("positions", []), "position")
            if any(key not in positions for key in old):
                raise CalendarError("An earlier calendar item refers to an unknown position.")
            audience["views"] = list(dict.fromkeys([
                *_strings(audience.get("views", []), "view"), *(positions[key] for key in old),
            ]))
    payload.pop("positions", None)
    payload["schemaVersion"] = 2
    return payload


def _unique_ids(items: tuple, description: str) -> None:
    ids = [item.id for item in items]
    if len(set(ids)) != len(ids):
        raise CalendarError(f"Duplicate {description} ID.")


def _parse(payload: object, digest: str | None, access: AccessConfiguration | None = None) -> CalendarData:
    try:
        if not isinstance(payload, dict) or payload.get("schemaVersion") not in (1, 2, 3):
            raise CalendarError("Unsupported Bursar Office Calendar format.")
        if payload["schemaVersion"] == 1:
            if access is None:
                raise CalendarError("Staff access is required to convert the earlier calendar.")
            payload = _migrate_positions(payload, access)
        events = []
        for item in _list(payload.get("events", [])):
            coverage = tuple(Coverage(
                _text(c["id"], "coverage ID"), _text(c["title"], "coverage title"),
                _integer(c["start_offset"], "Coverage start offset", -366, 366),
                _integer(c["end_offset"], "Coverage end offset", -366, 366),
                _audience(c["audience"]),
            ) for c in _list(item.get("coverage", [])))
            _unique_ids(coverage, "coverage")
            if any(c.start_offset > c.end_offset for c in coverage):
                raise CalendarError("Coverage cannot end before it starts.")
            months = tuple(_integer(m, "Month", 1, 12) for m in _list(item["months"]))
            if not months or len(set(months)) != len(months):
                raise CalendarError("Select distinct recurrence months.")
            event = CalendarEvent(
                _text(item["id"], "event ID"), _text(item["title"], "title"),
                _text(item["category"], "category"), _date(item["anchor"]),
                _text(item["recurrence"], "recurrence"), months,
                _date(item["until"]) if item.get("until") else None,
                _text(item["weekend"], "weekend rule"),
                _integer(item["duration"], "Duration", 1, 366),
                _integer(item["reminder_days"], "Reminder lead time", 0, 366),
                _audience(item["audience"]),
                _strings(item.get("tags", []), "billing detail"),
                _text(item.get("notes", ""), "notes", empty=True, limit=4000), coverage,
            )
            if event.recurrence not in ("once", "annual", "monthly"):
                raise CalendarError("Invalid recurrence.")
            if event.weekend not in ("keep", "monday", "friday"):
                raise CalendarError("Invalid weekend rule.")
            if event.until and event.until < event.anchor:
                raise CalendarError("Recurrence end cannot precede its first date.")
            events.append(event)
        events = tuple(events)
        _unique_ids(events, "event")
        event_map = {e.id: e for e in events}
        overrides = []
        for item in _list(payload.get("overrides", [])):
            override = DateOverride(
                _text(item["event_id"], "event ID"), _date(item["nominal"]), _date(item["actual"]),
                _boolean(item["approved"], "date approval"),
                _integer(item["duration"], "Duration", 1, 366),
                _strings(item.get("tags", []), "billing detail"),
                _text(item.get("notes", ""), "notes", empty=True, limit=4000),
                _boolean(item.get("hidden", False), "hidden occurrence"),
            )
            event = event_map.get(override.event_id)
            if event is None or override.nominal not in nominal_dates(event, override.nominal, override.nominal):
                raise CalendarError("A date exception no longer belongs to its recurring schedule.")
            overrides.append(override)
        if len({(o.event_id, o.nominal) for o in overrides}) != len(overrides):
            raise CalendarError("Duplicate date exception.")
        return CalendarData(events, tuple(overrides), digest,
                            payload.get("updatedBy"), payload.get("updatedAt"))
    except (KeyError, TypeError, AttributeError) as error:
        raise CalendarError("The Bursar Office Calendar contains malformed data.") from error


def _payload(data: CalendarData, actor: str) -> dict:
    def dates(value):
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, dict):
            return {k: dates(v) for k, v in value.items()}
        if isinstance(value, (tuple, list)):
            return [dates(v) for v in value]
        return value

    return {
        "schemaVersion": 3,
        "events": dates([asdict(e) for e in data.events]),
        "overrides": dates([asdict(o) for o in data.overrides]),
        "updatedBy": actor,
        "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def nominal_dates(event: CalendarEvent, start: date, end: date) -> tuple[date, ...]:
    """Expand from the original day; a February clamp never drifts March's date."""
    start = max(start, event.anchor)
    end = min(end, event.until or end)
    if start > end:
        return ()
    if event.recurrence == "once":
        return (event.anchor,) if start <= event.anchor <= end else ()
    result = []
    for year in range(start.year, end.year + 1):
        months = (event.anchor.month,) if event.recurrence == "annual" else event.months
        for month in sorted(months):
            day = min(event.anchor.day, calendar.monthrange(year, month)[1])
            candidate = date(year, month, day)
            if start <= candidate <= end:
                result.append(candidate)
    return tuple(result)


def adjust_weekend(day: date, rule: str) -> date:
    if day.weekday() < 5 or rule == "keep":
        return day
    if rule == "monday":
        return day + timedelta(days=7 - day.weekday())
    return day - timedelta(days=day.weekday() - 4)


def occurrences(data: CalendarData, start: date, end: date) -> tuple[Occurrence, ...]:
    """Include linked coverage and exceptions moved into the requested window."""
    overrides = {(o.event_id, o.nominal): o for o in data.overrides}
    result = []
    for event in data.events:
        before = max([event.duration - 1, 0] + [c.end_offset for c in event.coverage])
        after = max([0] + [-c.start_offset for c in event.coverage])
        low = max(date.min, start - timedelta(days=min(before + 3, (start - date.min).days)))
        high = min(date.max, end + timedelta(days=min(after + 3, (date.max - end).days)))
        dates = set(nominal_dates(event, low, high))
        dates.update(o.nominal for o in data.overrides if o.event_id == event.id)
        for nominal in sorted(dates):
            override = overrides.get((event.id, nominal))
            if override and override.hidden:
                continue
            actual = override.actual if override else adjust_weekend(nominal, event.weekend)
            duration = override.duration if override else event.duration
            occurrence = Occurrence(
                event, nominal, actual, actual + timedelta(days=duration - 1),
                override.approved if override else False,
                (not override.approved and (actual != nominal or
                 actual != adjust_weekend(nominal, event.weekend) or duration != event.duration))
                if override else actual != nominal,
                override.tags if override else event.tags, override.notes if override else event.notes,
            )
            if any(row.start <= end and row.end >= start for row in timeline_rows(occurrence)):
                result.append(occurrence)
    return tuple(sorted(result, key=lambda o: (o.actual, o.event.title.casefold(), o.event.id)))


def timeline_rows(occurrence: Occurrence) -> tuple[TimelineRow, ...]:
    event = occurrence.event
    rows = [TimelineRow(occurrence, event.title, occurrence.actual, occurrence.end, event.audience)]
    rows.extend(TimelineRow(
        occurrence, c.title, occurrence.actual + timedelta(days=c.start_offset),
        occurrence.actual + timedelta(days=c.end_offset), c.audience, True,
    ) for c in event.coverage)
    return tuple(rows)


def audience_labels(audience: Audience, access: AccessConfiguration) -> tuple[str, ...]:
    if audience.everyone:
        return ("Everyone",)
    vacant = unassigned_roles(audience, access)
    roles = tuple(f"{role_label(view)} — no active staff" if view in vacant else role_label(view)
                  for view in audience.views)
    people = tuple(person_label(person, access) + (" — unassigned" if not person_available(person, access) else "")
                   for person in audience.people)
    return roles + people


def role_label(view: str) -> str:
    return "Admin" if view == "administrator" else view.title()


def person_label(person: RolePerson, access: AccessConfiguration) -> str:
    profile = access.raw_profile_for_login(person.login)
    return f"{role_label(person.view)} — {profile.display_name if profile else person.login}"


def person_available(person: RolePerson, access: AccessConfiguration) -> bool:
    profile = access.profile_for_login(person.login)
    return profile is not None and profile.view == person.view


def audience_matches(audience: Audience, view: str, login: str | None = None) -> bool:
    """A person filter also includes deadlines that affect their whole role."""
    return (audience.everyone or view in audience.views or
            any(person.view == view and (login is None or person.login == login.casefold())
                for person in audience.people))


def unassigned_roles(audience: Audience, access: AccessConfiguration) -> tuple[str, ...]:
    active_views = {profile.view for profile in access.users.values() if profile.active}
    return tuple(view for view in audience.views
                 if view not in access.workflows_by_view or view not in active_views)


def unassigned_targets(audience: Audience, access: AccessConfiguration) -> tuple[str, ...]:
    return (tuple(role_label(view) for view in unassigned_roles(audience, access)) +
            tuple(person_label(person, access) for person in audience.people
                  if not person_available(person, access)))


def reminder_entries(
    data: CalendarData, access: AccessConfiguration, today: date,
) -> tuple[tuple[TimelineRow, str], ...]:
    """Visual reminders based on dates, never an inferred completion status."""
    entries = []
    for occurrence in occurrences(data, today - timedelta(days=7), today + timedelta(days=366)):
        for row in timeline_rows(occurrence):
            days = (row.start - today).days
            if row.end < today - timedelta(days=7) or days > occurrence.event.reminder_days:
                continue
            if row.end < today:
                messages = ["Date passed"]
            elif row.start <= today <= row.end:
                messages = ["Today" if row.start == row.end else "Active coverage" if row.coverage else "Current period"]
            else:
                messages = [f"Upcoming in {days} day(s)"]
            if occurrence.needs_review:
                messages.append(occurrence.review_reason)
            vacant = unassigned_targets(row.audience, access)
            if vacant:
                messages.append("Unassigned: " + ", ".join(vacant))
            entries.append((row, "; ".join(messages)))
    return tuple(sorted(entries, key=lambda entry: (entry[0].start, entry[0].title)))


def replace_event(data: CalendarData, event: CalendarEvent) -> CalendarData:
    """A series edit resets exceptions only for dates removed by its new pattern."""
    events = tuple(event if e.id == event.id else e for e in data.events)
    if not any(e.id == event.id for e in data.events):
        events += (event,)
    previous = next((e for e in data.events if e.id == event.id), None)
    date_rules_changed = previous is not None and any(
        getattr(previous, field) != getattr(event, field)
        for field in ("anchor", "recurrence", "months", "until", "weekend", "duration")
    )
    overrides = tuple(replace(o, approved=False) if o.event_id == event.id and date_rules_changed else o
                      for o in data.overrides if o.event_id != event.id or
                      o.nominal in nominal_dates(event, o.nominal, o.nominal))
    return replace(data, events=events, overrides=overrides)


def replace_future(data: CalendarData, occurrence: Occurrence, event: CalendarEvent) -> CalendarData:
    """Split at a nominal date, preserving earlier dates and exceptions."""
    original = occurrence.event
    if occurrence.nominal == original.anchor:
        updated = replace_event(data, replace(event, id=original.id))
        return replace(updated, overrides=tuple(o for o in updated.overrides if o.event_id != original.id))
    past = replace(original, until=occurrence.nominal - timedelta(days=1))
    events = tuple(past if e.id == original.id else e for e in data.events) + (event,)
    overrides = tuple(o for o in data.overrides
                      if o.event_id != original.id or o.nominal < occurrence.nominal)
    return replace(data, events=events, overrides=overrides)


def replace_override(data: CalendarData, override: DateOverride) -> CalendarData:
    remaining = tuple(o for o in data.overrides
                      if (o.event_id, o.nominal) != (override.event_id, override.nominal))
    return replace(data, overrides=remaining + (override,))


class CalendarStore:
    """Recheck admin access on reads/writes; reject stale local snapshots.

    OneDrive is asynchronous. A local lock is not a distributed lock; admins
    should synchronize before editing and avoid simultaneous offline edits.
    """

    def __init__(self, access_path: Path, actor: str) -> None:
        self.access_path = access_path
        self.path = calendar_path(access_path)
        self.actor = actor

    def access(self) -> AccessConfiguration:
        access = load_access_configuration(self.access_path)
        if not access.is_administrator(self.actor):
            raise CalendarError("Only an active administrator can access the Bursar Office Calendar.")
        return access

    def load(self) -> CalendarData:
        access = self.access()
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return CalendarData()
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError) as error:
            raise CalendarError("The Bursar Office Calendar could not be read. Check OneDrive or restore its backup.") from error
        return _parse(payload, hashlib.sha256(raw).hexdigest(), access)

    def save(self, data: CalendarData) -> CalendarData:
        self.access()
        payload = _payload(data, self.actor)
        _parse(payload, None)
        ensure_hidden_directory(self.path.parent)
        lock = self.path.with_suffix(".lock")
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as error:
            raise CalendarConflictError("The calendar is being saved. Reload and try again. If a save was interrupted, ask an admin to remove operations_calendar.lock.") from error
        temporary = None
        try:
            os.close(descriptor)
            current = self.load()
            if current.source_digest != data.source_digest:
                raise CalendarConflictError("Another administrator changed the calendar. Reload before saving.")
            if self.path.exists():
                shutil.copy2(self.path, self.path.with_name(".operations_calendar.backup.json"))
            descriptor, temporary = tempfile.mkstemp(prefix=".operations_calendar.", suffix=".tmp", dir=self.path.parent)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            self.access()
            os.replace(temporary, self.path)
            return self.load()
        finally:
            if temporary:
                Path(temporary).unlink(missing_ok=True)
            lock.unlink(missing_ok=True)
