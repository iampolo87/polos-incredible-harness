---
name: crawler-policy-audit
description: "Audit robots.txt, WAF user-agent rules and crawler access on a Magento / Adobe Commerce store (no active incident). Triggers: CDN or managed-robots change, new store domain, SEO/social-preview complaint, \"are we blocking Googlebot / Bing / Meta?\". Needs New Relic Logs."
user-invocable: true
argument-hint: "[domains...] [timeframe (default: 7d)]"
---

# Crawler Policy Audit

Two directions, both matter. Bots hitting too hard show up as CPU and cache misses. Bots blocked by mistake show up as nothing — deindexing, dead social previews, lost ad quality — and nothing alerts. The second is worse.

**Not for incidents.** Throughput spike, sawtooth, origin up while cache-hit drops → `detect-scrapers`. This skill audits policy on a calm day; that one hunts an actor now.

## Parameters

- `domains` — every storefront host. Multi-store projects must list all of them; parity is a phase here.
- `timeframe` — lookback for the traffic checks (default: `7d`)
- `app_name` — NR APM application name; auto-detect from the project if absent.

---

## Phase 0 — Prerequisites & Architecture

### 0.1 Tools
- New Relic MCP with Logs access (`SELECT count(*) FROM Log SINCE 5 minutes ago` returns > 0). Without it, Phases 3 and 5 are skipped and the report says so.
- `curl`, `dig`. Read access to the outer CDN's rules (WAF custom rules, Lists, managed robots.txt setting).

### 0.2 Real client IP
When one CDN fronts another (Cloudflare → Fastly on most ACC projects), `client_ip` in the logs is an edge node. Check once:
```nrql
SELECT count(*), latest(client_ip), latest(request_x_forwarded_for)
FROM Log WHERE geo_country_code = '{main market}' SINCE 30 minutes ago FACET geo_city LIMIT 5
```
If the two differ, `REAL_IP` = leftmost `request_x_forwarded_for` value for every later query and `dig`. Reverse DNS on the wrong field resolves everything to Cloudflare (AS13335).

Consequences: only the outermost CDN sees `REAL_IP`, so that is where UA/IP rules live; and blocks at the outer CDN never reach Fastly or NR — a legitimate crawler blocked there shows as **zero requests**, not as 403s.

### 0.3 Field names
```nrql
SELECT keyset() FROM Log SINCE 30 minutes ago
```
Fastly/ACC: `request_user_agent`, `request_x_forwarded_for`, `client_ip`, `status`, `url`, `cache_status`, `is_cacheable`, `response_cache_control`, `tls_client_servername` (the multi-store split key).

---

## Phase 1 — robots.txt Structural Audit

A correct-looking robots.txt can be entirely inert. Structure before content. Run per domain:
```bash
for d in {domains}; do
  echo "== $d"
  curl -sS "https://$d/robots.txt" | tr -d '\r' > "/tmp/robots-$d.txt"
  echo "  UA-* groups : $(grep -ci '^user-agent: \*$' "/tmp/robots-$d.txt")   (must be 1)"
  echo "  CDN-managed : $(grep -ci 'cloudflare managed\|BEGIN .* Managed' "/tmp/robots-$d.txt")"
  grep -n '^[Uu]ser-agent:\|^[Ss]itemap:\|^Content-Signal' "/tmp/robots-$d.txt"
done
```

### 1.1 The duplicate-group trap
**More than one `User-agent: *` group is a bug.** RFC 9309 lets a parser take the first matching group and stop. A CDN-injected managed block (`# START Cloudflare Managed Content … User-agent: * …`) above your own `User-agent: *` group shadows your entire ruleset for every parser that does not merge duplicates. Google merges; plenty of others do not.

Fix: disable the CDN's managed injection, or merge everything into one group. Re-add whatever the managed block provided (`Content-Signal`, AI-crawler groups) to your own file.

### 1.2 Structural checks

| Check | Why |
|---|---|
| `Content-Signal` sits **inside** a `User-agent` group | Group-member directive. After a blank line at EOF it belongs to no group |
| No leading whitespace on directives | RFC 9309 permits it; older parsers may not. Free to fix |
| `Sitemap:` present and its host matches the robots.txt host | Cross-host sitemaps are ignored — a store serving another store's file loses its sitemap |
| Dead patterns | `Disallow: /.php$` matches nothing; `/*.php$` is the working form |
| Path prefixes match reality | On Cloud `pub/` **is** the docroot: `Disallow: /pub/` and `/pub/media/` match nothing; the live paths are `/media/`, `/static/` |

**Do not "fix" `/pub/static/` → `/static/` or `/pub/media/` → `/media/`.** Blocking `/static/` stops Google rendering CSS/JS; blocking `/media/` kills Open Graph preview images. Leave the inert lines or delete them.

### 1.3 Content that must be there (Magento)
```
Disallow: /customer/          # the login-referer URL space
Disallow: /*?*                # facet / layered-nav combinatorics (or the module's own filter params)
Disallow: /checkout/
Disallow: /catalogsearch/     # optional; high-cost endpoint
```
`Crawl-delay` is ignored by Google and Meta; only Bing and Yandex honour it. Never rely on it.

---

## Phase 2 — Multi-store Parity

Same policy on every domain, or the gap is where the crawl goes.
```bash
cd /tmp && for a in {domains}; do for b in {domains}; do
  [ "$a" \< "$b" ] && { echo "== $a vs $b"; diff "robots-$a.txt" "robots-$b.txt" | head -20; }
done; done
```
Legitimate differences: `Sitemap:` host only. Everything else should diff empty. A domain returning another domain's file verbatim (wrong sitemap host) means the CDN cache key or the Magento store-view resolution ignores `Host` — fix that, not the file.

Traffic split, to know which domain a crawler actually hits:
```nrql
SELECT count(*), percentage(count(*), WHERE cache_status IN ('MISS','PASS')) AS 'origin%'
FROM Log WHERE request_user_agent LIKE '%{ua}%' SINCE {timeframe} ago FACET tls_client_servername
```
Remediation is applied per zone; multi-store projects get hit evenly across domains.

---

## Phase 3 — Reverse Audit: Who Is Being Blocked?

```nrql
SELECT count(*) FROM Log SINCE {timeframe} ago
FACET CASES(
  WHERE request_user_agent LIKE '%Googlebot%'            AS 'Googlebot',
  WHERE request_user_agent LIKE '%Googlebot-Image%'      AS 'Googlebot-Image',
  WHERE request_user_agent LIKE '%AdsBot-Google%'        AS 'AdsBot-Google',
  WHERE request_user_agent LIKE '%bingbot%'              AS 'bingbot',
  WHERE request_user_agent LIKE '%facebookexternalhit%'  AS 'facebookexternalhit',
  WHERE request_user_agent LIKE '%meta-externalads%'     AS 'meta-externalads',
  WHERE request_user_agent LIKE '%Applebot%'             AS 'Applebot'
), status LIMIT 40
```
**Zero requests, or requests with no `200`s, means blocked** — at the outer CDN (invisible here, 0.2) or by a rule at Fastly (visible as 403). Find which rule in Phase 4. Exception keyed on one predicate: zero requests from a sub-crawler (`Googlebot-Image`, `AdsBot-Google`) while its sibling passes → it may never have been invited (no image sitemap, no Ads campaign); confirm in Search Console / Ads before blaming a rule.

Verify identity before trusting a UA: `dig +short -x {REAL_IP}` — Googlebot `crawl-*.googlebot.com`, bingbot `msnbot-*.search.msn.com`, Applebot `*.applebot.apple.com`, Meta has no PTR (verify ASN 32934).

### Crawler reference — block, allow, or think

| User agent | Operator | Purpose | Safe to block? |
|---|---|---|---|
| `Googlebot` | Google | Search index | **No** — deindexing |
| `Googlebot-Image` | Google | Image search | Only if image search is worthless to you |
| `AdsBot-Google` | Google | Ads landing-page quality | **No** — degrades Ads quality score |
| `Google-Extended` | Google | AI training (Gemini) | Yes — no search impact |
| `GoogleOther` | Google | Misc / research | Yes |
| `bingbot` | Microsoft | Search index | **No** — also kills Copilot **and DuckDuckGo** (DDG uses Bing's index) |
| `facebookexternalhit` | Meta | **Link previews** — FB, Instagram, WhatsApp, Messenger | **No** — shared product links lose image, title, price |
| `meta-externalads` | Meta | Ads / catalog fetch | **No** if you run Meta Shopping |
| `meta-externalagent` | Meta | AI training | Yes |
| `meta-webindexer` | Meta | Search indexing | Case by case — heavy, and known to ignore robots.txt |
| `Applebot` | Apple | Siri / Spotlight | Usually no |
| `Applebot-Extended` | Apple | AI training | Yes |
| `Amazonbot`, `Bytespider`, `CCBot`, `ClaudeBot`, `GPTBot`, `PerplexityBot` | various | AI training / retrieval | Yes, by policy |
| `AhrefsBot`, `SemrushBot`, `MJ12bot`, `DotBot`, `BLEXBot`, `SerpstatBot`, `DataForSeoBot` | SEO tools | Competitor analysis | Yes — no traffic value to you |
| `PetalBot` | Huawei | Petal search | Yes unless you sell in Huawei markets |

**The Meta family is the most commonly misconfigured**: four bots, four purposes. Treat them individually, never with a blanket `meta` substring.

Hand-off: an **unverified** actor dominating this FACET with a flat 24/7 line is an incident, not policy → `detect-scrapers`.

---

## Phase 4 — WAF User-Agent Rules

Pull every crawler-related rule at the outer CDN and check each against these:

| Pattern | Also matches |
|---|---|
| `bot` | almost everything, including Googlebot, bingbot, Applebot |
| `spider` | any UA containing the word, including legitimate ones |
| `crawl` | `Googlebot` PTR hosts aside, several legitimate crawlers |
| `meta` | all four Meta bots at once |
| `discord`, `telegrambot`, `twitterbot` | link-preview fetchers — kills previews on those platforms |
| `claude`, `openai` | fine to block, but be deliberate |

Mechanics that silently defeat intent:
- **Rule order** — custom rules run top-down; the first terminating action wins. A "Verified bots allow" placed *below* a substring challenge/block never runs. Put allows and skips first.
- **`managed_challenge`** — verified bots pass it automatically (so it is not a block for them), non-browser crawlers cannot solve it (so it is a hard 403 for everyone else). Never the right action for machine traffic: use **Block**, scoped by UA + path, and exclude verified bots explicitly: `… and not cf.client.bot`.
- **`skip` with `ruleset: current`** voids every rule below it. Country-wide skips (`ip.src.country in {"AR"}`) bypass the whole WAF for any VPS in that country.
- **Broken boolean** `ip.src eq A and ip.src eq B` — always false. Grep for `and ip.src eq`.
- **Plan limits** — Free/Pro: no regex in custom rules; custom-rule quota per zone (Free 5 / Pro 20 / Business 100). Consolidate IP literals into one account-level List and one `ip.src in $list` rule.

---

## Phase 5 — Magento URL Space

Robots and WAF rules treat symptoms. Find what created an infinite crawlable surface:
```nrql
SELECT count(*) FROM Log SINCE {timeframe} ago
FACET CASES(
  WHERE url LIKE '/customer/account/login/referer/%' AS 'login-referer',
  WHERE url LIKE '%?%'                               AS 'query-string / facets',
  WHERE url LIKE '/catalogsearch/%'                  AS 'search'
), cache_status LIMIT 15
```

**1. Login links carrying an encoded referer.** `Magento\Customer\Model\Url::getLoginUrlParams()` appends a base64 copy of the current URL to every "Sign In" link, so every faceted URL spawns its own unique, `no-store` login URL. Native fix, no code: `Stores → Configuration → Customers → Customer Configuration → Login Options → Redirect Customer to Account Dashboard after Logging in = Yes` (`customer/startup/redirect_dashboard`, default `0`). That setting is the **fix**, not a risk. Trade-off: customers land on the dashboard after login — test add-to-cart → login → checkout first.

**2. Layered-navigation facet combinatorics.** Multi-select filters produce factorial URL growth. With Amasty Improved Layered Navigation check these are *set*, not defaulted:
```
amasty_shopby_seo/robots/control_robots      # module manages robots meta
amasty_shopby_seo/robots/noindex_multiple    # NOINDEX when >1 filter applied
amasty_shopby_seo/robots/rel_nofollow        # rel="nofollow" on filter links
amasty_shopby_seo/canonical/*                # canonical strategy
```
An unset value means "default", not "off". Add the module's actual filter parameters to `Disallow`, not just `product_list_order`/`product_list_mode`.

---

## Phase 6 — Verify

- **You cannot test by spoofing a UA.** `curl -A "Googlebot"` from your laptop returns 403 — correctly, the CDN sees an impostor. Use the Phase 3 query again after 24 h, or the operator's tool: Google Search Console (robots.txt tester, URL Inspection), Bing Webmaster Tools, Facebook Sharing Debugger.
- **Check your own egress** before trusting any live test: `curl -sS https://api.ipify.org` and `curl -sS https://{domain}/cdn-cgi/trace | grep -E 'loc=|colo='`. Inside a bypass rule, every test returns 200 regardless of configuration.
- **A block at the outer CDN is invisible in NR.** See it fire in the CDN's security events; see traffic disappear in NR.
- Re-run Phase 1 on every domain after any robots.txt change — managed injection can come back with a CDN setting.

---

## Output Report

```markdown
# Crawler Policy Audit — {project} — {date}

**Domains:** {list} | **CDN chain:** {outer → inner} | **Real-IP field:** {…} | **Period:** {timeframe}

## robots.txt
| Domain | UA-* groups | CDN-managed block | Sitemap host OK | Findings |

## Parity
{diff summary per pair; domains serving another store's file}

## Blocked by mistake
| Crawler | Evidence (0 requests / no 200s) | Blocked by (rule) | Business impact | Action |

## WAF rules
| Rule | Pattern | Collateral | Order/action problem | Fix |

## URL space
{login-referer share, facet share, redirect_dashboard state, Amasty settings state}

## Changes proposed
{ordered; robots.txt edits, rule reorders, config paths}

## Verification plan
{Phase 3 re-run date, operator tools to check, egress used for tests}
```
