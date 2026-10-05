import React, { useState, useEffect } from 'react';
import { RequestSummary, RequestType, RequestStatus } from '../types';
import { apiRequest } from '../api/client';
import { DeadlineBadge, StatusBadge, TypeBadge } from '../components/Badge';
import { NewRequestModal } from '../components/NewRequestModal';
import { Plus, Search, Filter, AlertTriangle, AlertCircle, CheckCircle2, Clock, ArrowRight, Shield } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

interface DashboardProps {
  onSelectRequest: (id: string) => void;
}

export const Dashboard: React.FC<DashboardProps> = ({ onSelectRequest }) => {
  const { user } = useAuth();
  const [requests, setRequests] = useState<RequestSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [deadlineFilter, setDeadlineFilter] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);

  useEffect(() => {
    fetchRequests();
  }, [statusFilter, typeFilter, deadlineFilter]);

  const fetchRequests = async () => {
    setLoading(true);
    setLoadError('');
    try {
      let query = '?';
      if (statusFilter) query += `status=${statusFilter}&`;
      if (typeFilter) query += `type=${typeFilter}&`;
      if (deadlineFilter) query += `deadline=${deadlineFilter}&`;

      const data = await apiRequest<RequestSummary[]>(`/requests${query}`);
      setRequests(data);
    } catch (e: any) {
      setLoadError(e.message || 'Failed to load requests');
    } finally {
      setLoading(false);
    }
  };

  const filtered = requests.filter(r => {
    const s = search.toLowerCase();
    return (
      r.requester_name.toLowerCase().includes(s) ||
      r.requester_email.toLowerCase().includes(s) ||
      r.id.toLowerCase().includes(s)
    );
  });

  const overdueCount = requests.filter(r => r.deadline.deadline_status === 'OVERDUE').length;
  const atRiskCount = requests.filter(r => r.deadline.deadline_status === 'AT_RISK').length;
  const activeCount = requests.filter(r => !['CLOSED', 'REJECTED', 'CANCELLED'].includes(r.status)).length;
  const closedCount = requests.filter(r => r.status === 'CLOSED').length;

  return (
    <div className="space-y-6">
      {/* Top Banner / KPIs */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center justify-between">
          <div>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Active Requests</p>
            <p className="text-2xl font-bold text-slate-900 mt-1">{activeCount}</p>
          </div>
          <div className="w-10 h-10 rounded-lg bg-sky-50 flex items-center justify-center text-sky-600">
            <Clock className="w-5 h-5" />
          </div>
        </div>

        <div
          onClick={() => setDeadlineFilter(deadlineFilter === 'AT_RISK' ? '' : 'AT_RISK')}
          className={`p-5 rounded-xl border shadow-sm flex items-center justify-between cursor-pointer transition-all ${
            deadlineFilter === 'AT_RISK' ? 'bg-amber-50 border-amber-300 ring-2 ring-amber-400' : 'bg-white border-slate-200 hover:border-amber-200'
          }`}
        >
          <div>
            <p className="text-xs font-semibold text-amber-700 uppercase tracking-wider">At Risk (&le; 7 Days)</p>
            <p className="text-2xl font-bold text-amber-900 mt-1">{atRiskCount}</p>
          </div>
          <div className="w-10 h-10 rounded-lg bg-amber-100 flex items-center justify-center text-amber-700">
            <AlertTriangle className="w-5 h-5" />
          </div>
        </div>

        <div
          onClick={() => setDeadlineFilter(deadlineFilter === 'OVERDUE' ? '' : 'OVERDUE')}
          className={`p-5 rounded-xl border shadow-sm flex items-center justify-between cursor-pointer transition-all ${
            deadlineFilter === 'OVERDUE' ? 'bg-red-50 border-red-300 ring-2 ring-red-400' : 'bg-white border-slate-200 hover:border-red-200'
          }`}
        >
          <div>
            <p className="text-xs font-semibold text-red-700 uppercase tracking-wider">Overdue</p>
            <p className="text-2xl font-bold text-red-900 mt-1">{overdueCount}</p>
          </div>
          <div className="w-10 h-10 rounded-lg bg-red-100 flex items-center justify-center text-red-700">
            <AlertCircle className="w-5 h-5" />
          </div>
        </div>

        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center justify-between">
          <div>
            <p className="text-xs font-semibold text-emerald-700 uppercase tracking-wider">Fulfilled & Closed</p>
            <p className="text-2xl font-bold text-emerald-900 mt-1">{closedCount}</p>
          </div>
          <div className="w-10 h-10 rounded-lg bg-emerald-50 flex items-center justify-center text-emerald-600">
            <CheckCircle2 className="w-5 h-5" />
          </div>
        </div>
      </div>

      {/* Action Bar & Filters */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex flex-col md:flex-row items-center justify-between gap-4">
        {/* Search */}
        <div className="relative w-full md:w-80">
          <Search className="w-4 h-4 absolute left-3 top-3 text-slate-400" />
          <input
            type="text"
            placeholder="Search by requester, email, or ID..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-4 py-2 text-xs border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-sky-500"
          />
        </div>

        {/* Filter Controls */}
        <div className="flex flex-wrap items-center gap-2 w-full md:w-auto justify-end">
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="text-xs border border-slate-300 rounded-lg px-2.5 py-2 bg-white text-slate-700"
          >
            <option value="">All Types</option>
            <option value="ACCESS">Access</option>
            <option value="CORRECTION">Correction</option>
            <option value="DELETION">Deletion</option>
          </select>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="text-xs border border-slate-300 rounded-lg px-2.5 py-2 bg-white text-slate-700"
          >
            <option value="">All Statuses</option>
            <option value="NEW">New</option>
            <option value="AWAITING_INFO">Awaiting Info</option>
            <option value="VERIFIED">Verified</option>
            <option value="PLAN_REVIEW">Plan Review</option>
            <option value="AWAITING_ACTION_APPROVAL">Action Approval</option>
            <option value="EXPORT_REVIEW">Export Review</option>
            <option value="EXECUTING">Executing</option>
            <option value="CLOSED">Closed</option>
          </select>

          {user?.role === 'analyst' && (
            <button
              onClick={() => setIsModalOpen(true)}
              className="flex items-center space-x-1.5 px-3.5 py-2 bg-sky-600 hover:bg-sky-700 text-white text-xs font-semibold rounded-lg shadow-sm transition-colors"
            >
              <Plus className="w-4 h-4" />
              <span>New Request</span>
            </button>
          )}
        </div>
      </div>

      {/* Requests Table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 font-semibold uppercase tracking-wider">
              <tr>
                <th className="py-3.5 px-4">Request ID</th>
                <th className="py-3.5 px-4">Type</th>
                <th className="py-3.5 px-4">Requester</th>
                <th className="py-3.5 px-4">Status</th>
                <th className="py-3.5 px-4">SLA Deadline</th>
                <th className="py-3.5 px-4 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400">
                    Loading requests...
                  </td>
                </tr>
              ) : loadError ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-red-600" role="alert">
                    {loadError} <button onClick={() => fetchRequests()} className="underline ml-2">Retry</button>
                  </td>
                </tr>
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400">
                    No requests match the selected criteria.
                  </td>
                </tr>
              ) : (
                filtered.map((req) => (
                  <tr
                    key={req.id}
                    onClick={() => onSelectRequest(req.id)}
                    className="hover:bg-slate-50/80 cursor-pointer transition-colors"
                  >
                    <td className="py-3.5 px-4 font-mono font-bold text-sky-700">{req.id}</td>
                    <td className="py-3.5 px-4">
                      <TypeBadge type={req.type} />
                    </td>
                    <td className="py-3.5 px-4">
                      <span className="font-semibold text-slate-900 block">{req.requester_name}</span>
                      <span className="text-slate-500 text-[11px] block">{req.requester_email}</span>
                    </td>
                    <td className="py-3.5 px-4">
                      <StatusBadge status={req.status} />
                    </td>
                    <td className="py-3.5 px-4">
                      <DeadlineBadge deadline={req.deadline} />
                    </td>
                    <td className="py-3.5 px-4 text-right">
                      <span className="inline-flex items-center space-x-1 text-sky-600 hover:text-sky-800 font-medium">
                        <span>Open</span>
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

      <NewRequestModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={(id) => {
          fetchRequests();
          onSelectRequest(id);
        }}
      />
    </div>
  );
};
