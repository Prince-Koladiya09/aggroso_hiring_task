import React from 'react';
import { AlertCircle } from 'lucide-react';

export const Footer: React.FC = () => {
  return (
    <footer className="bg-white border-t border-slate-200 mt-12 py-6 text-xs text-slate-500">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-start space-x-3 bg-slate-50 border border-slate-200 rounded-lg p-3.5">
          <AlertCircle className="w-5 h-5 text-sky-600 shrink-0 mt-0.5" />
          <div className="text-slate-600 leading-relaxed text-xs">
            <strong className="text-slate-800">Organizational Policy Notice:</strong> This tool supports internal handling of privacy requests according to the supplied organizational policy (mock &ldquo;Acme Privacy Request Handling Policy v1.0&rdquo;). It is an information-management and workflow aid. It does not provide legal advice and does not determine, certify, or guarantee legal or regulatory compliance. All outcomes require human review.
          </div>
        </div>
        <div className="mt-4 flex flex-col sm:flex-row items-center justify-between text-slate-400 text-[11px]">
          <span>Acme Privacy Request Fulfilment Workbench &bull; Version 1.0 (Mock Build)</span>
          <span className="mt-1 sm:mt-0">Humans approve every modifying action &bull; Deterministic Safety Enforced</span>
        </div>
      </div>
    </footer>
  );
};
