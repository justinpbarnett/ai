import math

from tokens import KIT, tokens

FONT_FILES = sorted((KIT / "fonts").glob("*.woff2"))


def linear(channel):
    share = channel / 255
    return share / 12.92 if share <= 0.03928 else ((share + 0.055) / 1.055) ** 2.4


def luminance(color):
    red, green, blue = (linear(int(color[i:i + 2], 16)) for i in (1, 3, 5))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(name):
    page = tokens()
    lighter, darker = sorted((luminance(page[name]), luminance(page["ground"])), reverse=True)
    ratio = f"{(lighter + 0.05) / (darker + 0.05):.2f}".rstrip("0")
    return ratio + "0" if ratio.endswith(".") else ratio


def font_bytes(name):
    return f"{(KIT / 'fonts' / name).stat().st_size:,}"


def fonts_bytes():
    return f"{sum(path.stat().st_size for path in FONT_FILES):,}"


def fonts_as_text_kb():
    return str(round(sum(4 * math.ceil(path.stat().st_size / 3) for path in FONT_FILES) / 1000))
