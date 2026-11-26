#!/usr/bin/env python3
"""Read-only usage report over Claude Code transcripts.

Reports what the provider recorded and what activity accompanied it. Writes
nothing, calls no model, stores no source text — every number comes from
~/.claude/projects/**/*.jsonl, which already exists.

Deliberate limits, so the output cannot be read as more than it is:

  * Measured vs estimated are separated. Sections 1, 2, 4 and 5 are measured.
    Section 3 is an estimate and is SKIPPED entirely unless rates are filled in
    at transcript-rates.json — the report never invents a price, and an
    estimate is not a bill and not a subscription-quota figure.
  * Usage is deduplicated on (sessionId, requestId): one API response emits
    several transcript records that each repeat the same usage object, so a
    naive sum roughly doubles every total.
  * "Introduced" and "consumed" are different quantities. Section 5 measures
    bytes a tool put INTO a conversation once. Section 2 measures tokens the
    provider billed across every subsequent request. A large read can recur in
    many later requests, so the two are not comparable as a ratio.

Usage:
    transcript-report.py [--days N] [--project SUBSTR] [--rates PATH] [--json]
"""
import argparse
import json
import pathlib
import statistics
import sys
import time
from collections import defaultdict

USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens",
              "cache_read_input_tokens", "output_tokens")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--days", type=int, default=30, help="window in days (default 30)")
    p.add_argument("--since", default="", help="frozen window start, ISO8601 (overrides --days)")
    p.add_argument("--until", default="", help="frozen window end, ISO8601 (default: now)")
    p.add_argument("--project", default="", help="only projects whose dir name contains this")
    p.add_argument("--root", default=str(pathlib.Path.home() / ".claude" / "projects"))
    p.add_argument("--rates", default=str(pathlib.Path(__file__).with_name("transcript-rates.json")))
    p.add_argument("--session", default="", help="restrict to one sessionId (prefix ok)")
    p.add_argument("--manifest", default="", help="write an input manifest (file hashes + versions) here")
    p.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return p.parse_args()


def result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def zero():
    return dict.fromkeys(USAGE_KEYS + ("write_5m", "write_1h"), 0)


def add(dst, u):
    for k in USAGE_KEYS:
        dst[k] += u.get(k, 0)
    cc = u.get("cache_creation") or {}
    dst["write_5m"] += cc.get("ephemeral_5m_input_tokens", 0)
    dst["write_1h"] += cc.get("ephemeral_1h_input_tokens", 0)


def iso(v):
    from datetime import datetime
    return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()


def collect(args):
    # A frozen window is what makes two runs comparable: --days is relative, so
    # re-running it later silently analyses a different window (this bit me once
    # already — a $8.67 "discrepancy" that was just the window moving).
    until = iso(args.until) if args.until else time.time()
    cutoff = iso(args.since) if args.since else until - args.days * 86400
    args._window = (cutoff, until)
    root = pathlib.Path(args.root)

    # (sessionId, requestId) -> (timestamp, usage, model, sidechain). Last wins:
    # if a duplicated record carries evolving counters, the final one is
    # authoritative rather than whichever happened to be read first.
    requests = {}
    dup_records = dup_divergent = 0
    missing_id = 0
    files = sessions = 0
    first_ts = last_ts = None
    manifest = []

    # section 4: first usage-bearing request per session
    session_meta = {}          # sid -> {repo, entrypoint, sidechain}
    session_first = {}         # sid -> (timestamp, usage dict)

    # section 5
    tool_bytes = defaultdict(lambda: [0, 0, 0])   # (tool, side) -> calls, bytes, over_50_lines
    reads = defaultdict(lambda: defaultdict(int))  # sid -> (path, offset, limit) -> n

    for f in root.rglob("*.jsonl"):
        try:
            if f.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        if args.project and args.project not in f.parent.name:
            continue
        files += 1
        manifest.append(f)
        repo = f.parent.name
        pending = {}   # tool_use_id -> (tool_name, sidechain)

        for line in f.open(errors="replace"):
            try:
                rec = json.loads(line)
            except ValueError:
                continue

            side = bool(rec.get("isSidechain"))
            sid = rec.get("sessionId") or rec.get("session_id")
            if args.session and not str(sid or "").startswith(args.session):
                continue
            ts = rec.get("timestamp")
            if ts:
                try:
                    t = iso(ts)
                except ValueError:
                    t = None
                if t is not None and not (cutoff <= t <= until):
                    continue

            msg = rec.get("message") or {}
            usage = msg.get("usage")
            if usage:
                rid = rec.get("requestId")
                if rid is None:
                    missing_id += 1
                    key = (sid, "uuid:" + str(rec.get("uuid")))
                else:
                    key = (sid, rid)
                if key in requests:
                    dup_records += 1
                    prev = requests[key][1]
                    if any(prev.get(k) != usage.get(k) for k in USAGE_KEYS):
                        dup_divergent += 1
                requests[key] = (ts, usage, msg.get("model"), side)

                if sid and sid not in session_meta:
                    session_meta[sid] = {"repo": repo,
                                         "entrypoint": rec.get("entrypoint") or "unknown",
                                         "sidechain": side}
                    sessions += 1
                if sid and ts and (sid not in session_first or ts < session_first[sid][0]):
                    session_first[sid] = (ts, usage)

                if ts:
                    first_ts = min(first_ts or ts, ts)
                    last_ts = max(last_ts or ts, ts)

            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    pending[block.get("id")] = (block.get("name", "?"), side)
                    if block.get("name") == "Read" and sid:
                        inp = block.get("input") or {}
                        # a malformed input can carry an unhashable value, so
                        # normalise the key rather than crash the whole report
                        reads[sid][(str(inp.get("file_path")), str(inp.get("offset")),
                                    str(inp.get("limit")))] += 1
                elif block.get("type") == "tool_result":
                    name_side = pending.get(block.get("tool_use_id"))
                    if not name_side:
                        continue
                    text = result_text(block.get("content"))
                    e = tool_bytes[name_side]
                    e[0] += 1
                    e[1] += len(text)
                    if text.count("\n") + 1 > 50:
                        e[2] += 1

    return dict(requests=requests, dup_records=dup_records, dup_divergent=dup_divergent,
                missing_id=missing_id, files=files, sessions=sessions,
                first_ts=first_ts, last_ts=last_ts, session_meta=session_meta,
                session_first=session_first, tool_bytes=tool_bytes, reads=reads,
                manifest=manifest)


def write_manifest(path, d, args):
    """Timestamps freeze the window; only hashes freeze the inputs. Transcript
    files are appended to continuously, so two runs over one window can still
    read different bytes."""
    import hashlib
    out = {"window": {"since": args._window[0], "until": args._window[1]},
           "report_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()[:16],
           "files": {}}
    try:
        out["rates_sha256"] = hashlib.sha256(
            pathlib.Path(args.rates).read_bytes()).hexdigest()[:16]
    except OSError:
        out["rates_sha256"] = None
    for f in d["manifest"]:
        try:
            b = f.read_bytes()
        except OSError:
            continue
        out["files"][str(f)] = {"sha256": hashlib.sha256(b).hexdigest()[:16], "bytes": len(b)}
    pathlib.Path(path).write_text(json.dumps(out, indent=2) + "\n")
    return len(out["files"])


def fmt(n):
    return f"{n:,}"


def report(d, args, rates):
    R = []
    P = R.append

    # ---- 1. coverage and data quality (measured) -------------------------
    P("=" * 78)
    P(f"TRANSCRIPT USAGE REPORT — last {args.days} days"
      + (f", projects matching {args.project!r}" if args.project else ""))
    P("=" * 78)
    P("\n1. COVERAGE AND DATA QUALITY  [measured]")
    P(f"   transcripts read      {fmt(d['files'])}")
    P(f"   sessions              {fmt(d['sessions'])}")
    P(f"   unique requests       {fmt(len(d['requests']))}")
    P(f"   records in window     {d['first_ts'] or '?'}  ..  {d['last_ts'] or '?'}")
    import datetime as _dt
    w0, w1 = (_dt.datetime.fromtimestamp(x, _dt.timezone.utc).isoformat().replace("+00:00", "Z")
              for x in args._window)
    P(f"   WINDOW REQUESTED      {w0}  ..  {w1}")
    P(f"   reproduce exactly     --since {w0} --until {w1}")
    total_records = len(d["requests"]) + d["dup_records"]
    infl = total_records / len(d["requests"]) if d["requests"] else 0
    P(f"   duplicate records     {fmt(d['dup_records'])} collapsed on (sessionId, requestId)"
      f"  — naive summing would inflate {infl:.2f}x")
    P(f"     of those, records whose usage counters DIFFERED from the first seen: "
      f"{fmt(d['dup_divergent'])} (last record wins)")
    P(f"   records missing requestId: {fmt(d['missing_id'])} "
      "(kept, keyed by uuid — counted, never silently dropped)")

    # ---- 2. measured usage ----------------------------------------------
    by_model = defaultdict(zero)
    by_side = defaultdict(zero)
    for _ts, u, model, side in d["requests"].values():
        add(by_model[(model or "unknown", side)], u)
        add(by_side["delegate" if side else "main"], u)

    P("\n2. MEASURED USAGE  [measured — provider-reported, deduplicated]")
    hdr = (f"   {'model':26} {'role':9} {'fresh in':>12} {'cache write':>13} "
           f"{'cache read':>15} {'output':>12}")
    P(hdr)
    P("   " + "-" * (len(hdr) - 3))
    # synthetic/compaction records carry a usage object of all zeros; they are
    # counted in section 1 but say nothing here
    by_model = {k: u for k, u in by_model.items() if any(u[j] for j in USAGE_KEYS)}
    for (model, side), u in sorted(by_model.items(), key=lambda kv: -kv[1]["cache_read_input_tokens"]):
        P(f"   {model[:26]:26} {'delegate' if side else 'main':9} "
          f"{u['input_tokens']:12,d} {u['cache_creation_input_tokens']:13,d} "
          f"{u['cache_read_input_tokens']:15,d} {u['output_tokens']:12,d}")
    P("   " + "-" * (len(hdr) - 3))
    for role in ("main", "delegate"):
        u = by_side[role]
        P(f"   {'TOTAL':26} {role:9} {u['input_tokens']:12,d} "
          f"{u['cache_creation_input_tokens']:13,d} {u['cache_read_input_tokens']:15,d} "
          f"{u['output_tokens']:12,d}")
    P("\n   cache writes by TTL (a 5m write is re-paid on every miss; a 1h write is not):")
    for role in ("main", "delegate"):
        u = by_side[role]
        tot = u["write_5m"] + u["write_1h"]
        pct = 100 * u["write_5m"] / tot if tot else 0
        P(f"     {role:9} 5m {u['write_5m']:14,d} ({pct:5.1f}%)   1h {u['write_1h']:14,d}")
    dele = by_side["delegate"]["cache_creation_input_tokens"]
    allc = dele + by_side["main"]["cache_creation_input_tokens"]
    if allc:
        P(f"   delegate share of cache creation: {100 * dele / allc:.1f}%")
        P("     NOTE: this is all content newly cached during delegate execution — task "
          "briefs,\n     tool results and messages alike. It is NOT a measure of "
          "bootstrapping overhead;\n     isolating that needs per-delegate first-request "
          "figures, not this aggregate.")

    # ---- 3. estimated cost (only if rates configured) --------------------
    P("\n3. NOTIONAL API VALUE AT CACHED LIST RATES  [ESTIMATE — not a bill,\n   not subscription spending, not quota saved]")
    models_cfg = (rates or {}).get("models", {})
    mult = (rates or {}).get("cache_multipliers", {})
    priced, unpriced = [], set()
    for (model, side), u in by_model.items():
        cfg = models_cfg.get(model) or {}
        cin, cout = cfg.get("usd_per_mtok_input"), cfg.get("usd_per_mtok_output")
        if cin is None or cout is None:
            unpriced.add(model)
            continue
        # a model may price cache reads directly instead of as a multiple of input
        cread = cfg.get("usd_per_mtok_cache_read")
        if cread is None:
            cread = cin * mult.get("read", 0.1)
        usd = (u["input_tokens"] * cin
               + u["write_5m"] * cin * mult.get("write_5m", 1.25)
               + u["write_1h"] * cin * mult.get("write_1h", 2.0)
               + u["cache_read_input_tokens"] * cread
               + u["output_tokens"] * cout) / 1_000_000
        priced.append((model, side, usd, cfg.get("effective_from")))
    if not priced:
        P("   SKIPPED — no rates configured.")
        P(f"   Fill in {args.rates} (models observed: "
          + ", ".join(sorted(m for m in unpriced if m)) + ").")
        P("   Rates are deliberately null by default: a guessed price would read like a "
          "measurement.")
    else:
        for model, side, usd, eff in sorted(priced, key=lambda r: -r[2]):
            P(f"   {model[:26]:26} {'delegate' if side else 'main':9} ${usd:10,.2f}"
              f"   (rate effective {eff or 'undated'})")
        P(f"   {'TOTAL':26} {'':9} ${sum(r[2] for r in priced):10,.2f}")
        if unpriced:
            P("   UNPRICED, excluded from the total: " + ", ".join(sorted(m for m in unpriced if m)))
        P("   Assumes list price for the whole window; a rate change inside the window is "
          "not modelled.")

    # ---- 4. first-request input, by repo and session type ----------------
    P("\n4. FIRST-REQUEST INPUT PER SESSION  [measured]")
    P("   A session's first usage-bearing request. It includes whatever the session opened")
    P("   with — the first task, resumed history, launch mode — so it is a BASELINE to")
    P("   compare across repos, not a measurement of the fixed preamble. Settling the cost")
    P("   of an instruction file needs a controlled before/after on the same repo.")
    groups = defaultdict(list)
    for sid, (_ts, u) in d["session_first"].items():
        m = d["session_meta"].get(sid, {})
        groups[(m.get("repo", "?"), m.get("entrypoint", "unknown"),
                "delegate" if m.get("sidechain") else "main")].append(u)
    hdr4 = (f"   {'repo':38} {'type':12} {'n':>4} {'med fresh':>10} "
            f"{'med write':>11} {'med read':>11}")
    P(hdr4)
    P("   " + "-" * (len(hdr4) - 3))
    for (repo, entry, role), us in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:15]:
        med = lambda k: int(statistics.median([x.get(k, 0) for x in us]))
        P(f"   {repo[-38:]:38} {(entry + "/" + role)[:12]:12} {len(us):4d} "
          f"{med('input_tokens'):10,d} {med('cache_creation_input_tokens'):11,d} "
          f"{med('cache_read_input_tokens'):11,d}")

    # ---- 5. tool-result volume and repeated reads ------------------------
    P("\n5. TOOL-RESULT VOLUME AND REPEATED READS  [measured — content INTRODUCED]")
    P("   Bytes a tool put into a conversation once. NOT comparable to section 2: content")
    P("   introduced once is re-sent on every later request, for as long as it stays in")
    P("   context, so these units do not divide into each other.")
    hdr5 = f"   {'tool':30} {'role':9} {'calls':>7} {'~tokens in':>12} {'>50 lines':>10}"
    P(hdr5)
    P("   " + "-" * (len(hdr5) - 3))
    for (tool, side), (calls, nbytes, over) in sorted(
            d["tool_bytes"].items(), key=lambda kv: -kv[1][1])[:12]:
        P(f"   {tool[:30]:30} {'delegate' if side else 'main':9} {calls:7,d} "
          f"{nbytes // 4:12,d} {over:10,d}")

    rep_sessions = rep_total = 0
    worst = []
    for sid, m in d["reads"].items():
        extra = sum(n - 1 for n in m.values() if n > 1)
        if extra:
            rep_sessions += 1
            rep_total += extra
            for key, n in m.items():
                if n > 1:
                    worst.append((n, key[0], sid))
    P(f"\n   repeated Read of an identical (path, offset, limit): {fmt(rep_total)} redundant"
      f" fetches across {fmt(rep_sessions)} sessions")
    worst.sort(reverse=True)
    for n, path, _sid in worst[:8]:
        P(f"     {n:3d}x  {str(path)[-70:]}")

    P("\nLIMITATIONS")
    P("  * Transcripts do not contain the system prompt, CLAUDE.md or tool schemas, so no")
    P("    section attributes usage to them. Section 4 is a baseline, not that attribution.")
    P("  * Sections 2 and 5 measure different quantities (consumed vs introduced).")
    P("  * Section 3, when enabled, is an estimate from configured list prices only.")
    return "\n".join(R)


def main():
    args = parse_args()
    try:
        rates = json.loads(pathlib.Path(args.rates).read_text())
    except (OSError, ValueError):
        rates = None
    d = collect(args)
    if not d["requests"]:
        print("no usage records in window", file=sys.stderr)
        return 1
    if args.manifest:
        n = write_manifest(args.manifest, d, args)
        print(f"manifest: {n} input files hashed -> {args.manifest}", file=sys.stderr)
    if args.json:
        by_model = defaultdict(zero)
        for _ts, u, model, side in d["requests"].values():
            add(by_model[(model or "unknown", "delegate" if side else "main")], u)
        print(json.dumps({
            "window_days": args.days,
            "files": d["files"], "sessions": d["sessions"],
            "unique_requests": len(d["requests"]),
            "duplicate_records": d["dup_records"],
            "duplicates_with_divergent_usage": d["dup_divergent"],
            "records_missing_request_id": d["missing_id"],
            "usage": {f"{m}|{r}": u for (m, r), u in by_model.items()},
        }, indent=2))
    else:
        print(report(d, args, rates))
    return 0


if __name__ == "__main__":
    sys.exit(main())
