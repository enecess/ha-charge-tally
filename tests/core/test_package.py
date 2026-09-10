"""Release archives are deterministic and accept only distributable files."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from zipfile import ZipFile


ROOT = Path(__file__).parents[2]


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / "scripts" / "package.py").is_file(), "The release packager must exist")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.component = self.root / "custom_components" / "charge_tally"
        shutil.copytree(ROOT / "custom_components" / "charge_tally", self.component,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copyfile(ROOT / "pyproject.toml", self.root / "pyproject.toml")

    def test_repeated_build_has_identical_bytes_and_only_installable_paths(self):
        from scripts.package import build
        first = build(self.root, self.root / "one.zip")
        second = build(self.root, self.root / "two.zip")
        self.assertEqual(hashlib.sha256(first.read_bytes()).digest(), hashlib.sha256(second.read_bytes()).digest())
        with ZipFile(first) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn("custom_components/charge_tally/manifest.json", archive.namelist())
            self.assertIn("custom_components/charge_tally/www/charge-tally-card.js", archive.namelist())
            self.assertTrue(all(name.startswith("custom_components/charge_tally/") for name in archive.namelist()))
            self.assertFalse(any("test" in name or ".gitkeep" in name for name in archive.namelist()))

    def test_unexpected_data_is_rejected_instead_of_leaked(self):
        from scripts.package import build
        for relative in ("ledger.sqlite3", "secret.py", "www/key.pem", "www/tests.js"):
            with self.subTest(relative=relative):
                path = self.component / relative
                path.write_text("private", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Unexpected"):
                    build(self.root)
                path.unlink()

    def test_archive_includes_card_and_native_translations_for_all_languages(self):
        from scripts.package import build
        with ZipFile(build(self.root)) as archive:
            prefix = "custom_components/charge_tally/"
            for language in ("en", "zh-Hans", "de", "fr", "pl"):
                for relative in (f"translations/{language}.json", f"www/locales/{language}.js"):
                    self.assertEqual(archive.read(prefix + relative), (self.component / relative).read_bytes())
            self.assertIn(prefix + "www/card-i18n.js", archive.namelist())

    def test_manifest_version_mismatch_is_rejected(self):
        from scripts.package import build
        path = self.component / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["version"] = "0.2.0"
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "version"):
            build(self.root)

    def test_shared_version_constant_must_match_manifest(self):
        from scripts.package import build
        path = self.component / "const.py"
        path.write_text(path.read_text(encoding="utf-8").replace('VERSION = "0.1.1"', 'VERSION = "0.2.0"'), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "version"):
            build(self.root)

    def test_frontend_module_version_mismatch_is_rejected(self):
        from scripts.package import build
        module = self.component / "www" / "charge-tally-card.js"
        module.write_text(module.read_text(encoding="utf-8").replace("?v=0.1.1", "?v=0.2.0"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "version"):
            build(self.root)
