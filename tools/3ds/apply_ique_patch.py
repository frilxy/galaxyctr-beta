#!/usr/bin/env python3
"""Applies a Chinese localization pack to already converted Japanese game files.

The pack is a Riivolution overlay for the Japanese disc (RMGJ01) that replaces the message
archive, the fonts and the layouts the game draws its text with. GalaxyCTR reads a converted
SD tree, so this converts the pack's archives for the 3DS, writes them over a copy of that
tree, and rebuilds the file cache (sdmc:/smg/cache).

    python3 tools/3ds/apply_ique_patch.py --patch SMG-CNzh11_5.zip \
        --base /path/to/smg --out /path/to/smg-cn

The pack must hold <root>/iQue/files/... or <root>/Digital Hearts/files/...; the Digital
Hearts tree is used when both are present, because it carries the corrected text, and --tree
picks one by hand.

Only archives the converter can rewrite as RARC are applied. The Wii HOME Menu resources
(HomeButton.arc, WiiRemoteStrapReplace.arc) are U8 archives, which the port does not read,
and are skipped.

Nothing is downloaded: the pack and the converted tree both come from the user's own copy.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile

TOOLS = Path(__file__).resolve().parent
sys.path[:0] = [str(TOOLS / "builder"), str(TOOLS)]

from build_files import Converter
from convert_smg_files import PACK_MAGIC, PACK_UNPACKED, build_file_pack

# Packs in the wild; the first that is present wins.
TREES = ("Digital Hearts", "iQue")


def choose_tree(available, tree):
    if tree is not None:
        if tree not in available:
            raise ValueError(f"The pack has no {tree} tree (it has: {', '.join(available) or 'none'})")
        return tree
    if not available:
        raise ValueError(f"The pack has no {TREES[0]} or {TREES[1]} tree")
    return available[0]


def overlay_files(patch, tree=None):
    """The overlay's archives, as {path under files/: bytes}."""
    if patch.is_file():
        with ZipFile(patch) as archive:
            names = archive.namelist()
            available = [name for name in TREES if any(f"{name}/files/" in n for n in names)]
            chosen = choose_tree(available, tree)
            marker = f"{chosen}/files/"
            files = {}
            for name in names:
                if name.endswith(".arc") and marker in name:
                    files[name.split(marker, 1)[1]] = archive.read(name)
            return chosen, files

    available = [name for name in TREES if (patch / name / "files").is_dir()]
    chosen = choose_tree(available, tree)
    root = patch / chosen / "files"
    return chosen, {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*.arc"))}


def convert_overlay(files):
    """Converted archives, as {path: (bytes, sha256 of the pack's own file)} plus skipped names."""
    overlay, skipped = {}, []
    for name, original in files.items():
        converted = Converter().convert(name, original)
        if converted[:4] != b"CRAR":
            skipped.append(name)
            continue
        overlay[name] = (converted, hashlib.sha256(original).hexdigest())
    if not overlay:
        raise ValueError("The pack has no archive the converter can rewrite")
    return overlay, skipped


def verify_cache(work, overlay):
    """Reads every applied archive back out of the rebuilt cache, from the pack or the card."""
    prefix = "sdmc:/smg/files/"
    remaining = {prefix + name: data for name, (data, _) in overlay.items()}
    cache = work / "cache"
    with (cache / "index.bin").open("rb") as index, (cache / "pack.bin").open("rb") as pack:
        if index.read(len(PACK_MAGIC)) != PACK_MAGIC:
            raise ValueError("Unexpected file cache format")
        while header := index.read(12):
            if len(header) != 12:
                raise ValueError("Truncated file cache index")
            offset, size, name_size = struct.unpack("<III", header)
            name_bytes = index.read(name_size)
            if len(name_bytes) != name_size:
                raise ValueError("Truncated file cache path")
            name = name_bytes.decode("utf-8")
            expected = remaining.pop(name, None)
            if expected is None:
                continue
            if offset == PACK_UNPACKED:
                actual = (work / "files" / name[len(prefix):]).read_bytes()
            else:
                pack.seek(offset)
                actual = pack.read(size)
            if size != len(expected) or actual != expected:
                raise ValueError(f"Cached bytes do not match the converted archive: {name}")
    if remaining:
        raise ValueError(f"Archives missing from the file cache: {', '.join(sorted(remaining))}")


def build(patch, base, out, tree=None):
    """Writes a copy of the converted tree at `base` with the pack applied, at `out`."""
    version = base / "port/GameVersion.txt"
    if not version.is_file() or version.read_bytes() != b"RMGJ01":
        raise ValueError("The converted tree must be the Japanese version (port/GameVersion.txt says RMGJ01)")
    if out.exists() or out.is_symlink():
        raise FileExistsError(f"Output already exists: {out}")
    out = out.resolve()
    if out.is_relative_to(base.resolve()):
        raise ValueError("Choose an output outside the source tree")

    chosen, files = overlay_files(patch, tree)
    overlay, skipped = convert_overlay(files)
    out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".galaxyctr-localization-", dir=out.parent) as temporary:
        work = Path(temporary) / "smg"
        work.mkdir()
        for name in ("files", "native", "port"):
            shutil.copytree(base / name, work / name)
        # The cache is rebuilt below, so only the converter version marker is carried over.
        if (base / "files_version.txt").is_file():
            shutil.copy2(base / "files_version.txt", work / "files_version.txt")

        changes = []
        for name, (data, source_hash) in overlay.items():
            destination = work / "files" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            changes.append(
                {
                    "file": name,
                    "input_sha256": source_hash,
                    "output_sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        build_file_pack(work / "files", work / "native")
        verify_cache(work, overlay)
        (work / "localization-manifest.json").write_text(
            json.dumps(
                {"game_id": "RMGJ01", "pack_tree": chosen, "files": changes},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if out.exists() or out.is_symlink():
            raise FileExistsError(f"Output already exists: {out}")
        work.rename(out)
    return chosen, changes, skipped, out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--patch", type=Path, required=True, help="the pack: a ZIP or its extracted folder")
    parser.add_argument("--base", type=Path, required=True, help="a converted Japanese smg folder")
    parser.add_argument("--out", type=Path, required=True, help="where to write the localized smg folder")
    parser.add_argument("--tree", choices=TREES, help="which tree of the pack to apply (default: the best present)")
    args = parser.parse_args()
    try:
        chosen, changes, skipped, out = build(args.patch, args.base, args.out, args.tree)
    except (BadZipFile, OSError, ValueError, KeyError) as error:
        parser.exit(1, f"{error}\n")
    print(f"{chosen}: {len(changes)} archives applied, {len(skipped)} skipped (not RARC)")
    for name in skipped:
        print(f"  skipped {name}")
    print(out)


if __name__ == "__main__":
    main()
