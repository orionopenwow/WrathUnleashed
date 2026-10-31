// Leyline Launcher: Community › Friends. Friends, presence and messages over the Rust core's social commands
// (src-tauri/src/social.rs), which talk to the portal's /wrath/api/social (stream/social.py; docs/SOCIAL.md).
//
// Loaded before app.js: it fills the Community page's Friends tab (#pane-friends in index.html); app.js's navigation
// shows it (show("community", false, "friends"), or the old page id "friends"). The unread count goes on the
// Community menu item and on the Friends tab.
// While signed in it keeps one long poll open ("events"): that is what shows you "in the launcher" to your friends.
// Sign-in is the website's own, in your browser (a code to approve); the launcher keeps only a revocable token.
// Everything from the server is shown with textContent: no markup from anyone's name or message.
(function () {
  "use strict";
  const tauri = window.__TAURI__ && window.__TAURI__.core ? window.__TAURI__.core.invoke : null;
  const invoke = tauri || (async (cmd) => {
    if (cmd === "social_status") return false;
    throw "This is a preview page: open it in the Leyline app.";
  });
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const REASONS = [["spam", "Spam"], ["harassment", "Harassment"], ["hate", "Hate"], ["cheating", "Cheating"], ["other", "Something else"]];

  // ---------------------------------------------------------------- the tab (index.html) and its badges
  const navBadge = $("nav-friends-count") || el("span", "badge");
  const tabBadge = $("tab-friends-count");
  navBadge.hidden = true;
  function setBadge(n) {
    for (const b of [navBadge, tabBadge]) { if (!b) continue; b.textContent = String(n); b.hidden = n === 0; }
  }

  const page = $("pane-friends");
  page.innerHTML = `
    <div class="sx">
      <div class="sx-head"><span class="sx-me" id="sx-me"></span></div>
      <div id="sx-out" hidden>
        <p class="lede">Your Leyline friends in game, in the launcher and on the website, and messages that reach them wherever they are.
          Sign in with the website (Google or your Hero Key) in your browser: the launcher never sees your password.</p>
        <div class="row"><button type="button" class="btn" id="sx-signin">SIGN IN WITH THE WEBSITE</button></div>
        <div id="sx-code" hidden>
          <p class="lede">Your browser opened the sign-in page. Check it shows this code, then approve:</p>
          <p class="sx-code" id="sx-code-text"></p>
          <div class="row"><button type="button" class="btn small" id="sx-reopen">OPEN THE PAGE AGAIN</button>
            <button type="button" class="btn small" id="sx-cancel">CANCEL</button></div>
        </div>
      </div>
      <div id="sx-in" class="sx-grid" hidden>
        <div class="sx-col">
          <form class="row sx-add" id="sx-add-form"><input id="sx-add" placeholder="Name#1234 or a character" maxlength="40" autocomplete="off" spellcheck="false" aria-label="Add a friend"><button type="submit" class="btn small">ADD</button></form>
          <div id="sx-requests"></div>
          <div class="sx-list" id="sx-friends" role="list" aria-label="Friends"></div>
          <details class="sx-more"><summary>Settings and blocked players</summary>
            <form class="row" id="sx-name-form"><input id="sx-name" maxlength="24" placeholder="Your name" aria-label="Your Leyline name" spellcheck="false"><button type="submit" class="btn small">SAVE NAME</button></form>
            <label class="check"><input type="checkbox" id="sx-offline"> Appear offline</label>
            <div id="sx-blocked"></div>
            <div class="row"><button type="button" class="btn small danger" id="sx-signout">SIGN OUT</button></div>
          </details>
        </div>
        <div class="sx-chat" id="sx-chat">
          <div class="sx-chat-head"><div><b id="sx-with"></b><span id="sx-with-where"></span></div>
            <div class="sx-actions" id="sx-actions" hidden>
              <button type="button" class="btn small" id="sx-report-open">REPORT</button>
              <button type="button" class="btn small" id="sx-block">BLOCK</button>
              <button type="button" class="btn small danger" id="sx-remove">REMOVE</button></div></div>
          <form class="sx-report" id="sx-report" hidden>
            <span>Report for</span><select id="sx-reason"></select>
            <input id="sx-note" maxlength="300" placeholder="What happened (optional)">
            <button type="submit" class="btn small">SEND REPORT</button>
            <p class="hint">The last messages between you go to the moderators with it.</p>
          </form>
          <div class="sx-msgs" id="sx-msgs" aria-live="polite"><p class="hint">Pick a friend to message them.</p></div>
          <form class="sx-say" id="sx-say-form"><input id="sx-say" maxlength="500" placeholder="Message" autocomplete="off" aria-label="Message" disabled><button type="submit" class="btn small" id="sx-send" disabled>SEND</button></form>
        </div>
      </div>
      <p class="status" id="sx-status" role="status"></p>
    </div>`;
  const shown = () => page.classList.contains("on") && !!page.closest(".page.on");
  for (const [v, t] of REASONS) { const o = el("option", "", t); o.value = v; $("sx-reason").appendChild(o); }

  function say(text, kind) { const s = $("sx-status"); s.textContent = text || ""; s.className = "status" + (kind ? " " + kind : ""); }
  const call = (action, args) => invoke("social_call", { action, args: args || {} });

  // ---------------------------------------------------------------- state
  let state = null, selected = null, signedIn = false, liveRunning = false, messages = [];

  function showSignedOut() {
    signedIn = false; state = null; selected = null;
    $("sx-out").hidden = false; $("sx-in").hidden = true; $("sx-code").hidden = true; $("sx-me").textContent = "";
    setBadge(0);
    renderHome();
  }

  function showSignedIn() {
    $("sx-out").hidden = true; $("sx-in").hidden = false;
  }

  const STATUS = { game: "In game", launcher: "In the launcher", offline: "Offline" };

  // Home's Friends card (owner 2026-10-30): who is on, in game first; a click opens the chat on Community › Friends.
  const RANK = { game: 0, launcher: 1, offline: 2 };
  function goFriends(pid) {
    if (window.LeylineNav) window.LeylineNav.show("community", false, "friends");
    if (pid) openChat(pid);
  }
  function renderHome() {
    const box = $("hf-list");
    if (!box) return;
    box.textContent = "";
    if (!signedIn || !state) {
      box.appendChild(el("p", "hint", "Sign in to see who's on."));
      const b = el("button", "btn wide", "SIGN IN"); b.type = "button"; b.onclick = () => goFriends();
      box.appendChild(b);
      return;
    }
    const fs = state.friends.slice().sort((a, b) => (RANK[a.status] ?? 3) - (RANK[b.status] ?? 3) || a.name.localeCompare(b.name));
    if (!fs.length) { box.appendChild(el("p", "hint", `No friends yet. You are ${state.me.name}#${state.me.tag}`)); return; }
    for (const f of fs) {
      const b = el("button", "sx-friend"); b.type = "button"; b.setAttribute("role", "listitem");
      b.appendChild(el("span", "sx-dot " + f.status));
      const t = el("span", "sx-ft"); t.append(el("b", "", f.name), el("i", "", where(f))); b.appendChild(t);
      if (f.unread) b.appendChild(el("span", "badge", String(f.unread)));
      b.onclick = () => goFriends(f.pid);
      box.appendChild(b);
    }
  }
  if ($("hf-all")) $("hf-all").addEventListener("click", () => goFriends());
  function where(f) { return f.status === "game" ? `In game: ${f.char} on ${f.realm}` : STATUS[f.status] || ""; }

  function render() {
    if (!state) return;
    const me = state.me;
    $("sx-me").textContent = `You: ${me.name}#${me.tag}` + (me.offline ? " (appearing offline)" : "");
    if (document.activeElement !== $("sx-name")) $("sx-name").value = me.name;
    $("sx-offline").checked = !!me.offline;
    // requests
    const req = $("sx-requests"); req.textContent = "";
    for (const r of state.incoming) {
      const row = el("div", "sx-req");
      row.appendChild(el("span", "", `${r.name}#${r.tag} wants to be friends`));
      const yes = el("button", "btn small", "ACCEPT"); yes.type = "button"; yes.onclick = () => act("accept", { pid: r.pid });
      const no = el("button", "btn small", "DECLINE"); no.type = "button"; no.onclick = () => act("decline", { pid: r.pid });
      const blk = el("button", "btn small danger", "BLOCK"); blk.type = "button"; blk.onclick = () => act("block", { pid: r.pid });
      row.append(yes, no, blk); req.appendChild(row);
    }
    for (const r of state.outgoing) {
      const row = el("div", "sx-req out");
      row.appendChild(el("span", "", `Request sent to ${r.name}`));
      const no = el("button", "btn small", "CANCEL"); no.type = "button"; no.onclick = () => act("decline", { pid: r.pid });
      row.appendChild(no); req.appendChild(row);
    }
    // friends
    const list = $("sx-friends"); list.textContent = "";
    if (!state.friends.length) list.appendChild(el("p", "hint", "No friends yet. Add someone with their Name#1234, or ask them to add you: " + `${me.name}#${me.tag}`));
    let unread = state.incoming.length;
    for (const f of state.friends) {
      unread += f.unread;
      const b = el("button", "sx-friend" + (selected === f.pid ? " on" : ""));
      b.type = "button"; b.setAttribute("role", "listitem");
      b.appendChild(el("span", "sx-dot " + f.status));
      const t = el("span", "sx-ft");
      t.append(el("b", "", f.name), el("i", "", where(f)));
      b.appendChild(t);
      if (f.unread) b.appendChild(el("span", "badge", String(f.unread)));
      b.onclick = () => openChat(f.pid);
      list.appendChild(b);
    }
    setBadge(unread);
    renderHome();
    // blocked
    const bl = $("sx-blocked"); bl.textContent = "";
    for (const x of state.blocked) {
      const row = el("div", "sx-req"); row.appendChild(el("span", "", `Blocked: ${x.name}#${x.tag}`));
      const u = el("button", "btn small", "UNBLOCK"); u.type = "button"; u.onclick = () => act("unblock", { pid: x.pid });
      row.appendChild(u); bl.appendChild(row);
    }
    renderChatHead();
  }

  function friendBy(pid) { return state && state.friends.find((f) => f.pid === pid); }

  function renderChatHead() {
    const f = selected && friendBy(selected);
    if (selected && !f) { selected = null; messages = []; renderMessages(); }
    $("sx-with").textContent = f ? f.name : "";
    $("sx-with-where").textContent = f ? " · " + where(f) : "";
    $("sx-actions").hidden = !f;
    $("sx-say").disabled = !f; $("sx-send").disabled = !f;
    if (!f) $("sx-report").hidden = true;
  }

  function renderMessages() {
    const box = $("sx-msgs"); box.textContent = "";
    if (!selected) { box.appendChild(el("p", "hint", "Pick a friend to message them.")); return; }
    if (!messages.length) box.appendChild(el("p", "hint", "No messages yet. Say hello: they get it in game, in the launcher or on the website."));
    for (const m of messages) {
      const d = el("div", "sx-msg" + (m.mine ? " mine" : ""));
      d.appendChild(el("span", "sx-text", m.text));
      const when = new Date(m.at * 1000);
      d.appendChild(el("span", "sx-when", when.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
        + (m.via === "game" ? " · in game" : "")));
      box.appendChild(d);
    }
    box.scrollTop = box.scrollHeight;
  }

  async function loadThread() {
    if (!selected) return;
    const pid = selected;
    try {
      const r = await call("thread", { with: pid });
      if (selected !== pid) return;
      messages = r.messages || [];
      renderMessages();
      const f = friendBy(pid);
      if (f && f.unread && shown()) { await call("read", { with: pid }); }
    } catch (e) { failed(e); }
  }

  function openChat(pid) {
    selected = pid; messages = []; $("sx-report").hidden = true;
    render(); renderMessages(); loadThread();
    $("sx-say").focus();
  }

  function failed(e) {
    if (String(e) === "signed_out") { showSignedOut(); say("You were signed out. Sign in again to see your friends.", "warn"); return; }
    say(String(e), "bad");
  }

  async function act(action, args, okText) {
    try {
      const r = await call(action, args);
      say(r.text || okText || "", "ok");
      await refresh();
      return r;
    } catch (e) { failed(e); return null; }
  }

  async function refresh() {
    try {
      const prev = state;
      state = await call("state");
      render();
      const f = selected && friendBy(selected);
      const pf = prev && selected && prev.friends.find((x) => x.pid === selected);
      if (f && (f.unread || (pf && pf.unread !== f.unread))) loadThread();
    } catch (e) { failed(e); }
  }

  // One long poll at a time, while signed in: live updates, and "in the launcher" for your friends.
  async function live() {
    if (liveRunning) return;
    liveRunning = true;
    try {
      while (signedIn) {
        try {
          const r = await call("events", { since: state ? state.v : 0 });
          if (!signedIn) break;
          if (!r.same) {
            const hadThread = selected && friendBy(selected);
            const before = hadThread ? hadThread.unread : 0;
            state = r; render();
            const f = selected && friendBy(selected);
            if (f && f.unread !== before) loadThread();
          }
        } catch (e) {
          if (String(e) === "signed_out") { failed(e); break; }
          await sleep(10000);   // offline or the server is busy: try again soon
        }
      }
    } finally { liveRunning = false; }
  }

  async function signedInNow() {
    signedIn = true;
    showSignedIn();
    await refresh();
    if (signedIn) live();
  }

  // ---------------------------------------------------------------- sign-in
  let polling = false;
  $("sx-signin").addEventListener("click", async () => {
    try {
      const s = await invoke("social_signin_start");
      $("sx-code-text").textContent = s.user_code;
      $("sx-code").hidden = false;
      say("Waiting for you to approve the code in your browser…");
      if (polling) return;
      polling = true;
      try {
        for (;;) {
          await sleep(5000);
          const p = await invoke("social_signin_poll");
          if (p.state === "pending") continue;
          $("sx-code").hidden = true;
          if (p.state === "signed_in") { say("Signed in.", "ok"); await signedInNow(); }
          else if (p.state === "denied") say("Not linked: the code was refused on the website.", "warn");
          else if (p.state === "expired") say("The code expired. Try again.", "warn");
          break;
        }
      } finally { polling = false; }
    } catch (e) { say(String(e), "bad"); }
  });
  $("sx-reopen").addEventListener("click", () => invoke("social_signin_reopen").catch((e) => say(String(e), "bad")));
  $("sx-cancel").addEventListener("click", async () => {
    await invoke("social_signin_cancel").catch(() => {});
    $("sx-code").hidden = true; say("");
  });
  $("sx-signout").addEventListener("click", async () => {
    signedIn = false;
    await invoke("social_signout").catch(() => {});
    showSignedOut(); say("Signed out. The sign-in was revoked on the website too.", "ok");
  });

  // ---------------------------------------------------------------- forms
  $("sx-add-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const to = $("sx-add").value.trim();
    if (!to) return;
    if (await act("request", { to })) $("sx-add").value = "";
  });
  $("sx-name-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    await act("profile", { name: $("sx-name").value.trim() }, "Saved.");
  });
  $("sx-offline").addEventListener("change", (ev) => act("profile", { offline: ev.target.checked },
    ev.target.checked ? "You appear offline to your friends." : "Your friends can see you again."));
  $("sx-say-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const text = $("sx-say").value.trim();
    if (!text || !selected) return;
    try {
      const r = await call("send", { to: selected, text });
      $("sx-say").value = "";
      messages.push(r.message); renderMessages(); say("");
    } catch (e) { failed(e); }
  });
  // Block and Remove ask once more on the button itself (no pop-up dialogs in the app window).
  function twice(btn, label, fn) {
    btn.addEventListener("click", async () => {
      if (btn.dataset.armed) { delete btn.dataset.armed; btn.textContent = label; await fn(); return; }
      btn.dataset.armed = "1"; btn.textContent = "SURE?";
      setTimeout(() => { if (btn.dataset.armed) { delete btn.dataset.armed; btn.textContent = label; } }, 4000);
    });
  }
  twice($("sx-block"), "BLOCK", async () => { const f = friendBy(selected); if (f) await act("block", { pid: f.pid }); });
  twice($("sx-remove"), "REMOVE", async () => { const f = friendBy(selected); if (f) await act("remove", { pid: f.pid }); });
  $("sx-report-open").addEventListener("click", () => { $("sx-report").hidden = !$("sx-report").hidden; });
  $("sx-report").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = friendBy(selected);
    if (!f) return;
    if (await act("report", { pid: f.pid, reason: $("sx-reason").value, note: $("sx-note").value.trim() })) {
      $("sx-report").hidden = true; $("sx-note").value = "";
    }
  });
  // opening the tab refreshes (and so marks the open conversation read)
  document.addEventListener("leyline:page", (ev) => {
    const d = ev.detail || {};
    if (signedIn && ((d.page === "community" && d.tab === "friends") || d.page === "friends")) refresh();
  });

  // ---------------------------------------------------------------- start
  (async () => {
    let yes = false;
    try { yes = await invoke("social_status"); } catch (_) { yes = false; }
    if (yes) signedInNow(); else showSignedOut();
  })();

  window.LeylineSocial = { refresh, state: () => state };
})();
