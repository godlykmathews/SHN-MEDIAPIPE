'use strict';

const $ = (id) => document.getElementById(id);
const state = {
  scans: [], filter: 'all', health: null, file: null, previewUrl: null,
  stream: null, cameraRequest: 0, busy: false, activeReport: null,
  toastTimer: null, progressTimer: null, historyLoaded: false, reportRequest: 0,
  historyTotal: 0, historyOffset: 0, historyRequest: 0, historyLoading: false,
  busyScanId: null,
};
const categories = { disease: 'Possible disease', pest: 'Possible pest', healthy: 'Looks healthy', uncertain: 'Needs a closer look', not_plant: 'Not a plant photo' };

function node(tag, className, text) {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (text !== undefined && text !== null) result.textContent = String(text);
  return result;
}

function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'icon');
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', `#i-${name}`);
  svg.append(use);
  return svg;
}

function safeImageUrl(value) {
  try {
    const url = new URL(value, location.origin);
    return url.origin === location.origin ? url.href : '';
  } catch { return ''; }
}

function errorMessage(error) {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.';
}

async function api(path, options = {}) {
  let response;
  try { response = await fetch(path, options); }
  catch (error) {
    if (error.name === 'AbortError' || error.name === 'TimeoutError') throw new Error('The local server took too long to respond. Please check that it is running.');
    throw new Error('Could not reach the local server. Check that Plant Clinic is running, then try again.');
  }
  if (response.status === 204) return null;
  let data;
  try { data = await response.json(); }
  catch { throw new Error('The server returned an unreadable response. Please try again.'); }
  if (!response.ok) {
    let message = data.detail || data.error || 'The request could not be completed.';
    if (Array.isArray(message)) message = message.map((item) => item.msg || 'Invalid input').join('. ');
    if (typeof message !== 'string') message = 'The request could not be completed.';
    throw new Error(message);
  }
  return data;
}

function toast(message) {
  clearTimeout(state.toastTimer);
  $('toast').textContent = message;
  $('toast').hidden = false;
  state.toastTimer = setTimeout(() => { $('toast').hidden = true; }, 5500);
}

function formatDate(value, long = false) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Saved scan';
  return new Intl.DateTimeFormat(undefined, long
    ? { day: 'numeric', month: 'long', year: 'numeric', hour: 'numeric', minute: '2-digit' }
    : { day: 'numeric', month: 'short' }).format(date);
}

function scanCategory(scan) {
  if (scan.status === 'error') return 'error';
  if (scan.status === 'processing') return 'processing';
  return scan.report?.category || 'uncertain';
}

function categoryLabel(scan) {
  const category = scanCategory(scan);
  if (category === 'error') return 'Could not finish';
  if (category === 'processing') return 'In progress';
  return categories[category] || 'Needs a closer look';
}

function scanTitle(scan) {
  if (scan.status === 'error') return 'Let’s try another look.';
  if (scan.status === 'processing') return 'Taking a closer look…';
  if (scan.report?.issue) return scan.report.issue;
  return scan.crop || 'A new plant story';
}

async function loadHealth() {
  $('refresh-status').disabled = true;
  try {
    state.health = await api('/api/health', { signal: AbortSignal.timeout(12000) });
    const health = state.health;
    const ready = Boolean(health.ollama?.available && (health.ollama?.vision_model || health.mediapipe?.available));
    $('status-label').textContent = ready ? 'LOCAL & READY' : 'CHECK LOCAL SETUP';
    $('status-dot').className = `status-dot ${ready ? 'ready' : 'warning'}`;
    renderSystem(health);
  } catch (error) {
    state.health = null;
    $('status-label').textContent = 'SERVER OFFLINE';
    $('status-dot').className = 'status-dot warning';
    const row = node('div', 'system-row');
    row.append(node('h3', '', 'The local server is unavailable'), node('p', '', errorMessage(error)));
    $('system-details').replaceChildren(row);
  } finally { $('refresh-status').disabled = false; }
}

function renderSystem(health) {
  const container = $('system-details');
  container.replaceChildren();
  function add(title, ready, description) {
    const row = node('div', 'system-row');
    const heading = node('h3');
    heading.append(node('span', `status-dot ${ready ? 'ready' : 'warning'}`), document.createTextNode(title));
    row.append(heading, node('p', '', description));
    container.append(row);
  }
  add('Local server', true, 'Connected. Your photos and reports are stored here, even after you close the page.');
  const ollama = health.ollama || {};
  add('Ollama', ollama.available, ollama.available
    ? `Connected${ollama.model ? ` · ${ollama.model}` : ''}${ollama.vision_model ? ` · Image model: ${ollama.vision_model}` : ''}`
    : (ollama.error || 'Start Ollama and make sure a local model is installed.'));
  const mediapipe = health.mediapipe || {};
  const models = Array.isArray(mediapipe.models) ? mediapipe.models.map((model) => typeof model === 'string' ? model : model.name || model.kind).filter(Boolean).join(', ') : '';
  add('Specialist image models', mediapipe.available, mediapipe.message || (models ? `MediaPipe models: ${models}` : 'No specialist plant or pest model is configured. If a local image model is available, reports will say when it is used.'));
}

async function loadHistory(showLoader = false, append = false) {
  if (append && state.historyLoading) return;
  const request = ++state.historyRequest;
  state.historyLoading = true;
  if (showLoader || !state.historyLoaded) $('history-loading').hidden = false;
  $('history-error').hidden = true;
  $('refresh-history').disabled = true;
  $('load-more-scans').disabled = true;
  $('history-grid').setAttribute('aria-busy', 'true');
  try {
    const offset = append ? state.historyOffset : 0;
    const data = await api(`/api/scans?limit=100&offset=${offset}`);
    if (request !== state.historyRequest) return;
    const items = Array.isArray(data.items) ? data.items : [];
    state.scans = append ? [...new Map([...state.scans, ...items].map((scan) => [scan.id, scan])).values()] : items;
    state.historyOffset = offset + items.length;
    state.historyTotal = Number.isFinite(data.total) ? data.total : state.scans.length;
    state.historyLoaded = true;
    $('scan-count').textContent = state.historyTotal;
    renderHistory();
  } catch (error) {
    if (request !== state.historyRequest) return;
    $('history-error').textContent = errorMessage(error);
    $('history-error').hidden = false;
    if (!state.historyLoaded) $('history-empty').hidden = true;
  } finally {
    if (request === state.historyRequest) {
      state.historyLoading = false;
      $('history-loading').hidden = true;
      $('refresh-history').disabled = false;
      $('load-more-scans').disabled = false;
      $('history-grid').setAttribute('aria-busy', 'false');
    }
  }
}

function renderHistory() {
  const filtered = state.scans.filter((scan) => state.filter === 'all' || scanCategory(scan) === state.filter);
  const grid = $('history-grid');
  grid.replaceChildren();
  const hasOlder = state.historyOffset < state.historyTotal;
  $('history-pagination').hidden = state.historyTotal <= 100 && !hasOlder;
  $('history-page-count').textContent = state.filter === 'all'
    ? `${state.scans.length} OF ${state.historyTotal} SCANS LOADED`
    : `${filtered.length} MATCHING · ${state.scans.length} OF ${state.historyTotal} SCANS LOADED`;
  $('load-more-scans').hidden = !hasOlder;
  $('history-empty').hidden = filtered.length > 0;
  if (!filtered.length) {
    const firstScan = state.scans.length === 0;
    $('empty-title').textContent = firstScan ? 'Every plant has a story.' : 'Nothing in this corner yet.';
    $('empty-copy').textContent = firstScan ? 'Your first scan starts yours. Photos and care notes will be saved right here.' : (hasOlder ? 'No matches among the scans loaded so far. Load older scans to keep looking, or choose All scans.' : 'Scans matching this filter will appear here. Your other photos are under All scans.');
    $('empty-new-scan').hidden = !firstScan;
    return;
  }
  for (const scan of filtered) {
    const card = node('button', 'history-card');
    card.type = 'button';
    card.setAttribute('aria-label', `Open ${scanTitle(scan)}, ${formatDate(scan.created_at)}`);
    const imageWrap = node('div', 'card-image-wrap');
    const image = node('img');
    image.src = safeImageUrl(scan.thumbnail_url || scan.image_url);
    image.alt = scan.report?.plant || scan.crop || 'Saved plant photo';
    image.loading = 'lazy';
    imageWrap.append(image, node('span', 'card-number', `#${String(state.historyTotal - state.scans.indexOf(scan)).padStart(3, '0')}`));
    const body = node('div', 'card-body');
    const meta = node('div', 'card-meta');
    meta.append(node('span', `category-tag ${scanCategory(scan)}`, categoryLabel(scan)), node('span', 'card-date', formatDate(scan.created_at)));
    const footer = node('div', 'card-footer');
    footer.append(node('span', '', scan.status === 'error' ? 'View & try again' : 'Open care notes'), icon('arrow'));
    const summary = scan.status === 'error' ? 'Your photo is saved. Open it for details and another try.' : (scan.status === 'processing' ? 'Your photo is saved while the analysis is prepared.' : scan.report?.summary || 'Open the saved report to see the findings.');
    body.append(meta, node('h3', 'card-title', scanTitle(scan)), node('p', 'card-summary', summary), footer);
    card.append(imageWrap, body);
    card.addEventListener('click', () => openReport(scan.id));
    grid.append(card);
  }
}

function stopCamera() {
  state.cameraRequest += 1;
  state.stream?.getTracks().forEach((track) => track.stop());
  state.stream = null;
  $('camera-video').srcObject = null;
}

function clearSelectedPhoto() {
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.previewUrl = null;
  state.file = null;
  $('selected-image').removeAttribute('src');
}

function resetCapture() {
  stopCamera();
  clearSelectedPhoto();
  $('capture-choices').hidden = false;
  $('camera-stage').hidden = true;
  $('image-preview').hidden = true;
  $('scan-form').hidden = true;
  $('processing-panel').hidden = true;
  $('capture-error').hidden = true;
  $('open-camera').disabled = false;
  $('identify-button').disabled = false;
  $('replace-photo').disabled = false;
  $('scan-form').reset();
}

function newScan() {
  if (state.busy) {
    if (!state.busyScanId && !$('scan-dialog').open) $('scan-dialog').showModal();
    else toast('A photo is already being checked. Your result will appear in Past scans.');
    return;
  }
  resetCapture();
  if (!$('scan-dialog').open) $('scan-dialog').showModal();
}

function showCaptureError(message) {
  $('capture-error').textContent = message;
  $('capture-error').hidden = false;
}

async function openCamera() {
  if (!navigator.mediaDevices?.getUserMedia) {
    showCaptureError('Live camera access needs localhost or HTTPS. You can still upload a photo from this device.');
    return;
  }
  stopCamera();
  const request = state.cameraRequest;
  $('open-camera').disabled = true;
  $('capture-error').hidden = true;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1600 }, height: { ideal: 1200 } }, audio: false });
    if (request !== state.cameraRequest || !$('scan-dialog').open) { stream.getTracks().forEach((track) => track.stop()); return; }
    state.stream = stream;
    $('camera-video').srcObject = stream;
    $('capture-choices').hidden = true;
    $('image-preview').hidden = true;
    $('scan-form').hidden = true;
    $('camera-stage').hidden = false;
    await $('camera-video').play();
    $('capture-photo').focus();
  } catch (error) {
    stopCamera();
    $('camera-stage').hidden = true;
    $('capture-choices').hidden = false;
    const messages = {
      NotAllowedError: 'Camera access was not allowed. Enable it in your browser settings, or upload a photo instead.',
      NotFoundError: 'No camera was found. Upload a photo from this device instead.',
      NotReadableError: 'The camera may be in use by another app. Close that app, or upload a photo instead.',
    };
    showCaptureError(messages[error.name] || 'The camera could not start. Please try again or upload a photo.');
  } finally { $('open-camera').disabled = false; }
}

async function capturePhoto() {
  const video = $('camera-video');
  if (!video.videoWidth || !video.videoHeight) { showCaptureError('The camera is still warming up. Try the shutter again in a moment.'); return; }
  const request = state.cameraRequest;
  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext('2d').drawImage(video, 0, 0);
  $('capture-photo').disabled = true;
  try {
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.92));
    if (request !== state.cameraRequest || !$('scan-dialog').open) return;
    if (!blob) throw new Error('The photo could not be captured. Please try again.');
    selectPhoto(new File([blob], `plant-${Date.now()}.jpg`, { type: 'image/jpeg' }));
  } catch (error) { showCaptureError(errorMessage(error)); }
  finally { $('capture-photo').disabled = false; }
}

function selectPhoto(file) {
  if (!file) return;
  if (state.busy) { toast('Please wait for the current photo to finish.'); return; }
  if (!$('scan-dialog').open) newScan();
  const supportedTypes = ['image/jpeg', 'image/png', 'image/webp'];
  if (!supportedTypes.includes(file.type) && !/\.(jpe?g|png|webp)$/i.test(file.name)) { showCaptureError('Choose a JPEG, PNG, or WebP image. Other formats need to be exported to one of these first.'); return; }
  if (file.size > 10 * 1024 * 1024) { showCaptureError('This photo is a little large. Choose an image under 10 MB.'); return; }
  stopCamera();
  clearSelectedPhoto();
  state.file = file;
  state.previewUrl = URL.createObjectURL(file);
  $('selected-image').src = state.previewUrl;
  $('capture-choices').hidden = true;
  $('camera-stage').hidden = true;
  $('image-preview').hidden = false;
  $('scan-form').hidden = false;
  $('capture-error').hidden = true;
  $('processing-panel').hidden = true;
}

function chooseUpload() {
  if (state.busy) { toast('Please wait for the current photo to finish.'); return; }
  if (!$('scan-dialog').open) newScan();
  $('photo-input').click();
}

function setProcessing(active) {
  state.busy = active;
  if (active) state.busyScanId = null;
  $('identify-button').disabled = active;
  $('replace-photo').disabled = active;
  $('scan-form').hidden = active;
  $('processing-panel').hidden = !active;
  if (active) {
    $('capture-error').hidden = true;
    $('processing-copy').textContent = 'Checking the photo and putting together the next steps.';
    $('processing-elapsed').textContent = 'WORKING LOCALLY · PLEASE KEEP THIS TAB OPEN';
    const started = Date.now();
    clearInterval(state.progressTimer);
    state.progressTimer = setInterval(() => {
      const seconds = Math.floor((Date.now() - started) / 1000);
      $('processing-elapsed').textContent = `WORKING LOCALLY · ${seconds}s ELAPSED`;
      if (seconds > 45) $('processing-copy').textContent = 'Still working. Local image analysis can take a little longer, especially on the first scan.';
    }, 1000);
  } else { clearInterval(state.progressTimer); state.progressTimer = null; }
}

async function submitScan(event) {
  event.preventDefault();
  if (!state.file || state.busy) return;
  const form = new FormData();
  form.append('file', state.file);
  form.append('crop', $('crop-input').value.trim());
  form.append('notes', $('notes-input').value.trim());
  setProcessing(true);
  try {
    const scan = await api('/api/scans', { method: 'POST', body: form });
    const showResult = $('scan-dialog').open;
    setProcessing(false);
    $('scan-dialog').close();
    resetCapture();
    await loadHistory();
    if (showResult) renderReport(scan, true);
    else toast(scan.status === 'error' ? 'Your photo is saved, but the analysis needs another try. Open Past scans.' : 'Your plant report is ready in Past scans.');
    loadHealth();
  } catch (error) {
    setProcessing(false);
    $('scan-form').hidden = !state.file;
    showCaptureError(errorMessage(error));
    if (!$('scan-dialog').open) toast(errorMessage(error));
    await loadHistory();
  }
}

async function openReport(id) {
  const request = ++state.reportRequest;
  const cached = state.scans.find((scan) => scan.id === id);
  if (cached) renderReport(cached, true);
  else {
    state.activeReport = null;
    $('report-title').textContent = 'Opening care notes…';
    $('report-content').replaceChildren(node('p', 'history-message', 'Loading the saved photo and report…'));
    $('delete-scan').disabled = true;
    $('delete-confirm').hidden = true;
    if (!$('report-dialog').open) $('report-dialog').showModal();
  }
  try {
    const scan = await api(`/api/scans/${encodeURIComponent(id)}`);
    if (request === state.reportRequest && $('report-dialog').open) renderReport(scan);
  } catch (error) { toast(errorMessage(error)); }
}

function reportSection(title, items, className = '') {
  if (!Array.isArray(items) || !items.length) return null;
  const section = node('section', `report-section ${className}`);
  section.append(node('h3', '', title));
  const list = node('ul');
  for (const item of items) if (typeof item === 'string' && item.trim()) list.append(node('li', '', item));
  if (!list.childElementCount) return null;
  section.append(list);
  return section;
}

function renderReport(scan, open = false) {
  state.activeReport = scan;
  $('report-title').textContent = 'Your care notes.';
  $('report-date').textContent = formatDate(scan.created_at, true).toUpperCase();
  $('delete-confirm').hidden = true;
  $('delete-scan').hidden = false;
  $('delete-scan').disabled = scan.status === 'processing' || (state.busy && state.busyScanId === scan.id);
  $('confirm-delete').disabled = false;
  const container = $('report-content');
  const restoreContentFocus = $('report-dialog').open && container.contains(document.activeElement);
  container.replaceChildren();
  const overview = node('div', 'report-overview');
  const photo = node('img', 'report-photo');
  photo.src = safeImageUrl(scan.image_url);
  photo.alt = scan.crop || scan.report?.plant || 'The saved plant photo';
  const summary = node('div', 'report-summary');
  summary.append(node('span', `category-tag ${scanCategory(scan)}`, categoryLabel(scan)));
  // A failed retry may retain the last report on disk. Never present that old report as a new finding.
  const report = ['error', 'processing'].includes(scan.status) ? null : scan.report;
  if (report?.plant || scan.crop) summary.append(node('p', 'plant-name', report?.plant || scan.crop));
  summary.append(node('h3', '', scanTitle(scan)));
  summary.append(node('p', '', report?.summary || (scan.status === 'processing' ? 'Your photo has been saved. The analysis is still being prepared. Refresh this report in a moment.' : 'Your photo is safely saved, but we could not finish checking it.')));
  overview.append(photo, summary);
  container.append(overview);

  if (scan.status === 'error' || scan.error) {
    const section = node('section', 'report-section error');
    section.append(node('h3', '', 'The analysis needs another try'), node('p', '', scan.error || 'The local model could not finish the analysis. Check your local setup and try again.'));
    const retry = node('button', 'button button-white button-small', 'Try this photo again');
    retry.type = 'button';
    retry.disabled = state.busy;
    retry.prepend(icon('retry'));
    retry.addEventListener('click', () => retryScan(scan.id, retry));
    section.append(retry);
    container.append(section);
  } else if (scan.status === 'processing') {
    const section = node('section', 'report-section uncertainty');
    section.append(node('h3', '', 'A little patience, a closer look'), node('p', '', 'Your computer is working on this photo. If the server was restarted, an interrupted scan may need another attempt.'));
    const refresh = node('button', 'button button-white button-small', 'Refresh report');
    refresh.type = 'button';
    refresh.prepend(icon('retry'));
    refresh.addEventListener('click', () => openReport(scan.id));
    section.append(refresh);
    container.append(section);
  }

  if (report) {
    if (report.uncertainty || report.needs_expert) {
      const section = node('section', 'report-section uncertainty');
      section.append(node('h3', '', report.needs_expert ? 'A second opinion would help' : 'Before you act'));
      section.append(node('p', '', report.uncertainty || 'A photo alone may not confirm the cause. Ask a local plant specialist before choosing a treatment.'));
      container.append(section);
    }
    const observations = reportSection('What the photo suggests', report.observations);
    if (observations) container.append(observations);
    const actions = reportSection('Start here', report.immediate_actions, 'actions');
    if (actions) container.append(actions);
    const treatment = reportSection('Care & treatment', report.treatment, 'treatment');
    if (treatment) container.append(treatment);
    const columns = node('div', 'report-two-col');
    const causes = reportSection('Possible causes', report.possible_causes);
    const prevention = reportSection('For next time', report.prevention);
    if (causes) columns.append(causes);
    if (prevention) columns.append(prevention);
    if (columns.childElementCount) container.append(columns);
    if (Array.isArray(report.sources) && report.sources.length) {
      const sources = node('div', 'report-sources');
      sources.append(node('p', '', 'CARE REFERENCES'));
      const list = node('ul');
      for (const source of report.sources) {
        try {
          const url = new URL(source.url);
          if (!['https:', 'http:'].includes(url.protocol)) continue;
          const link = node('a', '', source.title || url.hostname);
          link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
          const item = node('li'); item.append(link); list.append(item);
        } catch { /* Ignore malformed source links. */ }
      }
      if (list.childElementCount) { sources.append(list); container.append(sources); }
    }
  }
  if (scan.notes) {
    const note = node('div', 'report-note');
    note.append(node('strong', '', 'Your observations'), document.createTextNode(scan.notes));
    container.append(note);
  }
  const details = node('details', 'analysis-details');
  details.append(node('summary', '', 'About this analysis'));
  details.append(node('p', '', `Method: ${scan.analysis_method || 'Local analysis'}${scan.model ? ` · Model: ${scan.model}` : ''}`));
  if (Array.isArray(scan.predictions) && scan.predictions.length) {
    const list = node('ul');
    for (const prediction of scan.predictions) {
      const score = Number(prediction.score);
      list.append(node('li', '', `${prediction.label}${Number.isFinite(score) ? ` — model score ${score.toFixed(3)}` : ''}`));
    }
    details.append(list, node('p', '', 'Model scores are not a guarantee or a calibrated probability of a correct diagnosis.'));
  }
  details.append(node('p', '', 'A photo can suggest a cause, but it may not confirm it. Follow the label and local guidance for any plant treatment.'));
  container.append(details);
  if (open && !$('report-dialog').open) $('report-dialog').showModal();
  if (restoreContentFocus && $('report-dialog').open) {
    $('report-title').tabIndex = -1;
    $('report-title').focus({ preventScroll: true });
  }
}

async function retryScan(id, button) {
  if (state.busy) { toast('Another photo is being checked. Please wait for it to finish.'); return; }
  state.busy = true;
  state.busyScanId = id;
  state.reportRequest += 1;
  button.disabled = true;
  button.textContent = 'Taking another look…';
  $('delete-scan').disabled = true;
  try {
    const scan = await api(`/api/scans/${encodeURIComponent(id)}/retry`, { method: 'POST' });
    state.busy = false;
    state.busyScanId = null;
    if ($('report-dialog').open && state.activeReport?.id === id) {
      renderReport(scan);
      $('report-title').tabIndex = -1;
      $('report-title').focus({ preventScroll: true });
    } else toast(scan.status === 'error' ? 'The analysis could not finish. Details are saved in Past scans.' : 'The updated report is saved in Past scans.');
  } catch (error) {
    toast(errorMessage(error));
    button.textContent = 'Try this photo again';
    button.disabled = false;
  } finally {
    state.busy = false;
    state.busyScanId = null;
    $('delete-scan').disabled = state.activeReport?.status === 'processing';
    await loadHistory();
  }
}

async function deleteScan() {
  const id = state.activeReport?.id;
  if (!id) return;
  $('confirm-delete').disabled = true;
  try {
    await api(`/api/scans/${encodeURIComponent(id)}`, { method: 'DELETE' });
    $('report-dialog').close();
    state.activeReport = null;
    toast('Photo and care notes deleted.');
    await loadHistory();
    $('history-title').tabIndex = -1;
    $('history-title').focus({ preventScroll: true });
  } catch (error) { toast(errorMessage(error)); $('confirm-delete').disabled = false; }
}

$('new-scan').addEventListener('click', newScan);
$('empty-new-scan').addEventListener('click', newScan);
$('upload-shortcut').addEventListener('click', chooseUpload);
$('choose-upload').addEventListener('click', chooseUpload);
$('replace-photo').addEventListener('click', () => {
  stopCamera();
  $('capture-choices').hidden = false;
  $('image-preview').hidden = true;
  $('scan-form').hidden = true;
  $('capture-error').hidden = true;
  $('open-camera').focus();
});
$('open-camera').addEventListener('click', openCamera);
$('capture-photo').addEventListener('click', capturePhoto);
$('photo-input').addEventListener('change', (event) => { selectPhoto(event.target.files?.[0]); event.target.value = ''; });
$('selected-image').addEventListener('error', () => {
  if (!state.previewUrl) return;
  clearSelectedPhoto();
  $('image-preview').hidden = true;
  $('scan-form').hidden = true;
  $('capture-choices').hidden = false;
  showCaptureError('This file could not be opened as an image. Please choose another photo.');
});
$('scan-form').addEventListener('submit', submitScan);
$('refresh-history').addEventListener('click', () => loadHistory(true));
$('load-more-scans').addEventListener('click', () => loadHistory(false, true));
$('system-status').addEventListener('click', () => { $('system-dialog').showModal(); loadHealth(); });
$('refresh-status').addEventListener('click', loadHealth);
$('report-done').addEventListener('click', () => $('report-dialog').close());
$('delete-scan').addEventListener('click', () => { state.reportRequest += 1; $('delete-confirm').hidden = false; $('delete-scan').hidden = true; $('cancel-delete').focus(); });
$('cancel-delete').addEventListener('click', () => { $('delete-confirm').hidden = true; $('delete-scan').hidden = false; $('delete-scan').focus(); });
$('confirm-delete').addEventListener('click', deleteScan);
document.querySelectorAll('[data-filter]').forEach((button) => button.addEventListener('click', () => {
  state.filter = button.dataset.filter;
  document.querySelectorAll('[data-filter]').forEach((item) => {
    const selected = item === button;
    item.classList.toggle('active', selected);
    item.setAttribute('aria-pressed', String(selected));
  });
  renderHistory();
}));
document.querySelectorAll('.close-dialog').forEach((button) => button.addEventListener('click', () => button.closest('dialog').close()));
document.querySelectorAll('dialog').forEach((dialog) => dialog.addEventListener('click', (event) => {
  if (event.target === dialog) {
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  }
}));
$('scan-dialog').addEventListener('close', () => { stopCamera(); if (!state.busy) resetCapture(); });
$('report-dialog').addEventListener('close', () => { state.reportRequest += 1; });
window.addEventListener('pagehide', () => { stopCamera(); clearInterval(state.progressTimer); });
document.addEventListener('visibilitychange', () => {
  if (document.hidden && state.stream) {
    stopCamera();
    $('camera-stage').hidden = true;
    $('capture-choices').hidden = false;
    showCaptureError('The camera paused when you left this tab. Choose Take a photo to start it again.');
  }
});

loadHealth();
loadHistory();
