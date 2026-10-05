import React, { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import { apiRequest } from '../api/client';
import { DeadlineBadge, StatusBadge, TypeBadge } from '../components/Badge';
import { Skeleton, Banner } from '../components/Ui';
import { useAuth } from '../context/AuthContext';
import { OverviewTab } from '../tabs/OverviewTab';
import { VerificationTab } from '../tabs/VerificationTab';
import { PlanTab } from '../tabs/PlanTab';
import { InventoryTab } from '../tabs/InventoryTab';
import { ActionsTab } from '../tabs/ActionsTab';
import { ExportTab } from '../tabs/ExportTab';
import { ToolCallsTab } from '../tabs/ToolCallsTab';
import { AuditTab } from '../tabs/AuditTab';
import { RecordTab } from '../tabs/RecordTab';

const TABS = [
  ['overview', 'Overview & Timeline'], ['verification', 'Verification'], ['plan', 'Agent Plan'], ['inventory', 'Inventory'],
  ['actions', 'Actions & Approvals'], ['export', 'Export'], ['tools', 'Tool Calls'], ['audit', 'Audit Trail'], ['record', 'Fulfilment Record'],
] as const;
type TabId = typeof TABS[number][0];

export interface TabProps { req: any; reload: () => Promise<void>; }

export const RequestDetail: React.FC<{ requestId: string; onBack: () => void }> = ({ requestId, onBack }) => {
  const { user } = useAuth();
  const [req, setReq] = useState<any>(null);
  const [tab, setTab] = useState<TabId>('overview');
  const [error, setError] = useState('');

  const reload = useCallback(async () => {
    try {
      setReq(await apiRequest(`/requests/${requestId}`));
      setError('');
    } catch (e: any) {
      setError(e.message);
    }
  }, [requestId]);

  useEffect(() => { setReq(null); reload(); }, [reload, user?.id]);

  if (error && !req) {
    return (
      <div className="space-y-3">
        <button onClick={onBack} className="text-xs text-sky-700 underline">Back to dashboard</button>
        <Banner kind="error" title="Could not load this request">{error} <button className="underline ml-2" onClick={reload}>Retry</button></Banner>
      </div>
    );
  }
  if (!req) return <div className="bg-white rounded-2xl border border-slate-200 p-6"><Skeleton rows={4} /></div>;

  const props: TabProps = { req, reload };
  return (
    <div className="space-y-6">
      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-100 pb-4">
          <div className="flex items-center space-x-3">
            <button onClick={onBack} aria-label="Back to dashboard" className="p-1.5 rounded-lg border border-slate-200 hover:bg-slate-50 text-slate-600"><ArrowLeft className="w-4 h-4" /></button>
            <div>
              <div className="flex items-center space-x-2 flex-wrap gap-y-1">
                <span className="font-mono text-lg font-bold text-slate-900">{req.id}</span>
                <TypeBadge type={req.type} />
                <StatusBadge status={req.status} />
                <DeadlineBadge deadline={req.deadline} />
                {req.extended && <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200">EXTENDED</span>}
                {req.extension_pending && <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-50 text-amber-800 border border-amber-300">EXTENSION PENDING</span>}
              </div>
              <p className="text-xs text-slate-500 mt-1">{req.requester_name} &middot; {req.requester_email} &middot; due {new Date(req.due_at).toLocaleDateString()} &middot; inventory v{req.inventory_version}</p>
            </div>
          </div>
          <button onClick={reload} className="text-xs flex items-center space-x-1 text-slate-600 border border-slate-200 rounded-lg px-2.5 py-1.5 hover:bg-slate-50"><RefreshCw className="w-3.5 h-3.5" /><span>Refresh</span></button>
        </div>
        <p className="text-[11px] text-slate-500 mt-3 leading-snug">{req.disclaimer}</p>
      </div>

      <div className="flex flex-wrap gap-1 border-b border-slate-200" role="tablist">
        {TABS.map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
            className={`px-3 py-2 text-xs font-semibold border-b-2 -mb-px ${tab === id ? 'border-sky-600 text-sky-700' : 'border-transparent text-slate-500 hover:text-slate-800'}`}>{label}</button>
        ))}
      </div>

      <div role="tabpanel">
        {tab === 'overview' && <OverviewTab {...props} />}
        {tab === 'verification' && <VerificationTab {...props} />}
        {tab === 'plan' && <PlanTab {...props} />}
        {tab === 'inventory' && <InventoryTab {...props} />}
        {tab === 'actions' && <ActionsTab {...props} />}
        {tab === 'export' && <ExportTab {...props} />}
        {tab === 'tools' && <ToolCallsTab {...props} />}
        {tab === 'audit' && <AuditTab {...props} />}
        {tab === 'record' && <RecordTab {...props} />}
      </div>
    </div>
  );
};
