#!/usr/bin/env python3
"""
Generate UPGRADE-RUNBOOK.md — an actionable, ordered guide a developer (or a
Claude Code agent) follows to DO the upgrade the skill just estimated.

It turns the measured analysis into a phased checklist: the exact custom files to
migrate (signature-risk extends first), which Rector auto-fixes to apply, which
third-party vendors to verify, and the environment blockers discovered. Pre-existing
tech debt (UCT non-API/@deprecated) is listed as an OPTIONAL appendix, not upgrade work.

Reads from --report-dir: pert-estimation.json, signals.json, extension-impact-deep.json.
Usage: render-runbook.py --report-dir DIR --out UPGRADE-RUNBOOK.md
"""

import argparse
import json
from pathlib import Path

CAP = 60  # max checklist items per group before "+N más"


def load(p: Path, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def items(findings, rel, owner="custom", sigrisk=None):
    out = []
    for f in findings:
        if f.get("owner") != owner:
            continue
        r = f.get("relationship")
        if rel == "extends-impl":
            if r not in ("extends", "implements"):
                continue
        elif r != rel:
            continue
        if sigrisk is not None and bool(f.get("signature_risk")) != sigrisk:
            continue
        out.append(f)
    return out


def checklist(group, note=""):
    lines = []
    for f in group[:CAP]:
        tgt = f.get("magento_target", "?")
        det = f.get("detail")
        suffix = f" — {det}" if det else ""
        lines.append(f"- [ ] `{f.get('custom_file','?')}` → `{tgt}`{suffix}")
    if len(group) > CAP:
        lines.append(f"- … +{len(group) - CAP} más (ver `estimate.html`)")
    if not lines:
        lines.append("- _(ninguno)_")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate the upgrade runbook (Markdown).")
    ap.add_argument("--report-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    rd = args.report_dir

    est = load(rd / "pert-estimation.json", {})
    signals = load(rd / "signals.json", {})
    impact = load(rd / "extension-impact-deep.json", {})
    meta = est.get("meta", signals.get("meta", {}))
    findings = impact.get("findings", [])

    cur, tgt = meta.get("current_version", "?"), meta.get("target_version", "?")
    cphp, tphp = meta.get("current_php", "?"), meta.get("target_php", "?")
    edition = meta.get("edition", "?")
    rec_php = est.get("php_ladder", {}).get("recommended_php", tphp)
    tgt_nodot = str(tphp).replace(".", "")

    results = est.get("results", {})
    man = sum(v.get("E_total", 0) for k, v in results.items() if "automatización" not in k)
    aut = sum(v.get("E_total", 0) for k, v in results.items() if "automatización" in k)
    ci90 = sum(v.get("ci", {}).get("90%", 0) for k, v in results.items() if "automatización" not in k)

    rector = signals.get("rector", {}).get("by_ruleset", {})
    php_changes = rector.get("PHP_LEVEL", 0)
    modern = rector.get("CODE_QUALITY", 0) + rector.get("DEAD_CODE", 0) + rector.get("TYPE_DECLARATION", 0)
    tp_vendors = impact.get("summary", {}).get("third_party", {}).get("vendors", [])
    uct_pre = signals.get("uct", {}).get("preexisting", {}).get("findings", 0)
    uct_delta = signals.get("uct", {}).get("upgrade_delta", {}).get("findings", 0)

    prefs = items(findings, "preference")
    sig_ext = items(findings, "extends-impl", sigrisk=True)
    safe_ext = items(findings, "extends-impl", sigrisk=False)
    plugins = items(findings, "plugin")
    vtypes = items(findings, "virtualType")
    templates = items(findings, "template") + items(findings, "layout")

    md = f"""# Runbook de upgrade — Magento 2 `{cur}` → `{tgt}`

> Generado por el skill **m2-upgrade-estimation** a partir de análisis medido (diff de
> core, impacto en código custom, Rector, Adobe UCT). Seguí las fases en orden. Cada
> `- [ ]` es una tarea concreta. PHP objetivo recomendado: **{rec_php}** (PHP {cphp} → {rec_php}).
>
> **Estimación:** ~{aut:.0f}h con automatización · ~{man:.0f}h manual · CI 90% ≈ {ci90:.0f}h.
> Edición: {edition}. Ejecutá TODO en un worktree aislado, nunca sobre la rama de trabajo.

## Cómo usar este documento
- Hacé cada fase en su propio commit; corré `bin/magento setup:di:compile` entre fases.
- Las tareas marcadas **PRIORIDAD** son las de mayor riesgo de romper en runtime.
- Si sos un agente Claude Code: tratá cada `- [ ]` como una unidad de trabajo verificable.

---

## Fase 1 — Preparación

```bash
git worktree add ../$(basename "$PWD")-{tgt} -b upgrade-{tgt}
cd ../$(basename "$PWD")-{tgt}
# bump del metapackage y la edición a {tgt} en composer.json, luego:
composer update -W --no-scripts --no-plugins --ignore-platform-reqs
```

**Blockers conocidos (de este relevamiento):**
- [ ] Bumpear `magento/product-{'enterprise' if edition.startswith('ent') else 'community'}-edition` y `magento/magento-cloud-metapackage` al constraint de `{tgt}` (el pin del metapackage bloquea la resolución).
- [ ] Usar `--no-plugins` en composer dentro del worktree (el git-hook `php-composter` falla porque `.git` es un archivo, no un dir).
- [ ] Si hay error de autoload por `app/etc/*`, copiar los archivos de registro gitignoreados (`NonComposerComponentRegistration.php`, `registration_globlist.php`, `vendor_path.php`) desde el checkout principal.
- [ ] `--ignore-platform-reqs` si el PHP local es menor al objetivo.

## Fase 2 — Automatización con Rector (aplica solo, después revisás)

Rector auto-aplica **{php_changes}** cambios de versión PHP y **{modern}** de calidad/dead-code/tipos sobre el código a migrar.

```bash
RECTOR_PHP_VERSION={tgt_nodot} vendor/bin/rector process app/code --config=rector.php   # revisá el diff
RECTOR_PHP_VERSION={tgt_nodot} vendor/bin/rector process app/code --config=rector.php --no-dry-run
```
- [ ] Correr Rector en dry-run, revisar el diff, aplicar, commitear.
- [ ] `setup:di:compile` y smoke rápido tras aplicar.

## Fase 3 — Migración de código custom (el grueso del trabajo manual)

### 3a. PRIORIDAD — `extends`/`implements` con firma del padre cambiada ({len(sig_ext)})
La clase padre de Magento cambió una firma de método/constructor que tu override usa. Verificá cada uno:

{checklist(sig_ext)}

### 3b. Preferences ({len(prefs)}) — reemplazan una clase de core entera
{checklist(prefs)}

### 3c. Plugins ({len(plugins)}) — verificar firma del método interceptado
{checklist(plugins)}

### 3d. virtualType ({len(vtypes)}) + overrides de template/layout ({len(templates)})
{checklist(vtypes + templates)}

### 3e. `extends` sin cambio de firma ({len(safe_ext)})
Bajo riesgo (la clase padre cambió pero no la firma que usás). Recompilar + verificar; normalmente no requieren cambios.

## Fase 4 — Extensiones de terceros (verificar release compatible)

NO se migran a mano: el proveedor publica una release compatible con `{tgt}`. Para cada uno, verificá y bumpeá la versión:

{chr(10).join(f"- [ ] **{v}**: confirmar release compatible con {tgt} y `composer require {v}/...:^<nueva>`" for v in tp_vendors) or "- _(ninguno detectado)_"}

## Fase 5 — Base de datos, compilación y deploy
- [ ] `setup:upgrade` (revisar `db_schema_whitelist.json` / patches de datos).
- [ ] `setup:di:compile` + `setup:static-content:deploy` limpios.
- [ ] Smoke completo + regresión por área afectada.
- [ ] Dry-run de deploy (Cloud si aplica) antes de prod.

---

## Apéndice — Deuda técnica pre-existente (UCT, NO es trabajo del upgrade)

UCT reportó **{uct_pre}** hallazgos no-API / `@deprecated` / estilo que **ya existen en `{cur}`** — no los introduce el upgrade ({uct_delta} sí son introducidos: API removida/cambiada). Son mejora opcional; abordalos por separado. Detalle completo en `estimate.html` (sección "API deprecada / removida").
"""
    args.out.write_text(md)
    print(f"[runbook] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
