#!/usr/bin/env python3
"""Validate theme files and generate catalog.toml and the README theme table.

Standard library only (Python 3.11+).

    python3 tools/catalog.py check            validate; fail if catalog.toml, ids.txt or README is stale
    python3 tools/catalog.py build            rewrite catalog.toml, ids.txt and the README table
    python3 tools/catalog.py versions <ref>   fail if an id vanished or a changed theme kept its version
    python3 tools/catalog.py previews         write previews/derived.svg (every derived = true theme)
"""
import json
import re
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

ALLOWED_LICENSES = ["MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC",
                    "Unlicense", "CC0-1.0", "Zlib"]
CATALOG_FORMAT = 1
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
COLOR_KEYS = ["foreground", "background", "cursor", "selection", "black", "red", "green",
              "yellow", "blue", "magenta", "cyan", "white", "bright_black", "bright_red",
              "bright_green", "bright_yellow", "bright_blue", "bright_magenta",
              "bright_cyan", "bright_white"]
CREDIT_KEYS = ["project", "author", "url", "license", "copyright", "license_file",
               "description"]
MIN_CONTRAST = 4.5
README_START = "<!-- themes:start -->"
README_END = "<!-- themes:end -->"
ROOT = Path(__file__).resolve().parent.parent


def load_themes(root):
    """Return (themes by id, parse errors). Files are read in sorted order."""
    themes, errors = {}, []
    for path in sorted((root / "themes").glob("*.toml")):
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
            errors.append(f"{path.name}: cannot parse: {e}")
            continue
        data["_file"] = path.stem
        themes[path.stem] = data
    return themes, errors


def luminance(hex_color):
    def chan(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def validate_theme(root, stem, t):
    errors, warnings = [], []
    where = f"themes/{stem}.toml"

    def err(msg):
        errors.append(f"{where}: {msg}")

    tid = t.get("id")
    if not isinstance(tid, str) or not SLUG.match(tid):
        err(f"id {tid!r} is not a valid slug")
    elif tid != stem:
        err(f"id {tid!r} does not match the file name")
    if not SLUG.match(stem):
        err("file name is not a valid slug")
    if not isinstance(t.get("name"), str) or not t["name"].strip():
        err("name must be a non-empty string")
    if type(t.get("version")) is not int or t["version"] < 1:
        err("version must be an integer >= 1")
    if t.get("variant") not in ("dark", "light"):
        err('variant must be "dark" or "light"')
    if "font_family" in t and not isinstance(t["font_family"], str):
        err("font_family must be a string")
    if "font_size" in t and (isinstance(t["font_size"], bool)
                             or not isinstance(t["font_size"], (int, float))):
        err("font_size must be a number")
    if "withdrawn" in t and t["withdrawn"] is not True:
        err("withdrawn, when present, must be true")

    colors = t.get("colors")
    if not isinstance(colors, dict):
        err("missing [colors] table")
        colors = {}
    for k in COLOR_KEYS:
        v = colors.get(k)
        if not isinstance(v, str) or not HEX.match(v):
            err(f"colors.{k} must be #rrggbb, got {v!r}")
    for k in colors:
        if k not in COLOR_KEYS:
            err(f"unknown color key {k}")

    credit = t.get("credit")
    if not isinstance(credit, dict):
        err("missing [credit] table")
        credit = {}
    for k in CREDIT_KEYS:
        v = credit.get(k)
        if not isinstance(v, str) or not v.strip():
            err(f"credit.{k} is required and must be non-empty")
    if "derived" in credit and not isinstance(credit["derived"], bool):
        err("credit.derived must be a boolean")
    lic = credit.get("license")
    if isinstance(lic, str) and lic.strip() and lic not in ALLOWED_LICENSES:
        err(f"credit.license {lic!r} is not on the allowlist {ALLOWED_LICENSES}")
    url = credit.get("url")
    if isinstance(url, str) and url.strip() and not url.startswith("https://"):
        err("credit.url must be https://")
    lf = credit.get("license_file")
    if isinstance(lf, str) and lf.strip():
        p = (root / lf).resolve()
        if p.parent != (root / "LICENSES").resolve() or not p.is_file():
            err(f"credit.license_file {lf!r} must be an existing file under LICENSES/")

    fg, bg = colors.get("foreground"), colors.get("background")
    if isinstance(fg, str) and isinstance(bg, str) and HEX.match(fg) and HEX.match(bg):
        ratio = contrast(fg, bg)
        if ratio < MIN_CONTRAST:
            warnings.append(f"{where}: warning: contrast of foreground on background is "
                            f"{ratio:.2f}:1, below {MIN_CONTRAST}:1")
    return errors, warnings


def validate(root):
    themes, errors = load_themes(root)
    warnings = []
    for stem, t in themes.items():
        e, w = validate_theme(root, stem, t)
        errors += e
        warnings += w
    return errors, warnings


def q(s):
    return json.dumps(s, ensure_ascii=False)


def scalar(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return q(v)
    return repr(v)


def entry_lines(t):
    lines = ["[[themes]]"]
    for k in ("id", "name", "version", "variant", "font_family", "font_size", "withdrawn"):
        if k in t:
            lines.append(f"{k} = {scalar(t[k])}")
    lines += ["", "[themes.colors]"]
    lines += [f"{k} = {q(t['colors'][k])}" for k in COLOR_KEYS]
    lines += ["", "[themes.credit]"]
    for k in CREDIT_KEYS:
        lines.append(f"{k} = {q(t['credit'][k])}")
    lines.append(f"derived = {scalar(t['credit'].get('derived', False))}")
    return lines


def build_catalog(root):
    themes, _ = load_themes(root)
    out = [f"format = {CATALOG_FORMAT}", ""]
    for tid in sorted(themes):
        out += entry_lines(themes[tid]) + [""]
    return "\n".join(out)


def md(s):
    return str(s).replace("|", "\\|")


def readme_table(root):
    themes, _ = load_themes(root)
    rows = ["| Theme | Variant | Project | Author | License |", "|---|---|---|---|---|"]
    for tid in sorted(themes):
        t = themes[tid]
        c = t["credit"]
        rows.append(f"| {md(t['name'])} | {t['variant']} | [{md(c['project'])}]({c['url']}) "
                    f"| {md(c['author'])} | {md(c['license'])} |")
    return "\n".join(rows)


def render_readme(root):
    text = (root / "README.md").read_text(encoding="utf-8")
    s, e = text.find(README_START), text.find(README_END)
    if s < 0 or e < s:
        raise SystemExit(f"README.md must contain {README_START} and {README_END}")
    return text[:s + len(README_START)] + "\n" + readme_table(root) + "\n" + text[e:]


def catalog_to_themes(data):
    return {t["id"]: t for t in data.get("themes", [])}


def check_versions(base, cur, base_ids=None, cur_ids=None):
    """base and cur map id to theme dicts; *_ids are the ids.txt registries (optional).
    Return a list of error strings."""
    errors = []
    if base_ids is not None and cur_ids is not None:
        for i in sorted(set(base_ids) - set(cur_ids)):
            errors.append(f"{i}: id was dropped from ids.txt (the registry is append-only)")
        for i in sorted(set(base_ids) - set(base)):
            if i in cur:
                errors.append(f"{i}: id was used before and removed from the catalog; "
                              f"ids are never reused")
    for tid, old in sorted(base.items()):
        new = cur.get(tid)
        if new is None:
            errors.append(f"{tid}: id disappeared from the catalog (mark withdrawn instead)")
        elif new != old and new.get("version", 0) <= old.get("version", 0):
            errors.append(f"{tid}: changed but version did not grow "
                          f"({old.get('version')} -> {new.get('version')})")
    return errors


def read_ids(root):
    path = root / "ids.txt"
    if not path.is_file():
        return []
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def build_ids(root):
    """Append-only registry: previous ids.txt plus current theme ids, sorted, never dropping."""
    themes, _ = load_themes(root)
    return sorted(set(read_ids(root)) | set(themes))


def ids_text(ids):
    return "".join(f"{i}\n" for i in ids)


def registry_errors(root, check_stale=True):
    errors = []
    themes, _ = load_themes(root)
    for i in read_ids(root):
        if i not in themes:
            errors.append(f"{i}: id is in ids.txt but its theme file is gone "
                          f"(keep the file and set withdrawn = true instead of deleting)")
    path = root / "ids.txt"
    if check_stale and (not path.is_file()
                        or path.read_text(encoding="utf-8") != ids_text(build_ids(root))):
        errors.append("ids.txt is stale: run python3 tools/catalog.py build")
    return errors


def cmd_check(root):
    errors, warnings = validate(root)
    for w in warnings:
        print(w)
    if not errors:
        errors += registry_errors(root)
    if not errors:
        cat = root / "catalog.toml"
        if not cat.is_file() or cat.read_text(encoding="utf-8") != build_catalog(root):
            errors.append("catalog.toml is stale: run python3 tools/catalog.py build")
        if (root / "README.md").read_text(encoding="utf-8") != render_readme(root):
            errors.append("README.md theme table is stale: run python3 tools/catalog.py build")
    for e in errors:
        print(f"error: {e}")
    return 1 if errors else 0


def cmd_build(root):
    errors, warnings = validate(root)
    for w in warnings:
        print(w)
    if not errors:
        errors += registry_errors(root, check_stale=False)
    if errors:
        for e in errors:
            print(f"error: {e}")
        return 1
    (root / "ids.txt").write_text(ids_text(build_ids(root)), encoding="utf-8")
    (root / "catalog.toml").write_text(build_catalog(root), encoding="utf-8")
    (root / "README.md").write_text(render_readme(root), encoding="utf-8")
    return 0


def git_show(root, ref, path):
    """Return (state, text); state is "ok", "missing" (ref fine, file absent) or "error"."""
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    r = git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if r.returncode != 0:
        return "error", f"cannot resolve git ref {ref!r}"
    r = git("ls-tree", "--name-only", ref, "--", path)
    if r.returncode != 0:
        return "error", f"git ls-tree failed for {ref}:{path}: {r.stderr.strip()}"
    if not r.stdout.strip():
        return "missing", ""
    r = git("show", f"{ref}:{path}")
    if r.returncode != 0:
        return "error", f"git show {ref}:{path} failed: {r.stderr.strip()}"
    return "ok", r.stdout


def cmd_versions(root, ref):
    state, text = git_show(root, ref, "catalog.toml")
    if state == "error":
        print(f"error: {text}")
        return 1
    if state == "missing":
        print(f"no catalog.toml at {ref}; nothing to compare")
        return 0
    base = catalog_to_themes(tomllib.loads(text))
    cur = catalog_to_themes(tomllib.loads((root / "catalog.toml").read_text(encoding="utf-8")))
    state, ids_base = git_show(root, ref, "ids.txt")
    if state == "error":
        print(f"error: {ids_base}")
        return 1
    base_ids = [ln.strip() for ln in ids_base.splitlines() if ln.strip()]
    errors = check_versions(base, cur, base_ids, read_ids(root))
    for e in errors:
        print(f"error: {e}")
    return 1 if errors else 0


SVG_NS = "http://www.w3.org/2000/svg"
PREVIEW_SLOTS = ["background", "foreground", "cursor", "selection"] + COLOR_KEYS[4:]
SWATCH, GAP, LABEL_W, ROW_H, PAD = 28, 4, 230, 44, 16


def preview_svg(themes):
    """One row per theme on its own background: name (in the foreground) and id, then
    swatches of background, foreground, cursor, selection and the 16 colors."""
    ET.register_namespace("", SVG_NS)
    rows = [themes[tid] for tid in sorted(themes)]
    swatches_w = len(PREVIEW_SLOTS) * (SWATCH + GAP)
    width = PAD * 2 + LABEL_W + swatches_w
    height = PAD * 2 + 24 + ROW_H * len(rows)
    svg = ET.Element(f"{{{SVG_NS}}}svg", {
        "width": str(width), "height": str(height), "viewBox": f"0 0 {width} {height}",
        "font-family": "monospace", "font-size": "12"})

    def el(parent, tag, text=None, **attrs):
        e = ET.SubElement(parent, f"{{{SVG_NS}}}{tag}",
                          {k.replace("_", "-"): str(v) for k, v in attrs.items()})
        e.text = text
        return e

    el(svg, "rect", x=0, y=0, width=width, height=height, fill="#ffffff")
    header = "Derived themes: background, foreground, cursor, selection, 16 colors"
    el(svg, "text", header, x=PAD, y=PAD + 12, fill="#000000")
    for i, t in enumerate(rows):
        y = PAD + 24 + i * ROW_H
        c = t["colors"]
        el(svg, "rect", x=PAD, y=y, width=LABEL_W + swatches_w, height=ROW_H - GAP,
           fill=c["background"])
        el(svg, "text", t["name"], x=PAD + 8, y=y + 16, fill=c["foreground"])
        el(svg, "text", t["id"], x=PAD + 8, y=y + 32, fill=c["bright_black"])
        for j, slot in enumerate(PREVIEW_SLOTS):
            el(svg, "rect", x=PAD + LABEL_W + j * (SWATCH + GAP), y=y + 6, width=SWATCH,
               height=ROW_H - GAP - 12, fill=c[slot], stroke=c["foreground"],
               stroke_width="0.5")
    ET.indent(svg)
    return ET.tostring(svg, encoding="unicode", xml_declaration=True) + "\n"


def cmd_previews(root):
    errors, _ = validate(root)
    if errors:
        for e in errors:
            print(f"error: {e}")
        return 1
    themes, _ = load_themes(root)
    derived = {k: t for k, t in themes.items() if t["credit"].get("derived") is True}
    out = root / "previews" / "derived.svg"
    out.parent.mkdir(exist_ok=True)
    out.write_text(preview_svg(derived), encoding="utf-8")
    print(f"wrote {out.relative_to(root)} ({len(derived)} themes)")
    return 0


def main(argv):
    if len(argv) >= 2 and argv[1] == "check":
        return cmd_check(ROOT)
    if len(argv) >= 2 and argv[1] == "build":
        return cmd_build(ROOT)
    if len(argv) == 3 and argv[1] == "versions":
        return cmd_versions(ROOT, argv[2])
    if len(argv) >= 2 and argv[1] == "previews":
        return cmd_previews(ROOT)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
