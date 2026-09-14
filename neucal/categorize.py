"""Classify events along two independent dimensions.

The registrar publishes one university-wide calendar. Every row belongs to an
**audience** (who it applies to) and a **category** (what kind of event it is).
Neither is a filter applied at the root — both are published as branches, so a
subscriber picks a point in the tree rather than accepting ours.

Order matters within each dimension: the first match wins. "I Am Here" rows
mention classes too, so attendance is tested before class start/end.
"""

import re

# Campuses outside the Boston default. Match names individually, not one fixed
# ordering such as "Oakland and Silicon Valley".
OTHER_CAMPUSES = ("Vancouver", "Toronto", "Charlotte", "Oakland", "Silicon Valley",
                  "Miami", "Seattle", "Arlington", "Burlington", "Portland")
CAMPUS_ONLY = re.compile(
    r"\([^)]*\b(?:{})\b[^)]*\bonly\s*\)".format(
        "|".join(re.escape(name) for name in OTHER_CAMPUSES)), re.I)

# (key, ICS CATEGORIES value, label, pattern, blurb)
CATEGORIES = (
    ("attendance", "ATTENDANCE", "Attendance (I Am Here)",
     r"I Am Here",
     "Confirm-your-enrollment deadlines and the drops for missing them."),
    ("deadlines", "DEADLINE", "Add/drop & withdrawal deadlines",
     r"add/drop period|withdrawal period",
     "Add/drop and course withdrawal deadlines."),
    ("exams", "EXAM", "Final exam periods",
     r"final exam (?:period|window)",
     "Final exam windows."),
    ("holidays", "HOLIDAY", "Holidays & breaks",
     # "classes resume" normally gets absorbed into a Break span; it only
     # survives when its opening row is missing from that audience's rows.
     r"no classes|\b(?:fall|winter|spring|summer) break\b|classes resume",
     "No-class days, fall break, spring break."),
    ("registration", "REGISTRATION", "Registration periods",
     r"registration period",
     "When your registration window opens."),
    ("classes", "CLASS", "Term start & end dates",
     r"^(First|Last) day of .*class",
     "First and last days of each term, session, and third."),
    ("grades", "GRADES", "Grade deadlines",
     r"grade deadline",
     "Deadlines for faculty to submit grades."),
    ("schedules", "SCHEDULE", "Class schedule posting",
     r"schedule available",
     "When next term's course schedule goes live, so you can plan picks."),
    ("conferral", "CONFERRAL", "Degree conferral",
     r"degree conferral",
     "When degrees are formally awarded."),
)

# Bundles are named unions of categories — a third thing alongside audience and
# category. They exist so the common combinations are one subscription instead
# of three, and they are published as their own feeds.
# (key, label, member category keys, blurb)
BUNDLES = (
    ("essentials", "Essentials", ("deadlines", "exams", "holidays"),
     "Course deadlines, final exam periods, holidays and breaks."),
    ("planning", "Planning", ("holidays", "registration"),
     "Time off and registration windows for planning a term ahead."),
    # Derived, not listed: a hand-written member list would silently omit any
    # category added later.
    ("no-attendance", "Everything except attendance",
     tuple(c[0] for c in CATEGORIES if c[0] != "attendance"),
     "All categories except enrollment confirmations and attendance drops."),
    ("drop-risk", "Drop risk", ("attendance", "deadlines"),
     "Every date that can remove you from a course: attendance confirmations "
     "and add/drop or withdrawal deadlines."),
    ("enrollment", "Enrollment", ("registration", "schedules"),
     "When next term's schedule posts, and when your registration opens."),
    ("term-shape", "Term shape", ("classes", "holidays"),
     "First and last days of every term, session and third, plus breaks."),
    # Kept because current-undergrad-admin.ics was published before the split.
    ("admin", "Conferral & schedules", ("conferral", "schedules"),
     "Degree conferral dates and schedule postings."),
)

_BUNDLE_BY_KEY = {key: (label, members, blurb) for key, label, members, blurb in BUNDLES}

# Retained: ESSENTIALS was the only bundle before BUNDLES existed.
ESSENTIALS = _BUNDLE_BY_KEY["essentials"][1]


def bundle_members(key):
    return _BUNDLE_BY_KEY[key][1]


def bundle_label(key):
    return _BUNDLE_BY_KEY[key][0]


def bundle_blurb(key):
    return _BUNDLE_BY_KEY[key][2]


def bundle_keys():
    return [b[0] for b in BUNDLES]

# (key, label, pattern tested against the row text, blurb)
# Order matters. Anything unmatched is the default audience, "undergrad".
AUDIENCES = (
    ("law", "School of Law", r"School of Law|\b(JD|Law)\b",
     "JD classes, Law exam periods, Law registration."),
    ("other-program", "ABSN & CPS", r"ABSN|College of Professional Studies",
     "Accelerated nursing and College of Professional Studies."),
    ("canada-campus", "Canadian campuses", r"^CAN\s*:",
     "Vancouver and Toronto statutory holidays."),
    ("quarter-calendar", "Quarter-calendar programs", r"^QTR\s*:",
     "Programs on quarters rather than semesters."),
    ("other-campus", "Other US campuses", None,
     "Charlotte, Oakland, Silicon Valley, and similar campus-only rows."),
    ("faculty", "Faculty deadlines", r"^Faculty grade deadline",
     "Faculty grade submission deadlines. Student grade release times may differ."),
    ("grad-only", "Graduate-only", None,
     "Graduate registration that does not also name undergraduates."),
    ("undergrad", "Boston undergraduate", None,
     "The default: everything that applies to a Boston-campus undergraduate."),
)

_AUD_BY_KEY = {key: (label, blurb) for key, label, _, blurb in AUDIENCES}

_COMPILED = tuple((key, ics_val, re.compile(pat, re.I))
                  for key, ics_val, _, pat, _ in CATEGORIES)

_BY_KEY = {key: (ics_val, label, blurb)
           for key, ics_val, label, _, blurb in CATEGORIES}


def audience(title, campus_only_rx=CAMPUS_ONLY, other_campuses_present=True):
    """Return the audience key for a row.

    `campus_only_rx` and `other_campuses_present` are supplied by parse.py so the
    campus list stays configurable in one place.
    """
    title = " ".join(title.split())
    for key, _, pat, _ in AUDIENCES:
        candidate = without_prefix(title) if key == "faculty" else title
        if pat and re.search(pat, candidate, re.I):
            return key
        if key == "other-campus" and other_campuses_present and campus_only_rx.search(title):
            if not re.search(r"\bBoston\b", title, re.I):
                return key
    if re.search(r"\bgraduate\b", title, re.I) and not re.search(r"\bundergraduate\b", title, re.I):
        return "grad-only"
    return "undergrad"


def audience_label(key):
    return _AUD_BY_KEY[key][0] if key in _AUD_BY_KEY else key


def audience_blurb(key):
    return _AUD_BY_KEY[key][1] if key in _AUD_BY_KEY else ""


def audience_keys():
    return [a[0] for a in AUDIENCES]


# Audience prefixes like "QTR: " / "CAN: " / "USA: " sit in front of the text
# and would defeat the ^-anchored category patterns.
_AUD_PREFIX = re.compile(r"^(?:(?:QTR|CAN|USA)\s*:\s*)+", re.I)


def without_prefix(title):
    return _AUD_PREFIX.sub("", " ".join(title.split()))


def validate_scope(title):
    """Unknown source scope must not silently enter the Boston default."""
    prefix = re.match(r"^([A-Za-z]{2,5})\s*:", title)
    if prefix and prefix[1].upper() not in ("QTR", "CAN", "USA"):
        raise ValueError("Unknown audience prefix {!r} in {!r}".format(prefix[1], title))
    for qualifier in re.findall(r"\(([^()]*\bonly\s*)\)", title, re.I):
        campuses = ("Boston",) + OTHER_CAMPUSES
        if not any(re.search(r"\b" + re.escape(name) + r"\b", qualifier, re.I) for name in campuses):
            raise ValueError("Unknown audience qualifier {!r} in {!r}".format(qualifier, title))


def categorize(title):
    """Return (key, ICS CATEGORIES value) for an event title."""
    text = without_prefix(title)
    for key, ics_val, rx in _COMPILED:
        if rx.search(text):
            return key, ics_val
    return "other", "OTHER"


def label(key):
    return _BY_KEY[key][1] if key in _BY_KEY else "Other"


def blurb(key):
    return _BY_KEY[key][2] if key in _BY_KEY else ""


def keys():
    return [c[0] for c in CATEGORIES]


def ics_value(key):
    """Use the event's assigned category, rather than reclassifying its title."""
    try:
        return _BY_KEY[key][0]
    except KeyError as exc:
        raise ValueError("Unknown category {!r}".format(key)) from exc


def validate_config():
    """Fail before generating filenames if classification configuration is invalid."""
    groups = (keys(), bundle_keys(), audience_keys())
    all_keys = [key for group in groups for key in group]
    if len(all_keys) != len(set(all_keys)) or "all" in all_keys:
        raise ValueError("Category, bundle and audience keys must be unique; 'all' is reserved")
    if any(not re.fullmatch(r"[a-z]+(?:-[a-z]+)*", key) for key in all_keys):
        raise ValueError("Classification keys must be lowercase filename-safe words")
    values = [c[1] for c in CATEGORIES]
    if len(set(values)) != len(values) or any(not re.fullmatch(r"[A-Z]+", v) for v in values):
        raise ValueError("ICS category values must be unique uppercase words")
    for key, label_text, members, description in BUNDLES:
        if (len(set(members)) < 2 or len(set(members)) != len(members)
                or not set(members) <= set(keys()) or not label_text or not description):
            raise ValueError("Invalid bundle {!r}".format(key))
