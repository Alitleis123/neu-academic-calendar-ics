"""Classify events so subscribers can take only the slices they want.

Order matters: the first match wins. "I Am Here" rows mention classes too, so
they must be tested before the class start/end pattern.
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
     r"no classes|Break\s*$",
     "No-class days, fall break, spring break."),
    ("registration", "REGISTRATION", "Registration periods",
     r"registration period",
     "When your registration window opens."),
    ("classes", "CLASS", "Term start & end dates",
     r"^(First|Last) day of .*class",
     "First and last days of each term, session, and third."),
    ("admin", "ADMIN", "Degree conferral & schedules",
     r"degree conferral|schedule available",
     "Conferral dates and when next term's schedule posts."),
)

# Convenience bundle: what most undergraduates actually want to see.
ESSENTIALS = ("deadlines", "exams", "holidays")

_COMPILED = tuple((key, ics_val, re.compile(pat, re.I))
                  for key, ics_val, _, pat, _ in CATEGORIES)

_BY_KEY = {key: (ics_val, label, blurb)
           for key, ics_val, label, _, blurb in CATEGORIES}


def categorize(title):
    """Return (key, ICS CATEGORIES value) for an event title."""
    for key, ics_val, rx in _COMPILED:
        if rx.search(title):
            return key, ics_val
    return "other", "OTHER"


def label(key):
    return _BY_KEY[key][1] if key in _BY_KEY else "Other"


def blurb(key):
    return _BY_KEY[key][2] if key in _BY_KEY else ""


def keys():
    return [c[0] for c in CATEGORIES]
