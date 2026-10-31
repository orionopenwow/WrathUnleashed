// Leyline Launcher: what a player sees when something goes wrong. Never the raw error (a network library's text, a
// path, a stack): the error goes to the console for whoever is helping, and the player gets a plain sentence. A
// message the core wrote for players (a short sentence, nothing technical in it) is shown as it is; anything else
// gets the fallback the caller names, or the general one. Loaded first: every page script uses
// window.LeylineFriendly(e, fallback).
(function () {
  "use strict";
  const GENERAL = "Something went wrong. Try again, or ask on the Discord.";
  // what marks text as not written for players
  const TECH = /error sending|os error|io error|dns|tcp|tls|ssl|socket|timed? ?out|connection (refused|reset|closed)|refused|reqwest|ureq|serde|json|invalid type|missing field|expected .* at line|panick|stack|TypeError|ReferenceError|SyntaxError|undefined|\bnull\b|\bNaN\b|not a function|Cannot read|invoke|IPC|plugin|command .*not found|\bstatus code\b|\bhttps?:\/\/|\b[A-Z]:\\|\/(home|usr|tmp|Users|var)\/|\bEACCES|\bENOENT|\bat \S+:\d+|[{}<>]/i;
  function textOf(e) {
    if (e == null) return "";
    if (typeof e === "string") return e;
    if (typeof e === "object" && typeof e.message === "string") return e.message;
    try { return String(e); } catch (_) { return ""; }
  }
  // Shown to the player: `e` itself when it reads as a sentence for people, else `fallback` (or the general line).
  // A parenthesised technical tail ("The forum isn't answering right now (error sending request…)") is dropped.
  function friendly(e, fallback) {
    try { console.error("[leyline]", e); } catch (_) { /* no console */ }
    const fb = fallback || GENERAL;
    let t = textOf(e).trim();
    if (!t) return fb;
    t = t.replace(/\s*\([^()]*\)\s*([.!?])?\s*$/, (m, p) => (TECH.test(m) ? (p || ".") : m)).trim();
    if (t.length > 240 || TECH.test(t) || !/^[A-Z0-9“"'‘]/.test(t)) return fb;
    return t;
  }
  friendly.GENERAL = GENERAL;
  window.LeylineFriendly = friendly;
})();
