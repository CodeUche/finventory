"""
Static reference data for the HR / payroll module.

Nigerian states drive PAYE routing: under PITA (as amended) an employee's PAYE
is remitted to the State Internal Revenue Service of their state of *residence*,
not to FIRS and not to the state the employer is registered in. FIRS only
collects PAYE for the Armed Forces, the Police, officers of the Foreign Service
and residents of the FCT — hence the FCT-IRS entry below is the Federal Capital
Territory Internal Revenue Service.
"""

# (code, label, tax authority name, portal URL)
NIGERIAN_STATES = [
    ('AB', 'Abia',        'Abia State Internal Revenue Service',        'https://abiairs.gov.ng/'),
    ('AD', 'Adamawa',     'Adamawa State Board of Internal Revenue',    ''),
    ('AK', 'Akwa Ibom',   'Akwa Ibom State Internal Revenue Service',   'https://www.akirs.gov.ng/'),
    ('AN', 'Anambra',     'Anambra State Internal Revenue Service',     'https://www.anambrairs.gov.ng/'),
    ('BA', 'Bauchi',      'Bauchi State Board of Internal Revenue',     ''),
    ('BY', 'Bayelsa',     'Bayelsa State Board of Internal Revenue',    ''),
    ('BE', 'Benue',       'Benue State Internal Revenue Service',       ''),
    ('BO', 'Borno',       'Borno State Board of Internal Revenue',      ''),
    ('CR', 'Cross River', 'Cross River State Internal Revenue Service', ''),
    ('DE', 'Delta',       'Delta State Board of Internal Revenue',      'https://deltairs.gov.ng/'),
    ('EB', 'Ebonyi',      'Ebonyi State Internal Revenue Service',      ''),
    ('ED', 'Edo',         'Edo State Internal Revenue Service',         'https://www.edoirs.gov.ng/'),
    ('EK', 'Ekiti',       'Ekiti State Internal Revenue Service',       ''),
    ('EN', 'Enugu',       'Enugu State Internal Revenue Service',       ''),
    ('GO', 'Gombe',       'Gombe State Internal Revenue Service',       ''),
    ('IM', 'Imo',         'Imo State Internal Revenue Service',         ''),
    ('JI', 'Jigawa',      'Jigawa State Board of Internal Revenue',     ''),
    ('KD', 'Kaduna',      'Kaduna State Internal Revenue Service',      'https://kadirs.kdsg.gov.ng/'),
    ('KN', 'Kano',        'Kano State Internal Revenue Service',        'https://kirs.gov.ng/'),
    ('KT', 'Katsina',     'Katsina State Board of Internal Revenue',    ''),
    ('KE', 'Kebbi',       'Kebbi State Board of Internal Revenue',      ''),
    ('KO', 'Kogi',        'Kogi State Internal Revenue Service',        ''),
    ('KW', 'Kwara',       'Kwara State Internal Revenue Service',       'https://www.kw-irs.com/'),
    ('LA', 'Lagos',       'Lagos State Internal Revenue Service',       'https://lirs.gov.ng/'),
    ('NA', 'Nasarawa',    'Nasarawa State Internal Revenue Service',    ''),
    ('NI', 'Niger',       'Niger State Internal Revenue Service',       ''),
    ('OG', 'Ogun',        'Ogun State Internal Revenue Service',        'https://ogunirs.com/'),
    ('ON', 'Ondo',        'Ondo State Internal Revenue Service',        ''),
    ('OS', 'Osun',        'Osun State Internal Revenue Service',        ''),
    ('OY', 'Oyo',         'Oyo State Board of Internal Revenue',        ''),
    ('PL', 'Plateau',     'Plateau State Internal Revenue Service',     ''),
    ('RI', 'Rivers',      'Rivers State Internal Revenue Service',      'https://www.riversirs.gov.ng/'),
    ('SO', 'Sokoto',      'Sokoto State Board of Internal Revenue',     ''),
    ('TA', 'Taraba',      'Taraba State Board of Internal Revenue',     ''),
    ('YO', 'Yobe',        'Yobe State Board of Internal Revenue',       ''),
    ('ZA', 'Zamfara',     'Zamfara State Board of Internal Revenue',    ''),
    ('FC', 'FCT Abuja',   'FCT Internal Revenue Service',               'https://fctirs.gov.ng/'),
]

STATE_CHOICES = [(code, label) for code, label, _name, _url in NIGERIAN_STATES]

STATE_LOOKUP = {code: (label, name, url) for code, label, name, url in NIGERIAN_STATES}


# ── Statutory remittance deadlines ────────────────────────────────────────────
# Day-of-month in the month FOLLOWING the payroll period.
REMITTANCE_DEADLINE_DAY = {
    'paye':    10,   # PITA s.82 — within 10 days of the following month
    'pension': 7,    # PRA 2014 s.11(3)(b) — within 7 working days
    'nhf':     30,   # NHF Act — remitted monthly
    'nsitf':   30,   # Employee Compensation Act — monthly
}

# ITF is an annual levy (ITF Act s.6(1)) due by 1 April of the following year.
ITF_DUE_MONTH = 4
ITF_DUE_DAY = 1


# ── Daily-rate conversion ─────────────────────────────────────────────────────
# Standard Nigerian payroll convention for converting a monthly gross salary to
# a daily rate (used by leave encashment and the leave-accrual GL true-up).
# Single canonical constant so the two call sites can never silently diverge —
# see LeaveEncashmentService.daily_rate (apps/payroll/services.py) and
# AccountingService.post_leave_accrual_true_up (apps/accounting/services.py).
WORKING_DAYS_PER_MONTH = 26


# ── Default Nigerian leave entitlements ───────────────────────────────────────
# Labour Act s.18: a worker is entitled to at least 6 working days of paid
# annual leave after 12 months of continuous service. Most employers offer more,
# so 6 is seeded as the statutory floor and is editable per organisation.
DEFAULT_LEAVE_TYPES = [
    # (name, days_per_year, accrual_method, is_paid, carry_forward_max, gender_restriction)
    ('Annual Leave',    6.0,  'monthly_accrual', True,  5.0, ''),
    ('Sick Leave',      12.0, 'annual_grant',    True,  0.0, ''),
    ('Maternity Leave', 84.0, 'annual_grant',    True,  0.0, 'female'),
    ('Paternity Leave', 14.0, 'annual_grant',    True,  0.0, 'male'),
    ('Compassionate',   3.0,  'annual_grant',    True,  0.0, ''),
    ('Unpaid Leave',    0.0,  'annual_grant',    False, 0.0, ''),
]


# ── Fixed-date Nigerian public holidays ───────────────────────────────────────
# (month, day, name). Moveable Islamic (Eid-el-Fitr, Eid-el-Kabir, Eid-el-Maulud)
# and Christian (Good Friday, Easter Monday) dates are NEVER computed here —
# they must be entered manually per year by an admin.
FIXED_DATE_PUBLIC_HOLIDAYS = [
    (1, 1,  "New Year's Day"),
    (5, 1,  "Workers' Day"),
    (6, 12, "Democracy Day"),
    (10, 1, "Independence Day"),
    (12, 25, "Christmas Day"),
    (12, 26, "Boxing Day"),
]
