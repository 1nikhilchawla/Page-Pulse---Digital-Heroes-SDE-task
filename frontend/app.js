// Page Pulse frontend. No build step, no framework — this is a single
// static page served straight out of the FastAPI app.

const form = document.getElementById('audit-form');
const input = document.getElementById('url-input');
const scanBtn = document.getElementById('scan-btn');
const banner = document.getElementById('banner');
const waveformPanel = document.getElementById('waveform-panel');
const scoreValue = document.getElementById('score-value');
const gradeValue = document.getElementById('grade-value');
const statusLabel = document.getElementById('status-label');
const ekgPath = document.getElementById('ekg-path');
const ekgGlow = document.getElementById('ekg-glow');
const tilesEl = document.getElementById('tiles');
const emptyState = document.getElementById('empty-state');
const rawToggle = document.getElementById('raw-toggle');
const rawJson = document.getElementById('raw-json');

let lastReport = null;

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const url = input.value.trim();
  if (!url) return;
  await runScan(url);
});

rawToggle.addEventListener('click', () => {
  const showing = rawJson.classList.toggle('visible');
  rawToggle.textContent = showing ? 'Hide raw JSON' : 'Show raw JSON';
});

async function runScan(url) {
  setLoading(true);
  hideBanner();

  try {
    const res = await fetch('/api/audit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();

    if (!res.ok) {
      showError(data.message || 'That URL could not be audited.');
      hideResults();
      return;
    }

    renderReport(data);
  } catch (err) {
    // Genuine network failure between browser and our own API (e.g. the
    // backend is unreachable) — the API itself never throws raw errors,
    // it always returns structured JSON, so this branch is specifically
    // "couldn't reach Page Pulse at all."
    showError('Could not reach the Page Pulse API. Is the backend running?');
    hideResults();
  } finally {
    setLoading(false);
  }
}

function setLoading(loading) {
  scanBtn.disabled = loading;
  scanBtn.textContent = loading ? 'Scanning…' : 'Run scan';
}

function showError(message) {
  banner.textContent = message;
  banner.className = 'banner error visible';
}

function showWarnings(warnings) {
  if (!warnings || warnings.length === 0) {
    hideBanner();
    return;
  }
  banner.textContent = warnings.join(' ');
  banner.className = 'banner warn visible';
}

function hideBanner() {
  banner.className = 'banner';
  banner.textContent = '';
}

function hideResults() {
  waveformPanel.classList.remove('visible');
  tilesEl.classList.remove('visible');
  rawToggle.style.display = 'none';
  rawJson.classList.remove('visible');
  emptyState.style.display = 'block';
}

function renderReport(report) {
  lastReport = report;
  emptyState.style.display = 'none';
  waveformPanel.classList.add('visible');
  tilesEl.classList.add('visible');
  rawToggle.style.display = 'inline-block';
  rawJson.textContent = JSON.stringify(report, null, 2);

  showWarnings(report.warnings);

  const { score, metrics } = report;
  const tier = scoreTier(score.total);

  scoreValue.textContent = score.total;
  scoreValue.style.color = tierColor(tier);
  gradeValue.textContent = score.grade;
  gradeValue.style.color = tierColor(tier);
  statusLabel.textContent = score.label;

  drawEkg(score.total, tier);
  renderTiles(metrics, score);
}

function scoreTier(total) {
  if (total >= 75) return 'good';
  if (total >= 40) return 'warn';
  return 'bad';
}

function tierColor(tier) {
  const styles = getComputedStyle(document.documentElement);
  if (tier === 'good') return styles.getPropertyValue('--good').trim();
  if (tier === 'warn') return styles.getPropertyValue('--warn').trim();
  return styles.getPropertyValue('--bad').trim();
}

// --- EKG waveform -----------------------------------------------------
// The line's rhythm literally represents the score: a healthy page draws
// a strong, regular heartbeat; a struggling one draws a weak, irregular
// trace; a critical one is close to flat. Built as one repeating cycle
// tiled across the viewBox rather than randomly generated, so the same
// score always draws the same, legible waveform.

function drawEkg(total, tier) {
  const amplitude = 10 + (total / 100) * 45; // weak pages barely move the pen
  const jitter = tier === 'bad' ? 6 : tier === 'warn' ? 2 : 0; // irregular baseline for unhealthy pages
  const cycles = 4;
  const cycleWidth = 800 / cycles;
  const baseline = 65;

  let d = `M0,${baseline}`;
  for (let c = 0; c < cycles; c++) {
    const x0 = c * cycleWidth;
    const wobble = jitter ? (Math.sin(c * 2.1) * jitter) : 0;
    d += ` L${x0 + cycleWidth * 0.18},${baseline + wobble}`;
    // P wave
    d += ` Q${x0 + cycleWidth * 0.24},${baseline - amplitude * 0.15} ${x0 + cycleWidth * 0.30},${baseline}`;
    // QRS complex
    d += ` L${x0 + cycleWidth * 0.36},${baseline}`;
    d += ` L${x0 + cycleWidth * 0.40},${baseline + amplitude * 0.25}`;
    d += ` L${x0 + cycleWidth * 0.45},${baseline - amplitude}`;
    d += ` L${x0 + cycleWidth * 0.50},${baseline + amplitude * 0.45}`;
    d += ` L${x0 + cycleWidth * 0.55},${baseline}`;
    // T wave
    d += ` Q${x0 + cycleWidth * 0.66},${baseline - amplitude * 0.3} ${x0 + cycleWidth * 0.78},${baseline}`;
    d += ` L${x0 + cycleWidth},${baseline}`;
  }

  ekgPath.setAttribute('d', d);
  ekgGlow.setAttribute('d', d);
  const color = tierColor(tier);
  ekgPath.style.stroke = color;
  ekgGlow.style.stroke = color;

  // Draw-in animation via stroke-dasharray, skipped for reduced-motion users.
  const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!prefersReduced) {
    const length = ekgPath.getTotalLength();
    ekgPath.style.transition = 'none';
    ekgPath.style.strokeDasharray = `${length}`;
    ekgPath.style.strokeDashoffset = `${length}`;
    ekgPath.getBoundingClientRect(); // force reflow
    ekgPath.style.transition = 'stroke-dashoffset 1.1s ease-out';
    ekgPath.style.strokeDashoffset = '0';
  } else {
    ekgPath.style.strokeDasharray = 'none';
  }
}

// --- Metric tiles -------------------------------------------------------

function renderTiles(metrics, score) {
  const tiles = [];

  tiles.push(statusTile(metrics));
  tiles.push(timingTile(metrics));

  if (metrics.is_html) {
    tiles.push(titleTile(metrics));
    tiles.push(metaTile(metrics));
    tiles.push(h1Tile(metrics));
    tiles.push(imagesTile(metrics));
    tiles.push(wordCountTile(metrics));
  } else {
    tiles.push({
      label: 'Content type',
      dot: 'neutral',
      value: metrics.content_type || 'unknown',
      sub: 'Not HTML — SEO, accessibility, and content checks don\u2019t apply.',
    });
  }

  tilesEl.innerHTML = '';
  for (const t of tiles) {
    tilesEl.appendChild(buildTile(t));
  }
}

function buildTile({ label, dot, value, sub }) {
  const div = document.createElement('div');
  div.className = 'tile';
  div.innerHTML = `
    <div class="tile-head">
      <span class="tile-label">${label}</span>
      <span class="status-dot ${dot}"></span>
    </div>
    <div class="tile-value">${escapeHtml(String(value))}</div>
    ${sub ? `<div class="tile-sub">${escapeHtml(sub)}</div>` : ''}
  `;
  return div;
}

function statusTile(m) {
  const dot = m.http_status < 300 ? 'good' : m.http_status < 400 ? 'warn' : 'bad';
  return { label: 'HTTP status', dot, value: m.http_status };
}

function timingTile(m) {
  const dot = m.response_time_ms <= 800 ? 'good' : m.response_time_ms <= 3000 ? 'warn' : 'bad';
  return { label: 'Response time', dot, value: `${m.response_time_ms} ms` };
}

function titleTile(m) {
  if (!m.title) return { label: 'Title', dot: 'bad', value: 'Missing', sub: 'No <title> tag found.' };
  const len = m.title.length;
  const dot = len >= 10 && len <= 60 ? 'good' : 'warn';
  return { label: 'Title', dot, value: m.title, sub: `${len} characters` };
}

function metaTile(m) {
  if (!m.meta_description) {
    return { label: 'Meta description', dot: 'warn', value: 'Missing', sub: 'No meta description found.' };
  }
  const len = m.meta_description.length;
  const dot = len >= 50 && len <= 160 ? 'good' : 'warn';
  return { label: 'Meta description', dot, value: m.meta_description, sub: `${len} characters` };
}

function h1Tile(m) {
  const dot = m.h1_count === 1 ? 'good' : 'warn';
  const sub = m.h1_count === 0 ? 'Missing a primary heading.' : m.h1_count > 1 ? 'Multiple H1s — usually a structure smell.' : 'One primary heading.';
  return { label: 'H1 count', dot, value: m.h1_count, sub };
}

function imagesTile(m) {
  if (m.images_total === 0) {
    return { label: 'Images', dot: 'neutral', value: 'None on page', sub: '' };
  }
  const missing = m.images_missing_alt;
  const dot = missing === 0 ? 'good' : missing === m.images_total ? 'bad' : 'warn';
  const examples = m.images_missing_alt_examples.length
    ? `e.g. ${m.images_missing_alt_examples[0]}`
    : '';
  return {
    label: 'Images missing alt text',
    dot,
    value: `${missing} / ${m.images_total}`,
    sub: examples,
  };
}

function wordCountTile(m) {
  const dot = m.word_count >= 300 ? 'good' : m.word_count >= 100 ? 'warn' : 'bad';
  return { label: 'Word count', dot, value: m.word_count.toLocaleString() };
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
