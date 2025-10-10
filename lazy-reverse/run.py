#!/usr/bin/env python3
import itertools
import math
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

# Configuration
STACK_EXE = "stack"
TARGET_EXE = "lazy-reverse"

LIMITS = ["before", "after"]
CONS = ["sum", "length"]
PRODS = ["reverse", "rev_knot", "rev_forward", "rev_backward"]
LISTS = ["nats", "fibs", "fibs'"]

# Byte metrics ("allocated", "copied", "residency") are reported in MB (10^6 bytes).


# Skip rules:
# - reverse with after
# - after with sum
def is_skipped(limit: str, cons: str, prod: str) -> bool:
    if limit == "after" and prod == "reverse":
        return True
    if limit == "after" and cons == "sum":
        return True
    return False


# Order for tidy table
PROD_ORDER = ["reverse", "rev_forward", "rev_backward", "rev_knot"]
LIMIT_ORDER = ["before", "after"]
CONS_ORDER = ["sum", "length"]
LIST_ORDER = ["nats", "fibs", "fibs'"]

# Regex patterns for RTS -s parsing
RE_ALLOC = re.compile(r"^\s*([0-9,]+)\s+bytes allocated in the heap", re.M)
RE_COPIED = re.compile(r"^\s*([0-9,]+)\s+bytes copied during GC", re.M)
RE_RESIDENCY = re.compile(r"^\s*([0-9,]+)\s+bytes maximum residency", re.M)
RE_MEMORY = re.compile(
    r"^\s*([0-9]+(?:\.[0-9]+)?)\s+MiB total memory in use", re.M
)
RE_MUT = re.compile(
    r"^\s*MUT\s+time\s+([0-9.]+)s\s+\(\s*([0-9.]+)s elapsed\)", re.M
)
RE_GC = re.compile(
    r"^\s*GC\s+time\s+([0-9.]+)s\s+\(\s*([0-9.]+)s elapsed\)", re.M
)
RE_TOTAL = re.compile(
    r"^\s*Total\s+time\s+([0-9.]+)s\s+\(\s*([0-9.]+)s elapsed\)", re.M
)


def parse_bytes_num(s: str) -> Optional[int]:
    try:
        return int(s.replace(",", ""))
    except Exception:
        return None


def round_sig(x: float, sig: int = 3) -> float:
    if x == 0:
        return 0.0
    return round(x, sig - 1 - int(math.floor(math.log10(abs(x)))))


def pick_unit(value_bytes: int) -> Tuple[float, str]:
    mb = value_bytes / 1e6
    return mb, "MB"


def fmt_bytes_3sig(n_bytes: Optional[int]) -> str:
    if n_bytes is None:
        return "-"
    val, unit = pick_unit(n_bytes)
    # 3 significant digits; avoid scientific notation for typical ranges
    # Use general format with 3 sig figs, then normalize trailing zeros
    s = f"{val:.3g}"
    # Ensure there's at least one decimal if s would be an integer and < 100
    # (purely aesthetic; can be omitted if undesired)
    try:
        f = float(s)
        if f < 100 and abs(f - round(f)) < 1e-12:
            s = f"{f:.1f}"
    except Exception:
        pass
    return f"{s} {unit}"


def fmt_mib(x: Optional[float]) -> str:
    if x is None:
        return "-"
    if abs(x - round(x)) < 1e-9:
        return f"{int(round(x))} MiB"
    return f"{x:.1f} MiB"


def fmt_sec(s: Optional[float]) -> str:
    if s is None:
        return "-"
    return f"{s:.3f}s"


def parse_rts_stats(text: str) -> Dict[str, Optional[float]]:
    m_alloc = RE_ALLOC.search(text)
    m_copied = RE_COPIED.search(text)
    m_resid = RE_RESIDENCY.search(text)
    m_mem = RE_MEMORY.search(text)
    m_mut = RE_MUT.search(text)
    m_gc = RE_GC.search(text)
    m_total = RE_TOTAL.search(text)

    allocated = parse_bytes_num(m_alloc.group(1)) if m_alloc else None
    copied = parse_bytes_num(m_copied.group(1)) if m_copied else None
    residency = parse_bytes_num(m_resid.group(1)) if m_resid else None
    memory = float(m_mem.group(1)) if m_mem else None

    # Use elapsed times (values inside parentheses)
    mut_elapsed = float(m_mut.group(2)) if m_mut else None
    gc_elapsed = float(m_gc.group(2)) if m_gc else None
    total_elapsed = float(m_total.group(2)) if m_total else None

    return {
        "allocated": allocated,
        "copied": copied,
        "residency": residency,
        "memory_mib": memory,
        "mut_s": mut_elapsed,
        "gc_s": gc_elapsed,
        "total_s": total_elapsed,
    }


def run_stack_build() -> None:
    if shutil.which(STACK_EXE) is None:
        print("Error: 'stack' not found in PATH.", file=sys.stderr)
        sys.exit(1)
    try:
        subprocess.run([STACK_EXE, "build"], check=True)
    except subprocess.CalledProcessError as e:
        print("stack build failed.", file=sys.stderr)
        sys.exit(e.returncode)


def run_case(
    limit: str, cons: str, prod: str, lst: str
) -> Tuple[int, str, str]:
    cmd = [
        STACK_EXE,
        "exec",
        TARGET_EXE,
        "--",
        limit,
        cons,
        prod,
        lst,
        "+RTS",
        "-s",
        "-RTS",
    ]
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, check=True)
        # RTS -s goes to stderr; combine just in case
        combined = cp.stdout + "\n" + cp.stderr
        return (0, combined, "")
    except subprocess.CalledProcessError as e:
        combined = (e.stdout or "") + "\n" + (e.stderr or "")
        return (e.returncode, combined, "exec-failed")


def row_group_key(r: Dict) -> Tuple[str, str, str]:
    # Group rows by (limit, cons, list) -> up to 4 prods per group
    return (r["limit"], r["cons"], r["list"])


def main() -> None:
    run_stack_build()

    combos: List[Tuple[str, str, str, str]] = []
    for limit, cons, prod, lst in itertools.product(
        LIMITS, CONS, PRODS, LISTS
    ):
        if is_skipped(limit, cons, prod):
            continue
        combos.append((limit, cons, prod, lst))

    results: List[Dict] = []
    for i, (limit, cons, prod, lst) in enumerate(combos, 1):
        print(
            f"[{i}/{len(combos)}] {limit} {cons} {prod} {lst}",
            file=sys.stderr,
        )
        rc, out, errtag = run_case(limit, cons, prod, lst)
        stats = parse_rts_stats(out)

        row = {
            "limit": limit,
            "cons": cons,
            "prod": prod,
            "list": lst,
            "allocated": stats["allocated"],
            "copied": stats["copied"],
            "residency": stats["residency"],
            "memory_mib": stats["memory_mib"],
            "mut_s": stats["mut_s"],
            "gc_s": stats["gc_s"],
            "total_s": stats["total_s"],
            "error": None if rc == 0 else errtag or "error",
        }
        results.append(row)

    # Per-group baselines (reverse)
    baselines: Dict[Tuple[str, str, str], float] = {}
    for r in results:
        if r["prod"] == "reverse" and r["total_s"] is not None:
            baselines[row_group_key(r)] = r["total_s"]

    # Per-group best total among non-reverse rows
    group_best: Dict[Tuple[str, str, str], float] = {}
    for r in results:
        if r["prod"] == "reverse":
            continue
        if r["total_s"] is None:
            continue
        gk = row_group_key(r)
        best = group_best.get(gk)
        if best is None or r["total_s"] < best:
            group_best[gk] = r["total_s"]

    # Prepare printable rows and compute x_base
    printable: List[Dict] = []
    for r in results:
        gk = row_group_key(r)
        base = baselines.get(gk)
        x_base: Optional[float] = (
            (r["total_s"] / base) if (base and r["total_s"]) else None
        )
        printable.append({**r, "x_base": x_base})

    # Build table (Markdown) with dynamic widths and vertical separators
    headers = [
        "limit",
        "cons",
        "prod",
        "list",
        "allocated",
        "copied",
        "residency",
        "memory",
        "MUT",
        "GC",
        "total",
        "x_base",
    ]

    def row_to_strs(r: Dict) -> List[str]:
        # Highlight the winning product (within group, excluding reverse)
        gk = row_group_key(r)
        best = group_best.get(gk)
        is_winner = (
            r["prod"] != "reverse"
            and r["total_s"] is not None
            and best is not None
            and abs(r["total_s"] - best) < 1e-12
        )
        if r["prod"] == "reverse":
            prod_name = "reverse"
        elif is_winner:
            prod_name = f"**{r['prod']}**"
        else:
            prod_name = r["prod"]

        if r["x_base"] is not None:
            xbase_str = (
                "1.00x" if r["prod"] == "reverse" else f"{r['x_base']:.2f}x"
            )
        else:
            xbase_str = "n/a" if r["prod"] != "reverse" else "-"

        return [
            r["limit"],
            r["cons"],
            prod_name,
            r["list"],
            fmt_bytes_3sig(r["allocated"]),
            fmt_bytes_3sig(r["copied"]),
            fmt_bytes_3sig(r["residency"]),
            fmt_mib(r["memory_mib"]),
            fmt_sec(r["mut_s"]),
            fmt_sec(r["gc_s"]),
            fmt_sec(r["total_s"]),
            xbase_str,
        ]

    # Precompute all row strings and group keys for width calc and separators
    grouped: Dict[Tuple[str, str, str], List[Dict]] = defaultdict(list)
    for r in printable:
        grouped[row_group_key(r)].append(r)

    def group_sort_key(gk: Tuple[str, str, str]) -> Tuple[int, int, int]:
        return (
            LIMIT_ORDER.index(gk[0]),
            CONS_ORDER.index(gk[1]),
            LIST_ORDER.index(gk[2]),
        )

    ordered_group_keys = sorted(grouped.keys(), key=group_sort_key)

    body_rows: List[Tuple[Tuple[str, str, str], List[str]]] = []
    for gk in ordered_group_keys:
        entries = grouped[gk]
        entries.sort(
            key=lambda entry: PROD_ORDER.index(entry["prod"])
            if entry["prod"] in PROD_ORDER
            else 999
        )
        for entry in entries:
            body_rows.append((gk, row_to_strs(entry)))

    # Compute column widths
    colw = [0] * len(headers)
    for i, h in enumerate(headers):
        colw[i] = max(colw[i], len(h))
    for _, row in body_rows:
        for i, cell in enumerate(row):
            colw[i] = max(colw[i], len(cell))

    # Markdown emitters (with vertical lines)
    def emit_md_row(cells: List[str]) -> None:
        parts: List[str] = []
        for i, cell in enumerate(cells):
            align_left = i <= 3  # text columns left, numeric right
            text = cell.ljust(colw[i]) if align_left else cell.rjust(colw[i])
            parts.append(f" {text} ")
        print("|" + "|".join(parts) + "|")

    def emit_md_align_row() -> None:
        # Left align first 4, right align the rest
        parts: List[str] = []
        for i in range(len(headers)):
            if i <= 3:
                parts.append(":---")
            else:
                parts.append("---:")
        print("|" + "|".join(parts) + "|")

    def emit_md_group_rule_row() -> None:
        # Visual horizontal separator between groups in Markdown table
        parts: List[str] = []
        for _ in range(len(headers)):
            parts.append(" ")
        print("|" + "|".join(parts) + "|")

    # Header
    emit_md_row(headers)
    emit_md_align_row()

    # Body with group separators (horizontal rules between groups)
    for idx, (gk, row) in enumerate(body_rows):
        emit_md_row(row)
        if idx + 1 < len(body_rows):
            next_gk = body_rows[idx + 1][0]
            if next_gk != gk:
                emit_md_group_rule_row()

    # Exit code nonzero if any run failed
    failed = [r for r in results if r["error"]]
    if failed:
        print(
            f"\nWarning: {len(failed)} run(s) failed; they are included "
            "with missing metrics.",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
