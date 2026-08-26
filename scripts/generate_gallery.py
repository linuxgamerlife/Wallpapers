#!/usr/bin/env python3
"""Generate optimized wallpaper thumbnails and the README gallery."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
WALLPAPERS = ROOT / "ultrawide"
THUMBNAILS = ROOT / "thumbnails" / "ultrawide"
MANIFEST = ROOT / ".gallery-manifest.json"
START_MARKER = "<!-- gallery:start -->"
END_MARKER = "<!-- gallery:end -->"
IMAGE_PATTERN = re.compile(r"^(\d{4})\.(jpe?g|png|webp)$", re.IGNORECASE)
THUMBNAIL_WIDTH = 480
THUMBNAIL_QUALITY = 82
GENERATOR_VERSION = 1


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wallpapers() -> list[Path]:
    matches = [path for path in WALLPAPERS.iterdir() if path.is_file() and IMAGE_PATTERN.fullmatch(path.name)]
    stems = [path.stem for path in matches]
    if len(stems) != len(set(stems)):
        raise RuntimeError("Multiple wallpaper files use the same numeric identifier")
    return sorted(matches, key=lambda path: int(path.stem), reverse=True)


def load_manifest() -> dict:
    if not MANIFEST.exists():
        return {}
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def create_thumbnail(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp.webp")
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        height = max(1, round(image.height * THUMBNAIL_WIDTH / image.width))
        image = image.resize((THUMBNAIL_WIDTH, height), Image.Resampling.LANCZOS)
        image.save(
            temporary,
            format="WEBP",
            quality=THUMBNAIL_QUALITY,
            method=6,
            optimize=True,
        )
    temporary.replace(destination)


def gallery_block(images: list[Path]) -> str:
    entries = []
    for source in images:
        number = source.stem
        entries.append(
            f'<a href="./ultrawide/{source.name}"><img src="./thumbnails/ultrawide/{number}.webp" '
            f'width="240" alt="Wallpaper {number}" title="Wallpaper {number}" /></a>'
        )
    grid = "\n".join(entries)
    return (
        f"{START_MARKER}\n"
        "## Ultrawide Gallery\n\n"
        f"Browse all **{len(images)} wallpapers**, newest first. Select a thumbnail to open the full-resolution image.\n\n"
        '<p align="center">\n'
        f"{grid}\n"
        "</p>\n\n"
        "_This gallery is generated automatically when numbered wallpapers are added, changed, or removed._\n"
        f"{END_MARKER}"
    )


def updated_readme(block: str) -> str:
    current = README.read_text(encoding="utf-8")
    has_start = START_MARKER in current
    has_end = END_MARKER in current
    if has_start != has_end:
        raise RuntimeError("README contains only one gallery marker")
    if has_start:
        before, remainder = current.split(START_MARKER, 1)
        _, after = remainder.split(END_MARKER, 1)
        return f"{before}{block}{after}"
    insertion = "## Artwork"
    if insertion not in current:
        raise RuntimeError("Could not find the README Artwork section")
    return current.replace(insertion, f"{block}\n\n---\n\n{insertion}", 1)


def expected_manifest(images: list[Path], previous: dict, generate: bool) -> dict:
    old_images = previous.get("images", {}) if previous.get("version") == GENERATOR_VERSION else {}
    records: dict[str, dict[str, str]] = {}
    for source in images:
        source_hash = sha256(source)
        thumbnail = THUMBNAILS / f"{source.stem}.webp"
        old = old_images.get(source.name, {})
        valid = (
            old.get("source_sha256") == source_hash
            and thumbnail.exists()
            and old.get("thumbnail_sha256") == sha256(thumbnail)
        )
        if generate and not valid:
            create_thumbnail(source, thumbnail)
        thumbnail_hash = sha256(thumbnail) if thumbnail.exists() else ""
        records[source.name] = {
            "source_sha256": source_hash,
            "thumbnail": thumbnail.relative_to(ROOT).as_posix(),
            "thumbnail_sha256": thumbnail_hash,
        }
    return {
        "version": GENERATOR_VERSION,
        "thumbnail_width": THUMBNAIL_WIDTH,
        "thumbnail_quality": THUMBNAIL_QUALITY,
        "images": records,
    }


def serialized_manifest(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def stale_thumbnails(images: list[Path]) -> list[Path]:
    expected = {f"{source.stem}.webp" for source in images}
    if not THUMBNAILS.exists():
        return []
    return sorted(path for path in THUMBNAILS.glob("*.webp") if path.name not in expected)


def check(images: list[Path]) -> int:
    previous = load_manifest()
    expected = expected_manifest(images, previous, generate=False)
    expected_readme = updated_readme(gallery_block(images))
    problems = []
    if serialized_manifest(expected) != (MANIFEST.read_text(encoding="utf-8") if MANIFEST.exists() else ""):
        problems.append("manifest is stale")
    if expected_readme != README.read_text(encoding="utf-8"):
        problems.append("README gallery is stale")
    missing = [record["thumbnail"] for record in expected["images"].values() if not record["thumbnail_sha256"]]
    if missing:
        problems.append(f"{len(missing)} thumbnails are missing")
    stale = stale_thumbnails(images)
    if stale:
        problems.append(f"{len(stale)} stale thumbnails remain")
    if problems:
        for problem in problems:
            print(f"gallery check failed: {problem}", file=sys.stderr)
        return 1
    print(f"Gallery is current for {len(images)} wallpapers.")
    return 0


def generate(images: list[Path]) -> int:
    previous = load_manifest()
    manifest = expected_manifest(images, previous, generate=True)
    for thumbnail in stale_thumbnails(images):
        thumbnail.unlink()
    MANIFEST.write_text(serialized_manifest(manifest), encoding="utf-8")
    README.write_text(updated_readme(gallery_block(images)), encoding="utf-8")
    print(f"Generated gallery for {len(images)} wallpapers.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail without changing files if the gallery is stale")
    args = parser.parse_args()
    images = wallpapers()
    if not images:
        raise RuntimeError("No four-digit numbered wallpapers found in ultrawide/")
    return check(images) if args.check else generate(images)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as error:
        print(f"gallery generation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
