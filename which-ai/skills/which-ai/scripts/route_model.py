#!/usr/bin/env python3
"""which-ai router: LMArena ratings (quality) + OpenRouter prices. Nothing is estimated or invented."""
import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timezone

BUDGET_LABELS = {"free": 0.0, "low": 1.0, "medium": 5.0, "high": 100.0}  # $ per 1M input tokens
MODALITY_SOURCE = {"text": ("text", "overall"), "coding": ("text", "coding"), "vision": ("vision", "overall")}
SUFFIXES = re.compile(r"-(high|medium|low|max|min|thinking|nothinking|reasoning|preview|latest|exp|experimental|instruct|chat|it)$")


def parse_budget(value):
    label = value.strip().lower()
    if label in BUDGET_LABELS:
        return BUDGET_LABELS[label]
    try:
        return float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid budget '{value}'. Use a number ($ per 1M input tokens) or one of: {', '.join(BUDGET_LABELS)}")


def norm(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def base_name(name):
    n = name.lower().split("/")[-1]
    prev = None
    while prev != n:
        prev, n = n, SUFFIXES.sub("", n)
    return n


def params_b(name):
    """Total parameter count in billions read from the model name (largest 'NNb'), or None."""
    nums = [float(x) for x in re.findall(r"(?<![a-z])(?:a|e)?(\d+(?:\.\d+)?)b(?![a-z0-9])", name.lower())]
    return max(nums) if nums else None


def read_arena_file(p):
    if p.endswith(".parquet"):
        import pyarrow.parquet as pq
        return pq.read_table(p).to_pylist()
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and data.get("error"):
        raise ValueError(data["error"])
    return [r.get("row", r) for r in (data.get("rows", []) if isinstance(data, dict) else [])]


def load_arena(paths, category):
    rows, published = [], None
    for p in paths:
        try:
            file_rows = read_arena_file(p)
        except Exception as e:
            print(f"> Could not read Arena file {p}: {e}")
            continue
        for row in file_rows:
            if row.get("category") == category and row.get("rating"):
                rows.append(row)
                published = row.get("leaderboard_publish_date") or published
    best = {}
    for r in rows:
        k = r["model_name"]
        if k not in best or r["rating"] > best[k]["rating"]:
            best[k] = r
    return list(best.values()), published


def load_openrouter(path):
    if not path:
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("data", [])
    except Exception as e:
        print(f"> Could not read OpenRouter file {path}: {e}")
        return []


def index_openrouter(or_models):
    base, free = {}, {}
    for m in or_models:
        mid = m.get("id", "")
        if ":" not in mid:
            base[mid] = m
        elif mid.endswith(":free"):
            free[mid.split(":")[0]] = m
    return base, free


def tokens(name):
    """Name parts, e.g. 'claude-opus-4-5' and 'claude-opus-4.5' -> ['claude', 'opus', '4', '5']; trailing '-0' dropped."""
    t = [x for x in re.split(r"[^a-z0-9]+", base_name(name)) if x]
    while len(t) > 1 and t[-1] == "0":
        t.pop()
    return t


def match_openrouter(arena_name, base):
    """OpenRouter id whose name parts equal the Arena name's, or are a prefix of them.

    A leftover date or variant tag is fine ('claude-opus-4-5-20251101' -> 'claude-opus-4.5'); a leftover
    version number is not ('mistral-large-4' must not match the older 'mistral-large'). '~' ids are
    aliases that move to whatever model is newest, so they are never matched.
    """
    a = tokens(arena_name)
    best, best_len = None, 0
    for mid in base:
        if mid.startswith("~"):
            continue
        s = tokens(mid)
        if len("".join(s)) < 5 or a[: len(s)] != s or len(s) <= best_len:
            continue
        rest = a[len(s):]
        if rest and re.fullmatch(r"\d{1,3}", rest[0]) and not any(re.fullmatch(r"\d{4,}", x) for x in rest):
            continue  # next part is a version number: a different, newer model
        best, best_len = mid, len(s)
    return best


def price_per_m(m):
    try:
        return float(m.get("pricing", {}).get("prompt", 0)) * 1_000_000
    except (TypeError, ValueError):
        return None


def new_unrated(or_models, arena, a, usable):
    """OpenRouter models released in the last --new-days with no Arena rating for this task yet.

    Arena needs days to weeks of votes before it rates a model, so these are listed separately and never
    ranked: there is no quality score to rank them on.
    """
    base, free = index_openrouter(or_models)
    rated = {match_openrouter(r["model_name"], base) for r in arena}
    cutoff = time.time() - a.new_days * 86400
    out = []
    for mid, m in base.items():
        if mid in rated or mid.startswith("~") or (m.get("created") or 0) < cutoff:
            continue
        arch = m.get("architecture") or {}
        if "text" not in (arch.get("output_modalities") or ["text"]):
            continue
        if a.modality == "vision" and "image" not in (arch.get("input_modalities") or []):
            continue
        row = {"id": mid, "created": m["created"]}
        if a.deployment == "local":
            hf = m.get("hugging_face_id") or ""
            p = params_b(hf) or params_b(mid)
            if not hf or p is None or p * 0.58 + 0.5 > usable:
                continue
            row.update(id=hf, need=p * 0.58 + 0.5)
        else:
            pr = price_per_m(m)
            if (pr is None or pr > a.budget) and mid in free:
                row["id"], pr = free[mid]["id"], price_per_m(free[mid])
            if pr is None or pr < 0 or pr > a.budget:
                continue
            row["price"] = pr
        out.append(row)
    return sorted(out, key=lambda r: r["created"], reverse=True)


def print_new(new, a):
    if not new:
        print(f"\n_No unrated models released in the last {a.new_days} days fit this request._")
        return
    print(f"\n#### New in the last {a.new_days} days — not yet rated on Arena")
    print("_No quality score exists for these yet. Mention them; do not rank them against the rated models above._\n")
    print(f"| Released (UTC) | Model | {'RAM (4-bit)' if a.deployment == 'local' else 'Price /1M in'} |")
    print("|---|---|---|")
    for r in new[: a.top]:
        day = datetime.fromtimestamp(r["created"], timezone.utc).strftime("%Y-%m-%d")
        col = f"~{r['need']:.1f} GB" if a.deployment == "local" else f"${r['price']:.2f}"
        print(f"| {day} | `{r['id']}` | {col} |")
    if len(new) > a.top:
        print(f"\n_{len(new) - a.top} more; raise --top to see them._")


def main():
    ap = argparse.ArgumentParser(description="Intent-based LLM routing on LMArena ratings + OpenRouter prices.")
    ap.add_argument("--budget", type=parse_budget, default=None,
                    help="USD per 1M input tokens, or free/low/medium/high (required for --deployment cloud; ignored for local)")
    ap.add_argument("--deployment", choices=["cloud", "local"], default="cloud")
    ap.add_argument("--modality", choices=list(MODALITY_SOURCE), default="text")
    ap.add_argument("--ram", type=float, default=0.0, help="RAM in GB of the machine that will run the model (required for --deployment local)")
    ap.add_argument("--openrouter-file", default="", help="OpenRouter /api/v1/models JSON")
    ap.add_argument("--elo-file", nargs="+", default=[], help="Arena leaderboard: arena.parquet, or JSON page(s) from datasets-server")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--new-days", type=int, default=30, help="List unrated OpenRouter models released in the last N days")
    a = ap.parse_args()

    cfg, cat = MODALITY_SOURCE[a.modality]
    arena, published = load_arena(a.elo_file, cat)
    if not arena:
        print(f"### 🤖 which-ai Error\n> No Arena ratings loaded for `{cfg}/{cat}`. Re-download the leaderboard (SKILL.md step 2).")
        return
    or_models = load_openrouter(a.openrouter_file)

    picks, skipped, usable = [], 0, 0.0
    if a.deployment == "local":
        if a.ram <= 0:
            print("### 🤖 which-ai Error\n> Local deployment needs `--ram <GB>` of the machine that will run the model.")
            return
        usable = a.ram * 0.75 - 4.0  # GPU can wire ~75% of RAM on a Mac; keep ~4 GB for context
        for r in arena:
            if (r.get("license") or "").lower() in ("", "proprietary"):
                continue
            p = params_b(r["model_name"])
            if p is None:
                skipped += 1
                continue
            need = p * 0.58 + 0.5  # 4-bit weights
            if need <= usable:
                picks.append({**r, "need": need, "price": 0.0})
    else:
        if a.budget is None:
            print("### 🤖 which-ai Error\n> Cloud deployment needs `--budget` (USD per 1M input tokens, or free/low/medium/high). Ask the user; do not assume one.")
            return
        if not or_models:
            print("### 🤖 which-ai Error\n> Cloud routing needs the OpenRouter file for prices (SKILL.md step 2).")
            return
        base, free = index_openrouter(or_models)
        seen = {}
        for r in arena:
            mid = match_openrouter(r["model_name"], base)
            if not mid:
                skipped += 1
                continue
            use_id, pr = mid, price_per_m(base[mid])
            if (pr is None or pr > a.budget) and mid in free:
                use_id, pr = free[mid]["id"], price_per_m(free[mid])
            if pr is None or pr < 0 or pr > a.budget:
                continue
            if use_id not in seen or r["rating"] > seen[use_id]["rating"]:
                seen[use_id] = {**r, "or_id": use_id, "price": pr}
        picks = list(seen.values())

    new = new_unrated(or_models, arena, a, usable) if or_models else []
    if not picks:
        lim = f"RAM {a.ram:.0f} GB" if a.deployment == "local" else f"budget ${a.budget:.2f}/1M"
        print(f"### 🤖 which-ai Error\n> No rated model fits ({lim}, {a.modality}).")
        if or_models:
            print_new(new, a)
        return
    picks.sort(key=lambda r: r["rating"], reverse=True)
    top = picks[0]

    print("### 🤖 which-ai Recommendation")
    print(f"* **Recommended Model:** `{top.get('or_id', top['model_name'])}`" + (f" (Arena: `{top['model_name']}`)" if top.get("or_id") else ""))
    cost = "Cost: `free` (runs on your machine)" if a.deployment == "local" else f"Budget: `${a.budget:.2f}`/1M input"
    print(f"* **Intent Parsed:** Deployment: `{a.deployment.upper()}` | Modality: `{a.modality.upper()}` | {cost}")
    print(f"* **Arena Rating:** `{top['rating']:.0f}` (95% CI {top['rating_lower']:.0f}–{top['rating_upper']:.0f}, {int(top['vote_count'])} votes) — LMArena `{cfg}/{cat}`, published {published}")
    if a.deployment == "local":
        print(f"* **RAM:** `{a.ram:.0f} GB` machine, model needs `~{top['need']:.1f} GB` at 4-bit (fits under `{a.ram * 0.75 - 4:.1f} GB` usable)")
    else:
        print(f"* **Price:** `${top['price']:.2f}` / 1M input tokens (OpenRouter)")
    print(f"\n| # | Model | Arena | {'RAM (4-bit)' if a.deployment == 'local' else 'Price /1M in'} | License |")
    print("|---|---|---|---|---|")
    for i, r in enumerate(picks[: a.top], 1):
        col = f"~{r['need']:.1f} GB" if a.deployment == "local" else f"${r['price']:.2f}"
        print(f"| {i} | `{r.get('or_id', r['model_name'])}` | {r['rating']:.0f} | {col} | {r.get('license', '')} |")
    note = "open models with no size in their name" if a.deployment == "local" else "Arena models not found on OpenRouter"
    if skipped:
        print(f"\n_Not ranked: {skipped} {note}._")
    try:
        age = (date.today() - date.fromisoformat(str(published)[:10])).days
        if age > 7:
            print(f"\n_Arena snapshot is {age} days old; models released since then appear only in the list below._")
    except ValueError:
        pass
    if or_models:
        print_new(new, a)
    else:
        print("\n_New, unrated models not checked: pass --openrouter-file to see models released recently._")


if __name__ == "__main__":
    sys.exit(main())
