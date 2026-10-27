"""Validate the translation contract consumed by Home Assistant."""

import json
import re
import unittest
from pathlib import Path

INTEGRATION = Path(__file__).resolve().parents[2] / "custom_components" / "charge_tally"
LANGUAGES = ("en", "zh-Hans", "de", "fr", "pl", "it")


def flatten(value, prefix=()):
    """Return every leaf keyed by its complete JSON path."""
    if isinstance(value, dict):
        return {
            path: leaf
            for key, child in value.items()
            for path, leaf in flatten(child, (*prefix, key)).items()
        }
    return {prefix: value}


class TranslationTests(unittest.TestCase):
    def test_supported_languages_preserve_home_assistant_translation_contract(self):
        canonical = flatten(
            json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
        )
        for language in LANGUAGES:
            with self.subTest(language=language):
                path = INTEGRATION / "translations" / f"{language}.json"
                self.assertTrue(path.is_file(), f"Missing translation: {language}")
                translated = flatten(json.loads(path.read_text(encoding="utf-8")))
                self.assertEqual(set(canonical), set(translated))
                for key, source in canonical.items():
                    with self.subTest(key=".".join(key)):
                        target = translated[key]
                        self.assertIsInstance(target, str)
                        self.assertTrue(target.strip(), "Empty translation")
                        self.assertEqual(
                            set(re.findall(r"\{([^{}]+)\}", source)),
                            set(re.findall(r"\{([^{}]+)\}", target)),
                            "Translation changes template placeholders",
                        )

    def test_currency_labels_have_localized_names_and_iso_suffixes(self):
        canonical = json.loads(
            (INTEGRATION / "strings.json").read_text(encoding="utf-8")
        )
        self.assertIn("currency", canonical["selector"])
        codes = set(canonical["selector"]["currency"]["options"])
        self.assertTrue({"CNY", "JPY", "HKD", "TWD", "SGD"}.issubset(codes))
        for language in LANGUAGES:
            translated = json.loads(
                (INTEGRATION / "translations" / f"{language}.json").read_text(
                    encoding="utf-8"
                )
            )
            labels = translated["selector"]["currency"]["options"]
            self.assertEqual(set(labels), codes)
            for code, label in labels.items():
                with self.subTest(language=language, code=code):
                    self.assertRegex(code, r"^[A-Z]{3}$")
                    self.assertTrue(label.endswith(f"({code})"))
                    name = label[:-5]
                    self.assertTrue(name.strip())
                    self.assertNotEqual(name, code)
                    self.assertEqual(name, name.rstrip())
            if language == "zh-Hans":
                self.assertEqual(labels["CNY"], "人民币(CNY)")
            if language == "en":
                self.assertEqual(translated, canonical)


if __name__ == "__main__":
    unittest.main()
