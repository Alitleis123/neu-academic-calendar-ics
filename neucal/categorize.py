"""Classify events along two independent dimensions.

The registrar publishes one university-wide calendar. Every row belongs to an
**audience** (who it applies to) and a **category** (what kind of event it is).
Neither is a filter applied at the root — both are published as branches, so a
subscriber picks a point in the tree rather than accepting ours.

Order matters within each dimension: the first match wins. "I Am Here" rows
mention classes too, so attendance is tested before class start/end.
"""

import re

# (key, ICS CATEGORIES value, label, pattern, blurb)
CATEGORIES = (
    ("attendance", "ATTENDANCE", "Attendance (I Am Here)",
     r"I Am Here",
     "Confirm-your-enrollment deadlines and the drops for missing them."),
    ("deadlines", "DEADLINE", "Add/drop & withdrawal deadlines",
     r"add/drop period|withdrawal period",
     "The ones with money attached."),
    ("exams", "EXAM", "Final exam periods",
     r"final exam",
     "Final exam windows."),
    ("holidays", "HOLIDAY", "Holidays & breaks",
     # "classes resume" normally gets absorbed into a Break span; it only
     # survives when its opening row is missing from that audience's rows.
     r"no classes|Break\s*$|classes resume",
     "No-class days, fall break, spring break."),
    ("registration", "REGISTRATION", "Registration periods",
     r"registration period",
     "When your registration window opens."),
    ("classes", "CLASS", "Term start & end dates",
     r"^(First|Last) day of .*class",
     "First and last days of each term, session, and third."),
    ("grades", "GRADES", "Grade deadlines",
     r"grade deadline",
     "When faculty must submit grades — effectively when grades post."),
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
     "Anything that costs you money or cancels your day."),
    ("planning", "Planning", ("holidays", "registration"),
     "Time off and when to sign up for classes — for planning a term ahead."),
    # Derived, not listed: a hand-written member list would silently omit any
    # category added later.
    ("no-attendance", "Everything except attendance",
     tuple(c[0] for c in CATEGORIES if c[0] != "attendance"),
     "The full calendar minus the I Am Here rows — the usual complaint."),
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

_BUNDLE_BY_KEY = {k: (l, m, b) for k, l, m, b in BUNDLES}

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
    ("canada-campus", "Canadian campuses", r"^CAN:",
     "Vancouver and Toronto statutory holidays."),
    ("quarter-calendar", "Quarter-calendar programs", r"^QTR:",
     "Programs on quarters rather than semesters."),
    ("other-campus", "Other US campuses", None,
     "Charlotte, Oakland, Silicon Valley, and similar campus-only rows."),
    ("faculty", "Faculty deadlines", r"^Faculty grade deadline",
     "Grade submission deadlines — useful if you want to know when grades post."),
    ("grad-only", "Graduate-only", None,
     "Graduate registration that does not also name undergraduates."),
    ("undergrad", "Boston undergraduate", None,
     "The default: everything that applies to a Boston-campus undergraduate."),
)

_AUD_BY_KEY = {k: (l, b) for k, l, _, b in AUDIENCES}

_COMPILED = tuple((key, ics_val, re.compile(pat, re.I))
                  for key, ics_val, _, pat, _ in CATEGORIES)

_BY_KEY = {key: (ics_val, label, blurb)
           for key, ics_val, label, _, blurb in CATEGORIES}


def audience(title, campus_only_rx, other_campuses_present):
    """Return the audience key for a row.

    `campus_only_rx` and `other_campuses_present` are supplied by parse.py so the
    campus list stays configurable in one place.
    """
    for key, _, pat, _ in AUDIENCES:
        if pat and re.search(pat, title, re.I):
            return key
    if other_campuses_present and campus_only_rx.search(title) and "Boston" not in title:
        return "other-campus"
    # \b keeps this from matching inside "undergraduate"
    if re.search(r"\bgraduate\b", title) and not re.search(r"\bundergraduate\b", title):
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
_AUD_PREFIX = re.compile(r"^[A-Z]{2,4}:\s*")


def categorize(title):
    """Return (key, ICS CATEGORIES value) for an event title."""
    text = _AUD_PREFIX.sub("", title)
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
