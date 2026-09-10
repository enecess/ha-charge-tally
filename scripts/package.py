"""Build a deterministic, strictly allowlisted Charge Tally installation archive."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import tomllib
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


FILES = frozenset("""
__init__.py accounting.py api.py backup.py config_flow.py config_validation.py const.py
entity.py frontend.py history.py icons.json ledger.py manifest.json native_helpers.py
queries.py repairs.py runtime.py runtime_store.py select.py sensor.py services.yaml strings.json switch.py
core/__init__.py core/detection.py core/segments.py core/tariffs.py core/units.py
translations/en.json translations/zh-Hans.json
translations/de.json translations/fr.json translations/pl.json
www/card-dialog.js www/card-editor.js www/card-state.js www/card-styles.js www/card-ui.js www/charge-tally-card.js
www/card-i18n.js www/locales/en.js www/locales/zh-Hans.js www/locales/de.js www/locales/fr.js www/locales/pl.js
""".split())
BRAND_FILES = frozenset("brand/" + name + ".png" for name in (
    "icon", "logo", "icon@2x", "logo@2x", "dark_icon", "dark_logo", "dark_icon@2x", "dark_logo@2x"
))


def build(root: Path, output: Path | None = None) -> Path:
    """Validate release inputs, write fixed ZIP metadata, and verify the archive."""
    root = root.resolve()
    component = root / "custom_components" / "charge_tally"
    if component.is_symlink():
        raise ValueError("Unexpected component symlink")
    paths = {}
    for path in sorted(component.rglob("*")):
        relative = path.relative_to(component)
        name = relative.as_posix()
        if path.is_symlink():
            raise ValueError(f"Unexpected symlink: {name}")
        if "__pycache__" in relative.parts or path.suffix in (".pyc", ".pyo"):
            continue
        if path.is_dir():
            if name not in ("core", "translations", "www", "www/locales", "brand"):
                raise ValueError(f"Unexpected directory: {name}")
            continue
        if name == "www/.gitkeep":
            continue
        if name not in FILES | BRAND_FILES:
            raise ValueError(f"Unexpected release file: {name}")
        paths[name] = path
    if missing := FILES - paths.keys():
        raise ValueError(f"Missing release files: {sorted(missing)}")
    manifest = json.loads(paths["manifest.json"].read_text(encoding="utf-8"))
    version = manifest.get("version", "")
    if manifest.get("domain") != "charge_tally" or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Invalid manifest domain/version")
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    if project["project"]["version"] != version:
        raise ValueError("Project and manifest version mismatch")
    if f'VERSION = "{version}"' not in paths["const.py"].read_text(encoding="utf-8"):
        raise ValueError("Shared constant version mismatch")
    expected_url = f'/charge_tally/charge-tally-card.js?v={version}'
    if f'CARD_URL = "{expected_url}"' not in paths["frontend.py"].read_text(encoding="utf-8"):
        raise ValueError("Frontend URL version mismatch")
    for name, path in paths.items():
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
        if path.suffix != ".js":
            continue
        source = path.read_text(encoding="utf-8")
        for specifier in re.findall(r"^import\s+(?:[^;\n]+?\s+from\s+)?['\"]([^'\"]+)['\"]", source, re.MULTILINE):
            module, separator, query = specifier.partition("?v=")
            if not module.startswith("./") or ".." in module.split("/"):
                raise ValueError(f"Unexpected module import: {specifier}")
            if not separator or query != version:
                raise ValueError(f"Module version mismatch: {specifier}")
            if (Path(name).parent / module).as_posix() not in paths:
                raise ValueError(f"Missing module: {specifier}")
    output = (output or root / "dist" / f"charge_tally-{version}.zip").resolve()
    if output.is_relative_to(component.resolve()):
        raise ValueError("Archive must be outside the component directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in sorted(paths.items()):
            info = ZipInfo("custom_components/charge_tally/" + name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, path.read_bytes(), compresslevel=9)
    with ZipFile(output) as archive:
        expected = {"custom_components/charge_tally/" + name for name in paths}
        if set(archive.namelist()) != expected or archive.testzip() is not None:
            raise ValueError("Archive content verification failed")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Destination ZIP (default: dist/charge_tally-VERSION.zip)")
    args = parser.parse_args()
    artifact = build(Path(__file__).resolve().parents[1], args.output)
    print(f"{artifact}\nSHA256 {sha256(artifact.read_bytes()).hexdigest()}")
