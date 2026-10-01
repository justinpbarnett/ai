# Fonts

Five files, two faces. `style.css` embeds all five, so a built page needs nothing else.

| File | Face | Job |
|------|------|-----|
| `routed-gothic.woff2` | Routed Gothic Regular | Marks and titles, always in capitals |
| `jbm-Regular.woff2` | JetBrains Mono Regular | Anything read at length or updated live |
| `jbm-Bold.woff2` | JetBrains Mono Bold | `strong` |
| `jbm-Italic.woff2` | JetBrains Mono Italic | `em` |
| `jbm-BoldItalic.woff2` | JetBrains Mono Bold Italic | `em` inside `strong` |

`coverage.json` lists the characters each face holds. `check.py` reads it to warn about a character with no glyph, which a browser would draw in some other face.

## Routed Gothic

By Darren Embry, copyright 2017, under the SIL Open Font License 1.1 with the Reserved Font Name Routed Gothic. License text: `OFL-RoutedGothic.md`.

Source: https://github.com/dse/routed-gothic, the file `dist/ttf/routed-gothic.ttf`.

The file here is that whole font, unchanged, in the WOFF2 container:

```sh
woff2_compress routed-gothic.ttf
```

Keep it that way. The license reserves the name, so a subset or an altered copy would have to ship under another name.

It holds 522 characters. It has the middle dot, × − + ± °, the four arrows, ′ ″, µ, Ø, ⌀, §, #, and curly quotes. It has no ellipsis, no Greek (so no Ω), and no ≤ ≥ ≈ ✓ ■. Spell those out in a title or a drawing label, or keep them in reading text.

## JetBrains Mono

Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono), under the SIL Open Font License 1.1 with no reserved name. License text: `OFL-JetBrainsMono.txt`.

Source: the Nerd Fonts build of version 2.304 (Nerd Fonts 3.5.1), the files `JetBrainsMonoNerdFont-{Regular,Bold,Italic,BoldItalic}.ttf`.

Each file is a subset of 628 characters: Latin with its accented letters, Greek, punctuation, arrows, math signs, key symbols, and box drawing. No Nerd Fonts icon falls in the range.

```
U+0020-007E,U+00A0-00FF,U+0100-0131,U+0134-017F,U+0391-03A1,U+03A3-03A9,U+03B1-03C9,
U+2010,U+2013,U+2014,U+2018-201F,U+2020-2022,U+2026,U+2030,U+2032,U+2033,U+2039,U+203A,
U+2044,U+2070,U+2074-2079,U+2080-2089,U+20AC,U+2116,U+2122,U+2190-2199,U+21A9,U+21AA,
U+21D0-21D4,U+21E7,U+2202,U+2206,U+220F,U+2211,U+2212,U+2215,U+2219,U+221A,U+221E,
U+2227-222B,U+2248,U+2260,U+2261,U+2264,U+2265,U+2303,U+2318,U+2325,U+232B,U+23CE,
U+2500-257F,U+2580-259F,U+25A0,U+25A1,U+25AA,U+25AB,U+25B2,U+25B3,U+25B6,U+25B7,
U+25BC,U+25BD,U+25C0,U+25C1,U+25C6,U+25C7,U+25CB,U+25CF,U+25E6,U+2713,U+2717
```

Layout features are dropped, so `->` and `!=` stay two characters and never join into one sign. That also means `font-variant-numeric` does nothing here; the digits are already one width.

To rebuild a file (for `w` in Regular, Bold, Italic, BoldItalic, with the range above on one line in `$RANGE`):

```sh
pyftsubset "JetBrainsMonoNerdFont-$w.ttf" --unicodes="$RANGE" --layout-features='' --output-file="jbm-$w.ttf"
woff2_compress "jbm-$w.ttf"
```

After adding a character to the range, rebuild all four, then run `python3 coverage.py` in this folder. It rewrites `coverage.json`, the list `check.py` reads to warn when a page uses a character a face cannot draw.
