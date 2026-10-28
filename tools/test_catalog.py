import contextlib
import copy
import io
import os
import subprocess
import tempfile
import unittest
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


def theme_text(id="example", credit=None, colors=None, version=1):
    credit = dict(CREDIT if credit is None else credit)
    colors = colors or {k: "#%02x%02x%02x" % ((i * 11) % 256, 40, 200 - i * 3)
                        for i, k in enumerate(COLOR_KEYS)}
    out = [f'name = "Example"', f'id = "{id}"', f"version = {version}", 'variant = "dark"', "",
           "[colors]"]
    out += [f'{k} = "{v}"' for k, v in colors.items()]
    out += ["", "[credit]"]
    out += [f'{k} = "{v}"' for k, v in credit.items()] + ["derived = false", ""]
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


if __name__ == "__main__":
    unittest.main()
