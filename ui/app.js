// OmniKSU Build Studio Frontend Controller
// Author: Aniket Sharma <https://github.com/aniketlab>

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

const logEl = $('#log');
let timer = null;
let clock = null;
let plainLogs = [];
let t0 = 0;

// 1. Theme Management (Sage Light vs Charcoal Red Dark)
const htmlEl = document.documentElement;
const themeToggle = $('#theme-toggle');
const themeIcon = $('#theme-icon');
const themeName = $('#theme-name');

function setTheme(theme) {
  htmlEl.setAttribute('data-theme', theme);
  localStorage.setItem('omniksu_theme', theme);
  if (theme === 'dark') {
    themeIcon.textContent = '☀️';
    themeName.textContent = 'Light';
  } else {
    themeIcon.textContent = '🌙';
    themeName.textContent = 'Dark';
  }
}

// Initialize theme from storage or default to light
const savedTheme = localStorage.getItem('omniksu_theme') || 'light';
setTheme(savedTheme);

themeToggle.onclick = () => {
  const current = htmlEl.getAttribute('data-theme') || 'light';
  setTheme(current === 'light' ? 'dark' : 'light');
  log('INFO', `Theme switched to: ${current === 'light' ? 'Dark Mode (Charcoal + Red)' : 'Light Mode (Olive macOS)'}`);
};

// 2. Logging System
function log(tag, msg) {
  const t = new Date().toLocaleTimeString('en-GB');
  plainLogs.push(`[${t}] [${tag}] ${msg}`);
  const d = document.createElement('div');
  d.innerHTML = `<span class="ts">${t}</span>  <span class="t-${tag}">${tag.padEnd(5)}</span> ${msg}`;
  logEl.appendChild(d);
  logEl.scrollTop = logEl.scrollHeight;
}

// 3. Segmented Controls Helper
function seg(id, cb) {
  $$('#' + id + ' button').forEach(b => {
    b.onclick = () => {
      $$('#' + id + ' button').forEach(x => x.classList.remove('on'));
      b.classList.add('on');
      if (cb) cb(b);
    };
  });
}

const first = id => {
  const onEl = $('#' + id + ' .on');
  if (!onEl) return '';
  const title = onEl.querySelector('.seg-title');
  if (title) return title.textContent.trim();
  return onEl.childNodes[0].textContent.trim();
};

// 4. UI State Synchronization
function sync() {
  const codename = ($('#dev-codename').value || '').trim() || 'Universal Device';
  $('#k1').textContent = codename;
  $('#k2').textContent = first('eng');
  $('#k3').textContent = first('hook');

  const isCloud = $('#mode .on').dataset.m === 'cloud';
  $('#k4').textContent = isCloud ? 'GitHub Actions' : 'Local · WSL2';
  $('#sn').textContent = isCloud ? 'GitHub Runner' : 'WSL2 Ubuntu';
  $('#sd').textContent = isCloud ? 'Ubuntu 22.04 · 16GB RAM' : `Local PC · ${$('#thr').value} threads`;
}

function on_mode_change(b) {
  const isCloud = b.dataset.m === 'cloud';
  $('#cloud').classList.toggle('hide', !isCloud);
  $('#local').classList.toggle('hide', isCloud);
  sync();
  log('INFO', 'Build mode: ' + (isCloud ? 'Cloud (GitHub Actions - Free Runner)' : 'Local (WSL2 / Native Linux)'));
}

seg('mode', on_mode_change);
seg('eng', sync);
seg('hook', sync);

$('#dev-codename').oninput = sync;
$('#toolchain-preset').onchange = () => {
  log('INFO', 'Toolchain preset: ' + $('#toolchain-preset').selectedOptions[0].text);
  sync();
};

// --- Smart Repo Inspector & Auto-Configuration ---
function populate_dropdowns(info, targetBranch = '', targetDefconfig = '') {
  // 1. Branches dropdown
  if (info.branches && info.branches.length > 0) {
    const sel = document.createElement('select');
    sel.id = 'kernel-branch';
    const desiredBranch = targetBranch || info.active_branch || '';
    if (desiredBranch && !info.branches.includes(desiredBranch)) {
      info.branches.unshift(desiredBranch);
    }
    info.branches.forEach(b => {
      const opt = document.createElement('option');
      opt.value = b;
      opt.textContent = b;
      if (b === desiredBranch) opt.selected = true;
      sel.appendChild(opt);
    });
    if (desiredBranch) sel.value = desiredBranch;
    sel.onchange = () => {
      scan_repo($('#kernel-repo').value.trim(), sel.value);
    };
    $('#branch-container').innerHTML = '';
    $('#branch-container').appendChild(sel);
  }

  // 2. Defconfigs dropdown
  if (info.defconfigs && info.defconfigs.length > 0) {
    const sel = document.createElement('select');
    sel.id = 'kernel-defconfig';
    const codename = ($('#dev-codename').value || '').toLowerCase().trim();
    let bestMatch = '';

    if (targetDefconfig) {
      const hasDefconfig = info.defconfigs.some(c => c === targetDefconfig || c.endsWith('/' + targetDefconfig));
      if (!hasDefconfig) {
        info.defconfigs.unshift(targetDefconfig);
      }
    }

    info.defconfigs.forEach(cfg => {
      const opt = document.createElement('option');
      opt.value = cfg;
      opt.textContent = cfg;
      if (targetDefconfig && (cfg === targetDefconfig || cfg.endsWith('/' + targetDefconfig))) {
        bestMatch = cfg;
      } else if (!bestMatch && codename && cfg.toLowerCase().includes(codename)) {
        if (!bestMatch || cfg.includes('-perf')) bestMatch = cfg;
      }
      sel.appendChild(opt);
    });

    if (bestMatch) sel.value = bestMatch;
    else if (info.defconfigs.length > 0) sel.value = info.defconfigs[0];

    $('#defconfig-container').innerHTML = '';
    $('#defconfig-container').appendChild(sel);
  }
}

function show_compat_card(info) {
  const card = $('#compat-card');
  if (!card) return;
  card.classList.remove('hide');

  const ver = info.version_info ? (info.version_info.full_version || info.version_info.family) : 'Unknown';
  $('#cc-ver').textContent = 'Linux ' + ver;
  $('#cc-os').textContent = info.android_target || 'Android 8.0 - 12.0';
  $('#cc-engine').textContent = (info.recommended_engine || 'BakaSU').toUpperCase();
  $('#cc-rationale').textContent = info.rationale || 'Kernel source configuration verified.';

  const statusEl = $('#cc-status');
  const iconEl = $('#cc-status-icon');
  const noticeEl = $('#cc-notice');

  function setStatus(type, iconSvg, html) {
    if (statusEl) statusEl.className = 'cc-status ' + type;
    if (iconEl) iconEl.innerHTML = iconSvg;
    if (noticeEl) noticeEl.innerHTML = html;
  }

  const svgCheck = '<path d="M20 6L9 17l-5-5"/>';
  const svgWarn = '<circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/>';
  const svgErr = '<circle cx="12" cy="12" r="9"/><path d="M15 9l-6 6M9 9l6 6"/>';
  const svgInfo = '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>';

  // Safety hardware check against connected phone
  if (window.connectedDevice && window.connectedDevice.connected) {
    const dev = window.connectedDevice;
    const phoneKernel = dev.kernel_full_version || dev.kernel_release || '';
    const repoKernel = info.version_info ? (info.version_info.full_version || info.version_info.family) : '';

    if (repoKernel && phoneKernel) {
      const isExactFull = dev.kernel_release.includes(repoKernel) || repoKernel === dev.kernel_full_version;
      const isSameFamily = repoKernel.startsWith(dev.kernel_family);

      if (isExactFull || (isSameFamily && repoKernel === dev.kernel_full_version)) {
        setStatus(
          'status-ok',
          svgCheck,
          `Hardware Verified: Matches connected ${dev.model} (${dev.kernel_release} · Stock ${dev.is_stock_rom ? (dev.miui_version || 'ROM') : 'ROM'}).`
        );


      } else if (isSameFamily) {
        // e.g. Phone is 4.4.153, Repo is 4.4.271
        setStatus(
          'status-warn',
          svgWarn,
          `Sublevel Variance: Source is Linux ${repoKernel} while device runs ${dev.kernel_release}. Upstream kernels may cause OEM driver incompatibility on stock builds.`
        );


      } else {
        // Critical Mismatch (e.g. 4.4 vs 4.19 / 5.4)
        setStatus(
          'status-err',
          svgErr,
          `Architecture Mismatch: Source is Linux ${repoKernel} but connected device runs ${dev.kernel_release}. Incompatible kernel version.`
        );


      }
    } else {
      setStatus(
        'status-info',
        svgInfo,
        `Target System: ${info.android_target || 'Compatible Android version'}. Verify kernel compatibility prior to flashing.`
      );


    }
  } else {
    setStatus(
      'status-info',
      svgInfo,
      `Target System: ${info.android_target || 'Compatible Android version'}. Verify kernel compatibility prior to flashing.`
    );


  }

  // Auto-switch Engine button in UI
  if (info.recommended_engine) {
    $$('#eng button').forEach(b => {
      const val = b.dataset.val;
      if (val === info.recommended_engine) {
        $$('#eng button').forEach(x => x.classList.remove('on'));
        b.classList.add('on');
      }
    });
  }

  // Auto-switch Hook button in UI
  if (info.recommended_hook) {
    $$('#hook button').forEach(b => {
      const val = b.dataset.val;
      if (val === info.recommended_hook) {
        $$('#hook button').forEach(x => x.classList.remove('on'));
        b.classList.add('on');
      }
    });
  }

  // Auto-switch Toolchain preset
  if (info.recommended_toolchain) {
    $('#toolchain-preset').value = info.recommended_toolchain;
  }

  sync();
}

async function scan_repo(url, branch = '', targetDefconfig = '') {
  if (!url || !url.includes('github.com')) return;
  log('INFO', 'Inspecting remote repository: ' + url + (branch ? ` (${branch})` : ''));
  setSt('Inspecting…', 'run');

  if (window.pywebview && window.pywebview.api && window.pywebview.api.inspect_repo) {
    try {
      const res = await window.pywebview.api.inspect_repo(url, branch);
      if (res && res.ok) {
        populate_dropdowns(res, branch, targetDefconfig);
        show_compat_card(res);
        log('OK', `Kernel ${res.version_info.full_version} analyzed! Found ${res.defconfigs.length} defconfigs and ${res.branches.length} branches.`);
        setSt('Ready', '');
      } else {
        log('WARN', 'Could not inspect repo: ' + (res.error || 'Unknown error'));
        setSt('Idle', '');
      }
    } catch (e) {
      log('ERR', 'Inspection error: ' + e.message);
      setSt('Idle', '');
    }
  }
}

async function search_sources(phoneKernel = '', phoneBrand = '') {
  if (typeof phoneKernel !== 'string') phoneKernel = '';
  if (typeof phoneBrand !== 'string') phoneBrand = '';

  const q = $('#dev-search-input').value.trim();
  if (!q) {
    log('WARN', 'Please enter a device name or codename to search.');
    return;
  }

  if (!phoneKernel && window.connectedDevice) {
    phoneKernel = window.connectedDevice.kernel_full_version || window.connectedDevice.kernel_family || '';
    phoneBrand = window.connectedDevice.brand || '';
  }

  log('INFO', `Searching kernel sources matching: "${q}"${phoneKernel ? ' (Targeting Linux ' + phoneKernel + ')' : ''}...`);
  setSt('Searching…', 'run');

  const box = $('#search-results-box');
  const list = $('#search-results-list');
  box.classList.remove('hide');
  list.innerHTML = '<div style="padding: 8px; color: var(--mute);">Scanning verified profiles &amp; GitHub...</div>';

  if (window.pywebview && window.pywebview.api && window.pywebview.api.search_sources) {
    try {
      const token = ($('#tok') ? $('#tok').value.trim() : '') || localStorage.getItem('omniksu_gh_token') || '';
      const results = await window.pywebview.api.search_sources(q, phoneKernel, phoneBrand, token);
      list.innerHTML = '';
      if (!results || results.length === 0) {
        list.innerHTML = '<div style="padding: 8px; color: var(--mute);">No kernel repositories found. Try entering codename directly (e.g. whyred, beryllium).</div>';
        setSt('Idle', '');
        return;
      }

      results.forEach(item => {
        const d = document.createElement('div');
        d.className = 'sb-item' + (item.is_recommended ? ' rec' : '');
        const recBadge = item.is_recommended ? `<span class="rec-badge">⭐ Recommended</span>` : '';
        const metaReason = item.recommendation_reason ? `<span class="sb-meta-rec">[${item.recommendation_reason}]</span> ` : '';

        d.innerHTML = `
          <div class="sb-item-main">
            <div class="sb-item-header">
              <span class="sb-item-title" title="${item.full_name}">${item.full_name}</span>
              ${recBadge}
            </div>
            <div class="sb-item-meta">
              ${metaReason}<span>${item.description.slice(0, 55)}</span> · <span class="sb-branch-tag">${item.default_branch}</span>
            </div>
          </div>
          <div class="sb-item-stars">★ ${item.stars}</div>
        `;

        d.onclick = () => {
          $('#kernel-repo').value = item.clone_url;
          // Set real-time codename immediately
          const codename = item.detected_codename || q.toLowerCase().replace(/[^a-z0-9_]/g, '_');
          $('#dev-codename').value = codename;
          sync(); // Real-time update live status banner (#k1, etc.)
          box.classList.add('hide');
          log('OK', `Selected repository: ${item.full_name} (Codename: ${codename})`);
          scan_repo(item.clone_url, item.target_branch || item.default_branch, item.target_defconfig || '');
        };
        list.appendChild(d);
      });
      setSt('Idle', '');
    } catch (e) {
      list.innerHTML = `<div style="padding: 8px; color: #e53935;">Search failed: ${e.message}</div>`;
      setSt('Idle', '');
    }
  }
}

async function detect_phone() {
  log('INFO', 'Scanning USB ports for connected Android devices via ADB...');
  setSt('Checking USB…', 'run');

  if (window.pywebview && window.pywebview.api && window.pywebview.api.detect_connected_phone) {
    try {
      const res = await window.pywebview.api.detect_connected_phone();
      if (res && res.connected) {
        window.connectedDevice = res;
        $('#dev-codename').value = res.codename;
        $('#dev-search-input').value = res.codename;
        
        log('OK', `Hardware Connected: ${res.model} [${res.codename}] | Running Linux ${res.kernel_release} on ${res.is_stock_rom ? 'Stock ' + (res.miui_version || 'OEM') : 'Android ' + res.android_version}`);

        // 1. Check if verified hardware preset exists in devices.json (e.g. whyred, enchilada, hotdogb, etc.)
        if (res.matched_preset) {
          const p = res.matched_preset;
          log('OK', `⭐ Auto-Matched 100% Tested Profile for [${p.name || res.codename}]!`);
          log('INFO', `Auto-configuring official kernel source (${p.repo_url}) branch: ${p.branch}...`);

          $('#kernel-repo').value = p.repo_url;
          if (p.preferred_toolchain) $('#toolchain-preset').value = p.preferred_toolchain;

          // Switch engine & hook mode
          if (p.root_engine) {
            $$('#eng button').forEach(b => {
              b.classList.toggle('on', b.dataset.val === p.root_engine);
            });
          }
          if (p.hook_mode) {
            $$('#hook button').forEach(b => {
              b.classList.toggle('on', b.dataset.val === p.hook_mode);
            });
          }

          sync();
          setSt('Phone Configured', '');
          // Automatically scan the verified official repository with exact matching branch & defconfig!
          await scan_repo(p.repo_url, p.branch, p.defconfig);
        } else {
          // If not in verified presets, search GitHub with phone kernel and brand filters
          setSt('Connected', '');
          search_sources(res.kernel_full_version || res.kernel_family, res.brand);
        }
      } else {
        log('WARN', res.error || 'No device detected. Connect phone via USB with USB Debugging enabled.');
        setSt('No Device', 'err');
      }
    } catch (e) {
      log('ERR', 'ADB error: ' + e.message);
      setSt('Idle', '');
    }
  }
}

$('#btn-scan-repo').onclick = () => {
  const branchEl = $('#kernel-branch');
  const branch = branchEl ? (branchEl.value || '') : '';
  scan_repo($('#kernel-repo').value.trim(), branch);
};

$('#kernel-repo').onblur = () => {
  const val = $('#kernel-repo').value.trim();
  if (val && val.includes('github.com') && $('#compat-card').classList.contains('hide')) {
    scan_repo(val);
  }
};

$('#btn-search-sources').onclick = () => search_sources();
$('#dev-search-input').onkeydown = e => {
  if (e.key === 'Enter') search_sources();
};

$('#btn-detect-phone').onclick = () => detect_phone();

// Sidebar navigation
$$('.nav').forEach(n => {
  n.onclick = () => {
    $$('.nav').forEach(x => x.classList.remove('on'));
    n.classList.add('on');
    const target = n.dataset.nav;
    if (target && target !== 'new-build') {
      log('INFO', `Navigated to view: [${n.querySelector('span').textContent}]`);
    }
  };
});

// Password visibility toggle & token persistence
const savedTok = localStorage.getItem('omniksu_gh_token');
if (savedTok && $('#tok') && !$('#tok').value) {
  $('#tok').value = savedTok;
}
if ($('#tok')) {
  $('#tok').oninput = () => {
    localStorage.setItem('omniksu_gh_token', $('#tok').value.trim());
  };
}

// Password visibility toggle
$('#eye').onclick = () => {
  const t = $('#tok');
  const isPass = t.type === 'password';
  t.type = isPass ? 'text' : 'password';
  $('#eye').textContent = isPass ? 'Hide' : 'Show';
};

// Thread slider
$('#thr').oninput = e => {
  const v = e.target.value;
  $('#thv').textContent = `${v} threads${v == 16 ? ' (all cores)' : ''}`;
  sync();
};

// Directory Browse button (Calls Python pywebview API if available)
$('#brw').onclick = async () => {
  if (window.pywebview && window.pywebview.api && window.pywebview.api.select_folder) {
    const selected = await window.pywebview.api.select_folder();
    if (selected) {
      $('#out').value = selected;
      log('INFO', 'Output directory set to: ' + selected);
    }
  } else {
    $('#out').value = 'C:\\OmniKSU\\output';
    log('INFO', 'Output directory updated: C:\\OmniKSU\\output');
  }
};

// Clear & Copy logs
$('#clr').onclick = () => {
  logEl.innerHTML = '';
  plainLogs = [];
};

$('#cpy').onclick = async () => {
  try {
    await navigator.clipboard.writeText(plainLogs.join('\n'));
    $('#cpy').textContent = 'Copied!';
  } catch (e) {
    $('#cpy').textContent = 'Copy failed';
  }
  setTimeout(() => $('#cpy').textContent = 'Copy Logs', 1400);
};

// Pipeline & Progress
function setSt(statusText, chipClass) {
  const s = $('#st');
  s.innerHTML = '<i></i>Status: ' + statusText;
  s.className = 'chip ' + (chipClass || '');
}

function prog(percent) {
  $('#pb').style.width = percent + '%';
  $('#pc').textContent = percent + '%';
}

function pipe(activeStage, allDone = false) {
  $$('#pipe .stg').forEach((s, i) => {
    s.className = 'stg' + (allDone || i < activeStage ? ' done' : i === activeStage ? ' act' : '');
  });
  $$('#pipe .stg u').forEach((u, i) => {
    u.textContent = (allDone || i < activeStage) ? '✓' : (i + 1);
  });
}

function fmt() {
  const s = Math.floor((Date.now() - t0) / 1000);
  return String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
}

// Build Execution
async function on_build_start() {
  const isCloud = $('#mode .on').dataset.m === 'cloud';
  const codename = ($('#dev-codename').value || '').trim() || 'generic';
  const kernelRepo = ($('#kernel-repo').value || '').trim();
  const kernelBranch = ($('#kernel-branch').value || '').trim() || 'main';
  const defconfigName = ($('#kernel-defconfig').value || '').trim();
  const toolchainPreset = $('#toolchain-preset').value;
  const eng = first('eng');
  const hook = first('hook');

  if (isCloud && (!kernelRepo || !defconfigName)) {
    log('ERR', 'Please enter Kernel Git Repo URL and Defconfig File Name before starting!');
    setSt('Input Required', 'err');
    return;
  }

  t0 = Date.now();
  $('#go').disabled = true;
  $('#stop').disabled = false;
  setSt('Building…', 'run');
  prog(0);
  pipe(0);

  clock = setInterval(() => {
    $('#el').textContent = 'Elapsed ' + fmt();
  }, 1000);

  log('INFO', `Starting OmniKSU ${isCloud ? 'Cloud' : 'Local'} Build Pipeline for [${codename}]...`);

  // Check if running in PyWebView with Python backend
  if (window.pywebview && window.pywebview.api) {
    try {
      const payload = {
        mode: isCloud ? 'cloud' : 'local',
        device: codename,
        kernel_repo: kernelRepo,
        kernel_branch: kernelBranch,
        defconfig_name: defconfigName,
        toolchain_choice: toolchainPreset,
        engine: $('#eng .on')?.dataset.val || 'bakasu',
        hook: $('#hook .on')?.dataset.val || 'manual',
        token: $('#tok').value,
        repo: $('#target-repo').value,
        threads: $('#thr').value,
        out_dir: $('#out').value
      };

      if (isCloud) {
        log('INFO', 'Dispatching GitHub Action workflow on ' + payload.repo + '...');
        const res = await window.pywebview.api.start_cloud_build(payload);
        if (!res.ok) {
          log('ERR', res.message);
          setSt('Failed', 'err');
          on_build_stop();
        }
      } else {
        log('INFO', 'Launching Local Build...');
        const res = await window.pywebview.api.start_local_build(payload);
        if (!res.ok) {
          log('ERR', res.message);
          setSt('Failed', 'err');
          on_build_stop();
        }
      }
    } catch (e) {
      log('ERR', 'Build dispatch error: ' + e.message);
      on_build_stop();
    }
  } else {
    // Interactive Demonstration Mode (Simulated steps for preview)
    const stages = [
      [0, 'INFO', `Detecting device: ${devName} (Kernel ${k})`],
      [1, 'INFO', 'Cloning kernel source tree (depth=1)...'],
      [1, 'INFO', 'Toolchain resolved: AOSP GCC 4.9 / Clang 11'],
      [2, 'PATCH', `Integrating ${eng} into drivers/kernelsu/`],
      [2, 'PATCH', `Applying ${hook} hooks: fs/exec.c, fs/open.c, fs/stat.c, kernel/reboot.c`],
      [2, 'PATCH', 'CONFIG_KSU=y, CONFIG_OVERLAY_FS=y written to defconfig'],
      [3, 'BUILD', `make -j${$('#thr').value} ${devName}_defconfig`],
      [3, 'BUILD', 'Compiling kernel drivers and filesystem hooks...'],
      [3, 'BUILD', 'Linking vmlinux -> Generating Image.gz-dtb'],
      [4, 'PACK', 'Packaging output with AnyKernel3 flashable archive...'],
      [4, 'OK', `OmniKSU-${devName}-${eng}-Flashable.zip created successfully!`]
    ];

    let i = 0;
    timer = setInterval(() => {
      const s = stages[i++];
      log(s[1], s[2]);
      pipe(s[0]);
      prog(Math.round((i / stages.length) * 100));

      if (i >= stages.length) {
        clearInterval(timer);
        clearInterval(clock);
        pipe(0, true);
        setSt('Success', '');
        $('#go').disabled = false;
        $('#stop').disabled = true;
      }
    }, 700);
  }
}

function on_build_stop() {
  clearInterval(timer);
  clearInterval(clock);
  log('ERR', 'Build cancelled by user');
  setSt('Cancelled', 'err');
  $('#go').disabled = false;
  $('#stop').disabled = true;

  if (window.pywebview && window.pywebview.api && window.pywebview.api.cancel_build) {
    window.pywebview.api.cancel_build();
  }
}

$('#go').onclick = on_build_start;
$('#stop').onclick = on_build_stop;

// Initial logs
log('INFO', 'OmniKSU Build Studio v1.0.0 initialized');
log('INFO', 'Cloud runner: Ubuntu 22.04 (16GB RAM) ready');
log('INFO', 'Waiting for build configuration...');
sync();
