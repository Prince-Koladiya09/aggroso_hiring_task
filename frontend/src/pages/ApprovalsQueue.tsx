import React, { useState, useEffect } from 'react';
import { apiRequest } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { TypeBadge, StatusBadge } from '../components/Badge';
import { CheckSquare, ArrowRight, ShieldCheck, AlertCircle } from 'lucide-react';

interface ApprovalsQueueProps {
  onSelectRequest: (id: string) => void;
}

export const ApprovalsQueue: React.FC<ApprovalsQueueProps> = ({ onSelectRequest }) => {
  const { user } = useAuth();
  const [queue, setQueue] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    fetchQueue();
  }, []);

  const fetchQueue = async () => {
    setLoading(true);
    try {
      const data = await apiRequest('/approvals/queue');
      setQueue(data);
    } catch (e: any) {
      setLoadError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-slate-900 flex items-center space-x-2">
            <CheckSquare className="w-5 h-5 text-amber-600" />
            <span>Approvals Queue ({queue.length} Pending)</span>
          </h2>
          <p className="text-xs text-slate-500 mt-1">
            Requests awaiting Approver sign-off for Plan, Deletion, Correction, or Export release.
          </p>
        </div>

        {user?.role !== 'approver' && (
          <div className="px-3 py-1.5 bg-amber-50 border border-amber-200 rounded-lg text-amber-800 text-xs flex items-center space-x-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>Switch to an Approver account (e.g. Jordan Kaur) in top right to submit sign-offs.</span>
          </div>
        )}
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 font-semibold uppercase tracking-wider">
            <tr>
              <th className="py-3 px-4">Request ID</th>
              <th className="py-3 px-4">Type</th>
              <th className="py-3 px-4">Requester</th>
              <th className="py-3 px-4">Status</th>
              <th className="py-3 px-4">Initiating Analyst</th>
              <th className="py-3 px-4 text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr>
                <td colSpan={6} className="py-12 text-center text-slate-400">Loading queue...</td>
              </tr>
            ) : loadError ? (
              <tr>
                <td colSpan={6} className="py-12 text-center text-red-600" role="alert">{loadError} <button onClick={fetchQueue} className="underline ml-2">Retry</button></td>
              </tr>
            ) : queue.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-12 text-center text-slate-400">
                  No requests are currently pending approval.
                </td>
              </tr>
            ) : (
              queue.map((item) => (
                <tr
                  key={item.id}
                  onClick={() => onSelectRequest(item.id)}
                  className="hover:bg-slate-50 cursor-pointer"
                >
                  <td className="py-3.5 px-4 font-mono font-bold text-sky-700">{item.id}</td>
                  <td className="py-3.5 px-4"><TypeBadge type={item.type} /></td>
                  <td className="py-3.5 px-4">
                    <span className="font-semibold text-slate-900 block">{item.requester_name}</span>
                    <span className="text-slate-500 text-[11px] block">{item.requester_email}</span>
                  </td>
                  <td className="py-3.5 px-4">
                    <StatusBadge status={item.status} />
                    <span className="block text-[11px] text-amber-800 font-semibold mt-1">{item.needs}</span>
                  </td>
                  <td className="py-3.5 px-4 font-mono text-slate-600">
                    {item.plan_initiated_by || item.created_by}
                    {item.own_initiated && <span className="block text-[10px] text-red-700 font-bold">You initiated this: cannot approve a deletion (POL-APR-3)</span>}
                  </td>
                  <td className="py-3.5 px-4 text-right">
                    <span className="inline-flex items-center space-x-1 text-sky-600 font-semibold">
                      <span>Review & Approve</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
