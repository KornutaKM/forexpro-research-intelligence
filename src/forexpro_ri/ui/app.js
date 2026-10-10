'use strict';
(() => {
  let token = '';
  let snapshot = null;
  const $ = (id) => document.getElementById(id);
  const text = (node, value) => { node.textContent = String(value ?? '—'); return node; };
  const node = (tag, className, value) => {
    const n = document.createElement(tag);
    if (className) n.className = className;
    if (value !== undefined) text(n, value);
    return n;
  };
  const clear = (id) => { const el = $(id); el.replaceChildren(); return el; };
  const errorNotice = (msg) => { text($('notice'), msg); $('notice').classList.add('error'); };
  const notice = (msg) => { text($('notice'), msg); $('notice').classList.remove('error'); };
  const chip = (v) => node('span', 'chip ' + String(v).replace(/[^A-Z_]/g, ''), v);
  const kv = (container, key, value) => { const row = node('div', 'kv'); row.append(node('span','',key),node('strong','',value)); container.append(row); };
  const item = (container, first, second, right, click) => {
    const r = node('div','list-row');
    const col = node('div');
    if (click) {const b=node('button','select-record',first);b.addEventListener('click',click);col.append(b);} else col.append(node('strong','',first));
    col.append(node('div','minor',second));r.append(col,chip(right));container.append(r);
  };
  async function get(route) {
    if (!token) throw Error('Connect session first.');
    const res = await fetch(route,{headers:{'Authorization':'Bearer '+token},cache:'no-store',credentials:'omit'});
    if (!res.ok) throw Error(res.status === 401 ? 'Incorrect token. Reconnect using the token from your terminal.' : 'Request unavailable. Check local databases or signed-only policy.');
    return res.json();
  }
  async function refresh() {
    try {
      snapshot = await get('/api/overview');
      $('auth-state').classList.add('ok');text($('auth-state'),'CONNECTED');
      render(snapshot);
      notice(snapshot.warnings.length ? 'Local data sources unavailable: '+snapshot.warnings.join(', ') : 'Connected · advisory-only evidence and queue metadata. No source bundles are displayed.');
    } catch (err) { errorNotice(err.message); }
  }
  function render(state) {
    const q=state.queue.available?state.queue:null, m=state.memory.available?state.memory:null;
    text($('metric-research'),m?m.count:'—');
    text($('metric-queued'),q?q.counts.QUEUED+q.counts.RUNNING+q.counts.RETRY:'—');
    text($('metric-done'),q?q.counts.SUCCEEDED:'—');
    text($('metric-failed'),q?q.counts.FAILED:'—');
    const qo=clear('overview-queue'), mo=clear('overview-memory'), ql=clear('queue-content'), ml=clear('research-content');
    if (q){
      if (!q.jobs.length) {qo.append(node('p','empty','No queued jobs.'));ql.append(node('p','empty','No jobs yet.'));}
      for(const job of q.jobs.slice(-5).reverse())item(qo,job.job_id.slice(0,14)+'…','Attempts '+job.attempts+' / '+job.max_attempts,job.state);
      for(const job of q.jobs.slice().reverse())item(ql,job.job_id,'Attempts '+job.attempts+' / '+job.max_attempts+(job.error_code?' · '+job.error_code:''),job.state);
      if(q.truncated) ql.append(node('p','minor','Displaying the most recent 200 jobs.'));
    }else{qo.append(node('p','empty','Queue unavailable.'));ql.append(node('p','empty','Queue unavailable.'));}
    if(m){
      if(!m.experiments.length){mo.append(node('p','empty','No stored experiments.'));ml.append(node('p','empty','No stored experiments.'));}
      for(const exp of m.experiments.slice(-5).reverse())item(mo,exp.experiment_id,exp.disposition,exp.fail_count+' FAIL');
      for(const exp of m.experiments.slice().reverse())item(ml,exp.experiment_id,exp.disposition+' · '+exp.entry_sha256.slice(0,12)+'…',exp.fail_count+' FAIL',()=>loadDossier(exp.experiment_id));
      if(m.truncated)ml.append(node('p','minor','Displaying the most recent 200 records.'));
    }else{mo.append(node('p','empty','Research Memory unavailable.'));ml.append(node('p','empty','Research Memory unavailable.'));}
  }
  async function loadDossier(id){
    const target=clear('dossier-content');target.append(node('p','empty','Inspecting recorded evidence…'));
    try {
      const data=await get('/api/dossier?id='+encodeURIComponent(id)); target.replaceChildren();
      target.append(node('h3','',data.focus.experiment_id));
      kv(target,'Disposition',data.focus.recorded_disposition);
      kv(target,'Signed import',data.provenance.verification_status);
      kv(target,'Failed criteria',data.focus.recorded_criterion_counts.fail);
      kv(target,'Not evaluable',data.focus.recorded_criterion_counts.not_evaluable);
      kv(target,'Passed criteria',data.focus.recorded_criterion_counts.pass);
      target.append(node('div','note','Recorded verdicts are not scientific approvals, root-cause findings or trading advice.'));
      target.append(node('h3','','Procedure outcomes'));
      for(const p of data.procedures)item(target,p.procedure,'Recorded outcome',p.status);
      if(!data.procedures.length)target.append(node('p','empty','No procedure outcomes.'));
    }catch(err){text(target,err.message);}
  }
  async function loadProgram(){
    const target=clear('program-content');target.append(node('p','empty','Building verified research worklist…'));
    try{const d=await get('/api/program');target.replaceChildren();
      const tag=node('div','note',d.signed_only_gate_passed?'Historical signed-intake gate passed. Scientific authorization is still external.':'Synthetic-only mode: NOT trusted signed history.');target.append(tag);
      kv(target,'Recorded studies',d.observed_experiment_count);kv(target,'Topics identified',d.total_worklist_items);
      if(!d.worklist.length)target.append(node('p','empty','No recurring topics at current evidence thresholds.'));
      for(const x of d.worklist){const card=node('article','program-card');card.append(chip(x.kind),node('h4','',x.procedure+' · '+x.affected_experiment_count+' recorded studies'),node('p','',x.prospective_question));target.append(card);}
    }catch(e){text(target,e.message);}
  }
  async function loadAudit(){
    const el=clear('audit-content');el.append(node('p','empty','Checking local integrity…'));
    try{const data=await get('/api/audit');el.replaceChildren();kv(el,'Queue',data.queue.status);kv(el,'Research Memory',data.memory.status);kv(el,'Verified experiment count',data.memory.experiment_count);el.append(node('div','note','Local integrity is not cryptographic authentication or scientific approval.'));}catch(e){text(el,e.message);}
  }
  const titles={overview:'Overview',queue:'Job queue',research:'Research memory',program:'Research program',audit:'Integrity audit'};
  document.querySelectorAll('[data-view]').forEach((b)=>b.addEventListener('click',()=>{
    for(const n of document.querySelectorAll('[data-view]')) n.classList.toggle('active',n===b);
    for(const v of document.querySelectorAll('.view'))v.classList.toggle('active',v.id===b.dataset.view);
    text($('heading'),titles[b.dataset.view]);
    if (b.dataset.view==='program' && token) loadProgram();
  }));
  $('connect').addEventListener('click',()=>{
    const supplied=window.prompt('Paste the one-time Control Center token from the terminal:');
    if(!supplied)return;
    token=supplied.trim();refresh();
  });
  $('refresh').addEventListener('click',refresh);
  $('run-audit').addEventListener('click',loadAudit);
})();
