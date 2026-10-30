// The Leyline spinner on every loading state (spin.css). Every status line in the launcher says what it is doing with
// a text ending in "…" ("Loading the Workshop…", "Starting…", "Checking…", "Downloading … in the background…"), from
// app.js, host.js, modes.js, social.js and themes.js alike. This watches those lines and puts the spinning mark in
// front of the words while they end in "…", and takes it out when they don't. No line's code has to know about it:
// setting textContent drops the spinner and this puts it back.
//
//   LySpin.el(size)   a new spinner element (size in px, optional)
//   LySpin.mark(node) mark one element now (the observer does this by itself for WATCH)
(function () {
  "use strict";
  // the busy lines: the say() status lines, the host pack's hint lines, the Modes count, the title bar and server pills
  const WATCH = ".status, .hint, #md-net, #tb-status-text, #srv-state-text, #host-state-text, .meta > span";

  function el(size) {
    const s = document.createElement("span");
    s.className = "ly-spin";
    s.setAttribute("aria-hidden", "true");
    if (size) s.style.setProperty("--ly-spin-size", size + "px");
    return s;
  }

  function ownText(node) {
    let t = "";
    for (const c of node.childNodes) if (c.nodeType === 3) t += c.nodeValue;
    return t.trim();
  }

  function mark(node) {
    if (!node || node.nodeType !== 1) return;
    const busy = ownText(node).endsWith("…") && !/\b(bad|warn)\b/.test(node.className);
    const has = node.firstElementChild && node.firstElementChild.classList.contains("ly-spin") ? node.firstElementChild : null;
    if (busy && !has) node.prepend(el());
    else if (!busy && has) has.remove();
    node.classList.toggle("busy", busy);
  }

  function scan(root) {
    if (!root || root.nodeType !== 1) return;
    if (root.matches(WATCH)) mark(root);
    root.querySelectorAll(WATCH).forEach(mark);
  }

  function start() {
    scan(document.body);
    new MutationObserver((list) => {
      const seen = new Set();
      for (const m of list) {
        let t = m.target.nodeType === 3 ? m.target.parentElement : m.target;
        if (!t || seen.has(t)) continue;
        seen.add(t);
        if (t.matches(WATCH)) mark(t);
        for (const n of m.addedNodes) if (n.nodeType === 1 && !n.classList.contains("ly-spin")) scan(n);
      }
    }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["class"] });
  }

  window.LySpin = { el, mark };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
