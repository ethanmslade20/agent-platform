"""Master carrier list — every carrier name on record from Ethan's book.

These are the exact (lightly-normalized) carrier strings that appear in the
HealthSherpa data, so they match a client's `carrier` field verbatim. Used as the
options for the per-state appointment picker in Settings. Ethan can grow this over
time; an agent's own uploaded carriers are unioned in at runtime so nothing they
write is ever missing from the dropdown.
"""
from __future__ import annotations

MASTER: list[str] = [
    "AMGP Georgia Managed Care Company, Inc. dba Anthem Blue Cross and Blue Shield",
    "Aetna CVS Health",
    "Aetna Health Inc. (a GA corp.) DBA Coventry Healthcare of Georgia, Inc.",
    "Alliant Health Plans",
    "Ambetter Health",
    "Ambetter HomeState Health",
    "Ambetter from Absolute Total Care",
    "Ambetter from Arkansas Health & Wellness",
    "Ambetter from Buckeye Health Plan",
    "Ambetter from Louisiana Healthcare Connections",
    "Ambetter from MHS",
    "Ambetter from Magnolia Health",
    "Ambetter from Meridian",
    "Ambetter from Peach State Health Plan",
    "Ambetter from Sunflower Health Plan",
    "Ambetter from Superior Health Plan",
    "Ambetter of Alabama",
    "Ambetter of Illinois",
    "Ambetter of North Carolina Inc.",
    "Ambetter of Oklahoma",
    "Ambetter of Tennessee",
    "Anthem Blue Cross and Blue Shield",
    "Anthem Ins Companies Inc(Anthem BCBS)",
    "Blue Care Network of Michigan",
    "Blue Cross Blue Shield Healthcare Plan of Georgia",
    "Blue Cross Blue Shield of Michigan",
    "Blue Cross and Blue Shield of Alabama",
    "Blue Cross and Blue Shield of Illinois",
    "Blue Cross and Blue Shield of NC",
    "Blue Cross and Blue Shield of Oklahoma",
    "Blue Cross and Blue Shield of Texas",
    "BlueCross BlueShield of South Carolina",
    "BlueCross BlueShield of Tennessee",
    "CHRISTUS Health Plan",
    "CareSource",
    "CareSource (Common Ground Healthcare)",
    "CareSource Georgia Co.",
    "Cigna Health and Life Insurance Company",
    "Cigna Health and Life Insurance Company/Cigna HealthCare of North Carolina, Inc.",
    "Cigna HealthCare of Florida, Inc.",
    "Cigna HealthCare of Georgia, Inc./Cigna Health and Life Insurance Company",
    "Cigna Healthcare",
    "Compcare Health Serv Ins Co(Anthem BCBS)",
    "Florida Blue (BlueCross BlueShield FL)",
    "Florida Blue HMO (a BlueCross BlueShield FL company)",
    "HMO Louisiana",
    "Health First",
    "Kaiser Foundation Health Plan of Georgia",
    "MedMutual",
    "Molina",
    "Network Health",
    "Oscar",
    "Oscar Buckeye State",
    "Oscar Health Maintenance Organization of Florida, Inc",
    "Oscar Health Plan",
    "Oscar Health Plan of Georgia",
    "Oscar Health Plan of North Carolina, Inc",
    "Oscar Health Plan, Inc",
    "Oscar Insurance Company",
    "Oscar Insurance Company of Florida",
    "Priority Health",
    "Regence BlueCross BlueShield of Utah",
    "Scott and White Health Plan",
    "SelectHealth",
    "Simply Healthcare Plans Inc dba Wellpoint Florida Inc",
    "UnitedHealthcare",
    "University of Michigan Health Plan",
    "University of Utah",
    "Wellpoint Insurance Company",
]


# ── Carrier BRANDS ────────────────────────────────────────────────────────────
# Agents pick a brand (one "Ambetter", one "Anthem", …) and the system maps each
# client's specific legal-entity carrier to its brand. Order matters — the FIRST
# brand whose keyword appears in the carrier name wins, so Anthem-branded Blue Cross
# entities resolve to Anthem before the generic Blue Cross rule.
_BRANDS = [
    ("Ambetter", ["ambetter"]),
    ("Oscar", ["oscar"]),
    ("Anthem / Wellpoint", ["anthem", "wellpoint", "amgp", "compcare"]),
    ("Blue Cross Blue Shield", ["blue cross", "bluecross", "blue shield", "blueshield",
                                "bcbs", "florida blue", "regence", "blue care network",
                                "hmo louisiana"]),
    ("Cigna", ["cigna"]),
    ("UnitedHealthcare", ["unitedhealthcare", "united health", "uhc"]),
    ("Molina", ["molina"]),
    ("Aetna / Coventry", ["aetna", "coventry"]),
    ("CareSource", ["caresource"]),
    ("SelectHealth", ["selecthealth", "select health"]),
    ("Kaiser", ["kaiser"]),
    ("CHRISTUS", ["christus"]),
    ("Alliant", ["alliant"]),
    ("Health First", ["health first"]),
    ("Medical Mutual", ["medmutual", "medical mutual"]),
    ("Network Health", ["network health"]),
    ("Priority Health", ["priority health"]),
    ("Scott & White", ["scott and white", "scott & white"]),
    ("University of Michigan", ["university of michigan"]),
    ("University of Utah", ["university of uta", "u of u"]),
]


def brand_of(carrier) -> str:
    """Map a specific carrier name to its brand (or the name itself if unknown)."""
    c = str(carrier or "").lower().strip()
    if not c:
        return ""
    for brand, kws in _BRANDS:
        if any(k in c for k in kws):
            return brand
    return str(carrier).strip()


def brand_options(roster=None, extra=None) -> list[str]:
    """Brand names to offer in the appointment picker: every brand present in the
    master list, plus the brand of anything in the agent's own book or already
    saved on a state (so a pick is never missing)."""
    brands = {brand_of(n) for n in MASTER}
    if roster is not None and "carrier" in getattr(roster, "columns", []):
        brands |= {brand_of(c) for c in roster["carrier"].dropna()}
    if extra:
        brands |= {brand_of(c) for c in extra}
    brands.discard("")
    return sorted(brands, key=str.lower)


def options(roster=None, extra=None) -> list[str]:
    """Master list, unioned with any carriers in the agent's own book (and any
    carriers already saved on a state) so a selection can never go missing."""
    names = set(MASTER)
    if roster is not None and "carrier" in getattr(roster, "columns", []):
        names |= {str(c).strip() for c in roster["carrier"].dropna() if str(c).strip()}
    if extra:
        names |= {str(c).strip() for c in extra if str(c).strip()}
    return sorted(names, key=str.lower)
