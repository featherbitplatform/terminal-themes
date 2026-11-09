import contextlib
import copy
import io
import os
import subprocess
import tempfile
import unittest
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import catalog

COLOR_KEYS = ["foreground", "background", "cursor", "selection", "black", "red", "green",
              "yellow", "blue", "magenta", "cyan", "white", "bright_black", "bright_red",
              "bright_green", "bright_yellow", "bright_blue", "bright_magenta",
              "bright_cyan", "bright_white"]

CREDIT = {
    "project": "Example", "author": "Example Authors", "url": "https://example.org/x",
    "license": "MIT", "copyright": "Copyright (c) 2021 Example",
    "license_file": "LICENSES/example-MIT.txt", "description": "An example theme.",
}

FONT = {"family": "Example Mono", "url": "https://example.org/font", "license": "OFL-1.1"}


def theme_text(id="example", credit=None, colors=None, version=1, name="Example",
               derived=False, font=FONT):
    credit = dict(CREDIT if credit is None else credit)
    colors = colors or {k: "#%02x%02x%02x" % ((i * 11) % 256, 40, 200 - i * 3)
                        for i, k in enumerate(COLOR_KEYS)}
    out = [f"name = {catalog.q(name)}", f'id = "{id}"', f"version = {version}", 'variant = "dark"', "",
           "[colors]"]
    out += [f'{k} = "{v}"' for k, v in colors.items()]
    out += ["", "[credit]"]
    out += [f"{k} = {catalog.q(v)}" for k, v in credit.items()]
    out += [f"derived = {'true' if derived else 'false'}", ""]
    if font is not None:
        out += ["[suggested_font]"]
        out += [f"{k} = {catalog.q(v) if isinstance(v, str) else v}" for k, v in font.items()]
        out += [""]
    return "\n".join(out)


class Repo:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "themes").mkdir()
        (self.root / "LICENSES").mkdir()
        (self.root / "LICENSES/example-MIT.txt").write_text("MIT License\n")
        (self.root / "README.md").write_text(
            "# t\n\n<!-- themes:start -->\n<!-- themes:end -->\n")

    def add(self, id="example", **kw):
        (self.root / "themes" / f"{id}.toml").write_text(theme_text(id=id, **kw))

    def raw(self, name, text):
        (self.root / "themes" / name).write_text(text)

    def errors(self):
        return catalog.validate(self.root)[0]

    def warnings(self):
        return catalog.validate(self.root)[1]


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo._tmp.cleanup)

    def test_valid_theme_passes(self):
        self.repo.add()
        self.assertEqual(self.repo.errors(), [])

    def test_license_not_on_allowlist_fails(self):
        self.repo.add(credit={**CREDIT, "license": "GPL-3.0-only"})
        self.assertTrue(any("license" in e for e in self.repo.errors()))

    def test_missing_credit_field_fails(self):
        for field in ["project", "author", "url", "license", "copyright",
                      "license_file", "description"]:
            with self.subTest(field=field):
                credit = {k: v for k, v in CREDIT.items() if k != field}
                self.repo.add(credit=credit)
                self.assertTrue(any(field in e for e in self.repo.errors()))

    def test_license_file_must_exist(self):
        self.repo.add(credit={**CREDIT, "license_file": "LICENSES/nope.txt"})
        self.assertTrue(any("license_file" in e for e in self.repo.errors()))

    def test_url_must_be_https(self):
        self.repo.add(credit={**CREDIT, "url": "http://example.org"})
        self.assertTrue(any("url" in e for e in self.repo.errors()))

    def test_id_must_match_file_and_slug(self):
        self.repo.raw("other.toml", theme_text(id="example"))
        self.assertTrue(any("id" in e for e in self.repo.errors()))
        self.repo.raw("Bad_Id.toml", theme_text(id="Bad_Id"))
        self.assertTrue(any("slug" in e for e in self.repo.errors()))

    def test_id_length_limit(self):
        self.repo.add(id="a" * 65)
        self.assertTrue(any("64" in e for e in self.repo.errors()))

    def test_id_of_64_chars_passes(self):
        self.repo.add(id="a" * 64)
        self.assertEqual(self.repo.errors(), [])

    def test_gallery_prefix_is_reserved(self):
        self.repo.add(id="gallery-x")
        self.assertTrue(any("gallery-" in e for e in self.repo.errors()))

    def test_bad_color_fails(self):
        for bad in ["#12345", "red"]:
            with self.subTest(bad=bad):
                colors = {k: "#102030" for k in COLOR_KEYS}
                colors["red"] = bad
                self.repo.add(colors=colors)
                self.assertTrue(any("red" in e for e in self.repo.errors()))

    def test_build_is_deterministic(self):
        self.repo.add("zeta")
        self.repo.add("alpha")
        a = catalog.build_catalog(self.repo.root)
        b = catalog.build_catalog(self.repo.root)
        self.assertEqual(a, b)
        self.assertLess(a.index('id = "alpha"'), a.index('id = "zeta"'))
        self.assertTrue(a.startswith("format = 1\n"))

    def test_removed_id_fails_versions(self):
        base = {"a": {"id": "a", "version": 1}}
        self.assertTrue(catalog.check_versions(base, {}))

    def test_changed_theme_without_version_bump_fails(self):
        base = {"a": {"id": "a", "version": 1, "name": "A"}}
        cur = {"a": {"id": "a", "version": 1, "name": "B"}}
        self.assertTrue(catalog.check_versions(base, cur))
        cur["a"]["version"] = 2
        self.assertEqual(catalog.check_versions(base, cur), [])
        same = copy.deepcopy(base)
        self.assertEqual(catalog.check_versions(base, same), [])

    def test_contrast_is_reported_not_fatal(self):
        colors = {k: "#808080" for k in COLOR_KEYS}
        colors["foreground"], colors["background"] = "#777777", "#808080"
        self.repo.add(colors=colors)
        self.assertEqual(self.repo.errors(), [])
        self.assertTrue(any("example" in w and "contrast" in w for w in self.repo.warnings()))


class LicenseFilePathTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo._tmp.cleanup)

    def assert_rejected(self, path):
        self.repo.add(credit={**CREDIT, "license_file": path})
        self.assertTrue(any("license_file" in e for e in self.repo.errors()), path)

    def test_path_outside_licenses_fails(self):
        self.assert_rejected("README.md")

    def test_dotdot_escape_fails(self):
        outside = self.repo.root.parent / "outside-license.txt"
        outside.write_text("x")
        self.addCleanup(outside.unlink)
        self.assert_rejected("../outside-license.txt")
        self.assert_rejected("LICENSES/../README.md")

    def test_absolute_path_fails(self):
        self.assert_rejected(str(self.repo.root / "LICENSES/example-MIT.txt") + "x")
        self.assert_rejected("/etc/hosts")


def git(root, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)


def run_versions(root, ref):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = catalog.cmd_versions(root, ref)
    return rc, buf.getvalue()


class VersionsCommandTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo._tmp.cleanup)
        self.root = self.repo.root
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "base")

    def test_ref_without_catalog_passes_bootstrap(self):
        self.repo.add()
        (self.root / "catalog.toml").write_text(catalog.build_catalog(self.root))
        self.assertEqual(run_versions(self.root, "main")[0], 0)

    def test_unresolvable_ref_fails(self):
        (self.root / "catalog.toml").write_text("format = 1\n")
        rc, out = run_versions(self.root, "origin/does-not-exist")
        self.assertEqual(rc, 1)
        self.assertIn("cannot resolve", out)

    def test_not_a_git_repo_fails(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "catalog.toml").write_text("format = 1\n")
            self.assertEqual(run_versions(Path(d), "main")[0], 1)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo._tmp.cleanup)
        self.root = self.repo.root

    def build(self):
        self.assertEqual(catalog.cmd_build(self.root), 0)

    def check(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = catalog.cmd_check(self.root)
        return rc, buf.getvalue()

    def test_build_writes_sorted_ids_and_check_passes(self):
        self.repo.add("zeta")
        self.repo.add("alpha")
        self.build()
        self.assertEqual((self.root / "ids.txt").read_text(), "alpha\nzeta\n")
        self.assertEqual(self.check()[0], 0)

    def test_stale_ids_fails_check(self):
        self.repo.add("alpha")
        self.build()
        self.repo.add("beta")
        (self.root / "catalog.toml").write_text(catalog.build_catalog(self.root))
        rc, out = self.check()
        self.assertEqual(rc, 1)
        self.assertIn("ids.txt is stale", out)

    def test_deleted_theme_fails_and_build_never_drops_id(self):
        self.repo.add("alpha")
        self.repo.add("beta")
        self.build()
        (self.root / "themes/beta.toml").unlink()
        rc, out = self.check()
        self.assertEqual(rc, 1)
        self.assertIn("withdrawn", out)
        self.assertEqual(catalog.cmd_build(self.root), 1)
        self.assertIn("beta", (self.root / "ids.txt").read_text())

    def test_withdrawn_theme_stays_valid(self):
        self.repo.add("alpha")
        self.build()
        path = self.root / "themes/alpha.toml"
        path.write_text(path.read_text().replace('variant = "dark"',
                                                 'variant = "dark"\nwithdrawn = true'))
        self.build()
        self.assertEqual(self.check()[0], 0)

    def test_reused_id_caught_via_ids_registry(self):
        base_ids = ["alpha", "beta"]
        base = {"alpha": {"id": "alpha", "version": 1}}  # beta was removed from the catalog
        cur = {"alpha": {"id": "alpha", "version": 1}, "beta": {"id": "beta", "version": 1}}
        errors = catalog.check_versions(base, cur, base_ids, base_ids)
        self.assertTrue(any("beta" in e and "reused" in e for e in errors))

    def test_dropped_registry_id_fails_versions(self):
        errors = catalog.check_versions({}, {}, ["alpha", "beta"], ["alpha"])
        self.assertTrue(any("beta" in e for e in errors))


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo._tmp.cleanup)
        self.root = self.repo.root

    def test_previews_writes_svg_with_each_derived_theme(self):
        self.repo.add("alpha", name="Alpha <Derived> & Co", derived=True)
        self.repo.add("beta", name="Beta Mapped", derived=True)
        self.repo.add("gamma", name="Gamma Official")
        self.assertEqual(catalog.cmd_previews(self.root), 0)
        path = self.root / "previews/derived.svg"
        tree = ET.parse(path)
        svg = tree.getroot()
        self.assertEqual(svg.tag, "{http://www.w3.org/2000/svg}svg")
        texts = [t.text for t in svg.iter("{http://www.w3.org/2000/svg}text")]
        self.assertIn("Alpha <Derived> & Co", texts)
        self.assertIn("Beta Mapped", texts)
        self.assertNotIn("Gamma Official", texts)
        fills = {r.get("fill") for r in svg.iter("{http://www.w3.org/2000/svg}rect")}
        for color in ("#0b28c5", "#0028c8", "#1628c2", "#2128bf", "#2c28bc", "#d1288f"):
            self.assertIn(color, fills)

    def test_stale_preview_fails_check(self):
        self.repo.add("alpha", name="Alpha", derived=True)
        self.assertEqual(catalog.cmd_build(self.root), 0)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(catalog.cmd_check(self.root), 0)
        (self.root / "previews/derived.svg").write_text("<svg/>\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = catalog.cmd_check(self.root)
        self.assertEqual(rc, 1)
        self.assertIn("previews/derived.svg is stale", buf.getvalue())

    def test_previews_is_deterministic(self):
        self.repo.add("alpha", derived=True)
        catalog.cmd_previews(self.root)
        first = (self.root / "previews/derived.svg").read_bytes()
        catalog.cmd_previews(self.root)
        self.assertEqual((self.root / "previews/derived.svg").read_bytes(), first)


if __name__ == "__main__":
    unittest.main()


class TomlStringTests(unittest.TestCase):
    def test_every_string_reads_back_unchanged(self):
        for s in ["Nord", 'say "hi"', "back\\slash", "tab\there", "two\nlines",
                  "del\x7fchar", "ctrl\x01char", "café", "emoji \U0001F600"]:
            with self.subTest(s=s):
                self.assertEqual(tomllib.loads(f"k = {catalog.q(s)}")["k"], s)


class HiddenCharacterTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo._tmp.cleanup)

    def test_hidden_characters_in_credit_fail(self):
        for c in ["\x7f", "\x1b", "‮", "​", "﻿", "⁠", "­"]:
            with self.subTest(c=repr(c)):
                self.repo.add(credit={**CREDIT, "author": f"A{c}B"})
                self.assertTrue(any("credit.author" in e and "invisible" in e
                                    for e in self.repo.errors()), self.repo.errors())

    def test_newline_allowed_in_description_only(self):
        self.repo.add(credit={**CREDIT, "description": "line one\nline two"})
        self.assertEqual(self.repo.errors(), [])
        self.repo.add(credit={**CREDIT, "author": "A\nB"})
        self.assertTrue(any("credit.author" in e for e in self.repo.errors()))

    def test_hidden_character_in_name_fails(self):
        self.repo.add(name="Bad‮Name")
        self.assertTrue(any(e.endswith("(U+202E)") and "name" in e
                            for e in self.repo.errors()), self.repo.errors())


class SuggestedFontTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo._tmp.cleanup)

    def font_errors(self, font):
        self.repo.add(font=font)
        return [e for e in self.repo.errors() if "suggested_font" in e]

    def test_theme_without_suggested_font_fails(self):
        self.assertTrue(self.font_errors(None), self.repo.errors())

    def test_valid_suggested_font_passes(self):
        self.repo.add()
        self.assertEqual(self.repo.errors(), [])

    def test_every_key_is_required(self):
        for key in FONT:
            with self.subTest(key=key):
                font = {k: v for k, v in FONT.items() if k != key}
                errors = self.font_errors(font)
                self.assertTrue(any(f"suggested_font.{key}" in e for e in errors), errors)

    def test_empty_or_non_string_values_fail(self):
        for key in FONT:
            for bad in ["", "  ", 3]:
                with self.subTest(key=key, bad=bad):
                    errors = self.font_errors({**FONT, key: bad})
                    self.assertTrue(any(f"suggested_font.{key}" in e for e in errors), errors)

    def test_url_must_be_https_with_a_host(self):
        for bad in ["http://example.org/font", "https://", "https:///path",
                    "https://example.org/a b", "ftp://example.org", "example.org"]:
            with self.subTest(bad=bad):
                errors = self.font_errors({**FONT, "url": bad})
                self.assertTrue(any("suggested_font.url" in e for e in errors), errors)

    def test_license_must_be_on_the_font_allowlist(self):
        for ok in ["OFL-1.1", "Apache-2.0", "MIT"]:
            with self.subTest(ok=ok):
                self.assertEqual(self.font_errors({**FONT, "license": ok}), [])
        for bad in ["GPL-3.0-only", "Proprietary", "ofl-1.1", "UFL-1.0"]:
            with self.subTest(bad=bad):
                errors = self.font_errors({**FONT, "license": bad})
                self.assertTrue(any("suggested_font.license" in e for e in errors), errors)

    def test_unknown_key_fails(self):
        errors = self.font_errors({**FONT, "size": "12"})
        self.assertTrue(any("size" in e for e in errors), errors)

    def test_not_a_table_fails(self):
        self.repo.add(font=None)
        path = self.repo.root / "themes/example.toml"
        path.write_text('suggested_font = "Example Mono"\n' + path.read_text())
        self.assertTrue(any("suggested_font" in e for e in self.repo.errors()))

    def test_length_cap(self):
        at_cap = "x" * catalog.MAX_FIELD_CHARS
        self.assertEqual(self.font_errors({**FONT, "family": at_cap}), [])
        errors = self.font_errors({**FONT, "family": at_cap + "x"})
        self.assertTrue(any("suggested_font.family" in e and str(catalog.MAX_FIELD_CHARS) in e
                            for e in errors), errors)

    def test_hidden_characters_fail(self):
        for c in ["\x7f", "\x1b", "\n", "‮", "​", "﻿", "⁠", "­"]:
            for key in ("family", "url"):
                with self.subTest(c=repr(c), key=key):
                    errors = self.font_errors({**FONT, key: FONT[key] + c + "x"})
                    self.assertTrue(any(f"suggested_font.{key}" in e for e in errors), errors)

    def test_catalog_carries_the_suggested_font(self):
        font = {"family": 'Mono "Q" \\ é', "url": "https://example.org/f",
                "license": "Apache-2.0"}
        self.repo.add(font=font)
        built = tomllib.loads(catalog.build_catalog(self.repo.root))
        self.assertEqual(built["themes"][0]["suggested_font"], font)

    def test_readme_table_has_a_font_column(self):
        self.repo.add()
        header, _, row = catalog.readme_table(self.repo.root).splitlines()
        self.assertIn("| Font |", header)
        self.assertIn("[Example Mono](https://example.org/font) (OFL-1.1)", row)

    def test_changed_suggested_font_needs_a_version_bump(self):
        self.repo.add()
        base = catalog.catalog_to_themes(tomllib.loads(catalog.build_catalog(self.repo.root)))
        self.repo.add(font={**FONT, "family": "Other Mono"})
        cur = catalog.catalog_to_themes(tomllib.loads(catalog.build_catalog(self.repo.root)))
        self.assertTrue(catalog.check_versions(base, cur))
