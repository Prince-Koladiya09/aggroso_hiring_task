import React from 'react';
import { apiRequest } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { useUi, Banner, Empty } from '../components/Ui';
import type { TabProps } from '../pages/RequestDetail';

export const OverviewTab: React.FC<TabProps> = ({ req, reload }) => {
  const { user } = useAuth();
  const { toast, confirm } = useUi();
  const finished = ['CLOSED', 'REJECTED', 'CANCELLED', 'COMPLETED_PENDING_RECORD'].includes(req.status);

  const wrap = async (fn: () => Promise<any>, ok: string) => {
    try { await fn(); toast.success(ok); await reload(); } catch (e: any) { toast.error(e.message, e.correlationId ? `Reference: ${e.correlationId}` : undefined); }
  };

  const requestExt = async () => {
    const reason = await confirm({ title: 'Request a deadline extension', description: 'POL-SLA-2: one extension of up to 30 days is allowed with Approver justification.',
      lines: [`Current due date: ${new Date(req.due_at).toLocaleDateString()}`, 'An Approver must approve before the due date moves'], reasonLabel: 'Why is an extension needed?', confirmLabel: 'Request extension' });
    if (reason) wrap(() => apiRequest(`/requests/${req.id}/extension`, { method: 'POST', body: JSON.stringify({ reason }) }), 'Extension requested');
  };
  const decideExt = async (decision: 'APPROVED' | 'REJECTED') => {
    const reason = await confirm({ title: `${decision === 'APPROVED' ? 'Approve' : 'Reject'} extension`, lines: [`Requested because: ${req.extension_request_reason}`,
      decision === 'APPROVED' ? 'Due date moves by 30 calendar days; no further extension is possible' : 'Due date is unchanged'], reasonLabel: 'Justification', confirmLabel: decision === 'APPROVED' ? 'Approve' : 'Reject', danger: decision === 'REJECTED' });
    if (reason) wrap(() => apiRequest(`/requests/${req.id}/extension`, { method: 'POST', body: JSON.stringify({ decision, reason }) }), `Extension ${decision.toLowerCase()}`);
  };
  const cancel = async () => {
    const reason = await confirm({ title: 'Cancel this request?', lines: ['Request moves to CANCELLED (final)', 'No data is changed'], reasonLabel: 'Reason', confirmLabel: 'Cancel request', danger: true });
    if (reason) wrap(() => apiRequest(`/requests/${req.id}/cancel`, { method: 'POST', body: JSON.stringify({ reason }) }), 'Request cancelled');
  };

  return (
    <div className="grid lg:grid-cols-3 gap-6">
      <div className="lg:col-span-2 space-y-4">
        <div className="bg-white rounded-2xl border border-slate-200 p-5">
          <h3 className="text-sm font-bold text-slate-900 mb-3">Request details</h3>
          <dl className="grid grid-cols-2 gap-3 text-xs">
            <div><dt className="text-slate-500">Requester</dt><dd className="font-medium">{req.requester_name}</dd></div>
            <div><dt className="text-slate-500">Email</dt><dd className="font-medium">{req.requester_email}</dd></div>
            <div><dt className="text-slate-500">Account ID</dt><dd className="font-medium">{req.account_id || <em className="text-amber-700">missing</em>}</dd></div>
            <div><dt className="text-slate-500">Relationship</dt><dd className="font-medium">{req.relationship}{req.relationship === 'authorized_agent' && (req.authorization_on_file ? ' (authorization on file)' : ' (no authorization on file)')}</dd></div>
            <div><dt className="text-slate-500">Received</dt><dd className="font-medium">{new Date(req.received_at).toLocaleDateString()}</dd></div>
            <div><dt className="text-slate-500">Due (POL-SLA-1)</dt><dd className="font-medium">{new Date(req.due_at).toLocaleDateString()}{req.extended ? ` - extended: ${req.extension_reason}` : ''}</dd></div>
            <div className="col-span-2"><dt className="text-slate-500">Description</dt><dd className="font-medium whitespace-pre-wrap">{req.description}</dd></div>
          </dl>
        </div>

        {req.missing_verification?.length > 0 && !finished && (
          <Banner kind="warn" title="Information still needed before processing">
            {req.missing_verification.map((m: any) => <p key={m.item}><strong>{m.item}</strong> <span className="font-mono text-indigo-700">{m.policy_rule}</span> - {m.reason}</p>)}
          </Banner>
        )}

        <div className="bg-white rounded-2xl border border-slate-200 p-5">
          <h3 className="text-sm font-bold text-slate-900 mb-3">Status history</h3>
          {req.timeline.length === 0 ? <Empty title="No history yet" /> : (
            <ol className="relative border-l border-slate-200 ml-2 space-y-3">
              {req.timeline.map((e: any) => (
                <li key={e.seq} className="ml-4 text-xs">
                  <span className="absolute -left-1.5 mt-1 w-3 h-3 rounded-full bg-sky-500 border-2 border-white" />
                  <span className="font-semibold text-slate-800">{e.event_type === 'REQUEST_STATUS_CHANGED' ? `${e.payload.old_status} → ${e.payload.new_status}` : e.event_type.replace(/_/g, ' ')}</span>
                  <span className="text-slate-400"> &middot; {e.actor_role} {e.actor_id} &middot; {new Date(e.timestamp).toLocaleString()}</span>
                  {(e.payload?.reason || e.payload?.message) && <p className="text-slate-500">{e.payload.reason || e.payload.message}</p>}
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>

      <div className="space-y-4">
        <div className="bg-white rounded-2xl border border-slate-200 p-5 text-xs space-y-3">
          <h3 className="text-sm font-bold text-slate-900">Deadline</h3>
          <p>Days remaining: <strong>{req.deadline.days_remaining}</strong> ({req.deadline.deadline_status.replace('_', ' ')})</p>
          {req.extension_pending && (
            <Banner kind="warn" title="Extension requested">
              <p>{req.extension_request_reason}</p>
              {user?.role === 'approver' && <div className="flex gap-2 pt-1"><button onClick={() => decideExt('APPROVED')} className="px-2 py-1 bg-emerald-600 text-white rounded font-semibold">Approve</button><button onClick={() => decideExt('REJECTED')} className="px-2 py-1 bg-white border border-slate-300 rounded font-semibold">Reject</button></div>}
            </Banner>
          )}
          {!req.extended && !req.extension_pending && !finished && (user?.role === 'analyst' || user?.role === 'approver') &&
            <button onClick={requestExt} className="w-full border border-slate-300 rounded-lg py-1.5 font-semibold hover:bg-slate-50">Request extension</button>}
          {req.extended && <p className="text-indigo-700 font-semibold">One extension already used (POL-SLA-2).</p>}
        </div>
        {user?.role === 'analyst' && ['NEW', 'AWAITING_INFO', 'VERIFICATION_FAILED'].includes(req.status) &&
          <button onClick={cancel} className="w-full text-xs border border-red-300 text-red-700 rounded-lg py-2 font-semibold hover:bg-red-50">Cancel request</button>}
        <p className="text-[11px] text-slate-400 font-mono break-all">correlation: {req.correlation_id}</p>
      </div>
    </div>
  );
};
