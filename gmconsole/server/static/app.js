'use strict';
// WrathUnleashed GM console. Everything from the server is put on the page as text (textContent),
// never as markup: player names, log lines and remote JSON can't inject anything.
(function () {
  const CSRF = document.querySelector('meta[name=csrf]').content;
  const TABS = [
    ['overview', 'Overview'], ['players', 'Players'], ['updates', 'Updates'], ['streaming', 'Streaming'],
    ['beacons', 'Beacons'], ['speed', 'Speed'], ['logs', 'Logs'],
  ];
  const app = document.getElementById('app');
  let tab = 'overview';
  let timer = null;
  let jobTimer = null;
  const ui = { logs: { c: 'worldserver', n: 300, q: '', auto: true }, acctQ: '' };

  // ---- tiny DOM helpers -------------------------------------------------------------------
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v === null || v === undefined || v === false) continue;
        if (k === 'class') el.className = v;
        else if (k === 'text') el.textContent = v;
        else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
        else if (k === 'value') el.value = v;
        else el.setAttribute(k, v === true ? '' : v);
      }
    }
    for (const kid of kids.flat(3)) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.appendChild(typeof kid === 'object' ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }
  const card = (title, extra, ...body) => h('section', { class: 'card' },
    h('header', { class: 'card-h' }, h('h2', { text: title }), extra || null), h('div', { class: 'card-b' }, ...body));
  const dot = (state) => h('span', { class: 'dot ' + state, title: state });
  const badge = (text, cls) => h('span', { class: 'badge ' + (cls || ''), text });
  const kv = (rows) => h('dl', { class: 'kv' }, rows.filter(Boolean).map(([k, v]) => [h('dt', { text: k }), h('dd', null, v)]));
  function table(cols, rows, empty) {
    if (!rows.length) return h('p', { class: 'muted', text: empty || 'Nothing here.' });
    return h('div', { class: 'tbl-wrap' }, h('table', { class: 'tbl' },
      h('thead', null, h('tr', null, cols.map((c) => h('th', { class: c.cls || null, text: c.t })))),
      h('tbody', null, rows.map((r) => h('tr', { class: r._cls || null }, cols.map((c) => h('td', { class: c.cls || null }, c.f(r))))))));
  }
  function tile(label, value, sub, state) {
    return h('div', { class: 'tile ' + (state || '') }, h('div', { class: 'tile-l', text: label }),
      h('div', { class: 'tile-v', text: value }), sub ? h('div', { class: 'tile-s', text: sub }) : null);
  }
  const btn = (label, onclick, cls) => h('button', { class: 'btn ' + (cls || ''), type: 'button', onclick }, label);

  // ---- formatting ---------------------------------------------------------------------------
  function bytes(n) {
    if (n === null || n === undefined) return '?';
    const u = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return (i ? n.toFixed(n < 10 ? 2 : 1) : n) + ' ' + u[i];
  }
  function dur(s) {
    if (s === null || s === undefined) return '?';
    const d = Math.floor(s / 86400), hh = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
    return d ? `${d}d ${hh}h` : hh ? `${hh}h ${m}m` : `${m}m ${s % 60}s`;
  }
  function when(t) {
    if (!t) return '?';
    const d = new Date(typeof t === 'number' ? t * 1000 : t);
    const ago = Math.round((Date.now() - d.getTime()) / 1000);
    const rel = ago < 0 ? '' : ago < 90 ? `${ago}s ago` : ago < 5400 ? `${Math.round(ago / 60)}m ago` :
      ago < 172800 ? `${Math.round(ago / 3600)}h ago` : `${Math.round(ago / 86400)}d ago`;
    return d.toISOString().slice(0, 16).replace('T', ' ') + (rel ? ' (' + rel + ')' : '');
  }
  const num = (v) => (v === null || v === undefined ? '?' : String(v));

  // ---- server calls -------------------------------------------------------------------------
  async function api(path) {
    const r = await fetch(path, { credentials: 'same-origin', cache: 'no-store' });
    const j = await r.json().catch(() => ({ error: 'bad answer' }));
    if (r.status === 401) { location.reload(); throw new Error('signed out'); }
    if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
    return j;
  }
  async function act(name, args) {
    const r = await fetch('/api/action/' + name, {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRF': CSRF },
      body: JSON.stringify(args || {}),
    });
    const j = await r.json().catch(() => ({ error: 'bad answer' }));
    if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
    return j;
  }
  // Runs an action after an optional confirm dialog; shows the result as a toast.
  async function run(name, args, opts) {
    opts = opts || {};
    if (opts.confirm) {
      const ok = await modal({ title: opts.confirm, note: opts.note, ok: opts.ok || 'Do it', danger: true });
      if (!ok) return null;
      args = Object.assign({}, args, { confirm: true });
    }
    try {
      const res = await act(name, args);
      if (res.job) { toast(`${res.job.name} started`, 'ok'); watchJobs(); }
      else toast(String(res.message || 'done').split('\n')[0].slice(0, 200), 'ok');
      setTimeout(refresh, 300);
      return res;
    } catch (e) { toast(e.message, 'err'); return null; }
  }

  // ---- toast and modal ----------------------------------------------------------------------
  const toasts = h('div', { class: 'toasts', 'aria-live': 'polite' });
  function toast(text, cls) {
    const t = h('div', { class: 'toast ' + (cls || ''), text });
    toasts.appendChild(t);
    setTimeout(() => t.remove(), cls === 'err' ? 9000 : 4500);
  }
  // modal({title, note, fields:[{name,label,type,value,options,required,min,max}], ok, danger}) -> values | null
  function modal(o) {
    return new Promise((resolve) => {
      const inputs = {};
      const form = h('form', { class: 'modal', onsubmit: (ev) => { ev.preventDefault(); done(true); } },
        h('h3', { text: o.title }), o.note ? h('p', { class: 'muted', text: o.note }) : null,
        (o.fields || []).map((f) => {
          let inp;
          if (f.type === 'select') {
            inp = h('select', { name: f.name }, f.options.map(([v, l]) => h('option', { value: v, text: l })));
            if (f.value !== undefined) inp.value = f.value;
          } else if (f.type === 'textarea') {
            inp = h('textarea', { name: f.name, rows: 3, maxlength: f.max || 400, required: f.required || null });
            inp.value = f.value || '';
          } else {
            inp = h('input', { name: f.name, type: f.type || 'text', value: f.value ?? '', required: f.required || null,
              min: f.min ?? null, max: f.max ?? null, maxlength: f.maxlength || null, autocomplete: 'off' });
          }
          inputs[f.name] = inp;
          return h('label', { class: 'field' }, h('span', { text: f.label }), inp);
        }),
        h('div', { class: 'modal-btns' }, btn('Cancel', () => done(false)),
          h('button', { class: 'btn ' + (o.danger ? 'danger' : 'primary'), type: 'submit' }, o.ok || 'OK')));
      const back = h('div', { class: 'modal-back', onclick: (ev) => { if (ev.target === back) done(false); } }, form);
      function done(ok) {
        back.remove();
        document.removeEventListener('keydown', esc);
        if (!ok) return resolve(null);
        const v = {};
        for (const [k, el] of Object.entries(inputs)) v[k] = el.value;
        resolve(v);
      }
      function esc(ev) { if (ev.key === 'Escape') done(false); }
      document.addEventListener('keydown', esc);
      document.body.appendChild(back);
      const first = form.querySelector('input,select,textarea,button[type=submit]');
      if (first) first.focus();
    });
  }

  // ---- shell --------------------------------------------------------------------------------
  const pill = h('span', { class: 'pill', text: 'realm ...' });
  const jobPill = h('span', { class: 'pill job hidden' });
  const stamp = h('span', { class: 'stamp muted' });
  const nav = h('nav', { class: 'tabs', role: 'tablist' }, TABS.map(([k, l]) =>
    h('a', { href: '#' + k, 'data-tab': k, role: 'tab', text: l })));
  const main = h('main', { id: 'main' });
  app.append(h('div', { class: 'top' }, h('div', { class: 'brand' }, h('b', { text: 'WrathUnleashed' }), h('span', { text: 'GM console' })),
    pill, jobPill, h('span', { class: 'grow' }), stamp), nav, main, toasts);

  function setPill(realm) {
    if (!realm) return;
    pill.className = 'pill ' + (realm.online ? 'ok' : 'bad');
    pill.textContent = realm.online ? `online · ${num(realm.players)} players · ${num(realm.bots)} bots` : 'world server offline';
  }
  function setJobs(jobs) {
    const j = (jobs || []).find((x) => x.state === 'running');
    jobPill.classList.toggle('hidden', !j);
    if (j) jobPill.textContent = 'running: ' + j.name.replace(/_/g, ' ');
  }
  function watchJobs() {
    if (jobTimer) return;
    jobTimer = setInterval(async () => {
      try {
        const d = await api('/api/jobs');
        setJobs(d.jobs);
        document.querySelectorAll('[data-jobs]').forEach((el) => el.replaceWith(jobsBox(d.jobs)));
        if (!d.jobs.some((x) => x.state === 'running')) { clearInterval(jobTimer); jobTimer = null; refresh(); }
      } catch (_) { /* keep polling */ }
    }, 2000);
  }
  function jobsBox(jobs) {
    const list = (jobs || []).slice(0, 3);
    return h('div', { 'data-jobs': '1' }, list.length ? list.map((j) => h('div', { class: 'job-box' },
      h('div', { class: 'job-h' }, dot(j.state === 'running' ? 'warn' : j.state === 'ok' ? 'ok' : 'bad'),
        h('b', { text: j.name.replace(/_/g, ' ') }), h('span', { class: 'muted', text: `${j.state} · ${when(j.started)}` }),
        h('span', { class: 'grow' }), j.cancellable ? btn('Cancel', () => run('cancel_job', { id: j.id }), 'small') : null),
      h('pre', { class: 'log short', text: j.lines.slice(-14).join('\n') || '...' }))) :
      h('p', { class: 'muted', text: 'No actions run since the console started.' }));
  }

  // ---- Overview -----------------------------------------------------------------------------
  function overview(d) {
    const r = d.realm || {}, ho = d.host || {}, s = d.stream || {};
    const memUsed = ho.mem_total && ho.mem_avail !== null ? ho.mem_total - ho.mem_avail : null;
    const diffState = r.diff_ms === null || r.diff_ms === undefined ? '' : r.diff_ms > 150 ? 'bad' : r.diff_ms > 80 ? 'warn' : 'ok';
    const loadState = ho.load && ho.cpus ? (ho.load[0] > ho.cpus ? 'bad' : ho.load[0] > ho.cpus * 0.7 ? 'warn' : '') : '';
    const tiles = h('div', { class: 'tiles' },
      tile('Realm', r.online ? 'Online' : 'Offline', r.online ? `profile ${d.profile}` : (r.error || ''), r.online ? 'ok' : 'bad'),
      tile('Players', num(r.players), r.peak !== null && r.peak !== undefined ? `peak ${r.peak}` : 'connected sessions'),
      tile('Bots', num(r.bots), `in world: ${num(r.characters)}`),
      tile('Uptime', dur(r.uptime_s), 'world server'),
      tile('Update diff', r.diff_ms === null || r.diff_ms === undefined ? '?' : r.diff_ms + ' ms',
        r.mean_ms !== null && r.mean_ms !== undefined ? `mean ${r.mean_ms} · p95 ${num(r.p95_ms)} ms` : 'server info', diffState),
      tile('Disk free', bytes(ho.disk_free), `of ${bytes(ho.disk_total)}${ho.disk_warn ? ' · under 3 GB!' : ''}`, ho.disk_warn ? 'bad' : ''),
      tile('RAM used', bytes(memUsed), `of ${bytes(ho.mem_total)}`),
      tile('Load', ho.load ? ho.load[0].toFixed(2) : '?', ho.load ? `5m ${ho.load[1].toFixed(2)} · 15m ${ho.load[2].toFixed(2)} · ${num(ho.cpus)} CPUs` : '', loadState));
    const cont = card('Containers', null, table([
      { t: '', f: (c) => dot(c.health === 'ok' ? 'ok' : c.health === 'starting' ? 'warn' : c.health === 'other' ? 'off' : (c.key === 'wu-play' && !s.streaming) ? 'off' : 'bad'), cls: 'w1' },
      { t: 'Container', f: (c) => h('span', { class: 'mono', text: c.name }) },
      { t: 'Role', f: (c) => c.label, cls: 'hide-s' },
      { t: 'Status', f: (c) => h('span', { class: 'muted', text: c.status }) },
    ], d.containers.concat(d.other_containers || [])));
    const cl = d.client || null, old = d.client_old || null;
    const stream = card('Streaming', h('a', { href: '#streaming', class: 'link', text: 'details' }), kv([
      ['Streaming', s.streaming ? badge('on', 'ok') : badge('off', 'off')],
      ['Slice', `${s.slice} · ${s.size ? bytes(s.size.bytes) + ', ' + s.size.files + ' files' : 'not on the server'}`],
      ['Tiers', s.tier_count ? `0-${num(s.max_tier)} held of ${s.tier_count}` : '?'],
      ['wu-play', s.wu_play_status],
      ['Forever UI', s.foreverui ? badge('on', 'ok') : badge(s.foreverui_flag ? 'flag on, no overlay' : 'off', 'off')],
    ]));
    const client = card('Browser client', h('a', { href: '#updates', class: 'link', text: 'roll back' }), kv([
      ['Live build', h('span', { class: 'mono', text: cl ? (cl.id || '?') : 'none' })],
      cl && cl.stamp_source ? ['Stamp from', cl.stamp_source] : null,
      ['wasm', cl && cl.wasm ? `${bytes(cl.wasm.bytes)} · ${cl.wasm.br ? '.br ' : ''}${cl.wasm.gz ? '.gz' : ''}` : '?'],
      ['Uploaded', cl ? when(cl.index_mtime) : '?'],
      ['Previous (www.old)', old ? h('span', { class: 'mono', text: old.id || '?' }) : badge('none kept', 'warn')],
    ]));
    const logs = card('Important log lines', h('a', { href: '#logs', class: 'link', text: 'all logs' }),
      d.logs.length ? h('pre', { class: 'log', text: d.logs.join('\n') }) : h('p', { class: 'muted', text: 'No errors in the recent world server log.' }));
    const running = (d.jobs || []).some((j) => j.state === 'running');
    return [tiles, running ? card('Running now', null, jobsBox(d.jobs)) : null,
      h('div', { class: 'grid g2' }, cont, h('div', { class: 'stack' }, stream, client)), logs];
  }

  // ---- Players ------------------------------------------------------------------------------
  function players(d, accts) {
    const r = d.realm || {};
    const say = h('input', { type: 'text', placeholder: 'Message to everyone', maxlength: 255, class: 'grow' });
    const broadcast = card('Message everyone', null, h('div', { class: 'row' }, say,
      btn('Announce (chat)', () => say.value.trim() && run('announce', { text: say.value }).then((x) => x && (say.value = ''))),
      btn('Notify (screen)', () => say.value.trim() && run('notify', { text: say.value }).then((x) => x && (say.value = '')))));
    const rows = d.players.map((p) => Object.assign({}, p));
    const online = card(`Online characters (${rows.length})`,
      h('span', { class: 'muted small', text: `${num(d.bots_online)} bots online (accounts ${d.bot_prefix}*) · server: ${num(r.players)} sessions` }),
      d.error ? h('p', { class: 'err', text: d.error }) : null,
      table([
        { t: 'Name', f: (p) => h('b', { text: p.name }) },
        { t: 'Lvl', f: (p) => p.level, cls: 'num' },
        { t: 'Class', f: (p) => p.class, cls: 'hide-s' },
        { t: 'Race', f: (p) => p.race, cls: 'hide-s' },
        { t: 'Zone', f: (p) => p.zone },
        { t: 'Account', f: (p) => h('span', { class: 'mono muted', text: p.account }), cls: 'hide-s' },
        { t: 'Played', f: (p) => p.played_h + ' h', cls: 'num hide-s' },
        { t: '', cls: 'act-cell', f: (p) => h('span', { class: 'acts' },
          btn('Kick', () => run('kick', { name: p.name }, { confirm: `Kick ${p.name}?`, ok: 'Kick' }), 'small'),
          btn('Mute', async () => {
            const v = await modal({ title: `Mute ${p.name}`, ok: 'Mute', danger: true, fields: [
              { name: 'minutes', label: 'Minutes', type: 'number', value: 15, min: 1, max: 10080, required: true },
              { name: 'reason', label: 'Reason', value: '', maxlength: 120 }] });
            if (v) run('mute', { name: p.name, minutes: v.minutes, reason: v.reason, confirm: true });
          }, 'small'),
          btn('Unmute', () => run('unmute', { name: p.name }), 'small ghost'),
          btn('Dalaran', () => run('tele_dalaran', { name: p.name }, { confirm: `Teleport ${p.name} to Dalaran?`, ok: 'Teleport' }), 'small'),
          btn('Mail', async () => {
            const v = await modal({ title: `Mail an item to ${p.name}`, ok: 'Send', fields: [
              { name: 'subject', label: 'Subject', value: 'A gift from the GMs', maxlength: 60, required: true },
              { name: 'body', label: 'Text', type: 'textarea', value: '' },
              { name: 'item', label: 'Item id', type: 'number', min: 1, required: true },
              { name: 'count', label: 'Count', type: 'number', value: 1, min: 1, max: 200 }] });
            if (v) run('mail', Object.assign({ name: p.name }, v));
          }, 'small'))
        },
      ], rows, 'No real players online.'));
    const q = h('input', { type: 'search', placeholder: 'Account or character name', value: ui.acctQ, maxlength: 32, class: 'grow' });
    const results = h('div');
    async function search() {
      ui.acctQ = q.value.trim();
      if (!ui.acctQ) { results.replaceChildren(); return; }
      try {
        const a = await api('/api/accounts?q=' + encodeURIComponent(ui.acctQ));
        results.replaceChildren(acctTable(a.accounts));
      } catch (e) { results.replaceChildren(h('p', { class: 'err', text: e.message })); }
    }
    q.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') search(); });
    if (accts) results.replaceChildren(acctTable(accts));
    else if (ui.acctQ) search();
    const accounts = card('Accounts', null, h('div', { class: 'row' }, q, btn('Search', search, 'primary')), results);
    return [h('div', { class: 'tiles t3' }, tile('Real players', String(rows.length), 'characters online, bots excluded'),
      tile('Bots online', num(d.bots_online), `accounts ${d.bot_prefix}*`), tile('Sessions', num(r.players), 'server info')),
    broadcast, online, accounts];
  }
  function acctTable(list) {
    return table([
      { t: 'Account', f: (a) => h('b', { class: 'mono', text: a.username }) },
      { t: 'Characters', f: (a) => h('span', null, String(a.characters), h('span', { class: 'muted', text: a.names ? ' · ' + a.names : '' })) },
      { t: 'Last login', f: (a) => a.last_login || '-', cls: 'hide-s' },
      { t: 'State', f: (a) => h('span', null, a.online ? badge('online', 'ok') : null, a.banned ? badge('banned', 'bad') : null,
        a.muted ? badge('muted', 'warn') : null, !a.online && !a.banned && !a.muted ? h('span', { class: 'muted', text: '-' }) : null,
        a.ban_reason ? h('span', { class: 'muted small', text: ' ' + a.ban_reason }) : null) },
      { t: '', cls: 'act-cell', f: (a) => a.banned ?
        btn('Unban', () => run('unban', { account: a.username }, { confirm: `Unban ${a.username}?`, ok: 'Unban' }), 'small') :
        btn('Ban', async () => {
          const v = await modal({ title: `Ban account ${a.username}`, danger: true, ok: 'Ban',
            note: 'Bans the account (all its characters). Nothing is deleted; Unban lifts it.', fields: [
              { name: 'duration', label: 'Duration', type: 'select', value: '7d',
                options: [['1h', '1 hour'], ['1d', '1 day'], ['7d', '7 days'], ['30d', '30 days'], ['-1', 'Permanent']] },
              { name: 'reason', label: 'Reason (required)', required: true, maxlength: 200 }] });
          if (v) run('ban', { account: a.username, duration: v.duration, reason: v.reason, confirm: true });
        }, 'small danger') },
    ], list, 'No accounts match.');
  }

  // ---- Updates ------------------------------------------------------------------------------
  const FIX = {
    reload_ale: ['Reload realm scripts', () => run('reload_ale', {})],
    restart_world: ['Restart world', () => restartWorld()],
    rollback_client: ['Roll back client', () => rollback()],
    restart_portal: ['Restart wu-portal', () => run('restart_portal', {}, { confirm: 'Recreate wu-portal (the sign-in page)?', note: 'Sign-in is down for a few seconds. Players in game are not affected.', ok: 'Restart' })],
    reload_caddy: ['Reload Caddy', () => run('reload_caddy', {}, { confirm: 'Validate and reload the Caddyfile?', note: 'A file that does not validate is never loaded.', ok: 'Reload' })],
  };
  async function restartWorld() {
    const v = await modal({ title: 'Restart the world server', danger: true, ok: 'Start countdown',
      note: 'Announces in chat first, counts down, saves everyone, then recreates ov-ac-worldserver (docker compose up -d --no-deps --force-recreate) and waits until it is ready. Players are disconnected for 2-10 minutes. You can cancel during the countdown.',
      fields: [{ name: 'minutes', label: 'Countdown', type: 'select', value: '5', options: [['1', '1 minute'], ['5', '5 minutes'], ['15', '15 minutes']] },
        { name: 'reason', label: 'Reason shown to players (optional)', maxlength: 80 }] });
    if (v) run('restart_world', { minutes: Number(v.minutes), reason: v.reason, confirm: true });
  }
  function rollback() {
    return run('rollback_client', {}, { confirm: 'Roll back the browser client?', ok: 'Roll back',
      note: 'Swaps stream/www and www.old and restarts wu-play. New page loads get the previous client; running again swaps back.' });
  }
  function updates(d) {
    const train = card('Release train v0', null, h('ol', { class: 'train' }, d.train.map(([t, x]) => h('li', null, h('b', { text: t }), h('span', { text: ' ' + x })))));
    const pend = card('Pending on the server vs live', null, table([
      { t: '', cls: 'w1', f: (i) => dot(i.pending ? 'warn' : 'ok') },
      { t: 'What', f: (i) => h('b', { text: i.label }) },
      { t: 'Live', f: (i) => h('span', { class: 'mono', text: i.live }) },
      { t: 'Note', f: (i) => h('span', { class: 'muted', text: (i.pending ? 'PENDING · ' : '') + i.note }), cls: 'hide-s' },
      { t: '', cls: 'act-cell', f: (i) => i.fix && FIX[i.fix] ? btn(FIX[i.fix][0], FIX[i.fix][1], 'small' + (i.pending ? ' primary' : '')) : '' },
    ], d.items.map((i) => Object.assign({ _cls: i.pending ? 'pending' : null }, i))));
    const actions = card('Roll updates', null, h('div', { class: 'btn-grid' },
      btn('Reload realm scripts', FIX.reload_ale[1], 'primary'), btn('Restart world server…', restartWorld, 'danger'),
      btn('Roll back browser client', rollback), btn('Restart wu-portal', FIX.restart_portal[1]), btn('Reload Caddy', FIX.reload_caddy[1])),
    h('h3', { class: 'sub', text: 'Actions' }), jobsBox(d.jobs));
    const lua = card('Realm scripts', h('span', { class: 'muted small', text: 'world started ' + when(d.world_started) }), table([
      { t: '', cls: 'w1', f: (f) => dot(f.pending ? 'warn' : 'ok') },
      { t: 'File', f: (f) => h('span', { class: 'mono', text: f.name }) },
      { t: 'Changed', f: (f) => when(f.mtime) }, { t: 'Size', f: (f) => bytes(f.bytes), cls: 'num hide-s' }], d.lua, 'No Lua scripts.'),
    d.sql.length ? h('p', { class: 'muted small', text: 'SQL on the server: ' + d.sql.map((s) => s.name).join(', ') }) : null);
    const bats = card('Your .bat tools (they upload; this console applies)', null, table([
      { t: 'Tool', f: (b) => h('b', { class: 'mono', text: b.bat }) },
      { t: 'What it does', f: (b) => b.what }, { t: 'When', f: (b) => b.when, cls: 'hide-s' },
      { t: 'Restarts', f: (b) => h('span', { class: 'muted', text: b.restart }), cls: 'hide-s' }], d.bats));
    const hist = card('History (gmconsole-audit.log)', null, table([
      { t: 'When', f: (e) => h('span', { class: 'mono small', text: e.at.replace('T', ' ').replace('Z', '') }) },
      { t: 'Action', f: (e) => h('b', { text: e.action }) },
      { t: 'Detail', f: (e) => h('span', { class: 'mono small muted', text: e.detail === '{}' ? '' : e.detail }), cls: 'hide-s' },
      { t: 'Result', f: (e) => h('span', { class: /^(ok|started)/.test(e.result) ? '' : 'err', text: e.result }) }], d.audit, 'Nothing yet.'));
    return [h('div', { class: 'grid g2' }, train, actions), pend, h('div', { class: 'grid g2' }, lua, hist), bats];
  }

  // ---- Streaming ----------------------------------------------------------------------------
  function streaming(d) {
    const s = d.state;
    const toggles = card('Switches', null, h('div', { class: 'switches' },
      h('div', { class: 'sw' }, h('div', null, h('b', { text: 'Browser streaming' }), h('div', { class: 'muted small', text: 'stream-switch.sh: off releases every stream account at once' })),
        s.streaming ? badge('ON', 'ok') : badge('OFF', 'off'),
        s.streaming ? btn('Turn off', () => run('stream', { on: false }, { confirm: 'Turn browser streaming off?', note: '/wrath/play then says streaming is off; players on their own game files are not affected.', ok: 'Turn off' }), 'danger')
          : btn('Turn on', () => run('stream', { on: true }, { confirm: 'Turn browser streaming on?', ok: 'Turn on' }), 'primary')),
      h('div', { class: 'sw' }, h('div', null, h('b', { text: 'Forever UI' }), h('div', { class: 'muted small', text: 'WU_FOREVERUI in portal.env, then wu-portal is recreated' + (s.foreverui_overlay ? '' : ' · overlay not on the server') })),
        s.foreverui ? badge('ON', 'ok') : badge(s.foreverui_flag ? 'NO OVERLAY' : 'OFF', 'off'),
        s.foreverui_flag ? btn('Turn off', () => run('foreverui', { on: false }, { confirm: 'Turn Forever UI off (stock look)?', ok: 'Turn off' }), 'danger')
          : btn('Turn on', () => run('foreverui', { on: true }, { confirm: 'Turn Forever UI on?', ok: 'Turn on' }), 'primary'))),
    jobsBox(d.jobs));
    const info = card('Slice', null, kv([
      ['Name', s.slice], ['Stream site', s.stream_host || '?'],
      ['Size', s.size ? `${bytes(s.size.bytes)} · ${s.size.files} files` : 'not on the server'],
      ['Tiers held', `0-${num(s.max_tier)} of ${s.tier_count}`], ['Budget', s.budget_mb ? s.budget_mb + ' MB' : '?'],
      ['wu-play', h('span', null, dot(s.wu_play === 'ok' ? 'ok' : 'bad'), ' ' + s.wu_play_status)],
      ['Own game files mode', s.ownfiles ? badge('on', 'ok') : badge('off', 'off')]]));
    const tiers = card('Tiers', h('span', { class: 'muted small', text: d.tier_source + (d.tier_error ? ' (wu-play: ' + d.tier_error + ')' : '') }), table([
      { t: '#', f: (t) => t.tier, cls: 'num w1' }, { t: 'Name', f: (t) => t.name },
      { t: 'Files', f: (t) => t.files === null ? (t.held === false ? 'not held' : '-') : t.files, cls: 'num' },
      { t: 'Size', f: (t) => (t.bytes === null ? '-' : bytes(t.bytes)), cls: 'num' }],
    d.tiers.map((t) => Object.assign({ _cls: t.held === false ? 'dim' : null }, t)), 'No tier list.'));
    const logs = card('wu-play log', null, h('pre', { class: 'log tall', text: d.logs.join('\n') || '(empty)' }));
    return [h('div', { class: 'grid g2' }, toggles, info), h('div', { class: 'grid g2' }, tiers, logs)];
  }

  // ---- Beacons ------------------------------------------------------------------------------
  function beacons(d) {
    const recheck = () => load(true);
    const checks = card('Launch checklist: going public with Beacons', h('span', { class: 'row' },
      h('span', { class: 'muted small', text: 'checked ' + when(d.at) }), btn('Re-check all', recheck, 'small primary')),
    h('ul', { class: 'checks' }, d.checks.map((c) => h('li', null, dot(c.ok === true ? 'ok' : c.ok === false ? 'bad' : 'off'),
      h('div', { class: 'grow' }, h('b', { text: c.label }), h('div', { class: 'muted small mono', text: c.detail })),
      btn('Re-check', recheck, 'small ghost')))));
    const pre = (title, url, text) => card(title, h('span', { class: 'muted small mono', text: url }), h('pre', { class: 'log tall json', text: text || '(nothing)' }));
    return [checks, h('div', { class: 'grid g3' }, pre('status.json', d.urls.status, d.status_preview),
      pre('Community feed', d.urls.feed, d.feed_preview), pre('Our realm record', d.urls.site, d.record_preview))];
  }

  // ---- Speed --------------------------------------------------------------------------------
  function speed(d) {
    const checks = card('Swiftness checks', h('span', { class: 'row' }, h('span', { class: 'muted small', text: 'measured ' + when(d.at) }),
      btn('Run checks', () => load(true), 'small primary')),
    h('ul', { class: 'checks' }, d.checks.map((c) => h('li', null, dot(c.ok ? 'ok' : 'bad'), h('div', { class: 'grow' }, h('b', { text: c.label }),
      h('div', { class: 'muted small mono', text: c.detail }))))));
    const timing = card('Timings from the server', h('span', { class: 'muted small', text: 'public = through Caddy and TLS · origin = wu-play direct' }), table([
      { t: 'Request', f: (r) => h('span', { class: 'mono', text: r.label }), cls: 'wrap' }, { t: 'Path', f: (r) => badge(r.where, r.where === 'public' ? '' : 'off'), cls: 'hide-s' },
      { t: 'HTTP', f: (r) => r.error ? h('span', { class: 'err', text: r.error }) : String(r.status), cls: 'num' },
      { t: 'TTFB', f: (r) => (r.ttfb_ms === null || r.ttfb_ms === undefined ? '-' : r.ttfb_ms + ' ms'), cls: 'num' },
      { t: 'Total', f: (r) => (r.total_ms === null || r.total_ms === undefined ? '-' : r.total_ms + ' ms'), cls: 'num' },
      { t: 'Bytes', f: (r) => bytes(r.bytes), cls: 'num hide-s' }, { t: 'Enc', f: (r) => r.encoding || '-', cls: 'hide-s' },
      { t: 'Mbit/s', f: (r) => (r.mbps ? String(r.mbps) : '-'), cls: 'num hide-s' }], d.rows));
    const enc = card('Caddy encode and precompressed files', null, table([
      { t: 'Site', f: (e) => h('span', { class: 'mono', text: e.site }) }, { t: 'encode', f: (e) => h('span', { class: 'mono', text: e.encode }) }],
    d.encodes, 'No encode lines in the Caddyfile.'), table([
      { t: 'www file', f: (p) => h('span', { class: 'mono', text: p.name }) }, { t: 'Size', f: (p) => bytes(p.bytes), cls: 'num' },
      { t: '.br', f: (p) => (p.br ? `${bytes(p.br.bytes)} ×${p.br.ratio}${p.br.stale ? ' STALE' : ''}` : 'missing'), cls: 'num' },
      { t: '.gz', f: (p) => (p.gz ? `${bytes(p.gz.bytes)} ×${p.gz.ratio}${p.gz.stale ? ' STALE' : ''}` : 'missing'), cls: 'num' }],
    d.precompressed, 'No client in www.'));
    const done = d.plan.filter((p) => p.status === 'done').length;
    const plan = card(`Speed-pass plan (${done}/${d.plan.length} done)`, h('span', { class: 'muted small', text: 'from wrath-browser-loadtime-plan.md · stored on the server' }), table([
      { t: '', f: (p) => badge(p.level, p.level === 'P0' ? 'p0' : p.level === 'P1' ? 'p1' : p.level === 'P2' ? 'p2' : 'off'), cls: 'w1' },
      { t: 'Item', f: (p) => h('span', { class: p.status === 'done' ? 'done' : '', text: p.title }) },
      { t: 'Where', f: (p) => h('span', { class: 'muted', text: p.where }), cls: 'hide-s' },
      { t: 'Status', cls: 'act-cell', f: (p) => {
        const sel = h('select', { class: 'st-' + p.status, 'aria-label': 'status of ' + p.title }, d.states.map((s) => h('option', { value: s, text: s })));
        sel.value = p.status;
        sel.addEventListener('change', () => run('speed_mark', { id: p.id, status: sel.value }));
        return sel;
      } }], d.plan));
    return [h('div', { class: 'grid g2' }, checks, enc), timing, plan];
  }

  // ---- Logs ---------------------------------------------------------------------------------
  let logData = null;
  function logs(d) {
    logData = d;
    const L = ui.logs;
    const srcs = ['worldserver', 'authserver', 'wu-portal', 'wu-play', 'caddy', 'database', 'gmconsole'];
    const seg = h('div', { class: 'seg' }, srcs.map((s) => h('button', { type: 'button', class: s === L.c ? 'on' : '', text: s,
      onclick: () => { L.c = s; load(); } })));
    const filter = h('input', { type: 'search', placeholder: 'Filter (text)', value: L.q, class: 'grow' });
    const nsel = h('select', { 'aria-label': 'lines' }, [200, 300, 1000, 3000].map((n) => h('option', { value: n, text: n + ' lines' })));
    nsel.value = String(L.n);
    nsel.addEventListener('change', () => { L.n = Number(nsel.value); load(); });
    const auto = h('input', { type: 'checkbox', checked: L.auto || null });
    auto.addEventListener('change', () => { L.auto = auto.checked; });
    const pre = h('pre', { class: 'log full' });
    function paint() {
      const f = L.q.toLowerCase();
      const lines = (logData.lines || []).filter((l) => !f || l.toLowerCase().includes(f));
      pre.replaceChildren(...lines.map((l) => h('span', { class: /error|fatal|crash|exception/i.test(l) ? 'e' : /warn/i.test(l) ? 'w' : '', text: l + '\n' })));
      count.textContent = `${lines.length} of ${(logData.lines || []).length} lines · ${logData.container || ''}`;
      pre.scrollTop = pre.scrollHeight;
    }
    const count = h('span', { class: 'muted small' });
    filter.addEventListener('input', () => { L.q = filter.value; paint(); });
    const bar = h('div', { class: 'row wrap' }, seg, filter, nsel, h('label', { class: 'chk' }, auto, ' auto-refresh 5 s'), count);
    setTimeout(paint, 0);
    return [card('Logs', null, bar, pre)];
  }

  // ---- loading and refresh ------------------------------------------------------------------
  const PATH = {
    overview: () => '/api/overview', players: () => '/api/players', updates: () => '/api/updates',
    streaming: () => '/api/streaming', beacons: (f) => '/api/beacons' + (f ? '?fresh=1' : ''),
    speed: (f) => '/api/speed' + (f ? '?fresh=1' : ''),
    logs: () => `/api/logs?c=${encodeURIComponent(ui.logs.c)}&n=${ui.logs.n}`,
  };
  const RENDER = { overview, players, updates, streaming, beacons, speed, logs };
  const EVERY = { overview: 10000, players: 10000, updates: 15000, streaming: 15000, logs: 5000 };
  let loading = 0;
  async function load(fresh) {
    const my = ++loading, t = tab;
    if (fresh || !main.childElementCount) main.classList.add('busy');
    try {
      const d = await api(PATH[t](fresh));
      if (my !== loading || t !== tab) return;
      if (d.realm) setPill(d.realm);
      if (d.jobs) { setJobs(d.jobs); if (d.jobs.some((j) => j.state === 'running')) watchJobs(); }
      // keep what the owner is typing: don't redraw a tab while a field in it has focus
      const act = document.activeElement;
      if (!fresh && act && main.contains(act) && /INPUT|TEXTAREA|SELECT/.test(act.tagName) && t !== 'logs') return;
      if (t === 'logs' && main.querySelector('pre.log.full')) {
        logData = d; const f = main.querySelector('input[type=search]'); if (f) f.dispatchEvent(new Event('input')); return;
      }
      main.replaceChildren(...RENDER[t](d).filter(Boolean));
      stamp.textContent = 'updated ' + new Date().toLocaleTimeString();
    } catch (e) {
      if (my === loading) main.replaceChildren(card('Could not load', null, h('p', { class: 'err', text: e.message }), btn('Try again', () => load(true))));
    } finally { main.classList.remove('busy'); }
  }
  function refresh() { load(false); }
  function show(k) {
    if (!RENDER[k]) k = 'overview';
    const changed = k !== tab;
    tab = k;
    nav.querySelectorAll('a').forEach((a) => a.classList.toggle('on', a.dataset.tab === k));
    if (changed) main.replaceChildren();
    if (k === 'logs') ui.logs.q = ui.logs.q || '';
    load(false);
    clearInterval(timer);
    if (EVERY[k]) timer = setInterval(() => { if (document.hidden) return; if (k === 'logs' && !ui.logs.auto) return; refresh(); }, EVERY[k]);
  }
  window.addEventListener('hashchange', () => show(location.hash.slice(1)));
  tab = '';
  show(location.hash.slice(1) || 'overview');
  // the realm pill stays current on every tab
  if (location.hash.slice(1) !== 'overview') api('/api/overview').then((d) => { setPill(d.realm); setJobs(d.jobs); }).catch(() => {});
})();
