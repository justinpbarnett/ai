#!/usr/bin/env python3
# Run after rebuilding a font; needs woff2_decompress and ttx (fontTools) on the PATH.
# JetBrains Mono's entry is what all four of its files share: a glyph missing from any weight falls back.
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

SUBTABLE = re.compile(r'<cmap_format_(\d+) platformID="(\d+)" platEncID="(\d+)"[^>]*>(.*?)</cmap_format_\1>', re.S)
UNICODE_WINDOWS_ENCODINGS = ("1", "10")
HERE = Path(__file__).resolve().parent
FACES = {
    "Routed Gothic": ["routed-gothic"],
    "JetBrains Mono": ["jbm-Regular", "jbm-Bold", "jbm-Italic", "jbm-BoldItalic"],
}


def points(name, work):
    shutil.copy(HERE / f"{name}.woff2", work / f"{name}.woff2")
    subprocess.run(["woff2_decompress", str(work / f"{name}.woff2")], check=True)
    subprocess.run(["ttx", "-q", "-t", "cmap", "-o", str(work / f"{name}.ttx"), str(work / f"{name}.ttf")], check=True)
    dump = (work / f"{name}.ttx").read_text(encoding="utf-8")
    return {
        int(code, 16)
        for _, platform, encoding, body in SUBTABLE.findall(dump)
        if platform == "0" or (platform == "3" and encoding in UNICODE_WINDOWS_ENCODINGS)
        for code in re.findall(r'<map code="0x([0-9a-fA-F]+)"', body)
    }


def ranges(codes):
    out = []
    for code in sorted(codes):
        if out and code == out[-1][1] + 1:
            out[-1][1] = code
        else:
            out.append([code, code])
    return out


def main():
    work = Path(tempfile.mkdtemp(prefix="coverage-"))
    try:
        lines = []
        for face, files in FACES.items():
            shared = set.intersection(*(points(name, work) for name in files))
            spans = ", ".join(f"[{a}, {b}]" for a, b in ranges(shared))
            lines.append(f'  "{face}": [{spans}]')
            print(f"{face}: {len(shared)} characters")
        (HERE / "coverage.json").write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
