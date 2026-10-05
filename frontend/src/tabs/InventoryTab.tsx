import React, { useCallback, useEffect, useState } from 'react';
import { Download } from 'lucide-react';
import { apiRequest, downloadFile } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { useUi, Banner, Skeleton, Empty, RuleChips } from '../components/Ui';
import type { TabProps } from '../pages/RequestDetail';

const COLOR: Record<string, string> = { INCLUDE: 'bg-emerald-50 text-emerald-800 border-emerald-200', REDACT: 'bg-sky-50 text-sky-800 border-sky-200',
  EXCLUDE_RETENTION: 'bg-red-50 text-red-800 border-red-200', EXCLUDE_UNRELATED: 'bg-slate-100 text-slate-600 border-slate-200', NEEDS_REVIEW: 'bg-amber-50 text-amber-800 border-amber-300' };

export const InventoryTab: React.FC<TabProps> = ({ req, reload }) => {
  const { user } = useAuth();
  const { toast } = useUi();
  const [items, setItems] = useState<any[] | null>(null);
  const [fDec, setFDec] = useState(''); const [fSrc, setFSrc] = useState(''); const [fRel, setFRel] = useState('');
  const [edit, setEdit] = useState<any>(null);
  const [decision, setDecision] = useState('EXCLUDE_UNRELATED');
  const [reason, setReason] = useState('');
  const [err, setErr] = useState('');
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setItems(await apiRequest(`/requests/${req.id}/inventory`)); } catch (e: any) { toast.error(e.message); setItems([]); }
  }, [req.id]);
  useEffect(() => { load(); }, [load, req.status, req.inventory_version]);

  const canEdit = (user?.role === 'analyst' || user?.role === 'approver') && ['PLAN_REVIEW', 'PLAN_APPROVED', 'AWAITING_ACTION_APPROVAL', 'EXPORT_REVIEW'].includes(req.status);

  const save = async () => {
    setErr('');
    if (reason.trim().length < 5) { setErr('A justification of at least 5 characters is required.'); return; }
    try {
      const r = await apiRequest(`/requests/${req.id}/inventory/${edit.id}`, { method: 'PATCH', body: JSON.stringify({ decision, reason }) });
      toast.success(`Decision changed. Inventory is now v${r.inventory_version}; earlier approvals are void.`);
      setEdit(null); setReason(''); await load(); await reload();
    } catch (e: any) { setErr(`${e.message}${e.ruleIds?.length ? ` (${e.ruleIds.join(', ')})` : ''}`); }
  };

  if (!items) return <Skeleton rows={5} />;
  const shown = items.filter((i) => (!fDec || i.decision === fDec) && (!fSrc || i.source === fSrc) && (!fRel || i.relevance === fRel));
  const counts = items.reduce((m: any, i) => ({ ...m, [i.decision]: (m[i.decision] || 0) + 1 }), {});
  const sel = 'text-xs border border-slate-300 rounded-lg p-1.5 bg-white';

  if (items.length === 0) return <Empty title="No inventory yet" next="Run the agent (Agent Plan tab) to find and classify the subject's records." />;

  return (
    <div className="space-y-4">
      {counts.NEEDS_REVIEW > 0 && <Banner kind="warn" title={`${counts.NEEDS_REVIEW} item(s) need a human decision before the plan can be approved`} />}
      <div className="bg-white rounded-2xl border border-slate-200 p-4 flex flex-wrap items-center gap-3">
        <span className="text-xs font-bold text-slate-700">Inventory v{req.inventory_version} &middot; {items.length} records</span>
        <select aria-label="Filter by decision" className={sel} value={fDec} onChange={(e) => setFDec(e.target.value)}><option value="">All decisions</option>{Object.keys(COLOR).map((d) => <option key={d}>{d}</option>)}</select>
        <select aria-label="Filter by source" className={sel} value={fSrc} onChange={(e) => setFSrc(e.target.value)}><option value="">All sources</option><option>profiles</option><option>tickets</option><option>activity_logs</option></select>
        <select aria-label="Filter by relevance" className={sel} value={fRel} onChange={(e) => setFRel(e.target.value)}><option value="">All relevance</option><option>RELEVANT</option><option>UNRELATED</option><option>UNCERTAIN</option></select>
        <span className="flex-1" />
        <button onClick={() => downloadFile(`/requests/${req.id}/inventory/export?format=csv`, `${req.id}-inventory.csv`).catch((e) => toast.error(e.message))} className="text-xs border border-slate-300 rounded-lg px-2.5 py-1.5 inline-flex items-center hover:bg-slate-50"><Download className="w-3.5 h-3.5 mr-1" />CSV</button>
        <button onClick={() => downloadFile(`/requests/${req.id}/inventory/export?format=json`, `${req.id}-inventory.json`).catch((e) => toast.error(e.message))} className="text-xs border border-slate-300 rounded-lg px-2.5 py-1.5 inline-flex items-center hover:bg-slate-50"><Download className="w-3.5 h-3.5 mr-1" />JSON</button>
      </div>
      <p className="text-[11px] text-slate-500">Internal review view. Security-restricted values are withheld. Overrides can never weaken a retention or legal-hold exclusion; every override creates a new inventory version and voids earlier approvals.</p>

      <div className="bg-white rounded-2xl border border-slate-200 overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-left text-slate-500"><tr><th className="p-3">Source / record</th><th>Summary</th><th>Relevance</th><th>Decision</th><th>Reason &amp; rules</th><th /></tr></thead>
          <tbody>
            {shown.length === 0 && <tr><td colSpan={6} className="p-6 text-center text-slate-400">No records match these filters.</td></tr>}
            {shown.map((i) => (
              <React.Fragment key={i.id}>
                <tr className="border-t border-slate-100 align-top">
                  <td className="p-3"><span className="font-mono font-bold">{i.record_id}</span><span className="block text-slate-500">{i.source}{i.classification === 'THIRD_PARTY_CONTENT' && <span className="ml-1 text-[10px] font-bold text-purple-700">THIRD-PARTY</span>}</span></td>
                  <td className="text-slate-600 max-w-[14rem] truncate">{Object.values(i.summary || {}).filter(Boolean).join(' · ')}<button onClick={() => setOpen(open === i.id ? null : i.id)} className="block text-sky-700 underline">{open === i.id ? 'hide fields' : 'fields'}</button></td>
                  <td>{i.relevance}</td>
                  <td><span className={`px-2 py-0.5 rounded-full border font-bold text-[10px] ${COLOR[i.decision]}`}>{i.decision}</span></td>
                  <td className="max-w-xs">{i.reason}<div className="mt-1"><RuleChips ids={i.rule_ids} /></div>{i.override_by && <p className="text-[10px] text-indigo-700 mt-1">Overridden by {i.override_by}: {i.override_reason}</p>}</td>
                  <td className="p-3">{canEdit && <button disabled={i.decision === 'EXCLUDE_RETENTION'} title={i.decision === 'EXCLUDE_RETENTION' ? 'Deterministic exclusion cannot be overridden' : ''} onClick={() => { setEdit(i); setDecision(i.decision === 'INCLUDE' ? 'EXCLUDE_UNRELATED' : 'INCLUDE'); setErr(''); setReason(''); }} className="text-sky-700 font-semibold disabled:opacity-30">Override</button>}</td>
                </tr>
                {open === i.id && <tr className="bg-slate-50"><td colSpan={6} className="p-3"><pre className="text-[11px] whitespace-pre-wrap break-all">{JSON.stringify(i.raw_data, null, 2)}</pre></td></tr>}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>

      {edit && (
        <div className="fixed inset-0 z-[80] bg-slate-900/50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label="Override inventory decision">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6 space-y-3 text-xs">
            <h3 className="text-base font-bold">Override decision for {edit.record_id}</h3>
            <p className="text-slate-600">Current: <strong>{edit.decision}</strong>. This creates inventory v{req.inventory_version + 1} and voids any approval already given.</p>
            <label className="block"><span className="font-semibold">New decision</span>
              <select value={decision} onChange={(e) => setDecision(e.target.value)} className="mt-1 w-full border border-slate-300 rounded-lg p-2">
                {['INCLUDE', 'REDACT', 'EXCLUDE_UNRELATED', 'NEEDS_REVIEW'].map((d) => <option key={d}>{d}</option>)}</select></label>
            <label className="block"><span className="font-semibold">Justification *</span>
              <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} className="mt-1 w-full border border-slate-300 rounded-lg p-2" /></label>
            {err && <p className="text-red-600" role="alert">{err}</p>}
            <div className="flex justify-end gap-2"><button onClick={() => setEdit(null)} className="px-3 py-2 border border-slate-300 rounded-lg">Cancel</button><button onClick={save} className="px-3 py-2 bg-sky-600 text-white rounded-lg font-semibold">Save override</button></div>
          </div>
        </div>
      )}
    </div>
  );
};
