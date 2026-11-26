"""Vendored read-only minimal YAML reader (stdlib-only).

Parses ONLY the constrained subset that Magento Cloud config files use:
  - 2/4-space indent block maps (indent width is inferred, not hardcoded)
  - block lists (`- item`)
  - inline empty collections (`{}`, `[]`)
  - quoted keys/scalars (single + double), bare scalars
  - scalar coercion: true/false -> bool, null/~ -> None, ints, else str
  - `#` comments (full-line and inline-outside-quotes) and `---` doc markers

It NEVER writes YAML, so round-trip fidelity is not required — a faithful
read of maps/lists/scalars is enough to diff config against a catalog.
Unsupported constructs (anchors, flow maps with content, multiline scalars)
are not present in the target files; on a line it cannot parse it raises
ValueError with the offending line rather than silently mis-reading.

Named `_miniyaml` (not `_yaml`) to avoid colliding with PyYAML's C shim.
"""
from __future__ import annotations

from typing import Any


def load(text: str) -> Any:
    """Parse a YAML document (the supported subset) into Python data."""
    tokens = _tokenize(text)
    if not tokens:
        return None
    value, idx = _parse_block(tokens, 0, tokens[0][0])
    if idx != len(tokens):
        raise ValueError(
            f"_miniyaml: unparsed trailing content at line {tokens[idx][2]}: "
            f"{tokens[idx][1]!r}"
        )
    return value


# ── tokenize ───────────────────────────────────────────────────────────────

def _tokenize(text: str):
    """Return [(indent, content, lineno)] skipping blanks/comments/`---`."""
    out = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = _strip_inline_comment(raw)
        stripped = line.strip()
        if not stripped or stripped == "---":
            continue
        indent = len(line) - len(line.lstrip(" "))
        out.append((indent, stripped, lineno))
    return out


def _strip_inline_comment(raw: str) -> str:
    """Cut a `#` comment that sits outside quotes and after whitespace."""
    in_s = in_d = False
    for i, ch in enumerate(raw):
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif ch == "#" and not in_s and not in_d and (i == 0 or raw[i - 1] in " \t"):
            return raw[:i]
    return raw


# ── recursive parse ──────────────────────────────────────────────────────────

def _parse_block(tokens, i, indent):
    """Dispatch a block at `indent` to sequence or mapping parser."""
    content = tokens[i][1]
    if content == "-" or content.startswith("- "):
        return _parse_seq(tokens, i, indent)
    return _parse_map(tokens, i, indent)


def _parse_map(tokens, i, indent):
    result = {}
    while i < len(tokens):
        cur_indent, content, lineno = tokens[i]
        if cur_indent < indent:
            break
        if cur_indent > indent:
            raise ValueError(
                f"_miniyaml: unexpected indent at line {lineno}: {content!r}"
            )
        key, val = _split_kv(content, lineno)
        if val == "":
            # nested block or null
            if i + 1 < len(tokens) and tokens[i + 1][0] > indent:
                child, i = _parse_block(tokens, i + 1, tokens[i + 1][0])
                result[key] = child
            else:
                result[key] = None
                i += 1
        else:
            result[key] = _scalar(val)
            i += 1
    return result, i


def _parse_seq(tokens, i, indent):
    result = []
    while i < len(tokens):
        cur_indent, content, lineno = tokens[i]
        if cur_indent != indent or not (content == "-" or content.startswith("- ")):
            break
        item = content[1:].strip()
        if item == "":
            # nested block under the dash
            if i + 1 < len(tokens) and tokens[i + 1][0] > indent:
                child, i = _parse_block(tokens, i + 1, tokens[i + 1][0])
                result.append(child)
            else:
                result.append(None)
                i += 1
        else:
            result.append(_scalar(item))
            i += 1
    return result, i


def _split_kv(content, lineno):
    """Split `key: value` on the first top-level colon-space (or trailing colon)."""
    in_s = in_d = False
    for i, ch in enumerate(content):
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif ch == ":" and not in_s and not in_d:
            after = content[i + 1:]
            if after == "" or after[0] in " \t":
                return _unquote(content[:i].strip()), after.strip()
    raise ValueError(
        f"_miniyaml: expected 'key: value' at line {lineno}: {content!r}"
    )


def _scalar(s: str) -> Any:
    if s == "{}":
        return {}
    if s == "[]":
        return []
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return _unquote(s)
    if s in ("true", "True"):
        return True
    if s in ("false", "False"):
        return False
    if s in ("null", "~", "Null"):
        return None
    if _is_int(s):
        return int(s)
    if _is_float(s):
        return float(s)
    return s


def _unquote(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] == '"':
        return s[1:-1].replace('\\"', '"')
    if len(s) >= 2 and s[0] == s[-1] and s[0] == "'":
        return s[1:-1].replace("''", "'")
    return s


def _is_int(s: str) -> bool:
    t = s[1:] if s[:1] in "+-" else s
    return t.isdigit()


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False
