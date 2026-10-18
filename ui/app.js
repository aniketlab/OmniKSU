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

const first = id => $('#' + id + ' .on').childNodes[0].textContent.trim();

// 4. UI State Synchronization
function sync() {
  const dev = $('#dev').value;
  $('#k1').textContent = dev === 'custom' ? 'Custom kernel' : `${dev} · ${dev === 'enchilada' ? '4.9' : '4.4'}`;
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

function on_device_select() {
  const val = $('#dev').value;
  $('#cust').classList.toggle('show', val === 'custom');
  sync();
  log('INFO', 'Device profile selected: ' + $('#dev').selectedOptions[0].text);
}

seg('mode', on_mode_change);
seg('eng', sync);
seg('hook', sync);
$('#dev').onchange = on_device_select;

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
  const dev = $('#dev').value;
  const k = dev === 'enchilada' ? '4.9' : '4.4';
  const eng = first('eng');
  const hook = first('hook');
  const devName = dev === 'custom' ? ($('#cust-defconfig').value || 'custom') : dev;

  t0 = Date.now();
  $('#go').disabled = true;
  $('#stop').disabled = false;
  setSt('Building…', 'run');
  prog(0);
  pipe(0);

  clock = setInterval(() => {
    $('#el').textContent = 'Elapsed ' + fmt();
  }, 1000);

  log('INFO', `Starting OmniKSU ${isCloud ? 'Cloud' : 'Local'} Build Pipeline...`);

  // Check if running in PyWebView with Python backend
  if (window.pywebview && window.pywebview.api) {
    try {
      const payload = {
        mode: isCloud ? 'cloud' : 'local',
        device: dev,
        engine: eng.toLowerCase().includes('baka') ? 'bakasu' : 'kernelsu-next',
        hook: hook.toLowerCase().includes('manual') ? 'manual' : 'kprobes',
        token: $('#tok').value,
        repo: $('#target-repo').value,
        threads: $('#thr').value,
        out_dir: $('#out').value,
        custom_repo: $('#cust-repo').value,
        custom_branch: $('#cust-branch').value,
        custom_defconfig: $('#cust-defconfig').value
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
