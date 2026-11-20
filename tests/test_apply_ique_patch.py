import contextlib
import io
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools" / "3ds" / "builder"), str(ROOT / "tools" / "3ds")]

import apply_ique_patch


def empty_rarc():
    """A RARC with one folder and no files: enough to exercise the archive converter."""
    header_size, dir_offset, string_offset, data_offset = 0x20, 0x20, 0x30, 0x50
    size = header_size + data_offset
    out = bytearray(size)
    out[0:4] = b"RARC"
    struct.pack_into(">IIIIII", out, 0x04, size, header_size, data_offset, 0, 0, 0)
    struct.pack_into(">IIIIIIHHI", out, header_size, 1, dir_offset, 0, 0, 0x20, string_offset, 0, 0, 0)
    struct.pack_into(">IIHHI", out, header_size + dir_offset, 0, 0, 0, 0, 0)
    out[header_size + string_offset : header_size + string_offset + 5] = b"root\0"
    return bytes(out)


def make_base(root):
    base = root / "base"
    for name in ("files", "native", "port"):
        (base / name).mkdir(parents=True)
    (base / "port/GameVersion.txt").write_bytes(b"RMGJ01")
    (base / "files_version.txt").write_bytes(b"10")
    return base


def make_pack(path, entries):
    """A ZIP with overlays/<tree>/files/... for every (tree, name, bytes) entry."""
    with zipfile.ZipFile(path, "w") as archive:
        for tree, name, data in entries:
            archive.writestr(f"overlays/{tree}/files/{name}", data)


class ApplyIquePatchTests(unittest.TestCase):
    def test_converts_rarc_and_skips_archives_the_port_does_not_read(self):
        files = {
            "LayoutData/Font.arc": empty_rarc(),
            "JpJapanese/LayoutData/HomeButton.arc": b"U8\x00\x00\x00\x00\x00\x00",
        }
        overlay, skipped = apply_ique_patch.convert_overlay(files)
        self.assertEqual(list(overlay), ["LayoutData/Font.arc"])
        self.assertTrue(overlay["LayoutData/Font.arc"][0].startswith(b"CRAR"))
        self.assertEqual(skipped, ["JpJapanese/LayoutData/HomeButton.arc"])

    def test_only_the_ique_tree_is_applied(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pack = root / "pack.zip"
            make_pack(
                pack,
                [
                    ("iQue", "LayoutData/TitleLogo.arc", empty_rarc()),
                    ("Digital Hearts", "LayoutData/TitleLogo.arc", empty_rarc() + b"\0" * 32),
                ],
            )
            files = apply_ique_patch.overlay_files(pack)
            self.assertEqual(list(files), ["LayoutData/TitleLogo.arc"])
            self.assertEqual(files["LayoutData/TitleLogo.arc"], empty_rarc())

    def test_a_pack_without_the_ique_tree_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack.zip"
            make_pack(pack, [("Digital Hearts", "LayoutData/TitleLogo.arc", empty_rarc())])
            with self.assertRaises(ValueError):
                apply_ique_patch.overlay_files(pack)

    def test_build_writes_the_overlay_rebuilds_the_cache_and_keeps_the_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = make_base(root)
            pack = root / "pack.zip"
            names = ["LayoutData/Font.arc", "LayoutData/TitleLogo.arc", "JpJapanese/MessageData/Message.arc"]
            make_pack(pack, [("iQue", name, empty_rarc()) for name in names])
            out = root / "out/smg"

            with contextlib.redirect_stdout(io.StringIO()):
                changes, skipped, written = apply_ique_patch.build(pack, base, out)
            self.assertEqual(sorted(change["file"] for change in changes), sorted(names))
            self.assertEqual(written, out.resolve())
            self.assertEqual(sorted(path.name for path in (out / "files/LayoutData").iterdir()),
                             ["Font.arc", "TitleLogo.arc"])
            self.assertTrue((out / "cache/pack.bin").is_file())
            self.assertTrue((out / "cache/index.bin").is_file())
            self.assertTrue((out / "files_version.txt").is_file())
            self.assertEqual([p.name for p in base.iterdir() if p.name == "cache"], [])

            manifest = (out / "localization-manifest.json").read_text(encoding="utf-8")
            self.assertIn('"pack_tree": "iQue"', manifest)
            for name in names:
                self.assertIn(name, manifest)

            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(FileExistsError):
                    apply_ique_patch.build(pack, base, out)

    def test_build_refuses_a_tree_that_is_not_japanese(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = make_base(root)
            (base / "port/GameVersion.txt").write_bytes(b"RMGE01")
            pack = root / "pack.zip"
            make_pack(pack, [("iQue", "LayoutData/Font.arc", empty_rarc())])
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(ValueError):
                    apply_ique_patch.build(pack, base, root / "out/smg")


if __name__ == "__main__":
    unittest.main()
