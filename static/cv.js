'use strict';
const token = document.querySelector('meta[name="csrf-token"]').content;
const message = document.getElementById('message');
// Friendly fields and the advanced editor share one serialized document.
document.querySelectorAll('[data-editor]').forEach(form => {
  const serialized = form.querySelector('textarea');
  serialized.classList.add('serialized');
  const advanced = document.createElement('details');
  const summary = document.createElement('summary');
  summary.textContent = 'Advanced structured editor';
  advanced.append(summary, serialized.parentElement);
  form.prepend(advanced);
  const editor = document.createElement('div');
  form.prepend(editor);
  let data = JSON.parse(serialized.value);
  const sync = () => { serialized.value = JSON.stringify(data, null, 2); };
  function field(parent, title, value, set, options = {}) {
    const label = document.createElement('label');
    label.append(document.createTextNode(title));
    const input = document.createElement(options.choices ? 'select' : options.multiline ? 'textarea' : 'input');
    if (options.choices) options.choices.forEach(choice => {
      const option = document.createElement('option'); option.value = choice; option.textContent = choice; input.append(option);
    });
    else if (!options.multiline) input.type = options.checkbox ? 'checkbox' : 'text';
    if (options.multiline) input.rows = 3;
    if (options.readonly) input.readOnly = true;
    if (options.checkbox) input.checked = value;
    else input.value = value;
    input.addEventListener('input', () => { set(options.checkbox ? input.checked : input.value); sync(); });
    label.append(input); parent.append(label);
  }
  function listField(parent, title, object, key, separator = '\n') {
    field(parent, title, object[key].join(separator), value => {
      object[key] = value.split(separator).map(v => v.trim()).filter(Boolean);
    }, {multiline: separator === '\n'});
  }
  function action(parent, text, callback) {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = text;
    button.addEventListener('click', () => { callback(); sync(); render(); form.dispatchEvent(new Event('input', {bubbles: true})); });
    parent.append(button);
  }
  function render() {
    editor.replaceChildren();
    if (form.dataset.editor === 'profile') {
      field(editor, 'Original CV language', data.language, value => { data.language = value; });
      field(editor, 'Profile summary', data.summary, value => { data.summary = value; }, {multiline: true});
      listField(editor, 'Supporting source fact IDs (comma separated)', data, 'fact_ids', ',');
    } else if (form.dataset.editor === 'categories') {
      data.forEach((category, index) => {
        const card = document.createElement('fieldset');
        const legend = document.createElement('legend'); legend.textContent = 'Category ' + (index + 1); card.append(legend);
        field(card, 'Category name', category.name, value => { category.name = value; });
        field(card, 'Why this category fits', category.rationale, value => { category.rationale = value; }, {multiline: true});
        field(card, 'Fit', category.fit, value => { category.fit = value; }, {choices: ['strong', 'stretch']});
        listField(card, 'Suitable role titles (one per line)', category, 'role_titles');
        listField(card, 'Gaps (one per line)', category, 'gaps');
        listField(card, 'Relevant source fact IDs (comma separated)', category, 'fact_ids', ',');
        field(card, 'Approve this category', category.approved, value => { category.approved = value; }, {checkbox: true});
        action(card, 'Remove category', () => data.splice(index, 1));
        editor.append(card);
      });
      action(editor, 'Add category', () => data.push({name: '', rationale: '', fit: 'stretch', role_titles: [], gaps: [], fact_ids: [], approved: false}));
    } else {
      const latex = form.dataset.layout === 'latex';
      const fixedFacts = new Set(JSON.parse(form.dataset.fixedFacts || '[]'));
      field(editor, latex ? 'Text preview title' : 'CV title', data.title, value => { data.title = value; });
      data.sections.forEach((section, index) => {
        const card = document.createElement('fieldset');
        field(card, 'Section heading', section.heading, value => { section.heading = value; });
        section.items.forEach((item, itemIndex) => {
          const block = document.createElement('div');
          field(block, 'CV text', item.text, value => { item.text = value; }, {multiline: true, readonly: latex && fixedFacts.has(item.fact_ids[0])});
          listField(block, 'Supporting source fact IDs (comma separated)', item, 'fact_ids', ',');
          if (!latex) action(block, 'Remove item', () => section.items.splice(itemIndex, 1)); card.append(block);
        });
        if (!latex) action(card, 'Add item', () => section.items.push({text: '', fact_ids: []}));
        if (!latex) action(card, 'Remove section', () => data.sections.splice(index, 1)); editor.append(card);
      });
      if (!latex) action(editor, 'Add section', () => data.sections.push({heading: '', items: [{text: '', fact_ids: []}]}));
      listField(editor, 'Change summary (one per line)', data, 'changes');
      listField(editor, 'Improvement suggestions (excluded from the CV)', data, 'suggestions');
    }
  }
  serialized.addEventListener('change', () => {
    try { data = JSON.parse(serialized.value); render(); }
    catch (_) { message.textContent = 'The advanced editor must contain valid JSON.'; }
  });
  render();
});
async function api(url, body, multipart = false) {
  const headers = {'X-CSRF-Token': token};
  if (!multipart) headers['Content-Type'] = 'application/json';
  const response = await fetch(url, {method: 'POST', headers, body: multipart ? body : JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || JSON.stringify(result.detail));
  return result;
}
function handle(element, event, action) {
  element?.addEventListener(event, async e => {
    e.preventDefault();
    const button = element.matches('button') ? element : e.submitter;
    if (button) button.disabled = true;
    try { message.textContent = ''; await action(e); }
    catch (error) { message.textContent = error.message; message.scrollIntoView({block: 'center'}); }
    finally { if (button) button.disabled = false; }
  });
}
handle(document.getElementById('import-form'), 'submit', async e => {
  const result = await api('/api/import', new FormData(e.target), true);
  const form = document.getElementById('source-form');
  for (const key of ['filename', 'text', 'contacts']) form.elements[key].value = result[key];
  form.elements.latex_source.value = result.latex_source || '';
  document.getElementById('latex-source-editor').hidden = !result.latex_source;
  message.textContent = result.notice || 'Text extracted. Review and save before analysis.';
});
handle(document.getElementById('extract-latex'), 'click', async () => {
  const form = document.getElementById('source-form');
  const result = await api('/api/latex/extract', {latex_source: form.elements.latex_source.value});
  form.elements.text.value = result.text;
  // Preserve manually entered private details when re-extracting the template.
  form.elements.contacts.value = [...new Set((form.elements.contacts.value + '\n' + result.contacts).split('\n').filter(Boolean))].join('\n');
  message.textContent = 'LaTeX text updated. Review the facts and contact block, then save the source revision.';
});
handle(document.getElementById('source-form'), 'submit', async e => {
  await api('/api/source', Object.fromEntries(new FormData(e.target)));
  location.reload();
});
document.querySelectorAll('.json-form').forEach(form => handle(form, 'submit', async () => {
  const result = await api(form.dataset.url, JSON.parse(form.querySelector('textarea.serialized').value));
  if (form.dataset.versionRedirect) location.href = '/versions/' + result.version_id;
  else location.reload();
}));
handle(document.getElementById('approval-form'), 'submit', async e => {
  await api('/api/versions/' + e.target.dataset.versionId + '/approve', {reviewed: e.target.elements.reviewed.checked});
  location.reload();
});
let pending;
async function estimate(operation, args) {
  const result = await api('/api/estimate', {operation, args});
  pending = {operation, args, estimate_key: result.estimate_key};
  delete result.estimate_key;
  document.getElementById('estimate-summary').textContent = result.cached
    ? 'Your inputs have not changed. We’ll reuse the saved result without an API call.'
    : `${result.requests} request${result.requests === 1 ? '' : 's'} planned. Usage below is a conservative estimate before retries.`;
  const numbers = document.getElementById('estimate-numbers');
  numbers.replaceChildren();
  for (const [label, value] of [['Estimated input tokens', result.estimated_input_tokens], ['Reserved output tokens', result.reserved_output_tokens]]) {
    const card = document.createElement('div');
    const number = document.createElement('strong'); number.textContent = value.toLocaleString();
    const caption = document.createElement('span'); caption.textContent = label;
    card.append(number, caption); numbers.append(card);
  }
  document.getElementById('estimate-content').textContent = JSON.stringify(result, null, 2);
  document.getElementById('estimate-dialog').showModal();
}
document.querySelectorAll('.operation').forEach(button => handle(button, 'click', async () => {
  const args = {};
  if (button.dataset.sourceId) args.source_id = Number(button.dataset.sourceId);
  if (button.dataset.categoryId) args.category_id = Number(button.dataset.categoryId);
  const outputFormat = document.getElementById('output-format-' + button.dataset.categoryId);
  if (outputFormat) args.output_format = outputFormat.value;
  await estimate(button.dataset.operation, args);
}));
document.querySelectorAll('.retry').forEach(button => handle(button, 'click', () => estimate(button.dataset.operation, JSON.parse(button.dataset.args))));
handle(document.getElementById('start-operation'), 'click', async () => {
  await api('/api/tasks', pending);
  location.reload();
});
handle(document.getElementById('cancel-operation'), 'click', () => document.getElementById('estimate-dialog').close());
let dirty = false;
document.addEventListener('input', () => { dirty = true; });
const activeTasks = [...document.querySelectorAll('[data-task-id]')].filter(e => ['RUNNING', 'QUEUED'].includes(e.dataset.taskStatus));
if (activeTasks.length) {
  const timer = setInterval(async () => {
    try {
      const response = await fetch('/api/tasks');
      if (!response.ok) return;
      const tasks = await response.json();
      const watched = tasks.filter(t => activeTasks.some(e => Number(e.dataset.taskId) === t.id));
      document.getElementById('task-progress').textContent = watched.map(t => '#' + t.id + ': ' + t.progress + (t.error ? ' — ' + t.error : '')).join(' | ');
      if (watched.every(t => !['RUNNING', 'QUEUED'].includes(t.status))) {
        clearInterval(timer);
        if (!dirty) location.reload();
        else message.textContent = 'Operations finished. Save your edits before reloading to see results.';
      }
    } catch (_) { /* A temporary disconnect must not discard edits. */ }
  }, 1500);
}
