---
name: xdebug-web
description: Use when a Magento/PHP page served by local nginx + php-fpm misbehaves or is slow and reading code isn't enough — need the real function calls, arguments, return values and timing of one browser request (page load, checkout step, admin save, AJAX call). Triggers - "trace this request", "what runs when I click", "why is this page slow", "which observer/plugin fires", "trace the checkout".
---

# xdebug-web

Local FPM pools have Xdebug `trace` mode armed on trigger (see Setup). Send one request carrying `XDEBUG_TRIGGER`; Xdebug writes a full function trace to `/var/lib/xdebug/`; summarize with the bundled analyser. No code changes, no var_dump.

Needs a browser via chrome-devtools MCP, or curl. PhpStorm listening on 9003 pauses the traced request at breakpoints — ask the user to stop listening first.

## Steps

1. Trigger exactly one request. Query param must be unique — Magento FPC/Varnish serves cached pages without running PHP.
   - GET: `navigate_page` → `https://site.test/path?XDEBUG_TRIGGER=1&_xb=<epoch>`
   - POST/AJAX: `evaluate_script` → `document.cookie="XDEBUG_TRIGGER=1;path=/"`, perform the click/submit, then `document.cookie="XDEBUG_TRIGGER=;Max-Age=0;path=/"`. Every request while the cookie exists writes a trace.
   - curl: `curl -sk -o /dev/null -H 'Cookie: XDEBUG_TRIGGER=1' "https://site.test/path?_xb=$(date +%s)"`
2. Locate: `F=$(ls -t /var/lib/xdebug/trace.*.xt | head -1)` — confirm mtime is now, and `sed -n 4p "$F"` shows the expected project path.
3. Summarize (Derick Rethans' analyser from xdebug/contrib; ~4 s per 400 MB):
   ```bash
   php ~/.claude/skills/xdebug-web/tracefile-analyser.php "$F" time-own 25 | grep -vE '%\)|^\s*$|^-+$' | sed -E 's/ {2,}/  /g'
   ```
   Sort keys: `time-own` (hot spots), `time-inclusive` (call tree cost), `calls` (N+1 loops), `memory-own`, `memory-inclusive`. Columns: function, calls, time-inclusive, memory-inclusive, time-own, memory-own. Second arg = row count.
4. Drill into the raw trace when the summary isn't enough. `trace_format=1` is tab-separated: level, call id, 0=enter/1=exit, time, memory, function, user-defined, include file, file, line, argc, args…
   ```bash
   awk -F'\t' '$3==0 && $6 ~ /Magento\\Checkout\\Model/' "$F" | cut -f1,4,6,9,10 | head -40
   ```
   Args are on entry rows (`$12+`), return value on `R` rows. `grep -c` a function name for call counts.
5. Delete consumed traces: `rm /var/lib/xdebug/trace.*.xt`. A Magento page is 300–500 MB, ~2 M lines.

## Pitfalls

| Symptom | Cause / fix |
|---|---|
| No new file | Page came from FPC/Varnish, PHP never ran — change `_xb`. Or wrong pool: site's PHP version is in its nginx conf (`$FASTCGI_PASS`); `/opt/remi/phpXX/root/usr/bin/php -i \| grep xdebug.mode` must list `trace`. |
| File missing but request ran | `output_dir` still `/tmp` = FPM PrivateTmp, invisible. Re-run Setup. SELinux denial: `sudo ausearch -m AVC -ts recent`. |
| `.xt.gz` | `use_compression=0` not applied for that PHP version. Re-run Setup. |
| Analyser table empty | Trace truncated (request killed mid-way) — `tail -1 "$F"` must be `TRACE END`. |
| Unexpected extra traces | PhpStorm's `XDEBUG_SESSION` cookie also triggers trace mode. Remove the cookie when done. |

## Setup (once)

`sudo bash ~/.claude/skills/xdebug-web/setup.sh` — creates `/var/lib/xdebug`, SELinux label, installs `16-xdebug-trace.ini` into each PHP's `php.d`, reloads FPM units.
