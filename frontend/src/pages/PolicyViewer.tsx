import React, { useState, useEffect } from 'react';
import { apiRequest } from '../api/client';
import { PolicyData } from '../types';
import { Shield, BookOpen, AlertCircle, FileText } from 'lucide-react';

export const PolicyViewer: React.FC = () => {
  const [policy, setPolicy] = useState<PolicyData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchPolicy();
  }, []);

  const fetchPolicy = async () => {
    try {
      const data = await apiRequest<PolicyData>('/policy');
      setPolicy(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  if (loading || !policy) {
    return <div className="py-24 text-center text-xs text-slate-400">Loading organizational policy...</div>;
  }

  return (
    <div className="space-y-6">
      <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-slate-900 flex items-center space-x-2">
            <BookOpen className="w-5 h-5 text-sky-600" />
            <span>{policy.title}</span>
          </h2>
          <p className="text-xs text-slate-500 mt-1">
            Active version: <strong className="font-mono text-slate-800">{policy.policy_version}</strong> &bull; Organization: {policy.organization}
          </p>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm space-y-6 text-xs">
        {/* SLA parameters */}
        <div className="space-y-3">
          <h3 className="text-sm font-bold text-slate-900 border-b border-slate-100 pb-2">Service Level Agreement (SLA) Constants</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg">
              <span className="text-slate-400 block text-[10px] uppercase font-bold">Standard Fulfilment</span>
              <span className="text-base font-bold text-slate-900">{policy.sla.fulfil_days} Calendar Days</span>
            </div>
            <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg">
              <span className="text-slate-400 block text-[10px] uppercase font-bold">Acknowledgement</span>
              <span className="text-base font-bold text-slate-900">{policy.sla.acknowledge_days} Days</span>
            </div>
            <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg">
              <span className="text-slate-400 block text-[10px] uppercase font-bold">Extension Allowance</span>
              <span className="text-base font-bold text-slate-900">{policy.sla.extension_days} Days (Max {policy.sla.max_extensions})</span>
            </div>
            <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg">
              <span className="text-slate-400 block text-[10px] uppercase font-bold">At-Risk Threshold</span>
              <span className="text-base font-bold text-amber-700">&le; {policy.sla.at_risk_days} Days Left</span>
            </div>
          </div>
        </div>

        {/* Rule Definitions */}
        <div className="space-y-3">
          <h3 className="text-sm font-bold text-slate-900 border-b border-slate-100 pb-2">Policy Rule Catalog</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {Object.entries(policy.rules).map(([ruleId, rule]) => (
              <div key={ruleId} className="p-4 border border-slate-200 rounded-xl bg-slate-50/50 space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="font-mono font-bold text-sky-700 bg-sky-50 px-2 py-0.5 rounded border border-sky-200">
                    {ruleId}
                  </span>
                  <span className="text-xs font-bold text-slate-800">{rule.name}</span>
                </div>
                <p className="text-slate-600 text-[11px] leading-relaxed pt-1">{rule.description}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Editable fields */}
        <div className="space-y-3">
          <h3 className="text-sm font-bold text-slate-900 border-b border-slate-100 pb-2">Subject Self-Service Editable Profile Fields</h3>
          <div className="flex flex-wrap gap-2">
            {policy.editable_subject_fields?.map(f => (
              <span key={f} className="px-2.5 py-1 bg-slate-100 border border-slate-200 rounded font-mono text-slate-700 font-semibold">
                {f}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
