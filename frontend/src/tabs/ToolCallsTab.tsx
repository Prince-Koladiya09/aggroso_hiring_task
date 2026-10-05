import React, { useCallback, useEffect, useState } from 'react';
import { apiRequest } from '../api/client';
import { useUi, Skeleton, Empty } from '../components/Ui';
import type { TabProps } from '../pages/RequestDetail';

export const ToolCallsTab: React.FC<TabProps> = ({ req }) => {
  const { toast } = useUi();
  const [calls, setCalls] = useState<any[] | null>(null);
  const [only, setOnly] = useState('');
  const load = useCallback(async () => { try { setCalls(await apiRequest(`/requests/${req.id}/tool-calls`)); } catch (e: any) { toast.error(e.message); setCalls([]); } }, [req.id]);
  useEffect(() => { load(); }, [load, req.status]);
  if (!calls) return <Skeleton rows={4} />;
  const shown = calls.filter((c) => !only || c.status === only);
  const cls: Record<string, string> = { OK: 'text-emerald-700', ERROR: 'text-red-700', DENIED: 'text-amber-800' };
  return (
    <div className="bg-white rounded-2xl border border-slate-200 overflow-x-auto">
      <div className="p-4 flex items-center gap-3 border-b border-slate-100"><h3 className="text-sm font-bold flex-1">Tool calls (every call incl. denied, POL-AUD-1)</h3>
        <select aria-label="Filter status" value={only} onChange={(e) => setOnly(e.target.value)} className="text-xs border border-slate-300 rounded-lg p-1.5"><option value="">All</option><option>OK</option><option>DENIED</option><option>ERROR</option></select></div>
      {shown.length === 0 ? <div className="p-6"><Empty title="No tool calls yet" next="They appear once verification passes and the agent searches the sources." /></div> : (
        <table className="w-full text-xs"><thead className="bg-slate-50 text-left text-slate-500"><tr><th className="p-3">When</th><th>Tool</th><th>Caller</th><th>Status</th><th>Rows</th><th>ms</th><th>Result / denial reason</th></tr></thead>
          <tbody>{shown.map((c) => <tr key={c.id} className="border-t border-slate-100 align-top"><td className="p-3 whitespace-nowrap">{new Date(c.at).toLocaleTimeString()}</td><td className="font-mono">{c.tool}</td><td>{c.caller}</td><td className={`font-bold ${cls[c.status]}`}>{c.status}</td><td>{c.rows}</td><td>{Math.round(c.duration_ms)}</td><td className="max-w-md">{c.status === 'DENIED' ? c.denial_reason : c.result_summary}</td></tr>)}</tbody></table>)}
    </div>
  );
};
