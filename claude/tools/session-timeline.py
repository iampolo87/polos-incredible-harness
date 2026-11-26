#!/usr/bin/env python3
"""Wall-clock timeline of one Claude Code session: prompts, skills, agent spawns.
Usage: session-timeline.py <session-id-or-jsonl-path>  (searches ~/.claude/projects for the id)
Pair with transcript-report.py --session <id> for tokens/$.
"""
import json, sys, glob, os, datetime as dt
a = sys.argv[1]
f = a if a.endswith('.jsonl') else next(iter(glob.glob(os.path.expanduser(f'~/.claude/projects/*/{a}.jsonl'))), None)
if not f: sys.exit(f'no transcript for {a}')
rows, first, last, seen, reqs = [], None, None, set(), 0
for l in open(f):
    try: r = json.loads(l)
    except: continue
    ts, m = r.get('timestamp'), r.get('message') or {}
    if not ts: continue
    first, last = first or ts, ts
    if r.get('type') == 'user':
        c = m.get('content')
        t = c if isinstance(c, str) else next((x['text'] for x in c or [] if x.get('type') == 'text'), None)
        if t and not t.startswith('<'): rows.append((ts, 'PROMPT', t[:90].replace('\n', ' ')))
    if r.get('type') == 'assistant':
        if r.get('requestId') and r['requestId'] not in seen: seen.add(r['requestId']); reqs += 1
        for c in m.get('content', []):
            if c.get('type') != 'tool_use': continue
            n, i = c['name'], c['input']
            if n == 'Agent': rows.append((ts, 'AGENT', f"{i.get('subagent_type')} | {i.get('description')}"))
            elif n == 'Skill': rows.append((ts, 'SKILL', f"{i.get('skill')} {str(i.get('args',''))[:60]}"))
p = lambda s: dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
prev = p(first)
for ts, k, t in rows:
    cur = p(ts); print(f"{ts[11:19]}  +{int((cur-prev).total_seconds())//60:>3}m  {k:6} {t}"); prev = cur
print(f"\nwall {(p(last)-p(first)).total_seconds()/60:.0f} min, {reqs} main-thread requests, {sum(1 for r in rows if r[1]=='AGENT')} spawns")
