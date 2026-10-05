import React, { useCallback, useEffect, useState } from 'react';
import { Lock, RotateCcw, Play, ShieldAlert } from 'lucide-react';
import { apiRequest } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { useUi, Banner, Skeleton, Empty, RuleChips } from '../components/Ui';
import type { TabProps } from '../pages/RequestDetail';

const AST: Record<string, string> = { SUCCEEDED: 'bg-emerald-50 text-emerald-800 border-emerald-200', SUCCEEDED_RECONCILED: 'bg-teal-50 text-teal-800 border-teal-200',
  FAILED: 'bg-red-50 text-red-800 border-red-200', IN_PROGRESS: 'bg-blue-50 text-blue-800 border-blue-200', NOT_STARTED: 'bg-slate-100 text-slate-600 border-slate-200', PENDING: 'bg-slate-100 text-slate-600 border-slate-200' };

export const ActionsTab: React.FC<TabProps> = ({ req, reload }) => {
  const { user } = useAuth();
  const { toast, confirm } = useUi();
  const [actions, setActions] = useState<any[] | null>(null);
  const [approvals, setApprovals] = useState<any[]>([]);
  const [flags, setFlags] = useState<any>({});
  const [busy, setBusy] = useState('');
  const [fault, setFault] = useState('');

  const load = useCallback(async () => {
    try {
      const [a, p, f] = await Promise.all([apiRequest(`/requests/${req.id}/actions`), apiRequest(`/requests/${req.id}/approvals`), apiRequest('/system/flags')]);
      setActions(a); setApprovals(p); setFlags(f);
    } catch (e: any) { toast.error(e.message); setActions([]); }
  }, [req.id]);
  useEffect(() => { load(); }, [load, req.status]);

  const scope = req.type === 'CORRECTION' ? 'CORRECTION' : req.type === 'DELETION' ? 'DELETION' : null;
  const live = (actions || []).filter((a) => !['BLOCKED', 'SUPERSEDED', 'REJECTED'].includes(a.proposed_status));
  const blocked = (actions || []).filter((a) => a.proposed_status === 'BLOCKED');
  const iInitiated = user && [req.created_by, req.plan_initiated_by].includes(user.id);

  const act = async (key: string, fn: () => Promise<any>) => {
    setBusy(key);
    try { return await fn(); } catch (e: any) { toast.error(e.message, [e.ruleIds?.length ? `Rule: ${e.ruleIds.join(', ')}` : '', e.correlationId ? `Ref: ${e.correlationId}` : ''].filter(Boolean).join(' | ') || undefined); }
    finally { setBusy(''); await load(); await reload(); }
  };

  const approve = async (decision: 'APPROVED' | 'REJECTED') => {
    const lines = live.map((a) => scope === 'CORRECTION' ? `${a.source}.${a.record_id}.${a.field}: "${a.before_value}" → "${a.after_value}"` : `${a.strategy} ${a.source}/${a.record_id}`);
    const reason = await confirm({ title: `${decision === 'APPROVED' ? 'Approve' : 'Reject'} ${scope} of ${live.length} item(s)?`,
      description: `This is a separate approval bound to the exact action set (POL-APR-2). ${scope === 'DELETION' ? 'Four-eyes: you must not be the initiator (POL-APR-3).' : ''}`,
      lines, reasonLabel: 'Justification', confirmLabel: decision === 'APPROVED' ? `Approve ${scope?.toLowerCase()}` : 'Reject', danger: scope === 'DELETION' && decision === 'APPROVED' });
    if (!reason) return;
    const r = await act('approve', () => apiRequest(`/requests/${req.id}/approvals`, { method: 'POST', body: JSON.stringify({ scope, decision, reason }) }));
    if (r) toast.success(`${scope} ${decision.toLowerCase()}`);
  };

  const execute = async () => {
    const todo = live.filter((a) => !['SUCCEEDED', 'SUCCEEDED_RECONCILED'].includes(a.action_status));
    const ok = await confirm({ title: `Execute ${todo.length} approved ${scope?.toLowerCase()} action(s)?`, description: 'Each action runs at most once (idempotency key). Failed actions are retried only on request.',
      lines: todo.map((a) => scope === 'CORRECTION' ? `UPDATE ${a.source}/${a.record_id} set ${a.field} = "${a.after_value}"` : `${a.strategy === 'ANONYMIZE' ? 'ANONYMIZE' : 'DELETE'} ${a.source}/${a.record_id}`),
      confirmLabel: 'Execute now', danger: scope === 'DELETION' });
    if (ok === null) return;
    const r = await act('exec', () => apiRequest(`/requests/${req.id}/actions/execute`, { method: 'POST', body: JSON.stringify({ scope, inject_fault: fault || null }) }));
    if (r) r.all_succeeded ? toast.success('All actions succeeded') : toast.error('Some actions failed', 'Nothing was repeated. Use Retry on each failed action.');
  };

  const retry = async (id: string) => {
    const r = await act('retry' + id, () => apiRequest(`/actions/${id}/retry`, { method: 'POST' }));
    if (r) r.duplicate_suppressed ? toast.info('Already succeeded: duplicate suppressed, no write performed.') : r.reconciled ? toast.success('Reconciled: target was already in the final state; no second write.') : r.status === 'SUCCEEDED' ? toast.success(`Succeeded on attempt ${r.attempt}`) : toast.error(r.error || 'Retry failed', r.code);
  };

  if (!actions) return <Skeleton rows={4} />;
  if (!scope) return <Empty title="Access requests have no corrections or deletions" next="Use the Export tab to generate and release the redacted export." />;

  const canApprove = user?.role === 'approver' && req.status === 'AWAITING_ACTION_APPROVAL';
  const canExec = user?.role === 'analyst' && ['EXECUTING', 'PARTIALLY_FAILED'].includes(req.status);
  const failed = live.filter((a) => a.action_status === 'FAILED');

  return (
    <div className="space-y-4">
      {['NEW', 'AWAITING_INFO', 'VERIFIED', 'VERIFICATION_PENDING', 'PLANNING', 'PLAN_REVIEW'].includes(req.status) && (
        <Banner kind="info" title="Blocked: no modification is possible yet"><p>The plan must be approved (POL-APR-1), then a separate {scope?.toLowerCase()} approval is required (POL-APR-2).</p></Banner>)}
      {req.status === 'AWAITING_ACTION_APPROVAL' && <Banner kind="warn" title={`Awaiting separate ${scope} approval`}>The approved plan does not authorise any change. {scope === 'DELETION' && 'The approver must differ from the initiating analyst (POL-APR-3).'}</Banner>}
      {req.status === 'PARTIALLY_FAILED' && <Banner kind="error" title={`${failed.length} action(s) failed`}>Nothing was repeated automatically. Retry reconciles with the current data first, so a write that actually landed is never done twice.</Banner>}
      {iInitiated && scope === 'DELETION' && req.status === 'AWAITING_ACTION_APPROVAL' && user?.role === 'approver' && <Banner kind="error" title="You initiated this request: you cannot approve its deletion (POL-APR-3)">Switch to a different Approver.</Banner>}

      <div className="bg-white rounded-2xl border border-slate-200 overflow-x-auto">
        <div className="p-4 flex flex-wrap items-center gap-2 border-b border-slate-100">
          <h3 className="text-sm font-bold text-slate-900 flex-1">Proposed {scope?.toLowerCase()} actions ({live.length})</h3>
          {canApprove && <><button disabled={!!busy || live.length === 0 || (scope === 'DELETION' && !!iInitiated)} onClick={() => approve('APPROVED')} className="px-3 py-2 text-xs font-semibold bg-emerald-600 text-white rounded-lg disabled:opacity-40">Approve {scope?.toLowerCase()}</button>
            <button disabled={!!busy} onClick={() => approve('REJECTED')} className="px-3 py-2 text-xs font-semibold border border-slate-300 rounded-lg">Reject</button></>}
          {canExec && flags.fault_injection_enabled && (
            <select value={fault} onChange={(e) => setFault(e.target.value)} aria-label="Fault to inject" className="text-xs border border-amber-300 bg-amber-50 rounded-lg p-1.5"><option value="">No injected fault</option><option value="before_write">Fail before write</option><option value="after_write_before_commit">Crash after write</option></select>)}
          {canExec && <button disabled={!!busy} onClick={execute} className="px-3 py-2 text-xs font-semibold bg-sky-600 text-white rounded-lg inline-flex items-center disabled:opacity-40"><Play className="w-3.5 h-3.5 mr-1" />{busy === 'exec' ? 'Executing...' : 'Execute approved actions'}</button>}
        </div>
        {live.length === 0 ? <div className="p-6"><Empty title="No proposed actions" next="Everything in the inventory is excluded, or nothing was derived from the request. See the Inventory tab for rule IDs." /></div> : (
          <table className="w-full text-xs">
            <thead className="bg-slate-50 text-left text-slate-500"><tr><th className="p-3">Target</th><th>{scope === 'CORRECTION' ? 'Before → After' : 'Strategy'}</th><th>Risk &amp; rules</th><th>Status</th><th /></tr></thead>
            <tbody>{live.map((a) => (
              <React.Fragment key={a.proposed_action_id}>
                <tr className="border-t border-slate-100 align-top">
                  <td className="p-3"><span className="font-mono font-bold">{a.record_id}</span><span className="block text-slate-500">{a.source}{a.field && a.field !== '*' ? ` · ${a.field}` : ''}</span></td>
                  <td>{scope === 'CORRECTION' ? <div className="font-mono"><div className="bg-red-50 text-red-800 px-1 rounded line-through">{a.before_value}</div><div className="bg-emerald-50 text-emerald-800 px-1 rounded mt-0.5">{a.after_value}</div></div> : <span className={`font-bold ${a.strategy === 'ANONYMIZE' ? 'text-amber-700' : 'text-red-700'}`}>{a.strategy}</span>}</td>
                  <td className="max-w-xs">{a.risk_text}<div className="mt-1"><RuleChips ids={a.rule_ids} /></div></td>
                  <td><span className={`px-2 py-0.5 rounded-full border font-bold text-[10px] ${AST[a.action_status] || AST.NOT_STARTED}`}>{a.action_status}</span><span className="block text-slate-400 mt-1">approval: {a.proposed_status}</span>{a.attempts > 0 && <span className="block text-slate-500">attempts: {a.attempts}</span>}</td>
                  <td className="p-3">{canExec && a.action_status === 'FAILED' && <button disabled={!!busy} onClick={() => retry(a.action_id)} className="inline-flex items-center text-amber-800 border border-amber-300 bg-amber-50 rounded-lg px-2 py-1 font-semibold"><RotateCcw className="w-3 h-3 mr-1" />Retry</button>}</td>
                </tr>
                {(a.last_error || a.attempt_history?.length > 0 || a.pre_image) && (
                  <tr className="bg-slate-50"><td colSpan={5} className="px-3 py-2 text-[11px] space-y-1">
                    {a.last_error && a.action_status === 'FAILED' && <p className="text-red-700">Last error: {a.last_error}</p>}
                    {a.attempt_history?.length > 0 && <p>Attempts: {a.attempt_history.map((h: any) => `#${h.attempt_no} ${h.outcome}${h.error ? ` (${h.error.slice(0, 60)})` : ''}`).join(' → ')}</p>}
                    {a.idempotency_key && <p className="font-mono text-slate-400 truncate">key {a.idempotency_key}</p>}
                    {a.pre_image && <details><summary className="cursor-pointer text-slate-600 inline-flex items-center"><Lock className="w-3 h-3 mr-1" />Sealed pre-image (Approver/Auditor only, demo-only retention)</summary><pre className="mt-1 whitespace-pre-wrap break-all">{JSON.stringify(a.pre_image, null, 2)}</pre></details>}
                  </td></tr>)}
              </React.Fragment>))}</tbody>
          </table>)}
      </div>

      {blocked.length > 0 && (
        <div className="bg-white rounded-2xl border border-red-200 p-4 text-xs"><h4 className="font-bold text-red-800 flex items-center mb-2"><ShieldAlert className="w-4 h-4 mr-1" />Blocked ({blocked.length})</h4>
          {blocked.map((a) => <p key={a.proposed_action_id}><span className="font-mono">{a.source}/{a.record_id}</span> <RuleChips ids={a.rule_ids} /> excluded by reviewer or policy.</p>)}</div>)}

      <div className="bg-white rounded-2xl border border-slate-200 p-4">
        <h3 className="text-sm font-bold text-slate-900 mb-2">Approval history</h3>
        {approvals.length === 0 ? <p className="text-xs text-slate-400">No approvals yet.</p> : (
          <table className="w-full text-xs"><thead className="text-left text-slate-500"><tr><th className="py-1">Scope</th><th>Decision</th><th>Approver</th><th>Inv. v</th><th>Action-set hash</th><th>When</th><th>Reason</th></tr></thead>
            <tbody>{approvals.map((p) => <tr key={p.id} className="border-t border-slate-100"><td className="py-1 font-bold">{p.scope}</td><td className={p.decision === 'APPROVED' ? 'text-emerald-700 font-semibold' : 'text-red-700 font-semibold'}>{p.decision}</td><td className="font-mono">{p.approver_id}</td><td>{p.inventory_version}</td><td className="font-mono text-slate-400">{p.action_set_hash?.slice(0, 10)}</td><td>{new Date(p.created_at).toLocaleString()}</td><td>{p.reason}</td></tr>)}</tbody></table>)}
      </div>
    </div>
  );
};
