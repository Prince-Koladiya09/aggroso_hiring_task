import React, { useCallback, useEffect, useState } from 'react';
import { ShieldCheck, ShieldX } from 'lucide-react';
import { apiRequest } from '../api/client';
import { useUi, Skeleton, Empty } from '../components/Ui';
import type { TabProps } from '../pages/RequestDetail';

export const AuditTab: React.FC<TabProps> = ({ req }) => {
  const { toast } = useUi();
  const [events, setEvents] = useState<any[] | null>(null);
  const [chain, setChain] = useState<any>(null);
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => { try { setEvents(await apiRequest(`/requests/${req.id}/audit`)); } catch (e: any) { toast.error(e.message); setEvents([]); } }, [req.id]);
  useEffect(() => { load(); }, [load, req.status]);
  const verify = async () => { setBusy(true); try { setChain(await apiRequest('/audit/verify')); } catch (e: any) { toast.error(e.message); } finally { setBusy(false); } };
  if (!events) return <Skeleton rows={5} />;
  const shown = events.filter((e) => !q || e.event_type.toLowerCase().includes(q.toLowerCase()) || JSON.stringify(e.payload).toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl border border-slate-200 p-4 flex flex-wrap items-center gap-3">
        <div className="flex-1"><h3 className="text-sm font-bold">Audit trail ({events.length} events)</h3><p className="text-xs text-slate-500">Append-only and hash-chained: each event stores the hash of the previous one. There are no edit or delete endpoints.</p></div>
        <input aria-label="Search events" placeholder="Search events..." value={q} onChange={(e) => setQ(e.target.value)} className="text-xs border border-slate-300 rounded-lg p-1.5" />
        <button disabled={busy} onClick={verify} className="px-3 py-2 text-xs font-semibold bg-slate-800 text-white rounded-lg disabled:opacity-50">{busy ? 'Verifying...' : 'Verify hash chain'}</button>
      </div>
      {chain && <div className={`rounded-2xl border p-4 text-xs flex items-center space-x-2 ${chain.is_valid ? 'bg-emerald-50 border-emerald-200 text-emerald-900' : 'bg-red-50 border-red-300 text-red-900'}`} role="status">{chain.is_valid ? <ShieldCheck className="w-5 h-5" /> : <ShieldX className="w-5 h-5" />}<span className="font-bold">{chain.is_valid ? `Chain intact: ${chain.total_events_checked} events verified (whole system)` : `TAMPERING DETECTED at seq ${chain.broken_seq}: ${chain.error}`}</span></div>}
      {shown.length === 0 ? <Empty title="No events" /> : (
        <div className="bg-white rounded-2xl border border-slate-200 overflow-x-auto"><table className="w-full text-xs"><thead className="bg-slate-50 text-left text-slate-500"><tr><th className="p-3">#</th><th>When</th><th>Event</th><th>Actor</th><th>Details</th><th>Hash</th></tr></thead>
          <tbody>{shown.map((e) => <tr key={e.id} className="border-t border-slate-100 align-top"><td className="p-3 font-mono">{e.seq}</td><td className="whitespace-nowrap">{new Date(e.timestamp).toLocaleString()}</td>
            <td className={`font-semibold ${/FAILED|DENIED|ERROR|REFUSED/.test(e.event_type) ? 'text-red-700' : ''}`}>{e.event_type}</td><td>{e.actor_role}<span className="block font-mono text-slate-400">{e.actor_id}</span></td>
            <td className="max-w-md"><code className="text-[11px] break-all">{JSON.stringify(e.payload).slice(0, 220)}</code></td><td className="font-mono text-slate-400" title={`prev ${e.prev_hash}`}>{e.hash.slice(0, 8)}</td></tr>)}</tbody></table></div>)}
    </div>
  );
};
