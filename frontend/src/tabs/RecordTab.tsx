import React, { useCallback, useEffect, useState } from 'react';
import { Lock, Printer, Download } from 'lucide-react';
import { apiRequest } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { useUi, Banner, Skeleton, Empty, RuleChips } from '../components/Ui';
import type { TabProps } from '../pages/RequestDetail';

export const RecordTab: React.FC<TabProps> = ({ req, reload }) => {
  const { user } = useAuth();
  const { toast, confirm } = useUi();
  const [rec, setRec] = useState<any>(undefined);
  const [draft, setDraft] = useState<any>(null);
  const [text, setText] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');

  const load = useCallback(async () => {
    try { const r = await apiRequest(`/requests/${req.id}/fulfilment-record`); setRec(r.content ? r : null); } catch (e: any) { toast.error(e.message); setRec(null); }
  }, [req.id]);
  useEffect(() => { load(); }, [load, req.status]);

  const ready = req.status === 'COMPLETED_PENDING_RECORD';
  useEffect(() => {
    if (ready && user?.role === 'analyst' && !draft) apiRequest(`/requests/${req.id}/fulfilment-record/draft`).then((d) => { setDraft(d); setText(d.narrative); }).catch((e) => toast.error(e.message));
  }, [ready, user?.role]);

  const generate = async () => {
    const edited = text.trim() !== (draft?.narrative || '').trim();
    const ok = await confirm({ title: 'Generate the final fulfilment record and close the request?', description: 'The record is immutable once generated.',
      lines: ['Request moves to CLOSED (final)', `Narrative: ${edited ? 'human-edited' : draft?.source === 'AI_DRAFTED' ? 'AI-drafted, confirmed by you' : 'deterministic'}`, 'Later corrections can only be recorded as addendum events'], confirmLabel: 'Generate & close' });
    if (ok === null) return;
    setBusy(true);
    try {
      const body = edited ? { narrative_override: text } : { narrative: text, narrative_source: draft?.source, confirm_narrative: confirmed };
      await apiRequest(`/requests/${req.id}/fulfilment-record`, { method: 'POST', body: JSON.stringify(body) });
      toast.success('Fulfilment record generated; request closed.'); await reload(); await load();
    } catch (e: any) { toast.error(e.message); } finally { setBusy(false); }
  };

  const addAddendum = async () => {
    try { await apiRequest(`/requests/${req.id}/fulfilment-record/addendum`, { method: 'POST', body: JSON.stringify({ text: note }) }); setNote(''); toast.success('Addendum recorded as a separate audit event; the record is unchanged.'); await load(); }
    catch (e: any) { toast.error(e.message); }
  };

  if (rec === undefined) return <Skeleton rows={4} />;

  if (!rec) {
    if (!ready) return <Empty title="No fulfilment record yet" next="It can be generated when all approved work is complete (status COMPLETED_PENDING_RECORD)." />;
    const needsConfirm = draft?.requires_confirmation && text.trim() === draft.narrative.trim();
    return (
      <div className="bg-white rounded-2xl border border-slate-200 p-5 space-y-3 text-xs">
        <h3 className="text-sm font-bold text-slate-900">Ready to close</h3>
        {user?.role !== 'analyst' ? <p className="text-slate-500">An Analyst generates the record.</p> : !draft ? <Skeleton rows={2} /> : (
          <>
            <Banner kind="info" title={draft.source === 'AI_DRAFTED' ? 'AI-drafted narrative: human confirmation required' : 'Narrative generated from stored data'}>You can edit the text. Everything else in the record is generated deterministically from stored data.</Banner>
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={5} aria-label="Narrative" className="w-full border border-slate-300 rounded-lg p-2" />
            {needsConfirm && <label className="flex items-center space-x-2"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} /><span>I have reviewed this AI-drafted narrative and confirm it is accurate.</span></label>}
            <button disabled={busy || (needsConfirm && !confirmed) || text.trim().length < 20} onClick={generate} className="px-4 py-2 bg-sky-600 text-white font-semibold rounded-lg disabled:opacity-40">{busy ? 'Generating...' : 'Generate fulfilment record'}</button>
          </>)}
      </div>);
  }

  const c = rec.content;
  const Sec: React.FC<{ n: number; t: string; children: React.ReactNode }> = ({ n, t, children }) => <section className="border-t border-slate-100 pt-3"><h4 className="font-bold text-slate-900 mb-1">{n}. {t}</h4><div className="space-y-1 text-slate-700">{children}</div></section>;
  return (
    <div className="bg-white rounded-2xl border border-slate-200 p-6 text-xs space-y-3 print:border-0" id="fulfilment-record">
      <div className="flex items-center justify-between"><div><h3 className="text-base font-bold text-slate-900">Fulfilment Record - {c.request_id}</h3><p className="text-slate-500">{c.policy} &middot; policy v{c.policy_version}</p></div>
        <div className="flex gap-2 print:hidden"><span className="inline-flex items-center text-emerald-700 font-semibold"><Lock className="w-3.5 h-3.5 mr-1" />Immutable</span>
          <button onClick={() => window.print()} className="border border-slate-300 rounded-lg px-2.5 py-1.5 inline-flex items-center"><Printer className="w-3.5 h-3.5 mr-1" />Print / PDF</button>
          <button onClick={() => { const b = new Blob([JSON.stringify(rec, null, 2)], { type: 'application/json' }); const a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = `${c.request_id}-record.json`; a.click(); }} className="border border-slate-300 rounded-lg px-2.5 py-1.5 inline-flex items-center"><Download className="w-3.5 h-3.5 mr-1" />JSON</button></div></div>
      <Sec n={1} t="Request"><p>Type {c.request.type}, received {c.request.received_at.slice(0, 10)}, due {c.request.due_at.slice(0, 10)}{c.request.extended ? ' (extended)' : ''}, closed {c.request.closed_at.slice(0, 10)} - <strong className={c.sla_outcome === 'ON_TIME' ? 'text-emerald-700' : 'text-red-700'}>{c.sla_outcome === 'ON_TIME' ? 'on time' : 'LATE'}</strong></p></Sec>
      <Sec n={2} t="Verification"><p>Level {c.verification.level} {c.verification.result.toLowerCase()} by {c.verification.performed_by} {c.verification.at && `on ${c.verification.at.slice(0, 10)}`}{c.verification.failed_attempts_before_pass > 0 && ` (${c.verification.failed_attempts_before_pass} failed attempt(s) before)`}</p></Sec>
      <Sec n={3} t="Agent summary"><p className="italic">{rec.narrative}</p><p className="text-slate-500">{c.narrative_label}</p>{c.plan && <p>Plan v{c.plan.version} from {c.plan.source}; {c.plan.discarded_proposals} agent proposal(s) discarded by validation.</p>}</Sec>
      <Sec n={4} t="Inventory"><p>{c.inventory.total_found} records found: {c.inventory.included} included, {c.inventory.excluded_retention} excluded by retention, {c.inventory.excluded_unrelated} unrelated (inventory v{c.inventory.inventory_version}).</p>
        {c.inventory.exclusions.map((e: any, i: number) => <p key={i} className="font-mono">{e.source}/{e.record_id}: {e.decision} <RuleChips ids={e.rule_ids} /></p>)}</Sec>
      <Sec n={5} t="Approvals">{c.approvals.map((a: any, i: number) => <p key={i}><strong>{a.scope}</strong> {a.decision} by {a.approver} on {a.at?.slice(0, 16).replace('T', ' ')}{a.differs_from_initiator === true && ' (differs from initiator)'}{a.action_set_hash && <span className="font-mono text-slate-400"> hash {a.action_set_hash.slice(0, 10)}</span>}</p>)}</Sec>
      <Sec n={6} t="Actions"><p>{c.actions.executed}/{c.actions.proposed} executed; {c.actions.retried} retried; {c.actions.duplicates_executed} duplicate(s) executed; {c.actions.duplicates_suppressed} duplicate(s) suppressed.</p></Sec>
      <Sec n={7} t="Export / notice">{c.export ? <p>Export {c.export.export_id} released by {c.export.released_by}: {c.export.records} records, {c.export.total_redactions} redactions ({Object.entries(c.export.redactions_by_rule).map(([k, v]) => `${k}: ${v}`).join(', ')}), leak scan {c.export.leak_scan_passed ? 'passed' : 'failed'}.</p> : <p>n/a</p>}</Sec>
      <Sec n={8} t="Tool calls and LLM runs"><p>Tool calls: {c.tool_calls.total} ({c.tool_calls.denied} denied, {c.tool_calls.errors} errors). LLM runs: {c.llm_runs.total} ({c.llm_runs.invalid} invalid, {c.llm_runs.fallbacks} fallback(s)).</p></Sec>
      <Sec n={9} t="Failures">{c.failures.length === 0 ? <p>None</p> : c.failures.map((f: any, i: number) => <p key={i}>Action {f.action_id} ({f.record_id}) attempt {f.attempt}: {f.error}</p>)}</Sec>
      <Sec n={10} t="Disclaimer"><p className="font-semibold">{c.disclaimer}</p></Sec>
      <Sec n={11} t="Addenda (separate audit events; the record above never changes)">
        {(rec.addenda || []).length === 0 ? <p className="text-slate-400">None</p> : rec.addenda.map((a: any) => <p key={a.seq}>#{a.seq} {new Date(a.at).toLocaleString()} by {a.by}: {a.text}</p>)}
        {(user?.role === 'analyst' || user?.role === 'approver') && (
          <div className="flex gap-2 pt-1 print:hidden"><input aria-label="Addendum text" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add a later note..." className="flex-1 border border-slate-300 rounded-lg p-2" />
            <button disabled={note.trim().length < 5} onClick={addAddendum} className="px-3 py-2 border border-slate-300 rounded-lg font-semibold disabled:opacity-40">Add addendum</button></div>)}
      </Sec>
    </div>
  );
};
