// Runs inside the page under test. check.py fills the two tables, evaluates this file in the page,
// and gets back a promise of the findings as JSON.
(function () {
  var TOKENS = /*TOKENS*/{};        // "#0B0C0E": "ground", and so on, read from style.css
  var COVERAGE = /*COVERAGE*/{};    // family: [[first, last], ...], the code points each face can draw
  var FACES = ["Routed Gothic", "JetBrains Mono"];
  var DESIGNATION = /^(MIL-STD|MIL-HDBK|MIL-DTL|MIL-PRF|MIL-P|USB-IF|ISO|IEC|ANSI|SAE|AMS-STD|IEEE|ASTM|UL|EN|DIN|JIS|NEMA)\b/;
  var QUIET = "pre, code, kbd, samp, .nb, svg, script, style, textarea";
  var SKIP = { SCRIPT: 1, STYLE: 1, TEMPLATE: 1, NOSCRIPT: 1, TITLE: 1, META: 1, LINK: 1, BASE: 1, BR: 1, WBR: 1 };
  var XHTML = "http://www.w3.org/1999/xhtml";
  var SLOT = /\{\{[^{}]+\}\}/;      // a slot another tool was meant to fill, still showing

  var out = { fail: [], warn: [], note: [], info: {} };
  function put(level, kind, msg) { out[level].push([kind, msg]); }

  function name(el) {
    var s = el.tagName.toLowerCase();
    var c = (el.getAttribute("class") || "").trim();
    if (el.id) s += "#" + el.id;
    if (c) s += "." + c.split(/\s+/).join(".");
    var t = (el.textContent || "").replace(/\s+/g, " ").trim();
    if (t) s += ' "' + t.slice(0, 36) + (t.length > 36 ? "..." : "") + '"';
    return s;
  }

  function rgba(v) {
    var m = /rgba?\(([^)]+)\)/.exec(v || "");
    if (!m) return null;
    var p = m[1].split(/[,\s\/]+/).filter(Boolean).map(parseFloat);
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  }
  function hex(c) {
    return "#" + c.slice(0, 3).map(function (n) { return ("0" + Math.round(n).toString(16)).slice(-2); }).join("").toUpperCase();
  }

  // a color in use: it must be a token, and yellow and the status colors keep to their own places
  function tint(el, prop, value) {
    var c = rgba(value);
    if (!c || c[3] === 0) return;
    var h = hex(c), t = c[3] === 1 ? TOKENS[h] : null;
    if (!t) return put("warn", "color", h + (c[3] < 1 ? " at " + c[3] : "") + " as " + prop + " on " + name(el));
    if (t === "act" && !el.closest(".ask, .act, .state.caution")) put("warn", "yellow", "as " + prop + " on " + name(el));
    if ((t === "ok" || t === "fault") && !el.closest(".state")) put("warn", "status", h + " as " + prop + " on " + name(el));
  }

  function family(cs) { return cs.fontFamily.split(",")[0].trim().replace(/^["']|["']$/g, ""); }
  function ownText(el) {
    var s = "";
    for (var n = el.firstChild; n; n = n.nextSibling) if (n.nodeType === 3) s += n.nodeValue;
    return s.trim() ? s : "";
  }
  function drawable(fam, cp) {
    var r = COVERAGE[fam] || [];
    for (var i = 0; i < r.length; i++) if (cp >= r[i][0] && cp <= r[i][1]) return true;
    return false;
  }
  // the browser capitalises before it looks for a glyph, so the check does too
  function glyphs(el, fam, cs, s) {
    if (cs.textTransform === "uppercase") s = s.toUpperCase();
    var miss = [];
    Array.from(s).forEach(function (ch) {
      var cp = ch.codePointAt(0);
      if (cp <= 32 || cp === 0xAD || (cp >= 0x200B && cp <= 0x200D) || cp === 0xFEFF) return;
      var label = ch + " U+" + ("000" + cp.toString(16).toUpperCase()).slice(-4);
      if (!drawable(fam, cp) && miss.indexOf(label) < 0) miss.push(label);
    });
    if (miss.length) put("warn", "glyph", fam + " cannot draw " + miss.join(", ") + " in " + name(el));
  }
  function lettering(el, cs, s) {
    var fam = family(cs);
    if (FACES.indexOf(fam) < 0) put("fail", "font", fam + " on " + name(el));
    else if (s) glyphs(el, fam, cs, s);
  }

  function clipped(el) {
    for (var p = el.parentElement; p && p !== document.documentElement; p = p.parentElement) {
      var o = getComputedStyle(p).overflowX;
      if (o === "auto" || o === "scroll" || o === "hidden" || o === "clip") return true;
    }
    return false;
  }

  function run() {
    var root = document.documentElement, W = window.innerWidth;
    out.info = { width: W, wide: root.scrollWidth, height: root.scrollHeight };
    var all = Array.prototype.slice.call(document.body.querySelectorAll("*")).filter(function (el) {
      return el.namespaceURI === XHTML && !SKIP[el.tagName] && el.getClientRects().length;
    });

    if (root.scrollWidth > W + 1) {
      var over = all.filter(function (el) { return el.getBoundingClientRect().right > W + 1 && !clipped(el); }).slice(0, 300);
      var cause = over.filter(function (el) { return !over.some(function (o) { return o !== el && el.contains(o); }); });
      put("fail", "sideways", "the page is " + root.scrollWidth + " wide in a " + W + " window: " +
        (cause.slice(0, 4).map(name).join(" | ") || "nothing in the flow, look for a positioned part"));
    }

    all.forEach(function (el) {
      var cs = getComputedStyle(el);
      if (["borderTopLeftRadius", "borderTopRightRadius", "borderBottomRightRadius", "borderBottomLeftRadius"]
        .some(function (k) { return parseFloat(cs[k]) > 0; })) put("fail", "radius", "rounded corner on " + name(el));
      if (cs.boxShadow !== "none") put("fail", "shadow", "box shadow on " + name(el));
      if (cs.textShadow !== "none") put("fail", "shadow", "text shadow on " + name(el));
      if (/gradient\(/.test(cs.backgroundImage)) put("fail", "gradient", "gradient on " + name(el));

      tint(el, "background", cs.backgroundColor);
      ["Top", "Right", "Bottom", "Left"].forEach(function (side) {
        if (parseFloat(cs["border" + side + "Width"]) > 0 && cs["border" + side + "Style"] !== "none")
          tint(el, "border", cs["border" + side + "Color"]);
      });
      var s = ownText(el), control = el.matches("input, select, textarea");
      if (s || control) { tint(el, "text", cs.color); lettering(el, cs, s); }
    });

    Array.prototype.forEach.call(document.querySelectorAll("svg text, svg tspan"), function (el) {
      var s = ownText(el);
      if (s) lettering(el, getComputedStyle(el), s);
    });

    // dashes between words
    var walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT), node, words = [];
    while ((node = walk.nextNode())) {
      var host = node.parentElement;
      if (!host || host.closest(QUIET)) continue;
      var t = node.nodeValue.replace(/https?:\/\/\S+/g, "");
      var at = ' in "' + t.replace(/\s+/g, " ").trim().slice(0, 60) + '"';
      if (SLOT.test(t)) put("warn", "slot", "double braces left" + at + ": a slot that was never filled");
      if (/[–—]/.test(t)) put("warn", "dash", "an en or em dash" + at);
      if (/\s-{1,2}\s/.test(t)) put("warn", "dash", "a hyphen used as a dash" + at);
      (t.match(/[A-Za-z]+(?:-[A-Za-z]+)+/g) || []).forEach(function (w) {
        if (!DESIGNATION.test(w) && words.indexOf(w) < 0) words.push(w);
      });
    }
    if (words.length) put("note", "hyphen", "hyphenated words, each either a true compound or to be reworded: " + words.slice(0, 30).join(", "));

    var acts = document.querySelectorAll(".ask, .act").length;
    if (acts > 1) put("fail", "act", acts + " Act lines on the page: it takes one, on the one thing to do");
    Array.prototype.forEach.call(document.querySelectorAll(".state"), function (el) {
      var word = el.classList.contains("ok") ? "OK" : el.classList.contains("caution") ? "CAUTION" : el.classList.contains("fault") ? "FAULT" : "";
      var shown = el.textContent.trim().toUpperCase();
      if (!word) put("fail", "state", "a state that is not ok, caution, or fault: " + name(el));
      else if (shown !== word) put("fail", "state", "a " + word + ' state shows "' + shown + '": it shows its word, and the detail goes beside it');
    });

    Array.prototype.forEach.call(document.images, function (im) {
      var src = (im.getAttribute("src") || "").slice(0, 60);
      if (!(im.complete && im.naturalWidth > 0)) put("fail", "image", "did not load: " + src);
      if (!im.hasAttribute("alt")) put("warn", "alt", "an image with no alt text: " + src);
      else if (SLOT.test(im.alt)) put("warn", "slot", "double braces left in the alt text of " + src);
    });

    // a file carries everything inside itself; a page that an app serves may take what its own app serves
    var served = /^https?:$/.test(location.protocol), outside = [];
    function own(u) {
      try { return served && new URL(u, document.baseURI).origin === location.origin; } catch (e) { return false; }
    }
    Array.prototype.forEach.call(document.querySelectorAll("[src], link[href]"), function (el) {
      var u = el.getAttribute("src") || el.getAttribute("href") || "";
      if (u && !/^(data:|#)/i.test(u)) outside.push(u);
    });
    performance.getEntriesByType("resource").forEach(function (e) { if (!/^data:/i.test(e.name)) outside.push(e.name); });
    outside.filter(function (u, i) { return outside.indexOf(u) === i && !own(u); }).forEach(function (u) {
      put("warn", "outside", "the page reaches " + (served ? "another site" : "outside its own file") + " for " + u.slice(0, 90));
    });

    if (!document.title.trim()) put("warn", "title", "the page has no title");
    else if (SLOT.test(document.title)) put("warn", "slot", "double braces left in the title: a slot that was never filled");
    ["header", "footer"].forEach(function (tag) {
      var n = document.querySelectorAll(tag).length;
      if (n > 1) put("warn", "once", n + " " + tag + " elements: the stylesheet draws " + tag + " as the page's own, so use it once");
    });

    var faces = [];
    document.fonts.forEach(function (f) { faces.push(f); });
    faces.forEach(function (f) {
      if (f.status === "error") put("fail", "face", f.family + " " + f.weight + " " + f.style + " failed to load");
    });
    if (!faces.some(function (f) { return f.family.replace(/["']/g, "") === "Routed Gothic" && f.status === "loaded"; }))
      put("fail", "face", "Routed Gothic is not in use: titles and marks are set in it, so the stylesheet or its fonts are missing");
    return out;
  }

  var ready = document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve();
  return ready.then(function () { return JSON.stringify(run()); });
})();
