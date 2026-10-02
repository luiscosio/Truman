"""Styles and scripts for trace reports. Everything is inline so a report is one offline file.

Colour carries meaning: sky marks anything the constructed world supplied or
changed, ground marks reference content, rose marks removed text and errors.
Serif text is something that was read or written; sans is the interface.
"""

STYLE = """
:root{color-scheme:light dark;
--paper:#f3f5f8;--surface:#fff;--ink:#18202c;--slate:#5a6575;--line:#d8dee6;--soft:#e9edf2;
--sky:#2f78b7;--sky-tint:#ddeaf6;--sky-ink:#1d5b8f;--ground:#56654a;--ground-tint:#e6ebdf;
--rose:#a8434c;--rose-tint:#f5e1e3;--amber:#8f5d12;--amber-tint:#f6ead5;--violet:#6a4c9c;--violet-tint:#ece6f6;
--serif:Charter,"Bitstream Charter","Iowan Old Style","Sitka Text",Cambria,Georgia,serif;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;
--mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace}
@media(prefers-color-scheme:dark){:root{--paper:#10151c;--surface:#171e27;--ink:#e3e8ef;--slate:#9aa6b5;--line:#2b3542;--soft:#1f2832;
--sky:#73b0e6;--sky-tint:#1b3047;--sky-ink:#a9d0f2;--ground:#a3b78d;--ground-tint:#232c1f;--rose:#e88a93;--rose-tint:#3b2227;
--amber:#e2b46b;--amber-tint:#352a17;--violet:#b9a1e6;--violet-tint:#2a2340}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 var(--sans);-webkit-font-smoothing:antialiased}
main{max-width:1180px;margin:0 auto;padding:40px 28px 64px}
a{color:var(--sky-ink);text-underline-offset:2px}a:hover{color:var(--sky)}
button,select,input,textarea{font:inherit;color:inherit}
:focus-visible{outline:3px solid var(--sky);outline-offset:2px}
h1,h2,h3{font-weight:650;letter-spacing:-.01em;margin:0}
h2{font-size:21px;margin:48px 0 6px}h3{font-size:16px}
.lede{color:var(--slate);max-width:72ch;margin:4px 0 18px}
.prose{font:17px/1.62 var(--serif);max-width:72ch;overflow-wrap:anywhere}
.prose p{margin:0 0 .8em}.prose p:last-child{margin-bottom:0}
.prose h4{font:650 17px/1.35 var(--sans);margin:1.1em 0 .4em}.prose h4.md-h1,.prose h4.md-h2{font-size:19px}
.prose ul,.prose ol{margin:0 0 .8em;padding-left:1.3em}.prose li{margin:.2em 0}
.prose blockquote{margin:0 0 .8em;padding-left:14px;border-left:3px solid var(--line);color:var(--slate)}
.prose code{font:.86em var(--mono);background:var(--soft);padding:1px 4px;border-radius:4px}
.prose hr{border:0;border-top:1px solid var(--line);margin:1em 0}
.md-table{overflow-x:auto;margin:0 0 .8em}.md-table table{border-collapse:collapse;font:14px/1.45 var(--sans)}
.md-table th,.md-table td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}.md-table th{background:var(--soft)}
pre{font:12.5px/1.6 var(--mono);white-space:pre-wrap;overflow-wrap:anywhere;background:var(--soft);padding:12px 14px;border-radius:6px;max-height:460px;overflow:auto;margin:8px 0 0}
.url{font:13px/1.45 var(--mono);overflow-wrap:anywhere}

/* Header */
.masthead{display:flex;justify-content:space-between;gap:16px;align-items:baseline;flex-wrap:wrap;color:var(--slate);font-size:13px}
.masthead strong{color:var(--ink);font-weight:650}
.question{font:400 clamp(21px,2.6vw,27px)/1.42 var(--serif);max-width:58ch;margin:22px 0 8px}
.instructions{color:var(--slate);max-width:90ch;margin:0 0 20px;font-size:13.5px;overflow-wrap:anywhere;white-space:pre-line}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px 24px;margin:0;padding:16px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.facts div{min-width:0}.facts dt{font-size:12px;color:var(--slate)}.facts dd{margin:2px 0 0;font-weight:550;overflow-wrap:anywhere}
.notice{margin:16px 0 0;padding:12px 16px;border-radius:6px;background:var(--amber-tint);color:var(--ink);max-width:90ch}
.notice.sky{background:var(--sky-tint)}
.actions{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 0}
.button{border:1px solid var(--line);background:var(--surface);border-radius:6px;padding:7px 12px;cursor:pointer;font-size:13.5px}
.button:hover{border-color:var(--slate)}
.button.primary{background:var(--ink);color:var(--paper);border-color:var(--ink)}

/* Conditions */
.ref{--tone:var(--ground);--tone-tint:var(--ground-tint)}.syn{--tone:var(--sky);--tone-tint:var(--sky-tint)}.hist{--tone:var(--amber);--tone-tint:var(--amber-tint)}
.condition{display:inline-flex;align-items:center;gap:7px;font-weight:650}
.condition::before{content:"";width:10px;height:10px;border-radius:50%;background:var(--tone)}

/* Outcomes */
.outcomes{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));gap:18px;margin-top:14px}
.outcome{background:var(--surface);border:1px solid var(--line);border-top:4px solid var(--tone);border-radius:6px;padding:18px 20px;min-width:0;display:flex;flex-direction:column;gap:14px}
.outcome h3{font-size:15px;color:var(--slate);font-weight:500}
.tally{display:flex;flex-wrap:wrap;gap:6px 18px;margin:0;font-size:13.5px}.tally div{display:flex;gap:6px}.tally dt{color:var(--slate)}.tally dd{margin:0;font-weight:600}
.status-bad{color:var(--rose)}
.reads{list-style:none;margin:0;padding:0;display:grid;gap:6px}
.reads li{display:flex;justify-content:space-between;gap:10px;align-items:baseline;font-size:13.5px}
.chip{flex:none;display:inline-block;font-size:12px;font-weight:600;padding:2px 8px;border-radius:999px;background:var(--soft);color:var(--slate);white-space:nowrap}
.chip.changed{background:var(--sky-tint);color:var(--sky-ink)}.chip.original{background:var(--ground-tint);color:var(--ground)}.chip.failed{background:var(--rose-tint);color:var(--rose)}
a.chip{text-decoration:none}
.said{border-left:3px solid var(--tone);padding-left:14px}
.said .asked{font-size:13px;color:var(--slate);margin:0 0 4px}
.said .prose{font-size:15.5px}
.outcome .open-trace{align-self:flex-start;margin-top:auto}

/* Changes: the painted sky */
.page-changes{background:var(--surface);border:1px solid var(--line);border-radius:6px;margin-top:14px}
.page-changes>summary{list-style:none;cursor:pointer;display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px 16px;align-items:baseline;padding:14px 18px}
.page-changes>summary::-webkit-details-marker{display:none}
.page-changes>summary h3{font:600 16px/1.35 var(--sans)}
.page-changes>summary .url{color:var(--slate)}
.edits{list-style:none;margin:0;padding:0 18px 8px;counter-reset:edit}
.edit{padding:12px 0;border-top:1px solid var(--soft)}
.edit .kind{font-size:12.5px;color:var(--slate);margin:0 0 2px}
.edit .diff{font:16px/1.65 var(--serif);overflow-wrap:anywhere;max-width:78ch}
ins{background:var(--sky-tint);color:var(--sky-ink);text-decoration:none;border-bottom:2px solid var(--sky);padding:0 1px}
del{background:var(--rose-tint);color:var(--rose);text-decoration:line-through;text-decoration-thickness:1px}
.gap{color:var(--slate);padding:0 3px}
.key{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13px;color:var(--slate);margin:6px 0 0}
.empty{color:var(--slate);font-style:italic}

/* Trace tabs */
.tabs{display:flex;flex-wrap:wrap;gap:4px;border-bottom:1px solid var(--line);margin-top:14px}
.tab{border:1px solid transparent;border-bottom:0;background:none;padding:10px 14px 9px;border-radius:6px 6px 0 0;cursor:pointer;color:var(--slate);margin-bottom:-1px}
.tab[aria-selected="true"]{background:var(--surface);border-color:var(--line);color:var(--ink)}
.trace{background:var(--surface);border:1px solid var(--line);border-top:0;border-radius:0 0 6px 6px;padding:18px 22px 22px}
.trace[hidden]{display:none}
.toolbar{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;padding-bottom:14px;border-bottom:1px solid var(--soft)}
.filters{display:flex;flex-wrap:wrap;gap:6px}
.filter-pill{border:1px solid var(--line);background:var(--surface);border-radius:999px;padding:4px 11px;font-size:13px;cursor:pointer;color:var(--slate)}
.filter-pill[aria-pressed="true"]{border-color:var(--ink);color:var(--ink);background:var(--soft)}
.filter-pill:disabled{opacity:.4;cursor:default}
.filter-count{font-variant-numeric:tabular-nums;margin-left:3px;opacity:.75}
.search{flex:1 1 200px;max-width:320px;border:1px solid var(--line);border-radius:6px;padding:6px 10px;background:var(--surface)}
.filter-status{font-size:12.5px;color:var(--slate);margin:0}

/* Timeline */
.timeline{list-style:none;margin:6px 0 0;padding:0}
.step{display:grid;grid-template-columns:76px minmax(0,1fr);gap:0 14px;position:relative}
.step[hidden]{display:none}
.rail{position:relative;text-align:right;padding:14px 12px 0 0;font-size:12px;color:var(--slate);font-variant-numeric:tabular-nums;border-right:2px solid var(--soft)}
.rail::after{content:"";position:absolute;right:-6px;top:19px;width:10px;height:10px;border-radius:50%;background:var(--surface);border:2px solid var(--dot,var(--slate))}
.rail .n{display:block;font-weight:600;color:var(--ink)}
.body{padding:12px 0 14px;min-width:0}
.who{font-size:13px;font-weight:650;color:var(--dot,var(--slate));margin:0 0 6px;display:flex;flex-wrap:wrap;gap:4px 10px;align-items:baseline}
.who .quiet{font-weight:400;color:var(--slate)}
.step.user{--dot:var(--violet)}.step.assistant{--dot:var(--ink)}.step.tool-call{--dot:var(--sky)}.step.network{--dot:var(--amber)}
.step.thinking{--dot:var(--line)}.step.system{--dot:var(--slate)}.step.error{--dot:var(--rose)}
.step.user .prose{background:var(--violet-tint);padding:12px 16px;border-radius:6px}
.step.answer .prose{border-left:3px solid var(--ink);padding-left:16px}
.rail .n{overflow-wrap:anywhere}
.step.thinking .body{padding:8px 0}.step.thinking .rail{padding-top:8px}.step.thinking .rail::after{top:13px}
.step.thinking .who{font-weight:400;font-style:italic;margin:0;color:var(--slate)}
.part{margin-top:10px}
.part-label{font-size:12.5px;color:var(--slate);margin:0 0 4px}
.served{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:baseline;padding:8px 12px;border-radius:6px;background:var(--soft);font-size:13.5px;margin-top:6px}
.served .url{flex:1 1 260px}
.returned{border:1px solid var(--line);border-radius:6px;padding:12px 16px}
.returned .prose{font-size:15.5px}.returned .prose h4{font-size:15.5px}.returned .prose h4.md-h1,.returned .prose h4.md-h2{font-size:16.5px}
.returned>pre{margin:0;background:none;padding:0;max-height:none}
.js .clamp{max-height:440px;overflow:hidden;position:relative}
.js .clamp.overflowing::after{content:"";position:absolute;inset:auto 0 0;height:72px;background:linear-gradient(transparent,var(--surface));pointer-events:none}
.js .clamp.expanded{max-height:none}.js .clamp.expanded::after{display:none}
.expand{margin-top:6px}
.caveat{font-size:12.5px;color:var(--slate);margin:6px 0 0;max-width:80ch}
.raw{margin-top:8px;font-size:13px}.raw>summary{cursor:pointer;color:var(--slate)}
.raw[open]>summary{margin-bottom:4px}
mark{background:var(--amber-tint);color:inherit;border-radius:2px}

/* Review */
.review-section{margin-top:22px;padding-top:16px;border-top:1px solid var(--line)}
.review{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:2px 26px;margin-top:8px}
.review label{display:flex;justify-content:space-between;gap:12px;align-items:center;border-top:1px solid var(--soft);padding:8px 0;font-size:13.5px}
.review select{border:1px solid var(--line);border-radius:5px;padding:4px 6px;background:var(--surface)}
.review textarea{grid-column:1/-1;min-height:90px;border:1px solid var(--line);border-radius:6px;padding:8px;margin-top:8px;background:var(--surface);resize:vertical}

.copy-tools{display:flex;align-items:center;gap:10px;margin:6px 0 0;user-select:none}
.copy-text{border:0;background:none;padding:0;color:var(--slate);font-size:12px;cursor:pointer;text-decoration:underline;text-underline-offset:2px}
.copy-status{font-size:12px;color:var(--slate)}
footer{margin-top:48px;padding-top:16px;border-top:1px solid var(--line);color:var(--slate);font-size:13px;max-width:90ch}

@media(max-width:720px){main{padding:24px 16px 48px}.step{grid-template-columns:52px minmax(0,1fr);gap:0 10px}.rail{padding-right:8px}
.trace{padding:14px}.prose{font-size:16px}}
@media(prefers-reduced-motion:no-preference){.step.flash .body{animation:flash 1.2s ease-out}@keyframes flash{from{background:var(--amber-tint)}to{background:transparent}}}
@media print{.toolbar,.actions,.tabs,.copy-tools,.review-section{display:none}.trace[hidden]{display:block}pre{max-height:none}}
"""


COPY_SCRIPT = r"""
async function copyPlainText(text) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
  } catch (_) {}
  const active = document.activeElement;
  const selection = window.getSelection();
  const ranges = Array.from({length: selection.rangeCount}, (_, i) => selection.getRangeAt(i).cloneRange());
  const field = document.createElement('textarea');
  field.value = text;
  field.readOnly = true;
  field.style.cssText = 'position:fixed;left:-10000px;top:0';
  document.body.append(field);
  try {
    field.select();
    if (!document.execCommand('copy')) throw new Error('Copy unavailable');
  } finally {
    field.remove();
    active?.focus({preventScroll:true});
    selection.removeAllRanges();
    for (const range of ranges) selection.addRange(range);
  }
}
for (const content of document.querySelectorAll('.copyable')) {
  const tools = document.createElement('div');
  tools.className = 'copy-tools';
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'copy-text';
  button.textContent = 'Copy text';
  const step = content.closest('.trace-event');
  const raw = content.closest('details')?.classList.contains('raw');
  button.setAttribute('aria-label', raw ? 'Copy recorded event JSON' :
    step ? `Copy text from event #${step.dataset.eventId}` : 'Copy text');
  const status = document.createElement('span');
  status.className = 'copy-status';
  status.setAttribute('role','status');
  let reset;
  button.addEventListener('click', async () => {
    clearTimeout(reset);
    try {
      await copyPlainText(content.innerText);
      status.textContent = 'Copied';
    } catch (_) {
      status.textContent = 'Could not copy. Select the text and copy it with your keyboard.';
    }
    reset = setTimeout(() => { status.textContent = ''; }, 4000);
  });
  tools.append(button,status);
  content.after(tools);
}
"""


APP_SCRIPT = r"""
document.documentElement.classList.add('js');
for(const box of document.querySelectorAll('.clamp')){
  const panel=box.closest('.trace');const wasHidden=panel?.hidden;if(panel)panel.hidden=false;
  const long=box.scrollHeight>box.clientHeight+40;if(panel)panel.hidden=wasHidden;
  if(!long)continue;
  box.classList.add('overflowing');
  const button=document.createElement('button');button.type='button';button.className='button expand';
  button.textContent='Show all of it';button.setAttribute('aria-expanded','false');
  button.addEventListener('click',()=>{const open=box.classList.toggle('expanded');button.textContent=open?'Show less':'Show all of it';button.setAttribute('aria-expanded',String(open));if(!open)box.scrollIntoView({block:'nearest'});});
  box.after(button);
}
const traces=JSON.parse(document.getElementById('trace-data').textContent);
const batch=traces[0]?.batch_id||'report';
const storageKey='truman-review-'+batch;
const tabs=Array.from(document.querySelectorAll('[role="tab"]'));
const panels=Array.from(document.querySelectorAll('.trace'));
function download(name,data,type='application/json'){const blob=new Blob([typeof data==='string'?data:JSON.stringify(data,null,2)],{type});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
function review(){return {batch_id:batch,reviewed_at:new Date().toISOString(),runs:Array.from(document.querySelectorAll('.review')).map(box=>({id:box.dataset.run,...Object.fromEntries(Array.from(box.querySelectorAll('[data-field]')).map(el=>[el.dataset.field,el.value||null]))}))};}
try{const saved=JSON.parse(localStorage.getItem(storageKey)||'null');for(const item of saved?.runs||[]){const box=Array.from(document.querySelectorAll('.review')).find(el=>el.dataset.run===item.id);if(box)for(const el of box.querySelectorAll('[data-field]'))el.value=item[el.dataset.field]||'';}}catch(e){}
document.querySelectorAll('.review').forEach(box=>box.addEventListener('input',()=>{try{localStorage.setItem(storageKey,JSON.stringify(review()));}catch(e){}}));
document.getElementById('export-traces').onclick=()=>download(batch+'-traces.json',traces);
document.getElementById('export-review')?.addEventListener('click',()=>download(batch+'-review.json',review()));
function current(){return panels.find(panel=>!panel.hidden)||panels[0];}
function select(index,focus){
  if(!panels[index])return;
  tabs.forEach((tab,i)=>{tab.setAttribute('aria-selected',String(i===index));tab.tabIndex=i===index?0:-1;});
  panels.forEach((panel,i)=>{panel.hidden=i!==index;});
  history.replaceState(null,'','#trace='+encodeURIComponent(panels[index].dataset.runId));
  if(focus)tabs[index]?.focus();
  applyFilters(panels[index]);
}
tabs.forEach((tab,index)=>{
  tab.addEventListener('click',()=>select(index));
  tab.addEventListener('keydown',event=>{
    const step={ArrowRight:1,ArrowLeft:-1}[event.key];
    if(step){event.preventDefault();select((index+step+tabs.length)%tabs.length,true);}
    if(event.key==='Home'){event.preventDefault();select(0,true);}
    if(event.key==='End'){event.preventDefault();select(tabs.length-1,true);}
  });
});
for(const link of document.querySelectorAll('[data-open-trace]'))link.addEventListener('click',event=>{
  const index=panels.findIndex(panel=>panel.dataset.runId===link.dataset.openTrace);
  if(index<0)return;
  event.preventDefault();select(index);
  const target=link.dataset.event?panels[index].querySelector(`[data-event-id="${link.dataset.event}"]`):panels[index];
  target?.scrollIntoView({block:'start'});
  if(target?.classList.contains('step')){target.classList.remove('flash');void target.offsetWidth;target.classList.add('flash');}
});
function applyFilters(panel){
  if(!panel)return;
  const pills=Array.from(panel.querySelectorAll('[data-filter]'));
  const active=new Set(pills.filter(p=>p.dataset.filter!=='all'&&p.getAttribute('aria-pressed')==='true').map(p=>p.dataset.filter));
  const query=(panel.querySelector('.search')?.value||'').trim().toLowerCase();
  const steps=Array.from(panel.querySelectorAll('.step'));
  for(const pill of pills){
    const role=pill.dataset.filter;
    const count=steps.filter(step=>role==='all'||step.dataset.role===role).length;
    pill.querySelector('.filter-count').textContent=count;
    pill.disabled=role!=='all'&&count===0;
    if(role==='all')pill.setAttribute('aria-pressed',String(active.size===0));
  }
  let shown=0;
  for(const step of steps){
    const visible=(active.size===0||active.has(step.dataset.role))&&(!query||step.textContent.toLowerCase().includes(query));
    step.hidden=!visible;if(visible)shown++;
  }
  panel.querySelector('.filter-status').textContent=shown===steps.length?`${steps.length} steps`:`Showing ${shown} of ${steps.length} steps`;
  panel.querySelector('.filter-empty').hidden=shown!==0;
}
for(const panel of panels){
  panel.querySelectorAll('[data-filter]').forEach(pill=>pill.addEventListener('click',()=>{
    if(pill.dataset.filter==='all')panel.querySelectorAll('[data-filter]').forEach(p=>p.setAttribute('aria-pressed','false'));
    else pill.setAttribute('aria-pressed',String(pill.getAttribute('aria-pressed')!=='true'));
    applyFilters(panel);
  }));
  panel.querySelector('.search')?.addEventListener('input',()=>applyFilters(panel));
}
document.getElementById('export-current').onclick=()=>{
  const source=current();
  if(!source)return;
  const panel=source.cloneNode(true);
  panel.removeAttribute('hidden');
  panel.querySelectorAll('.review-section,.toolbar,.filter-empty,.copy-tools,.expand').forEach(node=>node.remove());
  panel.querySelectorAll('[hidden]').forEach(node=>node.removeAttribute('hidden'));
  panel.querySelectorAll('details').forEach(node=>node.open=true);
  const doc=document.implementation.createHTMLDocument(source.dataset.runId+' trace');
  doc.documentElement.lang='en';
  const charset=doc.createElement('meta');charset.setAttribute('charset','utf-8');doc.head.prepend(charset);
  const viewport=doc.createElement('meta');viewport.name='viewport';viewport.content='width=device-width,initial-scale=1';doc.head.append(viewport);
  const style=doc.createElement('style');style.textContent=document.querySelector('style').textContent+' pre{max-height:none;overflow:visible}.trace{border-top:1px solid var(--line);border-radius:6px}';doc.head.append(style);
  const main=doc.createElement('main');main.append(document.querySelector('.question').cloneNode(true),panel);doc.body.append(main);
  const script=doc.createElement('script');script.textContent=COPY;doc.body.append(script);
  download(source.dataset.runId+'-trace.html','<!doctype html>'+doc.documentElement.outerHTML,'text/html;charset=utf-8');
};
const requested=new URLSearchParams(location.hash.slice(1)).get('trace');
select(Math.max(0,panels.findIndex(panel=>panel.dataset.runId===requested)));
"""
