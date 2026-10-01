# Controls

A page to use starts from `kit/tool.tmpl.html`: a working contrast check whose markup and script are the pattern for the next tool. Section 10 of `kit/specimen.tmpl.html` shows every control once.

## The states of a control

| State | Look | Set by |
|-------|------|--------|
| At rest | ink letters in an ink frame, like a tag | nothing |
| Under the pointer, or pressed | filled with ink | `aria-pressed="true"`, or `aria-current` on `a.btn` |
| Disabled | muted letters in a muted frame | `disabled`, or `aria-disabled="true"` on `a.btn` |
| Focused | a 2 px ink outline, 2 px out | the keyboard |

A text field rests in a muted frame, and the frame turns ink when the field has focus.

## Parts

- **Buttons.** `button`, `a.btn`, and the input button types share one look. Group them in `.actions`.
- **The primary action** carries `.act`: the page's one yellow line, along the button's top edge. A page with an `.act` button has no `.ask`. The check fails a page that carries more than one of the two.
- **One of several.** `.seg` joins buttons edge to edge. Give it `role="group"` and an `aria-label`, and give each button `aria-pressed`.
- **Fields.** `.field` puts a label over its control. `.fields` lays fields out in as many columns as fit. A `select`, a `textarea`, and a file input take the look without a class.
- **Choices.** `label.check` wraps a checkbox or a radio button with its words. `fieldset` with a `legend` groups them. A radio button draws as a square turned on its corner, so it is never taken for a checkbox.
- **A result.** `.readout` holds the figure, with its unit in `small` and `aria-live="polite"` so a screen reader hears a change. A `.state` beside it shows only its word, and the sentence after it says what the word means here.
- **Data.** A table sits inside `.wide`, with `caption` for its name and `.num` on the cells and heads that hold figures.

## Behaviour

The tool page does each of these, and the next tool does them the same way.

- **Open on a real result.** The page runs its check once as it loads, on defaults that mean something.
- **Go stale honestly.** When an input changes, the result on show is no longer about what the fields say. Add `.stale` to the `.readout`, hide the `.state`, and say that the inputs changed. The next run clears all three.
- **Answer a bad input.** Show FAULT, and a sentence that says what to write instead, with an example.
- **Show and hide with the `hidden` attribute.** The stylesheet makes it hold against any display rule.
- **Handle `submit` in script** with `preventDefault()`. A form on a page like this has nowhere to send itself.
- **Read colors from the page.** `getComputedStyle(document.documentElement).getPropertyValue("--ink")` gives a token's value at run time, so script and stylesheet cannot drift apart.

Script goes inline at the foot of the template, or in a file named by `{{js:PATH}}`. The page's own rules go in a second `<style>`, few and built from the tokens. A color outside the tokens draws a `color` WARN.

## An app that serves its own CSS

```
python3 KIT/build.py --css OUT.css
```

That writes the stylesheet with its fonts inside. The app serves it as its first stylesheet and puts its own rules after it, built from the tokens. Each page keeps the kit's frame: a viewport `meta`, one `<div class="wrap">` around everything, and the kit's parts inside.

Check the running page by its address:

```
python3 KIT/check.py http://localhost:PORT/PAGE --shots DIR
```

Files the app serves itself pass. Anything fetched from another site draws an `outside` WARN.

## Exercise it

A tool is checked by using it. Drive every control from a short script, through the browser the check uses:

```python
import shutil, sys, tempfile
from pathlib import Path
sys.dont_write_bytecode = True          # keep the kit folder clean
sys.path.insert(0, "KIT")
import check

page, shots = Path("NAME.html").resolve(), Path("DIR")
shots.mkdir(parents=True, exist_ok=True)
work = Path(tempfile.mkdtemp())         # the browser's own scratch folder
b = check.Browser(check.find_browser(), work)
try:
    b.open(page.as_uri(), 1280, 900, False)
    # do one thing, wait a moment, then read back what the page shows
    print(b.ask("""(function () {
      var f = document.getElementById("fg");
      f.value = "zzz";
      f.dispatchEvent(new Event("input", { bubbles: true }));
      document.getElementById("pair").requestSubmit();
      return new Promise(function (done) {
        setTimeout(function () { done(JSON.stringify(document.getElementById("verdict").textContent)); }, 30);
      });
    })()"""))
    b.shoot(shots / "after.png", 0, 1280, 900)
finally:
    b.stop()
    shutil.rmtree(work, ignore_errors=True)
```

`b.ask()` takes script that returns a JSON string, or a promise of one. `b.shoot()` photographs the page as it stands, measured from the page's own top, so a state that only appears after a click can be read as a slice. `b.view(PATH)` photographs the window instead, which is how to see an open `dialog` or any part that floats over the page.

**Done when** every control has been driven once with a normal input and once with a bad one, each result has been read back, and the check prints PASS.
