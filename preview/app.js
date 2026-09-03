/* OBS Overlay Import Utility — preview UI logic (dev branch).
 * Functional demo of the Windows Tk app. Real engine logic runs in the
 * Windows application; here buttons drive clearly-labelled simulated flows
 * so the UI can be reviewed, fixed on dev, and later ported to Electron.
 */
(function () {
  'use strict';

  var app = document.getElementById('app');

  /* ---------------- Console / status helpers (like the Tk queue) ------- */
  function ts() { return '[' + new Date().toTimeString().slice(0, 8) + ']'; }
  function log(consoleEl, text, dim) {
    if (!consoleEl) return;
    var line = document.createElement('div');
    line.textContent = (dim ? '' : ts() + ' ') + text;
    if (dim) line.style.opacity = '.55';
    consoleEl.appendChild(line);
    consoleEl.scrollTop = consoleEl.scrollHeight;
  }
  function clear(consoleEl) { if (consoleEl) consoleEl.innerHTML = ''; }
  function setStatus(el, text) { if (el) el.textContent = text; }
  function pageStatusOf(btn) {
    var page = btn.closest('.page');
    return page ? page.querySelector('.run-row .status') : null;
  }

  /* Step runner: executes [{fn, ms}] sequentially, disabling during run. */
  function runSteps(btn, steps, finalText) {
    if (btn.dataset.busy) return;
    btn.dataset.busy = '1';
    var original = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Working…';
    var i = 0;
    function next() {
      if (i >= steps.length) {
        btn.disabled = false;
        btn.textContent = original;
        delete btn.dataset.busy;
        if (finalText) setStatus(pageStatusOf(btn), finalText);
        return;
      }
      var s = steps[i++];
      setTimeout(function () { try { s.fn(); } catch (e) { console.error(e); } next(); }, s.ms || 400);
    }
    next();
  }

  /* ---------------- Theme (Windows default / White / Dark) -------------- */
  var THEME_KEY = 'obs_preview_theme';
  var themeSel = document.getElementById('themeSel');
  var settingsTheme = document.getElementById('settingsTheme');
  function systemDark() {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  }
  function applyTheme(v) {
    var dark = v === 'Dark' || ((v === 'Windows default' || v === 'system') && systemDark());
    app.className = 'app ' + (dark ? 'theme-dark' : 'theme-light');
    // Theme the whole document (stage bar, drawer, modals, page background),
    // not just #app — otherwise black text/light panels survive in dark mode.
    document.body.classList.toggle('theme-dark', dark);
    document.body.classList.toggle('theme-light', !dark);
    settingsTheme.value = v === 'Dark' ? 'Dark' : (v === 'White' ? 'White' : 'Windows default');
    themeSel.value = v === 'Dark' ? 'theme-dark' : (v === 'White' ? 'theme-light2' : 'theme-light');
  }
  themeSel.addEventListener('change', function () {
    applyTheme(themeSel.value === 'theme-dark' ? 'Dark' : (themeSel.value === 'theme-light2' ? 'White' : 'Windows default'));
  });
  settingsTheme.addEventListener('change', function () { applyTheme(settingsTheme.value); });
  try { applyTheme(localStorage.getItem(THEME_KEY) || 'Windows default'); }
  catch (e) { applyTheme('Windows default'); }

  /* ---------------- UI zoom (75–150%, like the app zoom) ---------------- */
  var zoom = document.getElementById('zoom');
  var uiScale = document.getElementById('uiScale');
  var zoomVal = document.getElementById('zoomVal');
  var uiScaleVal = document.getElementById('uiScaleVal');
  function applyZoom(v) {
    document.documentElement.style.setProperty('--uz', (v / 100).toFixed(2));
    zoom.value = v; uiScale.value = v;
    zoomVal.textContent = v + '%'; uiScaleVal.textContent = v + '%';
  }
  zoom.addEventListener('input', function () { applyZoom(+this.value); });
  uiScale.addEventListener('input', function () { applyZoom(+this.value); });
  document.getElementById('zoomReset').addEventListener('click', function () { applyZoom(100); });

  /* ---------------- Navigation ------------------------------------------- */
  var navs = document.querySelectorAll('.nav-item');
  var pages = document.querySelectorAll('.page');
  function show(page) {
    navs.forEach(function (n) { n.classList.toggle('active', n.dataset.page === page); });
    pages.forEach(function (p) { p.classList.toggle('visible', p.dataset.page === page); });
  }
  navs.forEach(function (n) {
    n.addEventListener('click', function () { show(n.dataset.page); });
  });
  window.addEventListener('hashchange', function () { show(location.hash.replace('#', '')); });
  if (location.hash) show(location.hash.replace('#', '')); // deep link, e.g. #settings
  document.getElementById('collapseArrow').addEventListener('click', function () {
    var collapsed = document.body.classList.toggle('sidebar-collapsed');
    this.textContent = collapsed ? '▶' : '◀';
    this.title = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
  });

  /* ---------------- Import method cards: selection + accordion ------------ */
  var importSelected = 'obs'; // mirrors app import_method_var
  function importTitle(key) {
    return key === 'streamlabs' ? 'Import Streamlabs Scene File' : 'Import OBS Scene Collection File';
  }
  function selectImportMethod(key) {
    importSelected = key;
    document.querySelectorAll('.method').forEach(function (m) {
      var on = m.dataset.method === key;
      m.classList.toggle('expanded', on);
      m.querySelector('.method-arrow').textContent = on ? '▾' : '▸';
    });
    setStatus(importStatus, 'Selected: ' + importTitle(key));
  }
  document.querySelectorAll('.method').forEach(function (m) {
    m.querySelector('.method-head').addEventListener('click', function () {
      var key = m.dataset.method;
      if (importSelected !== key) {
        selectImportMethod(key); // accordion: expand this one, collapse the rest
      } else {
        m.classList.toggle('expanded');
        m.querySelector('.method-arrow').textContent =
          m.classList.contains('expanded') ? '▾' : '▸';
      }
    });
  });
  /* ---------------- Sample data (Windows-style) -------------------------- */
  var MOCK_COLLECTIONS = ['Main Scene Collection', 'Streamer Setup (imported)', 'Gaming Overlay', 'Just Chatting - New'];
  var MOCK_SCENES = ['Intro', 'Gameplay', 'BRB', 'Ending'];
  var MOCK_SOURCES = [
    'Webcam (a1b2c3d4-0001)', 'Game Capture (a1b2c3d4-0002)',
    'Overlay.png (a1b2c3d4-0003)', 'Mic/Aux (a1b2c3d4-0004)'
  ];
  function demoPath(name) {
    // Browsers hide real paths; the real Windows app shows C:\… dialogs.
    return 'C:\\Users\\Streamer\\Downloads\\' + name;
  }

  /* ---------------- File/folder pickers (real Windows dialogs in the app) */
  function wirePicker(btn, input, opts) {
    var f = document.createElement('input');
    f.type = 'file'; f.style.display = 'none';
    if (opts.dir) { f.setAttribute('webkitdirectory', ''); f.setAttribute('mozdirectory', ''); }
    if (opts.accept) f.accept = opts.accept;
    document.body.appendChild(f);
    btn.addEventListener('click', function () { f.click(); });
    f.addEventListener('change', function () {
      if (!f.files.length) return;
      var name = opts.dir ? f.files[0].webkitRelativePath.split('/')[0] : f.files[0].name;
      input.value = demoPath(name);
      input.dataset.picked = name;
      if (opts.onPick) opts.onPick(name);
      f.value = '';
    });
  }

  function pageSelector(page, sel) { return document.querySelector('[data-page="' + page + '"] ' + sel); }
  function methodInput(method) { return pageSelector('import', '[data-method="' + method + '"] .method-body input[type=text]'); }
  function methodBrowse(method) { return pageSelector('import', '[data-method="' + method + '"] .method-body .btn'); }

  /* ---------------- Import page ------------------------------------------ */
  var importConsole = pageSelector('import', '.console');
  var importStatus = pageSelector('import', '.run-row .status');
  var importRun = pageSelector('import', '.run-row .btn.primary');

  wirePicker(methodBrowse('obs'), methodInput('obs'), { dir: true });
  wirePicker(document.getElementById('zipBrowse'), methodInput('obs'), { accept: '.zip' });
  wirePicker(methodBrowse('streamlabs'), methodInput('streamlabs'), { accept: '.overlay,.zip' });

  importRun.addEventListener('click', function () {
    var streamlabs = importSelected === 'streamlabs';
    var picked = ((streamlabs ? methodInput('streamlabs') : methodInput('obs')).value || '').trim();
    var chosen = importTitle(importSelected);

    if (!picked) {
      log(importConsole, 'Error: choose a ' + (streamlabs ? '.overlay file' : 'folder') + ' first.', true);
      setStatus(importStatus, 'Nothing selected yet.');
      return;
    }
    clear(importConsole);
    setStatus(importStatus, 'Selected: ' + chosen);
    var folderName = picked.split('\\').pop();

    if (streamlabs) {
      var packageName = methodInput('streamlabs').dataset.picked || folderName;
      var scaleCanvasS = document.getElementById('scaleCanvasStreamlabs');
      var scaleChecked = scaleCanvasS && scaleCanvasS.checked;
      runSteps(importRun, [
        { fn: function () { log(importConsole, 'Validating archive ' + picked + ' (traversal / size limits OK)'); } },
        { fn: function () { log(importConsole, 'Extracted to ' + demoPath(packageName + '_extracted')); } },
        { fn: function () { log(importConsole, 'Converted 5/6 sources; 1 plugin source preserved as-is'); } },
        { fn: function () { log(importConsole, scaleChecked
            ? 'Scaled layout to the active OBS canvas (1920 × 1080), aspect preserved.'
            : 'Canvas left at Streamlabs 2560 × 1440 (scale-to-canvas off).'); } },
        { fn: function () { log(importConsole, 'Device sources auto-matched to local devices; unmatched screens/devices left for manual setup in OBS.'); } },
        { fn: function () { log(importConsole, 'Collection installed as "' + packageName + '" (no name collision).'); } }
      ], 'Simulation finished — real import runs in the Windows app.');
      return;
    }
    runSteps(importRun, [
      { fn: function () {
          if (folderName.toLowerCase().indexOf('.zip') !== -1) {
            log(importConsole, 'Extracted ZIP archive beside the selected file.');
          }
          log(importConsole, 'Scanning overlay folder: ' + picked);
        } },
      { fn: function () { log(importConsole, 'Detected scene_collection.json (OBS export)'); } },
      { fn: function () {
          // Strict checks and case-sensitive matching are always enabled.
          var clean = folderName.toLowerCase().indexOf('clean') !== -1;
          if (clean) {
            log(importConsole, 'Relinked all 48 local asset references (0 missing).');
            log(importConsole, 'Created ' + folderName + '_Updated.json with corrected paths.');
            log(importConsole, 'Installed as OBS scene collection "' + folderName + '" (no name collision).');
            log(importConsole, 'Local file references: 48 online · 0 missing.', false);
            if (document.getElementById('scaleCanvas').checked) {
              log(importConsole, 'Scaled layout to the active OBS canvas (1920 × 1080), aspect preserved.');
            } else {
              log(importConsole, 'Canvas left as-is (scale-to-canvas off).', true);
            }
            log(importConsole, 'Plugin sources/filters: none — all built-in OBS types.', false);
            log(importConsole, 'OBS open: switched to it live. Original export untouched.', false);
          } else {
            log(importConsole, 'Relinked 42/48 local asset references (6 missing).');
            log(importConsole, 'Strict matching is always enabled: output blocked until every referenced file is found.', true);
          }
        } }
    ], 'Simulation finished — real import runs in the Windows app.');
  });

  /* ---------------- Export page ------------------------------------------ */
  var exportConsole = pageSelector('export', '.console');
  var exportStatus = pageSelector('export', '.run-row .status');
  var exportRun = pageSelector('export', '.run-row .btn.primary');
  var exportCombo = pageSelector('export', 'select.combo');
  var exportRefresh = pageSelector('export', '.card .btn');
  var exportDest = pageSelector('export', 'input[type=text]');
  var exportBrowse = document.getElementById('exportDestBrowse');
  var exportZip = pageSelector('export', 'input[type=checkbox]');

  function fillCombo(combo, values, keep) {
    if (!combo) return;
    var prev = combo.value;
    combo.innerHTML = '';
    values.forEach(function (v) {
      var o = document.createElement('option');
      o.textContent = v; combo.appendChild(o);
    });
    combo.disabled = false;
    if (values.indexOf(prev) !== -1) combo.value = prev; else combo.selectedIndex = 0;
  }
  fillCombo(exportCombo, MOCK_COLLECTIONS);
  exportRefresh.addEventListener('click', function () {
    fillCombo(exportCombo, MOCK_COLLECTIONS);
    log(exportConsole, 'Refreshed collection list. (sample data — real OBS detection runs on Windows)', true);
  });
  wirePicker(exportBrowse, exportDest, { dir: true });
  exportCombo.addEventListener('change', function () {
    if (!exportDest.value) setStatus(exportStatus, 'Choose a destination folder too.');
  });

  function exportInventory(collection) {
    return [
      'Collection: ' + collection,
      'Local assets found: 48 (images 31, videos 9, audio 6, other 2)',
      'Missing references: 0',
      'Browser sources: 2 projects (HTML/CSS/JS/fonts included)',
      'Plugin settings preserved: 3 sources',
      'Package name: ' + collection.replace(/\s+/g, '_') + '_package'
    ];
  }

  function modal(title, lines, onConfirm) {
    var overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    var box = document.createElement('div');
    box.className = 'modal';
    var h = document.createElement('div');
    h.className = 'modal-title'; h.textContent = title;
    var body = document.createElement('div');
    body.className = 'modal-body';
    lines.forEach(function (l) {
      var d = document.createElement('div');
      d.textContent = l; body.appendChild(d);
    });
    var foot = document.createElement('div');
    foot.className = 'modal-foot';
    var ok = document.createElement('button'); ok.className = 'btn primary'; ok.textContent = 'Continue export';
    var cancel = document.createElement('button'); cancel.className = 'btn'; cancel.textContent = 'Cancel';
    foot.appendChild(cancel); foot.appendChild(ok);
    box.appendChild(h); box.appendChild(body); box.appendChild(foot);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    function close() { overlay.remove(); }
    cancel.addEventListener('click', function () { close(); log(exportConsole, 'Export cancelled by user.'); });
    ok.addEventListener('click', function () { close(); onConfirm(); });
    overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
  }

  exportRun.addEventListener('click', function () {
    var collection = exportCombo.value;
    var dest = exportDest.value.trim();
    if (!collection || !dest) {
      log(exportConsole, 'Error: choose a scene collection and a destination folder first.', true);
      return;
    }
    clear(exportConsole);
    log(exportConsole, 'Inventory of ' + collection + ':');
    exportInventory(collection).slice(1).forEach(function (l) { log(exportConsole, '  ' + l); });
    modal('Export inventory — confirm', exportInventory(collection), function () {
      runSteps(exportRun, [
        { fn: function () { log(exportConsole, 'Staging package in ' + demoPath('staging\\')); } },
        { fn: function () { log(exportConsole, 'Copying 48 files, rewriting collection JSON with packaged paths'); } },
        { fn: function () {
            if (exportZip.checked) log(exportConsole, 'Compressed package to ZIP (export_package.zip).');
            else log(exportConsole, 'Published organized package folder (no ZIP).');
            log(exportConsole, 'Done. Revalidation at publish time passed.', false);
          } }
      ], 'Simulation finished — real export runs in the Windows app.');
    });
  });

  /* ---------------- Resizer page ----------------------------------------- */
  var resizeConsole = pageSelector('resizer', '.console');
  var resizeStatus = pageSelector('resizer', '.run-row .status');
  var resizeRun = pageSelector('resizer', '.run-btns .btn.primary');
  var resizeUndo = pageSelector('resizer', '.run-btns .btn:not(.primary)');
  var resizeCollection = pageSelector('resizer', '.row select.combo');
  var resizeRefresh = pageSelector('resizer', '.card .btn');
  var resizeScope = document.getElementById('resizeScope');
  var resizeTarget = document.getElementById('resizeTarget');
  var resizeW = document.getElementById('resizeW');
  var resizeH = document.getElementById('resizeH');
  var screenHint = pageSelector('resizer', '.hint');

  fillCombo(resizeCollection, MOCK_COLLECTIONS);
  resizeRefresh.addEventListener('click', function () {
    fillCombo(resizeCollection, MOCK_COLLECTIONS);
    log(resizeConsole, 'Refreshed collection list. (sample data — real OBS detection runs on Windows)', true);
  });
  function syncResizeTargets() {
    var scope = resizeScope.value;
    fillCombo(resizeTarget, scope === 'Scene' ? MOCK_SCENES : MOCK_SOURCES, true);
    resizeTarget.disabled = scope === 'Entire collection';
  }
  resizeScope.addEventListener('change', syncResizeTargets);
  syncResizeTargets();

  var sizeRadios = document.querySelectorAll('[data-page=resizer] input[name=size]');
  function syncSizeMode() {
    var custom = false;
    sizeRadios.forEach(function (r) {
      if (r.checked && r.parentElement.textContent.indexOf('Custom') !== -1) custom = true;
    });
    resizeW.disabled = !custom;
    resizeH.disabled = !custom;
    if (!custom) {
      setStatus(screenHint, 'Screen size: checking OBS profile…');
      setTimeout(function () { setStatus(screenHint, 'Screen size: 1920 × 1080 (active OBS profile — sample)'); }, 700);
    }
  }
  sizeRadios.forEach(function (r) {
    r.addEventListener('change', syncSizeMode);
  });
  syncSizeMode();

  var lastResize = null;
  resizeRun.addEventListener('click', function () {
    var collection = resizeCollection.value;
    if (!collection) {
      log(resizeConsole, 'Error: choose an OBS scene collection first.', true);
      return;
    }
    clear(resizeConsole);
    var scope = resizeScope.value;
    var target = scope === 'Entire collection' ? 'collection' : resizeTarget.value;
    var size = resizeW.disabled ? 'screen (1920 × 1080)' : resizeW.value + ' × ' + resizeH.value;
    var mode = document.querySelector('[data-page=resizer] input[name=mode]:checked').parentElement.textContent.trim();
    if (scope !== 'Entire collection' && !target) {
      log(resizeConsole, 'Error: choose the scene or source to resize.', true);
      return;
    }
    lastResize = { scope: scope, target: target, size: size, mode: mode };
    runSteps(resizeRun, [
      { fn: function () { log(resizeConsole, 'Scope: ' + scope + ' — target: ' + target); } },
      { fn: function () { log(resizeConsole, 'Mode: ' + mode + ' → ' + size); } },
      { fn: function () {
          log(resizeConsole, 'Backup snapshot saved (resize_backup.json).');
          log(resizeConsole, scope === 'Entire collection'
            ? 'Collection canvas updated. Undo available.' : 'Layout updated; canvas preserved.');
          resizeUndo.disabled = false;
        } }
    ], 'Simulation finished — real resize runs in the Windows app.');
  });
  resizeUndo.addEventListener('click', function () {
    if (!lastResize) return;
    clear(resizeConsole);
    log(resizeConsole, 'Restoring backup snapshot for ' + lastResize.target + '…');
    setTimeout(function () {
      log(resizeConsole, 'Undo complete. Original layout restored.', false);
      resizeUndo.disabled = true;
      lastResize = null;
    }, 600);
  });

  /* ---------------- Settings page ---------------------------------------- */
  var SETTINGS_KEY = 'obs_preview_settings';
  var customPy = document.getElementById('customPy');
  var customObs = document.getElementById('customObs');
  var saveBtn = null, restoreBtn = null, settingsStatus = null;
  document.querySelectorAll('[data-page=settings] .run-row .btn').forEach(function (b) {
    if (b.classList.contains('primary')) saveBtn = b; else restoreBtn = b;
  });
  settingsStatus = pageSelector('settings', '.run-row .status');

  function settingsInputs() {
    var behavior = document.querySelectorAll('#cardBehavior input[type=checkbox]');
    return {
      theme: settingsTheme.value,
      zoom: +uiScale.value,
      customPy: customPy.checked,
      customObs: customObs.checked,
      rememberFolder: behavior[0].checked,
      openOutput: behavior[1].checked,
      showToolLogs: document.getElementById('showToolLogs').checked
    };
  }
  function applyToolLogs(show) {
    document.querySelectorAll('.console, .log-title').forEach(function (el) {
      el.style.display = show ? '' : 'none';
    });
  }
  function writeSettingsToUI(s) {
    if (!s) return;
    applyTheme(s.theme || 'Windows default');
    applyZoom(s.zoom || 100);
    customPy.checked = !!s.customPy;
    customObs.checked = !!s.customObs;
    var behavior = document.querySelectorAll('#cardBehavior input[type=checkbox]');
    ['rememberFolder', 'openOutput'].forEach(function (key, i) {
      behavior[i].checked = !!s[key];
    });
    document.getElementById('showToolLogs').checked = s.showToolLogs !== false;
    applyToolLogs(document.getElementById('showToolLogs').checked);
    syncCustomPaths();
  }
  function syncCustomPaths() {
    document.querySelectorAll('#cardPaths .row').forEach(function (row, i) {
      var on = i === 0 ? customPy.checked : customObs.checked;
      row.querySelectorAll('input,button').forEach(function (el) { el.disabled = !on; });
    });
  }
  customPy.addEventListener('change', syncCustomPaths);
  customObs.addEventListener('change', syncCustomPaths);
  document.getElementById('showToolLogs').addEventListener('change', function () {
    applyToolLogs(this.checked);
  });
  syncCustomPaths();

  saveBtn.addEventListener('click', function () {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(settingsInputs()));
      localStorage.setItem(THEME_KEY, settingsTheme.value);
      setStatus(settingsStatus, 'Settings saved (demo persistence). Real app saves per Windows user.');
    } catch (e) {
      setStatus(settingsStatus, 'Could not save settings in this browser.');
    }
  });
  restoreBtn.addEventListener('click', function () {
    try {
      localStorage.removeItem(SETTINGS_KEY);
      localStorage.removeItem(THEME_KEY);
    } catch (e) { /* private mode */ }
    applyTheme('Windows default');
    applyZoom(100);
    customPy.checked = false;
    customObs.checked = false;
    document.querySelectorAll('#cardBehavior input[type=checkbox]').forEach(function (c) {
      c.checked = true; // defaults all on
    });
    document.getElementById('showToolLogs').checked = true; // tool logs default on
    applyToolLogs(true);
    syncCustomPaths();
    setStatus(settingsStatus, 'Defaults restored (demo). Real app restores Windows defaults.');
  });
  try { writeSettingsToUI(JSON.parse(localStorage.getItem(SETTINGS_KEY))); } catch (e) { /* first run */ }

  /* ---------------- Work plan drawer ------------------------------------- */
  var notes = document.getElementById('notes');
  document.getElementById('notesToggle').addEventListener('click', function () { notes.classList.add('open'); });
  document.getElementById('notesClose').addEventListener('click', function () { notes.classList.remove('open'); });

  window.__PREVIEW_READY__ = true;
})();