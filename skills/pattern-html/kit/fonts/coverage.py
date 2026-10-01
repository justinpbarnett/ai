#!/usr/bin/env python3
"""Write coverage.json: the characters each face in this folder can draw.

    coverage.py

Run it after rebuilding a font. It needs woff2_decompress and ttx (fontTools) on the PATH.
JetBrains Mono's entry is what all four of its files share, since a missing bold or italic
glyph falls back to another face just as a missing regular one does.
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FACES = {
    "Routed Gothic": ["routed-gothic"],
    "JetBrains Mono": ["jbm-Regular", "jbm-Bold", "jbm-Italic", "jbm-BoldItalic"],
}


def points(name, work):
    """The code points one font file maps to a glyph."""
    shutil.copy(HERE / f"{name}.woff2", work / f"{name}.woff2")
    subprocess.run(["woff2_decompress", str(work / f"{name}.woff2")], check=True)
    subprocess.run(["ttx", "-q", "-t", "cmap", "-o", str(work / f"{name}.ttx"), str(work / f"{name}.ttf")], check=True)
    dump = (work / f"{name}.ttx").read_text(encoding="utf-8")
    return {int(code, 16) for code in re.findall(r'<map code="0x([0-9a-fA-F]+)"', dump)}


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
