import React, { useCallback, useEffect, useState } from 'react';
import { Download, ShieldCheck, ShieldX } from 'lucide-react';
import { apiRequest, downloadFile } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { useUi, Banner, Skeleton, Empty, RuleChips } from '../components/Ui';
import type { TabProps } from '../pages/RequestDetail';

export const ExportTab: React.FC<TabProps> = ({ req, reload }) => {
  const { user } = useAuth();
  const { toast, confirm } = useUi();
  const [list, setList] = useState<any[] | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [exp, setExp] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<'diff' | 'json' | 'html'>('diff');

  const loadList = useCallback(async () => {
    try { const l = await apiRequest(`/requests/${req.id}/export`); setList(l); if (l.length && !sel) setSel(l[0].export_id); }
    catch (e: any) { toast.error(e.message); setList([]); }
  }, [req.id]);
  useEffect(() => { loadList(); }, [loadList, req.status]);
  useEffect(() => { if (sel) apiRequest(`/requests/${req.id}/export/${sel}`).then(setExp).catch((e) => toast.error(e.message)); else setExp(null); }, [sel, req.status]);

  if (req.type !== 'ACCESS') return <Empty title="Exports are only produced for access requests" />;
  if (!list) return <Skeleton rows={3} />;

  const generate = async () => {
    setBusy(true);
    try { const r = await apiRequest(`/requests/${req.id}/export`, { method: 'POST' }); setSel(r.export_id); toast.success(`Export generated: ${r.redaction_report.total_redactions} redactions, leak scan ${r.leak_scan.passed ? 'passed' : 'FAILED'}`); await loadList(); await reload(); }
    catch (e: any) { toast.error(e.message, e.ruleIds?.length ? `Rule: ${e.ruleIds.join(', ')}` : undefined); } finally { setBusy(false); }
  };
  const release = async () => {
    const reason = await confirm({ title: 'Release this export to the data subject?', description: 'FR-604: nothing can be downloaded before this approval.',
      lines: [`${exp.content.length} record(s)`, `${exp.redaction_report.total_redactions} redaction(s) applied`, `Leak scan: ${exp.leak_scan.passed ? 'passed' : 'FAILED'}`, 'Request moves to COMPLETED_PENDING_RECORD'],
      reasonLabel: 'Release justification (what did you check?)', confirmLabel: 'Release export' });
    if (!reason) return;
    try { await apiRequest(`/requests/${req.id}/export/${exp.export_id}/release`, { method: 'POST', body: JSON.stringify({ reason }) }); toast.success('Export released'); await reload(); await loadList(); setSel(exp.export_id); }
    catch (e: any) { toast.error(`Release blocked: ${e.message}`, e.ruleIds?.join(', ')); }
  };
  const dl = (fmt: string) => downloadFile(`/requests/${req.id}/export/${exp.export_id}/download?format=${fmt}`, `${req.id}-export.${fmt}`).catch((e) => toast.error(e.message));

  const canGen = user?.role === 'analyst' && req.status === 'EXPORT_REVIEW';
  const canRelease = user?.role === 'approver' && req.status === 'EXPORT_REVIEW' && exp && !exp.is_released && !exp.stale && exp.leak_scan?.passed;

  return (
    <div className="space-y-4">
      {['NEW', 'AWAITING_INFO', 'VERIFIED', 'PLANNING', 'PLAN_REVIEW', 'VERIFICATION_PENDING'].includes(req.status) && <Banner kind="info" title="Blocked: the plan must be approved before an export can be generated (POL-APR-1)" />}
      <div className="bg-white rounded-2xl border border-slate-200 p-4 flex flex-wrap items-center gap-3">
        <div className="flex-1"><h3 className="text-sm font-bold text-slate-900">Redacted subject export</h3><p className="text-xs text-slate-500">Built only from the approved inventory. Other people's data, internal identifiers and security fields are removed (POL-RED-1/2/3). Redaction is rule-based and not guaranteed to catch every mention: a human reviews every export.</p></div>
        {list.length > 1 && <select aria-label="Choose export" value={sel || ''} onChange={(e) => setSel(e.target.value)} className="text-xs border border-slate-300 rounded-lg p-1.5">{list.map((l) => <option key={l.export_id} value={l.export_id}>{l.export_id}{l.released ? ' (released)' : ''}{l.stale ? ' (stale)' : ''}</option>)}</select>}
        {canGen && <button disabled={busy} onClick={generate} className="px-3 py-2 text-xs font-semibold bg-sky-600 text-white rounded-lg disabled:opacity-50">{busy ? 'Generating...' : list.length ? 'Regenerate export' : 'Generate export'}</button>}
      </div>

      {!exp ? <Empty title="No export generated yet" next={canGen ? 'Generate the export to review the redaction diff.' : 'An Analyst generates it once the plan is approved.'} /> : (
        <>
          {exp.stale && <Banner kind="warn" title="Stale export">The inventory changed after this export was generated. Generate a new one; this one cannot be released.</Banner>}
          <div className={`rounded-2xl border p-4 text-xs flex items-start space-x-3 ${exp.leak_scan.passed ? 'bg-emerald-50 border-emerald-200' : 'bg-red-50 border-red-300'}`} role={exp.leak_scan.passed ? 'status' : 'alert'}>
            {exp.leak_scan.passed ? <ShieldCheck className="w-5 h-5 text-emerald-700" /> : <ShieldX className="w-5 h-5 text-red-700" />}
            <div><p className="font-bold">{exp.leak_scan.passed ? 'Post-redaction leak scan passed' : 'Leak scan FAILED: release is blocked (FR-605)'}</p>
              {!exp.leak_scan.passed && <ul className="list-disc ml-4">{exp.leak_scan.leaks_found.map((l: string, i: number) => <li key={i}>{l}</li>)}</ul>}
              <p className="text-slate-600 mt-1">{exp.redaction_report.total_redactions} redaction(s) &middot; {exp.content.length} record(s) &middot; inventory v{exp.inventory_version}</p></div>
            <span className="flex-1" />
            {canRelease && <button onClick={release} className="px-3 py-2 bg-emerald-600 text-white font-semibold rounded-lg">Release export</button>}
            {user?.role === 'approver' && req.status === 'EXPORT_REVIEW' && !canRelease && !exp.is_released && <span className="text-slate-500 self-center">Release unavailable (stale or leak scan failed)</span>}
          </div>

          {exp.is_released && (
            <div className="bg-white rounded-2xl border border-emerald-300 p-4 text-xs flex items-center gap-3"><span className="font-bold text-emerald-800 flex-1">Released by {exp.released_by} on {new Date(exp.released_at).toLocaleString()}</span>
              {(user?.role === 'analyst' || user?.role === 'approver') && <><button onClick={() => dl('json')} className="border border-slate-300 rounded-lg px-2.5 py-1.5 inline-flex items-center"><Download className="w-3.5 h-3.5 mr-1" />JSON</button><button onClick={() => dl('html')} className="border border-slate-300 rounded-lg px-2.5 py-1.5 inline-flex items-center"><Download className="w-3.5 h-3.5 mr-1" />HTML</button></>}</div>)}

          <div className="flex gap-1 text-xs">{(['diff', 'json', 'html'] as const).map((v) => <button key={v} onClick={() => setView(v)} className={`px-3 py-1.5 rounded-lg border ${view === v ? 'bg-sky-50 border-sky-300 text-sky-800 font-semibold' : 'border-slate-200'}`}>{v === 'diff' ? 'Redaction diff' : v === 'json' ? 'Exported JSON' : 'Subject-facing view'}</button>)}</div>

          {view === 'diff' && (
            <div className="bg-white rounded-2xl border border-slate-200 overflow-x-auto">
              {exp.redaction_report.diff.length === 0 ? <div className="p-6"><Empty title="No redactions were needed" /></div> : (
                <table className="w-full text-xs"><thead className="bg-slate-50 text-left text-slate-500"><tr><th className="p-3">Record / field</th><th>Original (internal view)</th><th>Exported</th><th>Rule</th></tr></thead>
                  <tbody>{exp.redaction_report.diff.map((d: any, i: number) => (
                    <tr key={i} className="border-t border-slate-100 align-top"><td className="p-3 font-mono">{d.record_id}<span className="block text-slate-500">{d.field}</span></td>
                      <td className="max-w-sm"><span className="bg-red-50 text-red-900 px-1 rounded break-words">{String(d.original)}</span></td>
                      <td className="max-w-sm"><span className="bg-emerald-50 text-emerald-900 px-1 rounded break-words">{String(d.exported)}</span></td>
                      <td><RuleChips ids={d.rules} /></td></tr>))}</tbody></table>)}
            </div>)}
          {view === 'json' && <pre className="bg-slate-900 text-slate-100 rounded-2xl p-4 text-[11px] overflow-auto max-h-[28rem]">{JSON.stringify(exp.content, null, 2)}</pre>}
          {view === 'html' && <iframe title="Subject-facing export" sandbox="" srcDoc={exp.html_preview} className="w-full h-[28rem] bg-white rounded-2xl border border-slate-200" />}
        </>)}
    </div>
  );
};
