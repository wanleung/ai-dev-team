# Discussion Stage Milestone B — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `pipeline_builder/index.html` so the 💬 Discuss block supports two modes — *Inline* (structured participant rows with role, persona, and optional LLM override) and *Preset* (reference an external YAML file) — with collapse/expand per participant row.

**Architecture:** All changes are isolated to `pipeline_builder/index.html`. The discuss block's in-memory state changes from a flat string of role names to a richer object. The YAML generator and parser are updated in lockstep. No backend changes needed — `DiscussionAgent` already handles the extended inline format.

**Tech Stack:** Vanilla HTML/JS/CSS (no build step, no external deps)

**Branch:** `feature/discussion-milestone-b`

---

## File Map

| File | Change |
|------|--------|
| `pipeline_builder/index.html` | All changes: CSS, state model, render, toYaml, parseYaml |

---

## Task 1: Switch to `feature/discussion-milestone-b`

- [ ] **Step 1: Check out the feature branch**

```bash
cd /home/wanleung/Projects/ai-software-house
git checkout feature/discussion-milestone-b
```

Expected: `Switched to branch 'feature/discussion-milestone-b'`

---

## Task 2: Add CSS for participant rows

**Files:**
- Modify: `pipeline_builder/index.html` (inside the `<style>` block, after `.discuss-form textarea` rule at line 37)

The current `.discuss-form` styles (lines 32–37) handle the old textarea. We add new rules for participant rows, the edit button, and the mode toggle.

- [ ] **Step 1: Add CSS rules for participant rows and mode toggle**

Find the line:
```css
  .discuss-form textarea { height: 60px; resize: vertical; }
```

Replace with:
```css
  .discuss-form textarea { height: 60px; resize: vertical; }
  .discuss-mode-toggle { display: flex; gap: 4px; margin-bottom: 8px; }
  .discuss-mode-btn { background: #313244; border: 1px solid #6c7086; border-radius: 4px;
    color: #6c7086; padding: 2px 8px; font-size: 11px; cursor: pointer; }
  .discuss-mode-btn.active { background: #a6e3a1; border-color: #a6e3a1; color: #1e1e2e; font-weight: 600; }
  .participant-row { background: #2a2a3e; border-radius: 5px; padding: 5px 8px;
    margin-bottom: 4px; }
  .participant-row-header { display: flex; align-items: center; gap: 6px; }
  .participant-role-input { background: #1e1e2e; border: 1px solid #6c7086; border-radius: 3px;
    color: #cdd6f4; padding: 2px 5px; width: 80px; font-size: 11px; }
  .participant-persona-preview { color: #6c7086; font-size: 10px; flex: 1;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .participant-edit-btn { background: none; border: none; color: #89b4fa; cursor: pointer;
    font-size: 12px; padding: 0 3px; }
  .participant-expanded { margin-top: 5px; }
  .participant-expanded textarea { background: #1e1e2e; border: 1px solid #89b4fa; border-radius: 3px;
    color: #cdd6f4; padding: 4px 6px; width: 100%; box-sizing: border-box;
    font-size: 10px; height: 40px; resize: none; margin-top: 3px; }
  .participant-expanded select { background: #1e1e2e; border: 1px solid #6c7086; border-radius: 3px;
    color: #cdd6f4; padding: 2px 5px; font-size: 10px; width: 100%; margin-top: 3px; }
  .participant-add-btn { color: #89b4fa; font-size: 11px; cursor: pointer;
    background: none; border: none; padding: 2px 0; margin-top: 3px; }
```

- [ ] **Step 2: Verify the file still renders in browser**

Open `pipeline_builder/index.html` in a browser. Existing blocks should look unchanged. No JS errors in console.

---

## Task 3: Update discuss block state model

**Files:**
- Modify: `pipeline_builder/index.html` (JS section — `dropOnList` function, ~line 191)

The current drop handler creates:
```js
{ type: 'discuss', participants: 'analyst\nskeptic\noptimist', max_rounds: 2, output_mode: 'both' }
```

We change it to:
```js
{
  type: 'discuss',
  mode: 'inline',          // 'inline' | 'preset'
  participants: [           // used when mode === 'inline'
    { role: 'analyst',  persona: '', llm: '' },
    { role: 'skeptic',  persona: '', llm: '' },
    { role: 'optimist', persona: '', llm: '' },
  ],
  preset_file: '',          // used when mode === 'preset'
  max_rounds: 2,
  output_mode: 'both',
  _expanded: {},            // { participantIndex: true } — UI state only, not serialized
}
```

- [ ] **Step 1: Update the drop handler**

Find:
```js
    } else if (dragSource.type === 'discuss') {
      stages.splice(toIndex, 0, {
        type: 'discuss',
        participants: 'analyst\nskeptic\noptimist',
        max_rounds: 2,
        output_mode: 'both',
      });
```

Replace with:
```js
    } else if (dragSource.type === 'discuss') {
      stages.splice(toIndex, 0, {
        type: 'discuss',
        mode: 'inline',
        participants: [
          {role: 'analyst',  persona: '', llm: ''},
          {role: 'skeptic',  persona: '', llm: ''},
          {role: 'optimist', persona: '', llm: ''},
        ],
        preset_file: '',
        max_rounds: 2,
        output_mode: 'both',
        _expanded: {},
      });
```

---

## Task 4: Rewrite the discuss block render function

**Files:**
- Modify: `pipeline_builder/index.html` (JS `render()` function, discuss block branch, ~lines 242–266)

This is the largest change. We replace the old textarea-based form with:
- Mode toggle buttons (Inline / Preset file)
- Inline mode: participant rows (collapsed by default, expand on ✏️)
- Preset mode: single text input for preset file

- [ ] **Step 1: Replace the discuss block render branch**

Find the block:
```js
    } else if (item.type === 'discuss') {
      const wrap = document.createElement('div');
      wrap.className = 'discuss-item';
      wrap.dataset.index = idx;
      wrap.draggable = true;
      wrap.ondragstart = e => dragStartListItem(e, idx);
      wrap.innerHTML = `
        <div class="discuss-header">
          💬 Discuss
          <button class="remove-btn" style="margin-left:auto" onclick="removeItem(${idx})">×</button>
        </div>
        <div class="discuss-form">
          <label>Participants (one role per line)</label>
          <textarea onchange="stages[${idx}].participants=this.value;updatePreview()"></textarea>
          <label>Max rounds</label>
          <input type="number" min="1" max="10" value="${item.max_rounds}"
                 onchange="stages[${idx}].max_rounds=parseInt(this.value) || 1;updatePreview()">
          <label>Output mode</label>
          <select onchange="stages[${idx}].output_mode=this.value;updatePreview()">
            <option value="both" ${item.output_mode==='both'?'selected':''}>both</option>
            <option value="synthesis" ${item.output_mode==='synthesis'?'selected':''}>synthesis</option>
            <option value="transcript" ${item.output_mode==='transcript'?'selected':''}>transcript</option>
          </select>
        </div>`;
      wrap.querySelector('textarea').value = item.participants;
      wrap.ondragend = clearDragOver;
      list.appendChild(wrap);
```

Replace with:
```js
    } else if (item.type === 'discuss') {
      const wrap = document.createElement('div');
      wrap.className = 'discuss-item';
      wrap.dataset.index = idx;
      wrap.draggable = true;
      wrap.ondragstart = e => dragStartListItem(e, idx);
      wrap.ondragend = clearDragOver;

      // Build participant rows HTML (inline mode)
      const buildParticipantRows = () => {
        if (!item.participants || !item.participants.length) {
          return '<div style="color:#6c7086;font-size:11px">No participants — click + Add</div>';
        }
        return item.participants.map((p, pi) => {
          const expanded = item._expanded && item._expanded[pi];
          const personaPreview = p.persona ? p.persona.slice(0, 55) + (p.persona.length > 55 ? '…' : '') : '';
          if (expanded) {
            return `<div class="participant-row">
              <div class="participant-row-header">
                <input class="participant-role-input" value="${_esc(p.role)}"
                  oninput="stages[${idx}].participants[${pi}].role=this.value.replace(/ /g,'_');updatePreview()">
                <button class="remove-btn" onclick="removeParticipant(${idx},${pi})">×</button>
              </div>
              <div class="participant-expanded">
                <div style="font-size:10px;color:#6c7086;margin-top:3px">Persona (optional)</div>
                <textarea placeholder="How this participant should behave..."
                  oninput="stages[${idx}].participants[${pi}].persona=this.value;updatePreview()"
                >${_esc(p.persona)}</textarea>
                <div style="font-size:10px;color:#6c7086;margin-top:3px">LLM override (optional)</div>
                <select onchange="stages[${idx}].participants[${pi}].llm=this.value;updatePreview()">
                  <option value="" ${!p.llm?'selected':''}}>(default)</option>
                  <option value="openai" ${ p.llm==='openai'?'selected':''}>openai</option>
                  <option value="grok" ${p.llm==='grok'?'selected':''}>grok</option>
                  <option value="codex" ${p.llm==='codex'?'selected':''}>codex</option>
                </select>
                <button class="participant-edit-btn" style="margin-top:4px;color:#6c7086"
                  onclick="toggleParticipantExpanded(${idx},${pi})">▲ collapse</button>
              </div>
            </div>`;
          } else {
            return `<div class="participant-row">
              <div class="participant-row-header">
                <input class="participant-role-input" value="${_esc(p.role)}"
                  oninput="stages[${idx}].participants[${pi}].role=this.value.replace(/ /g,'_');updatePreview()">
                <span class="participant-persona-preview">${_esc(personaPreview)}</span>
                <button class="participant-edit-btn" onclick="toggleParticipantExpanded(${idx},${pi})">✏️</button>
                <button class="remove-btn" onclick="removeParticipant(${idx},${pi})">×</button>
              </div>
            </div>`;
          }
        }).join('');
      };

      // Mode-specific body
      const modeBody = item.mode === 'preset'
        ? `<label style="font-size:11px;color:#cdd6f4;display:block;margin-top:4px">Preset file</label>
           <input style="background:#1e1e2e;border:1px solid #6c7086;border-radius:4px;color:#cdd6f4;
             padding:3px 6px;width:100%;box-sizing:border-box;font-size:12px"
             placeholder="discussions/my-debate.yaml"
             value="${_esc(item.preset_file)}"
             oninput="stages[${idx}].preset_file=this.value;updatePreview()">`
        : `<div id="prows-${idx}">${buildParticipantRows()}</div>
           <button class="participant-add-btn" onclick="addParticipant(${idx})">+ Add participant</button>`;

      wrap.innerHTML = `
        <div class="discuss-header">
          💬 Discuss
          <button class="remove-btn" style="margin-left:auto" onclick="removeItem(${idx})">×</button>
        </div>
        <div class="discuss-form">
          <div class="discuss-mode-toggle">
            <button class="discuss-mode-btn${item.mode==='inline'?' active':''}"
              onclick="setDiscussMode(${idx},'inline')">Inline</button>
            <button class="discuss-mode-btn${item.mode==='preset'?' active':''}"
              onclick="setDiscussMode(${idx},'preset')">Preset file</button>
          </div>
          ${modeBody}
          <label>Max rounds</label>
          <input type="number" min="1" max="10" value="${item.max_rounds}"
                 onchange="stages[${idx}].max_rounds=parseInt(this.value)||1;updatePreview()">
          <label>Output mode</label>
          <select onchange="stages[${idx}].output_mode=this.value;updatePreview()">
            <option value="both" ${item.output_mode==='both'?'selected':''}>both</option>
            <option value="synthesis" ${item.output_mode==='synthesis'?'selected':''}>synthesis</option>
            <option value="transcript" ${item.output_mode==='transcript'?'selected':''}>transcript</option>
          </select>
        </div>`;
      list.appendChild(wrap);
```

- [ ] **Step 2: Add helper functions before `render()`**

Find the line `function render() {` and insert before it:

```js
function _esc(s) {
  return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function setDiscussMode(idx, mode) {
  stages[idx].mode = mode;
  if (!stages[idx]._expanded) stages[idx]._expanded = {};
  render();
}

function addParticipant(idx) {
  stages[idx].participants.push({role: 'role_' + (stages[idx].participants.length + 1), persona: '', llm: ''});
  render();
}

function removeParticipant(idx, pi) {
  stages[idx].participants.splice(pi, 1);
  if (stages[idx]._expanded) delete stages[idx]._expanded[pi];
  render();
}

function toggleParticipantExpanded(idx, pi) {
  if (!stages[idx]._expanded) stages[idx]._expanded = {};
  stages[idx]._expanded[pi] = !stages[idx]._expanded[pi];
  render();
}
```

- [ ] **Step 3: Open the pipeline builder in a browser and verify**

Open `pipeline_builder/index.html`. Drag a 💬 Discuss block onto the canvas. Verify:
- Mode toggle shows "Inline" active by default
- Three participant rows (analyst, skeptic, optimist) appear collapsed
- ✏️ expands a row revealing persona textarea and LLM dropdown
- ▲ collapse button collapses the row
- + Add participant adds a new row
- ✕ removes a row
- Switching to "Preset file" mode shows a single text input
- Switching back to "Inline" mode restores participant rows

---

## Task 5: Update `toYaml()` for both modes

**Files:**
- Modify: `pipeline_builder/index.html` (JS `toYaml()` function, discuss block branch, ~lines 311–317)

- [ ] **Step 1: Replace the discuss YAML generation**

Find:
```js
    } else if (item.type === 'discuss') {
      const roles = item.participants.split('\n').map(r => r.trim()).filter(Boolean);
      out += `  - discuss:\n`;
      out += `      participants:\n`;
      roles.forEach(r => { out += `        - role: ${r}\n`; });
      out += `      max_rounds: ${item.max_rounds}\n`;
      out += `      output_mode: ${item.output_mode}\n`;
```

Replace with:
```js
    } else if (item.type === 'discuss') {
      out += `  - discuss:\n`;
      if (item.mode === 'preset') {
        if (item.preset_file) out += `      preset: ${item.preset_file}\n`;
      } else {
        const parts = (item.participants || []).filter(p => p.role && p.role.trim());
        if (parts.length) {
          out += `      participants:\n`;
          parts.forEach(p => {
            out += `        - role: ${p.role.trim()}\n`;
            if (p.persona && p.persona.trim()) out += `          persona: "${p.persona.trim().replace(/"/g, '\\"')}"\n`;
            if (p.llm && p.llm.trim()) out += `          llm: ${p.llm.trim()}\n`;
          });
        }
      }
      out += `      max_rounds: ${item.max_rounds}\n`;
      out += `      output_mode: ${item.output_mode}\n`;
```

- [ ] **Step 2: Verify YAML preview in browser**

In the pipeline builder:
1. Drag in a Discuss block (inline mode). Check YAML preview shows `participants:` with role/persona/llm.
2. Edit a participant persona and LLM. Verify YAML updates live.
3. Switch to Preset mode, type `discussions/test.yaml`. Verify YAML shows `preset: discussions/test.yaml`.
4. Empty participants in inline mode → no `participants:` key generated.

---

## Task 6: Update `parseYaml()` for both modes + backward compat

**Files:**
- Modify: `pipeline_builder/index.html` (JS `parseYaml()` function, discuss block branch, ~lines 366–383)

- [ ] **Step 1: Replace the discuss YAML parser**

Find:
```js
    } else if (discussMatch) {
      const disc = {type:'discuss', participants:'', max_rounds:2, output_mode:'both'};
      i++;
      const roleLines = [];
      while (i < lines.length) {
        const l = lines[i];
        const roundsM = l.match(/^\s+max_rounds:\s+(\d+)/);
        const modeM = l.match(/^\s+output_mode:\s+(\S+)/);
        const roleM = l.match(/^\s+-\s+role:\s+(\S+)/);
        if (roundsM) disc.max_rounds = parseInt(roundsM[1]);
        else if (modeM) { const validModes = ['both', 'synthesis', 'transcript']; disc.output_mode = validModes.includes(modeM[1]) ? modeM[1] : 'both'; }
        else if (roleM) roleLines.push(roleM[1]);
        else if (l.match(/^\s{2}-/)) { i--; break; }
        i++;
      }
      disc.participants = roleLines.join('\n');
      result.push(disc);
      continue;
```

Replace with:
```js
    } else if (discussMatch) {
      const disc = {
        type:'discuss', mode:'inline',
        participants:[], preset_file:'',
        max_rounds:2, output_mode:'both', _expanded:{},
      };
      i++;
      let curParticipant = null;
      while (i < lines.length) {
        const l = lines[i];
        const roundsM   = l.match(/^\s+max_rounds:\s+(\d+)/);
        const modeM     = l.match(/^\s+output_mode:\s+(\S+)/);
        const presetM   = l.match(/^\s+preset:\s+(.+)/);
        const roleM     = l.match(/^\s+-\s+role:\s+(\S+)/);
        const personaM  = l.match(/^\s+persona:\s+"?(.*?)"?\s*$/);
        const llmM      = l.match(/^\s+llm:\s+(\S+)/);
        const plainRoleM= l.match(/^\s+-\s+(\w+)\s*$/);  // backward compat: "- analyst"
        if (roundsM) disc.max_rounds = parseInt(roundsM[1]);
        else if (modeM) { const v = ['both','synthesis','transcript']; disc.output_mode = v.includes(modeM[1]) ? modeM[1] : 'both'; }
        else if (presetM) { disc.mode = 'preset'; disc.preset_file = presetM[1].trim(); }
        else if (roleM) { curParticipant = {role:roleM[1], persona:'', llm:''}; disc.participants.push(curParticipant); }
        else if (personaM && curParticipant) { curParticipant.persona = personaM[1].replace(/\\"/g,'"'); }
        else if (llmM && curParticipant) { curParticipant.llm = llmM[1]; }
        else if (plainRoleM && !l.match(/^\s+-\s+(role|persona|llm|preset|participants|max_rounds|output_mode):/)) {
          curParticipant = {role:plainRoleM[1], persona:'', llm:''};
          disc.participants.push(curParticipant);
        }
        else if (l.match(/^\s{2}-/)) { i--; break; }
        i++;
      }
      result.push(disc);
      continue;
```

- [ ] **Step 2: Test round-trip import in browser**

In the pipeline builder, use "Save pipeline.yaml ↓" to download, then:

Paste this YAML into a test (use browser console: `stages = parseYaml(testYaml); render()`):

```yaml
stages:
  - discuss:
      participants:
        - role: analyst
          persona: "You examine data objectively."
          llm: grok
        - role: skeptic
      max_rounds: 3
      output_mode: synthesis
  - discuss:
      preset: discussions/my-debate.yaml
      max_rounds: 2
      output_mode: both
  - discuss:
      participants:
        - role: visionary
        - role: critic
      max_rounds: 1
      output_mode: transcript
```

Expected result:
- First discuss: inline mode, analyst (with persona + grok), skeptic (no persona)
- Second discuss: preset mode with `discussions/my-debate.yaml`
- Third discuss: inline mode, two role-only participants

- [ ] **Step 3: Commit**

```bash
git add pipeline_builder/index.html
git commit -m "feat: Discussion Stage Milestone B — inline participant rows in pipeline builder

- Add mode toggle: Inline / Preset file
- Inline mode: structured participant rows with collapse/expand
  - Role name input, persona textarea (expand on ✏️), LLM dropdown
  - Add/remove participant buttons
- Preset mode: single text input for preset YAML filename
- Updated toYaml(): emits role/persona/llm per participant in inline mode,
  emits preset: key in preset mode
- Updated parseYaml(): handles both forms + backward compat for plain role strings
- Helper functions: setDiscussMode, addParticipant, removeParticipant,
  toggleParticipantExpanded, _esc"
```

---

## Task 7: Open PR

- [ ] **Step 1: Push branch and open PR**

```bash
git push -u origin feature/discussion-milestone-b
gh pr create \
  --title "feat: Discussion Stage Milestone B — inline discuss block in pipeline builder" \
  --body "## Summary

Extends the 💬 Discuss block in the pipeline builder UI with full inline participant editing.

## Changes

- **Mode toggle**: Inline / Preset file
- **Inline mode**: structured participant rows (collapse/expand), role + persona + LLM override per row, add/remove buttons
- **Preset mode**: single text input referencing a \`discussions/\` YAML file
- YAML generator updated for both forms
- YAML parser updated with backward compatibility for plain role strings

## Testing

Open \`pipeline_builder/index.html\` — drag 💬 Discuss, add participants with personas, switch modes, verify YAML preview.

Closes Discussion Stage Milestone B spec: \`docs/superpowers/specs/2026-05-28-discussion-milestone-b-design.md\`" \
  --base master \
  --head feature/discussion-milestone-b
```
