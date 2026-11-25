"""Ishu's DataCheck Bot: a web app that checks a CSV table and answers questions about it.
Built by Iswarya Subburaj (Ishu), with AI assistance. Run with: streamlit run app.py
"""
import base64
import io
import re

import pandas as pd
import streamlit as st

MAX_BYTES = 5_000_000

# ============================================================
# Data, checks and answers
# ============================================================


data = pd.DataFrame({
    "customer_id": [1, 2, 3, 4, 5, 6, 6, 8, 8],
    "city":        ["Berlin", "Munich", "berlin ", None, "Hamburg", "Munich", "Munich", "Berlin", "Hamburg"],
    "age":         [25, 31, 42, 29, -5, 38, 38, 33, 27],
    "balance":     [1200, 1500, 1100, 1300, 1250, 1400, 1400, 99000, 1350],
    "join_date":   ["2025-01-10", "2025-02-11", "2025-03-12", "2025-13-40", "2025-05-14",
                    "2025-06-15", "2025-06-15", "2025-07-16", "2025-08-17"],
})


def rows(mask):
    return [int(i) for i in mask[mask].index]

def numbers(df, col):
    return pd.to_numeric(df[col], errors="coerce")

def missing(df, col):
    return rows(df[col].isna())

def duplicate_rows(df, col=None):
    return rows(df.duplicated(keep=False))

def duplicate_ids(df, col):
    return rows(df[col].notna() & df[col].duplicated(keep=False))

def negative(df, col):
    return rows(numbers(df, col) < 0)

def unusual(df, col):
    n = numbers(df, col)
    low, high = n.quantile(0.25), n.quantile(0.75)
    gap = 1.5 * (high - low)
    return rows((n < low - gap) | (n > high + gap))

def spelling(df, col):
    text = df[col].dropna().astype(str)
    return rows(text.groupby(text.str.strip().str.lower()).transform("nunique") > 1)

def bad_dates(df, col):
    parsed = pd.to_datetime(df[col], format="%Y-%m-%d", errors="coerce")
    return rows(df[col].notna() & parsed.isna())

def too_young(df, col):
    return rows(numbers(df, col) < 18)

def too_old(df, col):
    return rows(numbers(df, col) > 100)

# check name: (function, words used in answers)
CHECKS = {
    "missing": (missing, "missing values"),
    "duplicate_rows": (duplicate_rows, "rows that appear more than once"),
    "duplicate_ids": (duplicate_ids, "rows with a repeated ID"),
    "negative": (negative, "negative values"),
    "unusual": (unusual, "unusual values (may be correct)"),
    "spelling": (spelling, "rows with mixed spelling or spacing"),
    "bad_dates": (bad_dates, "invalid dates (expected YYYY-MM-DD)"),
    "too_young": (too_young, "values under 18 (may be correct)"),
    "too_old": (too_old, "values over 100 (may be correct)"),
}

def columns_for(df, check):
    """Which columns does a check make sense for?"""
    is_id = lambda c: re.search(r"(^|_)id$|Id$|^ID$", str(c)) is not None
    number = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not is_id(c)]
    text = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
    date = [c for c in df.columns if "date" in str(c).lower()]
    age = [c for c in df.columns if str(c).lower() == "age"]
    return {
        "missing": list(df.columns), "duplicate_ids": [c for c in df.columns if is_id(c)],
        "negative": number, "unusual": number, "spelling": [c for c in text if c not in date],
        "bad_dates": date, "too_young": age, "too_old": age,
    }[check]


WORDS = [   # order matters: the first match wins
    ("duplicate_ids", r"(duplicate|repeated)\w* ids?\b"),
    ("duplicate_rows", r"duplicate|repeated"),
    ("missing", r"missing|empty|blank|null"),
    ("negative", r"negative|below zero|below 0"),
    ("unusual", r"unusual|outlier|strange"),
    ("spelling", r"spell"),
    ("bad_dates", r"\bdates?\b"),
    ("too_young", r"too young|under 18|below 18"),
    ("too_old", r"too old|over 100|above 100"),
]

def find_column(question, df):
    for c in df.columns:
        for name in {str(c).lower(), str(c).lower().replace("_", " ")}:
            plural = name[:-1] + "ies" if name.endswith("y") else name + "s"
            if re.search(rf"\b({re.escape(name)}|{re.escape(plural)})\b", question):
                return c
    return None

def simple_understand(question, df):
    q = question.lower().strip()
    if q in ("help", "?"):
        return {"action": "help"}
    if re.search(r"check (all|everything|my data|the data)|^check$", q):
        return {"action": "check_all"}
    if re.search(r"summary|columns|how many rows", q) and not re.search(r"missing|duplicate", q):
        return {"action": "summary"}
    row = re.search(r"\brow (\d+)", q)
    if row:
        return {"action": "show_row", "row": int(row[1])}
    for check, pattern in WORDS:
        if re.search(pattern, q):
            return {"action": "check", "check": check, "column": find_column(q, df)}
    return None


# Simple questions: counts, averages, highest, lowest, totals. Everything is calculated here, on your table.
COUNT_WORDS = r"\b(how many|count|number of|most common)\b"
STATS = {"average": "mean", "mean": "mean", "median": "median", "highest": "max", "maximum": "max",
         "max": "max", "lowest": "min", "minimum": "min", "min": "min", "total": "sum", "sum": "sum"}
STAT_NAMES = {"mean": "Average", "median": "Median", "max": "Highest", "min": "Lowest", "sum": "Total"}
CHECK_WORDS = r"missing|empty|blank|null|duplicate|repeated|negative|unusual|outlier|strange|spell|invalid|\bcheck\b"
COMPARE = {"above": ">", "over": ">", "more than": ">", "greater than": ">", "older than": ">",
           "under": "<", "below": "<", "less than": "<", "younger than": "<",
           "equal to": "==", "is": "==", "=": "==", "": "=="}
FILLER = set("""a an the are is was were be there of in on for with who whose which what where do does did
have has had and we i me my our your you it they them their this that these those all show give tell find please
students student people person persons customers customer rows row records record entries entry values value
column data dataset table file total from live lives""".split())

def clean(text):
    return re.sub(r"\s+", " ", str(text).lower()).strip()

def pattern_for(words):
    plural = words[:-1] + "ies" if words.endswith("y") else words + "s"
    return rf"(?<!\w)(?:{re.escape(words)}|{re.escape(plural)})(?!\w)"

def data_question(question, df):
    """Return an answer for a counting or number question, or None if it is another kind of question."""
    q = clean(re.sub(r"[?!,]|\.(?!\d)|'s\b", " ", question.lower()))
    counting = re.search(COUNT_WORDS, q) is not None
    stat_words = [w for w in STATS if re.search(rf"\b{w}\b", q)]
    if not counting and not stat_words:
        return None
    if re.search(CHECK_WORDS, q):
        text = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
        found = {clean(v) for c in text if df[c].nunique() <= 200 for v in df[c].dropna().unique()}
        if counting and any(v and v not in FILLER and re.search(pattern_for(v), q) for v in found):
            return "I cannot mix a data check with a filter yet. Ask them one at a time."
        return None
    stats = [] if counting else sorted({STATS[w] for w in stat_words})
    q = clean(re.sub(COUNT_WORDS, " ", q))
    for word in stat_words:
        q = re.sub(rf"\b{word}\b", " ", q)

    names = {c: sorted({clean(c), clean(str(c).replace("_", " "))}, key=len, reverse=True) for c in df.columns}

    # 1. Number conditions, such as "age above 25"
    conditions = []
    operators = "|".join(re.escape(o) for o in sorted(COMPARE, key=len, reverse=True) if o)
    for col in df.columns:
        for name in names[col]:
            found = re.search(rf"(?<!\w){re.escape(name)}s?\s*(?:is\s+)?({operators})?\s*(-?\d+(?:\.\d+)?)(?!\w)", q)
            if found:
                conditions.append((col, COMPARE[found[1] or ""], float(found[2])))
                q = q[:found.start()] + " " + q[found.end():]
                break
    age = next((c for c in df.columns if clean(c) == "age"), None)
    found = re.search(r"\b(older than|younger than)\s*(\d+)\b|\b(under|below) (18)\b", q)
    if found and age is not None:
        conditions.append((age, COMPARE[found[1] or found[3]], float(found[2] or found[4])))
        q = q[:found.start()] + " " + q[found.end():]

    # 2. Column names and values written in the question (longest first)
    options = [(len(n), 0, n, c, None) for c in df.columns for n in names[c]]
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]) and not pd.api.types.is_bool_dtype(df[col]):
            continue
        values = {clean(v) for v in df[col].dropna().unique()}
        if len(values) <= 200:
            options += [(len(v), 1, v, col, v) for v in values if v]
    options.sort(key=lambda o: (-o[0], o[1]))
    columns, hits = [], {}
    for _, _, words, col, value in options:
        if value in FILLER:
            continue
        if re.search(pattern_for(words), q):
            if value is None:
                columns.append(col)
                q = re.sub(pattern_for(words), " ", q)
            else:
                hits.setdefault(words, []).append(col)
    values = {}
    for words, cols in hits.items():
        if not re.search(pattern_for(words), q):
            continue   # already used by a longer name or value
        named = [c for c in cols if c in columns]
        if len(named) == 1:
            cols = named
        if len(cols) > 1:
            return f"'{words}' appears in several columns: {', '.join(map(str, cols))}. Add one column name."
        values.setdefault(cols[0], []).append(words)
        q = re.sub(pattern_for(words), " ", q)

    # 3. Never answer if part of the question was not understood
    unknown = [w for w in q.split() if w not in FILLER]
    if unknown:
        return (f"I am not sure about: {', '.join(unknown)}. I did not answer, to avoid a wrong result.\n"
                "Use exact column names and values. Type summary to see the columns.")

    keep = pd.Series(True, index=df.index)
    used = []
    for col, sign, number in conditions:
        n = numbers(df, col)
        keep &= (n > number) if sign == ">" else (n < number) if sign == "<" else (n == number)
        used.append(f"{col} {'=' if sign == '==' else sign} {number:g}")
    several = {}
    for col, wanted in values.items():
        column = df[col].map(clean, na_action="ignore")
        keep &= column.isin(wanted)
        used.append(f"{col} = {' or '.join(wanted)}")
        if len(wanted) > 1:
            several[col] = wanted
    others = [c for c in columns if c not in values]
    where = f" where {' and '.join(used)}" if used else ""
    table = df[keep]

    if stats:
        if len(stats) > 1:
            return "Ask for one calculation at a time."
        if len(others) != 1:
            if stats == ["sum"] and not others and used:
                return f"Count{where}: {len(table)} of {len(df)} rows."
            return "Name one number column, for example: average age"
        col, kind = others[0], stats[0]
        n = numbers(table, col).dropna()
        if n.empty:
            return f"I found no numbers in '{col}'{where}."
        skipped = len(table) - len(n)
        note = f" {skipped} rows without a number were left out." if skipped else ""
        result = round(float(getattr(n, kind)()), 2)
        shown = f"{result:.0f}" if result.is_integer() else f"{result}"
        return f"{STAT_NAMES[kind]} {col}{where}: {shown} (from {len(n)} rows).{note}"

    if not used and not others:
        return None
    lines = []
    if used:
        share = 100 * len(table) / len(df) if len(df) else 0
        lines.append(f"Count{where}: {len(table)} of {len(df)} rows ({share:.1f}%).")
    for col in list(several) + others:
        counts = table[col].map(clean, na_action="ignore").fillna("(empty)").value_counts()
        lines.append(f"{col}:")
        lines += [f"- {value}: {total}" for value, total in counts.head(15).items()]
        if len(counts) > 15:
            lines.append(f"(showing the top 15 of {len(counts)} different values)")
    return "\n".join(lines)


HELP = """Try:
  check all
  any missing city?
  any duplicate rows?
  check spelling in city
  show row 4
  how many female?
  how many age above 25?
  average age
  count city
With AI on, ask in your own words:
  which city has the highest average balance?
  what percentage of Berlin customers are under 30?
  show the 3 oldest customers
  summary
Upload your own public or fake CSV in the sidebar.
Row numbers start at 0."""

def describe(df, check, col):
    found = CHECKS[check][0](df, col)
    label = CHECKS[check][1]
    place = f"{col}: " if col is not None else ""
    if not found:
        return f"{place}no {label} found."
    shown = ", ".join(map(str, found[:10]))
    more = f" and {len(found) - 10} more" if len(found) > 10 else ""
    return f"{place}{label}: {len(found)}. Rows: {shown}{more}."

def check_all(df):
    lines = [describe(df, "duplicate_rows", None)]
    for check in CHECKS:
        if check == "duplicate_rows":
            continue
        for col in columns_for(df, check):
            if CHECKS[check][0](df, col):
                lines.append(describe(df, check, col))
    return "\n".join(lines)


# The AI turns a question into a plan. It gets the question, column names and column types, never your rows.
import json

MODELS = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.1-flash-lite"]
CHECK_NAMES = ["missing", "duplicate_rows", "duplicate_ids", "negative", "unusual",
               "spelling", "bad_dates", "too_young", "too_old"]

def obj(**properties):
    return {"type": "object", "properties": properties, "required": list(properties)}

def one_of(*choices):
    return {"type": "string", "enum": list(choices)}

TEXT = {"type": "string"}
FILTERS = {"type": "array", "items": obj(
    column=TEXT, op=one_of("=", "!=", ">", ">=", "<", "<=", "contains", "empty", "not_empty"),
    values={"type": "array", "items": TEXT})}

PLAN_SCHEMA = obj(
    action=one_of("calculate", "check", "cannot_answer"),
    calculation=one_of("count", "percent", "sum", "mean", "median", "min", "max",
                       "distinct", "list", "correlation", "none"),
    check=one_of(*CHECK_NAMES, "none"),
    column=TEXT, second_column=TEXT, group_by=TEXT,
    filters=FILTERS, among=FILTERS, match=one_of("all", "any"),
    order=one_of("largest", "smallest"), limit={"type": "integer"}, reason=TEXT)

INSTRUCTIONS = """Turn the user's question about one table into a plan. Python will run it.
Rules:
- Use only the listed column names. Use "" for unused text fields, [] for unused lists, 0 for no limit.
- Never drop or change a condition. If the plan cannot express the whole question, use cannot_answer and say why.
- Use cannot_answer for why, prediction, advice, or anything that is not in the columns.
- filters pick rows. Several values in one filter mean any of them. match says if all or any filters must be true.
- percent: filters is the part being measured, among is the group it is measured within (empty means all rows).
  Example: percentage of women who survived: filters Survived = 1, among Sex = female.
- group_by gives one result per group. "Which X has the most Y": calculation sum of Y, group_by X, order largest, limit 1.
- "Most common X": count, group_by X, order largest, limit 1.
- list shows rows, sorted by column if given. correlation uses column and second_column.
- check is only for data quality questions: set action check, the check name and optionally column.
- You cannot see the values. Write text values as the user said them; for yes/no meaning in a number column use 1 or 0."""

def ai_plan(question, df, client):
    columns = [{"name": str(c), "type": "number" if pd.api.types.is_numeric_dtype(df[c]) else "text"}
               for c in df.columns]
    prompt = f"{INSTRUCTIONS}\nColumns: {json.dumps(columns)}\nQuestion: {question}"
    problem = "no reply"
    for model in MODELS:
        try:
            result = client.interactions.create(
                model=model, input=prompt, store=False,
                response_format={"type": "text", "mime_type": "application/json", "schema": PLAN_SCHEMA})
            return json.loads(result.output_text), None
        except Exception as error:
            problem = type(error).__name__
    return None, problem

# ---------- Python checks the plan and does the calculation ----------

class CannotAnswer(Exception):
    pass

def real_column(df, name):
    simple = lambda t: re.sub(r"[\s_]+", "", str(t).lower())
    matches = [c for c in df.columns if str(c) == name] or [c for c in df.columns if simple(c) == simple(name)]
    if len(matches) != 1:
        raise CannotAnswer(f"I cannot find the column '{name}'.")
    return matches[0]

def as_numbers(df, col):
    """The column as numbers, or an error if it is mostly not numbers."""
    n = numbers(df, col)
    filled = df[col].notna().sum()
    if pd.api.types.is_bool_dtype(df[col]) or filled == 0 or n.notna().sum() < 0.9 * filled:
        raise CannotAnswer(f"'{col}' is not a number column.")
    return n

def to_number(text):
    try:
        return float(str(text).replace(",", ""))
    except ValueError:
        raise CannotAnswer(f"'{text}' is not a number.")

def one_filter(df, item):
    col, op, values = real_column(df, item["column"]), item["op"], item.get("values") or []
    blank = df[col].isna() | (df[col].astype(str).str.strip() == "")
    if op in ("empty", "not_empty"):
        return (blank if op == "empty" else ~blank), f"{col} is {'empty' if op == 'empty' else 'filled'}"
    if not values:
        raise CannotAnswer(f"No value was given for '{col}'.")
    label = f"{col} {op} {' or '.join(map(str, values))}"
    is_number = pd.api.types.is_numeric_dtype(df[col]) and not pd.api.types.is_bool_dtype(df[col])
    if op == "contains":
        text = df[col].astype(str).str.lower()
        mask = pd.Series(False, index=df.index)
        for value in values:
            mask |= text.str.contains(str(value).lower(), regex=False)
        return mask & ~blank, label
    if op in ("=", "!="):
        if is_number:
            mask = numbers(df, col).isin([to_number(v) for v in values])
        else:
            column = df[col].map(clean, na_action="ignore")
            existing = set(column.dropna())
            wanted = [clean(v) for v in values]
            for value in wanted:
                if value not in existing:
                    examples = ", ".join(sorted(existing)[:8])
                    raise CannotAnswer(f"'{value}' is not a value in '{col}'. Some values there: {examples}")
            mask = column.isin(wanted)
        return (mask if op == "=" else ~mask) & ~blank, label
    if op not in (">", ">=", "<", "<=") or len(values) != 1:
        raise CannotAnswer(f"I cannot apply that condition to '{col}'.")
    text = df[col].dropna().astype(str)
    if not is_number and len(text) and text.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        column = pd.to_datetime(df[col], format="%Y-%m-%d", errors="coerce")
        limit = pd.to_datetime(str(values[0]), format="%Y-%m-%d", errors="coerce")
        if pd.isna(limit):
            raise CannotAnswer("Write the date as YYYY-MM-DD.")
    else:
        column, limit = as_numbers(df, col), to_number(values[0])
    compare = {">": column.gt, ">=": column.ge, "<": column.lt, "<=": column.le}[op]
    return compare(limit), label

def select(df, items, match="all"):
    masks = [one_filter(df, item) for item in items]
    keep = pd.Series(match != "any" or not masks, index=df.index)
    for mask, _ in masks:
        keep = (keep | mask) if match == "any" else (keep & mask)
    joiner = " or " if match == "any" else " and "
    return keep, joiner.join(label for _, label in masks)

def show_number(value):
    value = round(float(value), 2)
    return f"{value:.0f}" if value.is_integer() else f"{value:.2f}"

def run_plan(plan, df):
    if plan.get("action") == "cannot_answer":
        raise CannotAnswer(plan.get("reason") or "This cannot be answered from the table.")
    if plan.get("action") == "check":
        check = plan.get("check")
        if check not in CHECKS or plan.get("filters") or plan.get("among") or plan.get("group_by"):
            raise CannotAnswer("I cannot combine a data check with filters or groups.")
        if check == "duplicate_rows":
            return describe(df, check, None)
        cols = [real_column(df, plan["column"])] if plan.get("column") else columns_for(df, check)
        if check != "missing":
            cols = [c for c in cols if c in columns_for(df, check)]
        if not cols:
            raise CannotAnswer("No suitable column for that check.")
        return "\n".join(describe(df, check, c) for c in cols)

    kind = plan.get("calculation")
    names = {"count": "count rows", "percent": "percentage", "sum": "total", "mean": "average",
             "median": "median", "min": "lowest", "max": "highest", "distinct": "different values",
             "list": "show rows", "correlation": "relationship"}
    if kind not in names:
        raise CannotAnswer("I could not work out which calculation you need.")
    base, base_text = select(df, plan.get("among") or [])
    chosen, chosen_text = select(df, plan.get("filters") or [], plan.get("match", "all"))
    col = real_column(df, plan["column"]) if plan.get("column") else None
    group = real_column(df, plan["group_by"]) if plan.get("group_by") else None
    order, limit = plan.get("order") or "largest", max(int(plan.get("limit") or 0), 0)
    if group is not None and kind in ("list", "correlation", "distinct"):
        raise CannotAnswer("I cannot group that kind of question yet.")
    if kind in ("sum", "mean", "median", "min", "max", "distinct", "correlation") and col is None:
        raise CannotAnswer("I could not tell which column to use.")

    said = f"I understood: {names[kind]}" + (" of rows" if kind == "percent" else "")
    if col is not None and kind not in ("count", "percent"):
        said += f" of {col}"
    if kind == "correlation":
        said += f" and {plan.get('second_column')}"
    if chosen_text:
        said += f"; rows where {chosen_text}"
    if base_text:
        said += f"; within rows where {base_text}"
    if group is not None:
        said += f"; for each {group}"
    if limit:
        said += f"; {order} {limit}"
    rows_used = df[base & chosen]

    if kind == "percent":
        if not chosen_text:
            raise CannotAnswer("I could not tell what to take the percentage of.")
        def result(index):
            total = int(base.loc[index].sum())
            part = int((base & chosen).loc[index].sum())
            if total == 0:
                return None, ""
            return 100 * part / total, f"% ({part} of {total} rows)"
    elif kind == "count":
        def result(index):
            return int((base & chosen).loc[index].sum()), " rows"
    elif kind in ("sum", "mean", "median", "min", "max"):
        n = as_numbers(df, col)
        def result(index):
            values = n.loc[index][(base & chosen).loc[index]].dropna()
            if values.empty:
                return None, ""
            return getattr(values, kind)(), f" (from {len(values)} rows)"

    if kind in ("count", "percent", "sum", "mean", "median", "min", "max"):
        if group is None:
            value, note = result(df.index)
            if value is None:
                return f"{said}.\nNo matching data."
            if kind in ("sum", "mean", "median", "min", "max") and len(rows_used) > n[base & chosen].notna().sum():
                note += " Rows without a number were left out."
            return f"{said}.\nAnswer: {show_number(value)}{note}"
        keys = df[group].map(clean, na_action="ignore").fillna("(empty)")
        found = []
        for key, part in df.groupby(keys, sort=False):
            value, note = result(part.index)
            if value is not None and not (kind == "count" and value == 0):
                label = "(empty)" if key == "(empty)" else str(part[group].iloc[0]).strip()
                found.append((value, label, note))
        if not found:
            return f"{said}.\nNo matching data."
        found.sort(key=lambda x: x[0], reverse=order == "largest")
        wanted = limit or 15
        shown = found[:wanted]
        if limit:   # keep ties
            shown = [x for x in found if x in shown or x[0] == shown[-1][0]]
        lines = [f"- {label}: {show_number(value)}{note}" for value, label, note in shown[:15]]
        if len(found) > len(lines):
            lines.append(f"({len(lines)} of {len(found)} groups shown)")
        return "\n".join([said + "."] + lines)

    if rows_used.empty:
        return f"{said}.\nNo matching rows."
    if kind == "distinct":
        counts = rows_used[col].map(clean, na_action="ignore").value_counts()
        lines = [f"- {value}: {total}" for value, total in counts.head(15).items()]
        return "\n".join([f"{said}.", f"Answer: {len(counts)} different values (empty cells not counted)"] + lines)
    if kind == "correlation":
        other = real_column(df, plan.get("second_column") or "")
        pair = pd.DataFrame({"a": as_numbers(df, col), "b": as_numbers(df, other)}).loc[rows_used.index].dropna()
        if len(pair) < 3 or pair.a.nunique() < 2 or pair.b.nunique() < 2:
            raise CannotAnswer("There is not enough varied data to compare these columns.")
        r = pair.a.corr(pair.b)
        strength = "very weak or none" if abs(r) < 0.2 else "weak" if abs(r) < 0.4 else "moderate" if abs(r) < 0.7 else "strong"
        direction = "" if abs(r) < 0.2 else (", rising together" if r > 0 else ", one rises as the other falls")
        return (f"{said}.\nCorrelation: {r:.2f} ({strength}{direction}), from {len(pair)} rows. "
                "This measures a straight-line link only. It does not show cause.")
    if col is not None:
        try:
            key = as_numbers(df, col).loc[rows_used.index]
        except CannotAnswer:
            key = rows_used[col].astype(str).where(rows_used[col].notna())
        rows_used = rows_used.loc[key.sort_values(ascending=order == "smallest", na_position="last").index]
    wanted = min(limit or 5, 15)
    lines = [f"Row {i}: " + ", ".join(f"{c}={v}" for c, v in row.items()) for i, row in rows_used.head(wanted).iterrows()]
    return "\n".join([said + ".", f"Showing {len(lines)} of {len(rows_used)} rows:"] + lines)


CHECK_TALK = set("""any check are is there the a in of for ok values value rows row missing empty blank null duplicate
duplicates duplicated repeated negative unusual outlier outliers strange spelling spell invalid wrong valid correct
dates date id ids how many find show under over below above too young old 18 100 do we have column data""".split())

def simple_check(question, df):
    """True only if every word belongs to a plain data check, so nothing is ignored."""
    q = clean(re.sub(r"[?!.,]", " ", question.lower()))
    for c in sorted(df.columns, key=lambda c: -len(str(c))):
        for name in {clean(c), clean(str(c).replace("_", " "))}:
            q = re.sub(pattern_for(name), " ", q)
    return all(word in CHECK_TALK for word in q.split())

def answer(question, df, client=None):
    intent = simple_understand(question, df)
    action = intent["action"] if intent else None
    plain = clean(re.sub(r"[?!.]", " ", question.lower()))

    # 1. Fixed commands
    if action == "help":
        return HELP
    if action == "check_all":
        return check_all(df)
    if re.fullmatch(r"(show )?(summary|columns)|how many rows( are there)?", plain):
        return f"{len(df)} rows. Columns: {', '.join(map(str, df.columns))}."
    if re.fullmatch(r"(show )?row \d+", plain):
        n = int(plain.split()[-1])
        return df.iloc[n].to_string() if n < len(df) else f"Choose a row from 0 to {len(df) - 1}."

    # 2. Simple questions that Python fully understands
    local = data_question(question, df)
    refused = local is not None and local.startswith(("I am not sure", "'", "Name one", "Ask for one", "I found no numbers", "I cannot mix"))
    if local is not None and not refused:
        return local
    if action == "check" and simple_check(question, df):
        check, col = intent["check"], intent.get("column")
        if check == "duplicate_rows":
            return describe(df, check, None)
        allowed = columns_for(df, check)
        if col is not None and check != "missing" and col not in allowed:
            return f"That check does not suit the column '{col}'."
        cols = [col] if col is not None else allowed
        return "\n".join(describe(df, check, c) for c in cols) if cols else "No suitable column for that check."

    # 3. Everything else: the AI plans, Python calculates
    if client is not None:
        plan, problem = ai_plan(question, df, client)
        if plan is None:
            return f"The AI did not respond ({problem}). Check your API key, or try again in a minute."
        try:
            return run_plan(plan, df)
        except CannotAnswer as reason:
            return f"I could not answer: {reason}"
        except Exception as error:
            return f"I could not answer this safely ({type(error).__name__}). Try simpler words."
    if local is not None:
        return local + "\nThe AI is OFF. Add your Gemini key in the sidebar for harder questions."
    return "I don't know. The AI is OFF, so only simple questions work. Add your Gemini key in the sidebar, or type help."

# ============================================================
# Web page
# ============================================================

GREETING = "Hi! I am Ishu's data checker.\nType: check all\nType help for more examples."

def read_table(content):
    """Read CSV bytes into a table."""
    try:
        table = pd.read_csv(io.BytesIO(content), encoding="utf-8-sig")
    except UnicodeDecodeError:
        table = pd.read_csv(io.BytesIO(content), encoding="latin-1")
    if table.empty:
        raise ValueError("no rows")
    return table

# ---------- Look and feel ----------

# Original drawing: a girl robot checking a table with a magnifying glass
ROBOT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 220 190">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#4cc9ff"/><stop offset="1" stop-color="#a855f7"/></linearGradient></defs>
<g stroke="url(#g)" stroke-width="4" stroke-linejoin="round" stroke-linecap="round" fill="#4c2889">
<path d="M32 50C8 58 4 92 18 112c3-14 10-20 20-24z"/>
<path d="M114 50c24 8 28 42 14 62-3-14-10-20-20-24z"/>
<g fill="#111a4a">
<rect x="28" y="34" width="90" height="74" rx="32"/>
<path d="M54 114h38l22 50H32z"/>
<path d="M73 34V20" fill="none"/>
<path d="M48 126L24 146M98 126l32-6" fill="none"/>
<path d="M56 164v18M90 164v18" fill="none"/>
</g>
<path d="M34 55c8-22 52-30 76-8-18 2-30-2-38-12-6 12-20 20-38 20z"/>
<path d="M102 34L86 22v24zM102 34l16-12v24z" fill="#7c3aed"/>
<circle cx="102" cy="34" r="5" fill="#c4b5fd"/>
</g>
<circle cx="73" cy="15" r="6" fill="#c4b5fd"/>
<g fill="#7ee7ff"><ellipse cx="55" cy="73" rx="8" ry="10"/><ellipse cx="91" cy="73" rx="8" ry="10"/></g>
<g fill="#ffffff"><circle cx="58" cy="69" r="3"/><circle cx="94" cy="69" r="3"/></g>
<path d="M47 66l-8-5M52 62l-4-7M99 66l8-5M94 62l4-7" stroke="#7ee7ff" stroke-width="3" stroke-linecap="round"/>
<g fill="#8b5cf6" opacity=".75"><circle cx="43" cy="90" r="6"/><circle cx="103" cy="90" r="6"/></g>
<path d="M62 91q11 10 22 0" fill="none" stroke="#c4b5fd" stroke-width="4" stroke-linecap="round"/>
<path d="M73 147c-14-9-13-20-6-20 3 0 5 2 6 5 1-3 3-5 6-5 7 0 8 11-6 20z" fill="#7c3aed"/>
<g fill="#111a4a" stroke="url(#g)" stroke-width="4" stroke-linejoin="round" stroke-linecap="round">
<rect x="130" y="118" width="80" height="62" rx="8"/>
<path d="M130 138h80M130 159h80M157 118v62M183 118v62" fill="none" stroke-width="2"/>
<circle cx="164" cy="96" r="30" fill="#4cc9ff" fill-opacity=".18"/>
<path d="M142 116l-11 5" fill="none" stroke-width="7"/>
</g>
<path d="M153 97l8 8 15-17" fill="none" stroke="#7ee7ff" stroke-width="5" stroke-linecap="round"/>
</svg>"""

STYLE = """<style>
.stApp { background: radial-gradient(circle at 75% 5%, #2b1870 0%, #0d1240 38%, #060924 100%); color:#e8ecff; }
[data-testid="stHeader"] { background:transparent; }
[data-testid="stHeader"] button, [data-testid="stHeader"] a, [data-testid="stToolbar"] * { color:#cdd6ff !important; }
[data-testid="stSidebar"] { background:linear-gradient(180deg,#0b1038,#140c3d); border-right:1px solid #36408f; }
.stApp h1, .stApp h2, .stApp h3, .stApp label, .stApp label p, .stApp li,
[data-testid="stMarkdownContainer"] p, [data-testid="stText"], [data-testid="stText"] * { color:#e8ecff !important; }
.stApp [data-testid="stCaptionContainer"] [data-testid="stMarkdownContainer"] p, .stApp [data-testid="stCaptionContainer"] { color:#b9c3f5 !important; opacity:1; }
[data-testid="stTextInput"] button, [data-testid="stTextInput"] button svg { color:#cdd6ff !important; fill:#cdd6ff; }

.hero { display:flex; align-items:center; gap:22px; flex-wrap:wrap; padding:20px 24px; border-radius:20px;
  background:linear-gradient(120deg,rgba(33,55,140,.65),rgba(76,29,149,.55)); border:1px solid #6d5df6;
  box-shadow:0 0 28px rgba(109,93,246,.45); }
.hero img { width:170px; max-width:40%; filter:drop-shadow(0 0 10px rgba(76,201,255,.65)); }
.hero div { flex:1; min-width:220px; }
.hero h1 { margin:0; padding:0; font-size:2rem; line-height:1.2; text-shadow:0 0 16px rgba(76,201,255,.7); }
.hero p { margin:8px 0 0; color:#c3ccff; }

[data-testid="stAlertContainer"] { background:rgba(124,58,237,.18); border:1px solid rgba(124,108,255,.8); }
[data-testid="stAlertContainer"] p { color:#cdd6ff !important; }
[data-testid="stFileUploaderDropzone"] { background:#10184a; border:1px dashed #6d5df6; }
[data-testid="stFileUploaderDropzone"] * { color:#e8ecff !important; }
[data-testid="stFileUploaderDropzone"] button { background:#2a2f7a; border:1px solid #6d5df6; }
[data-testid="stFileChip"], [data-testid="stFileUploaderFile"] { background:#1b2362 !important; }
[data-testid="stTextInput"] div[data-baseweb="input"], [data-testid="stTextInput"] div[data-baseweb="base-input"],
[data-testid="stTextInputRootElement"] { background:#10184a !important; border-color:#6d5df6 !important; }
[data-testid="stTextInput"] input { color:#ffffff !important; caret-color:#ffffff; }

[data-testid="stExpander"] details { background:rgba(23,31,92,.75); border:1px solid #3f4bb0; }
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary * { color:#e8ecff !important; }
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary:hover { background:#1b2468 !important; border-color:#3f4bb0 !important; }
.stApp [data-testid="stSidebar"] a, .stApp [data-testid="stChatMessage"] a { color:#7ee7ff !important; }
.preview { overflow-x:auto; }
.preview table { border-collapse:collapse; font-size:.85rem; color:#e8ecff; }
.preview th, .preview td { border:1px solid #3f4bb0; padding:5px 10px; white-space:nowrap; }
.preview th { background:#27307a; }

[data-testid="stChatMessage"] { background:rgba(26,36,104,.78); border:1px solid #3f6fe0; border-radius:16px;
  box-shadow:0 0 14px rgba(63,111,224,.28); padding:14px; }
[data-testid="stChatMessage"]:has([aria-label="Chat message from user"]) { background:rgba(70,30,130,.7);
  border-color:#a855f7; box-shadow:0 0 14px rgba(168,85,247,.32); }

[data-testid="stBottom"], [data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] { background:#080b2b !important; }
[data-testid="stChatInput"] > div { background:#121a52 !important; border:1px solid #7c6cff !important;
  box-shadow:0 0 18px rgba(124,108,255,.45); }
[data-testid="stChatInput"] div { background-color:transparent; }
[data-testid="stChatInput"] textarea { color:#ffffff !important; caret-color:#ffffff; }
[data-testid="stChatInput"] textarea::placeholder { color:#aab4e8 !important; }
[data-testid="stChatInput"] > div:focus-within, [data-testid="stTextInput"] div[data-baseweb="input"]:focus-within {
  border-color:#7c6cff !important; box-shadow:0 0 18px rgba(124,108,255,.8) !important; }
[data-testid="stExpander"] summary:hover, [data-testid="stExpander"] summary:hover * { color:#7ee7ff !important; fill:#7ee7ff !important; }
[data-testid="stFileUploader"] button:hover, [data-testid="stFileUploader"] button:focus { border-color:#7ee7ff !important; color:#7ee7ff !important; }
[data-testid="stButton"] button:focus, [data-testid="stButton"] button:active { border-color:#7ee7ff !important; color:#fff !important; }
[data-testid="InputInstructions"], [data-testid="InputInstructions"] *, [data-testid="stChatInput"] [data-testid="stChatInputInstructions"] { color:#b9c3f5 !important; }
[data-testid="stSidebarCollapseButton"] *, [data-testid="stSidebarHeader"] button * { color:#e8ecff !important; }
[data-testid="stChatInput"] button { color:#ffffff; }

/* stars */
.stApp::before { content:""; position:fixed; inset:0; pointer-events:none; opacity:.55;
  background-image: radial-gradient(1.5px 1.5px at 20px 30px,#fff,transparent), radial-gradient(1.5px 1.5px at 140px 110px,#7ee7ff,transparent),
  radial-gradient(1px 1px at 90px 190px,#c4b5fd,transparent), radial-gradient(2px 2px at 230px 60px,#c4b5fd,transparent);
  background-size:260px 230px; animation:twinkle 5s ease-in-out infinite alternate; }
@keyframes twinkle { from { opacity:.25; } to { opacity:.7; } }
@keyframes float { 0%,100% { transform:translateY(0) rotate(-1deg); } 50% { transform:translateY(-12px) rotate(1deg); } }
@keyframes glow { 0%,100% { box-shadow:0 0 24px rgba(109,93,246,.45); } 50% { box-shadow:0 0 44px rgba(168,85,247,.55); } }

.hero { position:relative; padding:30px 28px !important; animation:glow 5s ease-in-out infinite;
  background:linear-gradient(120deg,rgba(30,64,175,.75),rgba(91,33,182,.7),rgba(76,29,149,.55)) !important; }
.hero img { width:215px !important; max-width:55% !important; animation:float 4s ease-in-out infinite; }
.stApp .hero h1 { font-size:2.4rem; text-shadow:none; background:linear-gradient(90deg,#7ee7ff,#c4b5fd,#c4b5fd);
  -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent;
  filter:drop-shadow(0 0 10px rgba(124,108,255,.8)); }
.badges { display:flex; flex-wrap:wrap; gap:8px; margin-top:14px; }
.badges span { padding:6px 12px; border-radius:999px; font-size:.82rem; color:#fff;
  background:rgba(255,255,255,.12); border:1px solid rgba(255,255,255,.35); }

[data-testid="stButton"] button { width:100%; min-height:52px; border-radius:14px; border:1px solid rgba(255,255,255,.3);
  background:linear-gradient(100deg,#2563eb,#7c3aed,#9333ea); box-shadow:0 0 16px rgba(124,58,237,.5);
  transition:transform .15s, box-shadow .15s; }
.stApp [data-testid="stButton"] button p { color:#fff !important; font-weight:600; }
[data-testid="stButton"] button:hover { transform:translateY(-3px); box-shadow:0 0 28px rgba(168,85,247,.75); border-color:#fff; }
[data-testid="stChatInput"] button { background:linear-gradient(135deg,#7c3aed,#9333ea) !important; border-radius:10px; }
@media (max-width:640px) { .hero { padding:14px 16px !important; gap:8px; } .hero img { width:110px !important; }
  .stApp .hero h1 { font-size:1.6rem; } .badges { display:none; } .hero p { font-size:.85rem; }
  [data-testid="stButton"] button { min-height:40px; } }
@media (prefers-reduced-motion: reduce) { .stApp::before, .hero, .hero img { animation:none !important; } }
</style>"""

# The girl robot's face, used beside the bot's messages
FACE = ROBOT.replace('viewBox="0 0 220 190"', 'viewBox="12 4 124 114" width="64" height="64"').split('<path d="M54 114h38')[0]
FACE += "</g>" + ROBOT[ROBOT.index('<path d="M34 55c8'):ROBOT.index('<path d="M73 147c')] + "</svg>"

USER_FACE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">'
             '<rect width="64" height="64" rx="14" fill="#4c2889"/><circle cx="32" cy="25" r="11" fill="#7ee7ff"/>'
             '<path d="M12 56c2-24 38-24 40 0z" fill="#7ee7ff"/></svg>')

def as_picture(svg):
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()

def show_header():
    st.html(STYLE)
    st.html(f'<div class="hero"><img src="{as_picture(ROBOT)}" alt="Girl robot checking a table">'
            "<div><h1>Ishu's DataCheck Bot</h1><p>Checks a CSV table for possible problems and answers "
            "questions about it. A prototype: always verify the answers.</p>"
            '<div class="badges"><span>Finds data problems</span><span>Counts and averages</span>'
            '<span>AI questions with your key</span></div></div></div>')

# ---------- How to get a key ----------

KEY_STEPS = """1. Open [Google AI Studio](https://aistudio.google.com/apikey).
2. Sign in with your Google account and accept the terms.
3. Copy the key shown there, or click **Create API key**.
4. Paste it into **Your Gemini API key** in the left panel and press **Enter**. On a phone, open the panel with **>>**.

A free tier with usage limits is available. Billing is not needed to try this app. Never share your key."""

def show_text(text):
    """The fixed key instructions get a clickable link. Everything else is shown as plain text."""
    if text == KEY_STEPS:
        st.markdown(text)
    else:
        st.text(text)

def make_client(key):
    if not key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=key)
    except Exception as error:
        st.sidebar.error(f"The AI could not start ({type(error).__name__}).")
        return None

AVATARS = {"assistant": as_picture(FACE), "user": as_picture(USER_FACE)}

st.set_page_config(page_title="Ishu's DataCheck Bot", page_icon=as_picture(FACE))
show_header()

with st.sidebar:
    st.header("Your data")
    st.warning("Use only public or fake data. Your file is uploaded to the server that runs this app.")
    upload = st.file_uploader("Upload a CSV file (under 5 MB)", type="csv", max_upload_size=5)
    st.header("AI (optional)")
    key = st.text_input("Your Gemini API key", type="password")
    with st.expander("How to get a key"):
        st.markdown(KEY_STEPS)
    st.caption("The AI receives your question, column names and column types, not your data rows. This app does not save your key to a file.")

# Which table is in use? Start a new chat when it changes.
source = upload.file_id if upload is not None else "practice"
if st.session_state.get("source") != source:
    st.session_state.source = source
    note = "Practice data is loaded."
    table = data
    if upload is not None:
        try:
            if upload.size > MAX_BYTES:
                raise ValueError("too big")
            table = read_table(upload.getvalue())
            note = f"Loaded {upload.name} with {len(table)} rows."
        except Exception as error:
            reason = "it is over 5 MB" if upload.size > MAX_BYTES else type(error).__name__
            note = f"I could not load {upload.name} ({reason}). Practice data is loaded instead."
    st.session_state.table = table
    st.session_state.messages = [("assistant", f"{GREETING}\n{note}")]

df = st.session_state.table
client = make_client(key.strip())
st.sidebar.write("AI is **ON**." if client else "AI is **OFF**: only simple questions work.")

with st.expander(f"Preview: {len(df)} rows, {len(df.columns)} columns (first 5 shown)"):
    st.html(f'<div class="preview">{df.head().to_html(border=0)}</div>')

clicked = None
quick = [("Check all", "check all"), ("Summary", "summary"), ("Help", "help"),
         ("Get a key", "get a key")]
for column, (label, command) in zip(st.columns(4), quick):
    if column.button(label, width="stretch"):
        clicked = command

for who, text in st.session_state.messages:
    with st.chat_message(who, avatar=AVATARS[who]):
        show_text(text)

typed = st.chat_input("Ask about your data", max_chars=300)
question = clicked or typed
if question and question.strip():
    with st.chat_message("user", avatar=AVATARS["user"]):
        st.text(question)
    with st.chat_message("assistant", avatar=AVATARS["assistant"]):
        with st.spinner("Checking..."):
            try:
                if re.fullmatch(r"(how (can i |do i |to )?)?get (a |an |the )?(api |gemini )?key *[?]?", question.strip().lower()):
                    reply = KEY_STEPS
                else:
                    reply = answer(question.strip(), df, client)
            except Exception as error:
                reply = f"Sorry, something went wrong ({type(error).__name__})."
        show_text(reply)
    st.session_state.messages += [("user", question), ("assistant", reply)]
