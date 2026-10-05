import React from 'react';
import { DeadlineState, RequestStatus, RequestType } from '../types';
import { AlertCircle, Clock, CheckCircle2, AlertTriangle, ShieldCheck } from 'lucide-react';

export const DeadlineBadge: React.FC<{ deadline: DeadlineState }> = ({ deadline }) => {
  if (deadline.deadline_status === 'OVERDUE') {
    return (
      <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-bold bg-red-100 text-red-800 border border-red-200 animate-pulse">
        <AlertCircle className="w-3.5 h-3.5" />
        <span>OVERDUE ({Math.abs(deadline.days_remaining)}d past)</span>
      </span>
    );
  }

  if (deadline.deadline_status === 'AT_RISK') {
    return (
      <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-100 text-amber-800 border border-amber-300">
        <AlertTriangle className="w-3.5 h-3.5" />
        <span>AT RISK ({deadline.days_remaining}d left)</span>
      </span>
    );
  }

  if (deadline.deadline_status === 'COMPLETED') {
    return (
      <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
        <CheckCircle2 className="w-3.5 h-3.5" />
        <span>COMPLETED</span>
      </span>
    );
  }

  return (
    <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-sky-50 text-sky-700 border border-sky-200">
      <Clock className="w-3.5 h-3.5" />
      <span>ON TRACK ({deadline.days_remaining}d left)</span>
    </span>
  );
};

export const StatusBadge: React.FC<{ status: RequestStatus }> = ({ status }) => {
  const getStyle = () => {
    switch (status) {
      case 'NEW':
      case 'AWAITING_INFO':
        return 'bg-slate-100 text-slate-700 border-slate-200';
      case 'VERIFICATION_PENDING':
        return 'bg-blue-50 text-blue-700 border-blue-200';
      case 'VERIFIED':
        return 'bg-emerald-50 text-emerald-700 border-emerald-200';
      case 'VERIFICATION_FAILED':
        return 'bg-red-50 text-red-700 border-red-200';
      case 'PLANNING':
        return 'bg-indigo-50 text-indigo-700 border-indigo-200 animate-pulse';
      case 'PLAN_REVIEW':
      case 'AWAITING_ACTION_APPROVAL':
      case 'EXPORT_REVIEW':
        return 'bg-amber-50 text-amber-800 border-amber-300';
      case 'PLAN_APPROVED':
        return 'bg-teal-50 text-teal-700 border-teal-200';
      case 'EXECUTING':
        return 'bg-purple-50 text-purple-700 border-purple-200';
      case 'PARTIALLY_FAILED':
        return 'bg-orange-50 text-orange-800 border-orange-300';
      case 'COMPLETED_PENDING_RECORD':
        return 'bg-emerald-100 text-emerald-800 border-emerald-300';
      case 'CLOSED':
        return 'bg-slate-900 text-white border-slate-900';
      case 'REJECTED':
      case 'CANCELLED':
        return 'bg-rose-100 text-rose-800 border-rose-200';
      default:
        return 'bg-slate-100 text-slate-600 border-slate-200';
    }
  };

  return (
    <span className={`inline-block px-2.5 py-0.5 rounded-full text-[11px] font-semibold tracking-wide border uppercase ${getStyle()}`}>
      {status.replace(/_/g, ' ')}
    </span>
  );
};

export const TypeBadge: React.FC<{ type: RequestType }> = ({ type }) => {
  const styles: Record<RequestType, string> = {
    ACCESS: 'bg-sky-100 text-sky-800 border-sky-300',
    CORRECTION: 'bg-emerald-100 text-emerald-800 border-emerald-300',
    DELETION: 'bg-rose-100 text-rose-800 border-rose-300',
    UNSUPPORTED: 'bg-gray-100 text-gray-800 border-gray-300',
  };

  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-bold border tracking-wider uppercase ${styles[type] || 'bg-slate-100 text-slate-700'}`}>
      {type}
    </span>
  );
};
