# Figures

A **figure** is an image in a 1 px frame with a credit line under it. **Pins** and **notes** turn it into an annotated reference: numbered squares on the things worth seeing, and one note for each in the same order. Section 07 of `kit/specimen.tmpl.html` holds the markup for every layout below.

## 1. Prepare the image

Put each image in `fig/` beside the template, no larger than the page can show: up to 1600 px on the longest side. A photograph goes in as JPEG at quality 84. A flat screenshot or a drawing goes in as PNG.

```
magick IN -resize '1600x1600>' -strip -quality 84 fig/NAME.jpg
```

Reference board 01 carries 14 photographs this way in 1.8 MB. The check warns when a built page passes 16 MB.

Open each image once with Read, so its alt text and its notes describe what is really in it.

**Done when** every image is in `fig/` at its final size and has been looked at.

## 2. Place it

```html
<figure>
  <div class="img">
    <img src="{{img:fig/NAME.jpg}}" alt="What the image shows, for a reader who cannot see it">
  </div>
  <figcaption>
    <p class="figno">Fig 01 · Subject · Photo: Source</p>
  </figcaption>
</figure>
```

Three layouts:

- **One figure** at full width, with its notes beneath. The default for an image that carries pins.
- **`.pair`** wraps two figures side by side for a comparison. They stack on a phone.
- **`.grid`** wraps many figures, as many columns as fit, each with its credit line and no notes.

**Done when** every image sits in a `figure` with alt text that says what it shows.

## 3. Pin it

A pin goes inside `.img`, after the `img`:

```html
<span class="pin" style="left:62.5%;top:22%">1</span>
```

`left` and `top` place the pin's centre as a share of the image: distance from the left edge over the width, distance from the top edge over the height. Put the centre on the thing itself, to half a percent. A pin placed this way stays on its target at every width.

Number the pins from 1 in every figure, in the order a reader would look. Keep two pins at least one pin apart: a pin is 26 px on a desktop and 22 px on a phone, where the image is about 360 px wide. When two things sit closer than that, pin one and name the other in its note.

A pin that misses in a slice moves by the share of the image it missed by.

**Done when**, in the slices at both widths, every pin sits on its target and no pin covers another.

## 4. Note it

One `<li>` in `ol.notes` for each pin, in pin order. The list numbers itself.

```html
<ol class="notes">
  <li><span class="tag take">Take</span><span><strong>Lead phrase.</strong> One or two sentences.</span></li>
</ol>
```

Each note opens with one tag, then an optional lead phrase in `strong`, then one or two sentences. The four tags of a reference board:

| Tag | Class | Look | Means |
|-----|-------|------|-------|
| TAKE | `tag take` | filled with ink | It goes into the work |
| HAVE | `tag` | ink frame | The language already holds it |
| SKIP | `tag skip` | muted | Left out, and the note says why |
| CALL | `tag call` | dashed frame | A decision that waits for Justin |

A page with another job may letter its own words in the same four looks. The tag column holds one word of up to five letters.

**Done when** every pin has one note, in the same order, and every note opens with a tag.

## 5. Credit it

`<p class="figno">` opens the `figcaption`: figure number, subject, credit, joined by ` · `. Figure numbers take two digits and run on through the whole page.

```
Fig 01 · Lid closed, from above · Photo: PanzerTool
Fig 08 · District 9 (2009) · MNU body armor · Prop and photo: Weta Workshop
Fig 11 · District 9 · Exosuit study in black · Concept art: Greg Broadmore, Weta Workshop
Fig 01 · Test card · Drawn for this page
```

Name who made the image, and who made the thing in it when that is someone else. An image made for the page says so.

Links to where the images and facts came from go in one `ul.sources` near the foot of the page, grouped under short capitals:

```html
<ul class="sources">
  <li><b>Group</b><a href="https://example.com/a">Name of the source</a> · <a href="https://example.com/b">Another</a></li>
</ul>
```

**Done when** every figure has a number, a subject, and a credit, and every source on the page is linked in the sources list.

## Someone else's images

A page that holds photographs or film images that belong to someone else is a private reference. Its footer says so: "Photographs and film images belong to their owners and are kept here for private reference."

The page stays a local file, shared on Justin's private network only (the workshop's `docs/infrastructure.md` says how). It never becomes an Artifact or a doc, and its `fig/` folder never enters a public repo.
