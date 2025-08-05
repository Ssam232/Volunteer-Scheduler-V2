"""
Scheduler2.py

Pure Python scheduling module for Streamlit integration.
Contains build_schedule(df) as entrypoint, with lex-optimal solver.
"""
import pandas as pd
from ortools.sat.python import cp_model

# ----------------------------------
# Configuration
# ----------------------------------
MAX_PER_SHIFT = 3
# Lexicographic weights: ensure maximizing # of 1st choices, then 2nd, etc.
LEX_WEIGHTS = {
    1: 100000,
    2: 10000,
    3: 1000,
    4: 100,
    5: 10
}
# Minimum weight for any fallback assignment
FALLBACK_WEIGHT = 1

# ----------------------------------
# Data Loading and Preparation
# ----------------------------------
def load_preferences(df: pd.DataFrame):
    """
    Parse DataFrame into volunteers, roles, shifts, weights, prefs_map.
    Expects Name (or First/Last), Role, and Pref*/Availability* columns.
    """
    df = df.copy()
    cols_lower = {c.lower(): c for c in df.columns}
    # Build Name column
    if 'first name' in cols_lower and 'last name' in cols_lower:
        df['Name'] = df[cols_lower['first name']].astype(str) + ' ' + df[cols_lower['last name']].astype(str)
    elif 'firstname' in cols_lower and 'lastname' in cols_lower:
        df['Name'] = df[cols_lower['firstname']].astype(str) + ' ' + df[cols_lower['lastname']].astype(str)
    elif 'name' in cols_lower:
        df['Name'] = df[cols_lower['name']].astype(str)
    else:
        df['Name'] = df.iloc[:, 0].astype(str) + ' ' + df.iloc[:, 1].astype(str)
    # Role
    if 'role' not in cols_lower:
        raise ValueError("Missing 'Role' column.")
    role_col = cols_lower['role']

    volunteers = df['Name'].tolist()
    roles = {}
    prefs_map = {}
    # Pref columns
    pref_cols = [c for c in df.columns if c.lower().startswith('pref') or c.lower().startswith('availability')]
    if not pref_cols:
        raise ValueError("No preference columns detected.")
    for _, row in df.iterrows():
        name = row['Name']
        rv = str(row[role_col]).strip().lower()
        if 'mentor' in rv:
            roles[name] = 'mentor'
        elif 'mentee' in rv:
            roles[name] = 'mentee'
        else:
            roles[name] = 'volunteer'
        # collect preferences
        prefs = []
        for col in pref_cols:
            v = row[col]
            if pd.notna(v):
                prefs.append(str(v))
        prefs_map[name] = prefs
    # distinct shifts
    shifts = sorted({slot for prefs in prefs_map.values() for slot in prefs})
    # build weight matrix (lex weights)
    weights = {}
    for name, prefs in prefs_map.items():
        for rank, slot in enumerate(prefs, start=1):
            weights[(name, slot)] = LEX_WEIGHTS.get(rank, FALLBACK_WEIGHT)
    # fallback for other slots
    for name in volunteers:
        for slot in shifts:
            if (name, slot) not in weights:
                weights[(name, slot)] = FALLBACK_WEIGHT
    return volunteers, roles, shifts, weights, prefs_map

# ----------------------------------
# Solver Logic (Lexicographic via Large Weights)
# ----------------------------------
def solve_schedule(volunteers, roles, shifts, weights):
    """
    Build and solve CP-SAT model with lexicographic weights:
      - each volunteer assigned to exactly one shift (no unassigned)
      - max MAX_PER_SHIFT per shift
      - if any mentee in shift => at least one mentor
      - maximize weighted sum (lex order via large weights)
    Returns schedule dict mapping slot->list of {'Name','Role','Fallback'}.
    """
    model = cp_model.CpModel()
    # Decision variables
    x = {(v, s): model.NewBoolVar(f"x_{v}_{s}") for v in volunteers for s in shifts}

    # Each volunteer exactly one shift
    for v in volunteers:
        model.Add(sum(x[(v, s)] for s in shifts) == 1)

    # Capacity constraint
    for s in shifts:
        model.Add(sum(x[(v, s)] for v in volunteers) <= MAX_PER_SHIFT)

    # Mentor-mentee pairing
    mentees = [v for v in volunteers if roles[v] == 'mentee']
    mentors = [v for v in volunteers if roles[v] == 'mentor']
    if mentees and mentors:
        y = {s: model.NewBoolVar(f"has_mentee_{s}") for s in shifts}
        for s in shifts:
            # Link y[s] to any mentee presence
            model.Add(sum(x[(v, s)] for v in mentees) >= 1).OnlyEnforceIf(y[s])
            model.Add(sum(x[(v, s)] for v in mentees) == 0).OnlyEnforceIf(y[s].Not())
            # If any mentee, require a mentor
            model.Add(sum(x[(v, s)] for v in mentors) >= 1).OnlyEnforceIf(y[s])

    # Objective: lexicographic preference
    objective_terms = [weights[(v, s)] * x[(v, s)] for v in volunteers for s in shifts]
    model.Maximize(sum(objective_terms))

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("No feasible schedule found.")

    # Extract schedule assignments
    schedule = {s: [] for s in shifts}
    for (v, s), var in x.items():
        if solver.Value(var) == 1:
            schedule[s].append({
                'Name': v,
                'Role': roles[v],
                'Fallback': weights[(v, s)] == FALLBACK_WEIGHT
            })
    return schedule

# ----------------------------------
# Utility: DataFrame Builders
# ----------------------------------
def prepare_schedule_df(schedule):
    """
    Convert schedule dict to DataFrame with consistent columns,
    even if schedule is empty.
    """
    rows = []
    for slot, items in schedule.items():
        for a in items:
            rows.append({
                'Time Slot': slot,
                'Name': a.get('Name', ''),
                'Role': a.get('Role', ''),
                'Fallback': a.get('Fallback', False)
            })
    # Build DataFrame ensuring all columns exist
    df = pd.DataFrame(rows)
    for col in ['Time Slot', 'Name', 'Role', 'Fallback']:
        if col not in df.columns:
            df[col] = []
    # Enforce column order
    return df[['Time Slot', 'Name', 'Role', 'Fallback']]


def compute_breakdown(schedule, prefs_map):
    total = sum(len(items) for items in schedule.values())
    counts = {
        '1st availability': 0,
        '2nd availability': 0,
        '3rd availability': 0,
        '4th availability': 0,
        '5th availability': 0,
        'Fallback (outside prefs)': 0
    }
    ord_map = {i: key for i, key in enumerate(list(counts)[:-1])}
    for slot, items in schedule.items():
        for a in items:
            name = a['Name']
            prefs = prefs_map[name]
            if slot in prefs:
                counts[ord_map[prefs.index(slot)]] += 1
            else:
                counts['Fallback (outside prefs)'] += 1
    breakdown = []
    for k, v in counts.items():
        pct = (v / total * 100) if total else 0
        breakdown.append({'Preference': k, 'Count': v, 'Percentage': f"{pct:.1f}%"})
    return pd.DataFrame(breakdown)

# ----------------------------------
# Entrypoint
# ----------------------------------
def build_schedule(df: pd.DataFrame):
    """Entrypoint for Streamlit: returns sched_df, unassigned_df (empty), breakdown_df."""
    # Load data and preferences
    volunteers, roles, shifts, weights, prefs_map = load_preferences(df)
    # Solve schedule (every volunteer assigned exactly once, with fallback if needed)
    schedule = solve_schedule(volunteers, roles, shifts, weights)
    # Build schedule DataFrame
    sched_df = prepare_schedule_df(schedule)
    # No unassigned volunteers: fallback ensures everyone is placed
    unassigned_df = pd.DataFrame(columns=['Name'])
    # Build preference breakdown
    breakdown_df = compute_breakdown(schedule, prefs_map)
    return sched_df, unassigned_df, breakdown_df
