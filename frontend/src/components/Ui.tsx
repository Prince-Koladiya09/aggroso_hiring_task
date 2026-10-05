import React, { createContext, useCallback, useContext, useRef, useState } from 'react';
import { CheckCircle2, XCircle, Info, X, AlertTriangle } from 'lucide-react';

type ToastKind = 'success' | 'error' | 'info';
interface ToastItem { id: number; kind: ToastKind; message: string; hint?: string }

export interface ConfirmOptions {
  title: string;
  /** Exact list of what will change (SRS 13.3). */
  lines?: string[];
  description?: string;
  confirmLabel?: string;
  danger?: boolean;
  /** When set, a justification of at least minReasonLength characters is mandatory. */
  reasonLabel?: string;
  minReasonLength?: number;
  reasonDefault?: string;
}

interface UiCtx {
  toast: { success: (m: string) => void; error: (m: string, hint?: string) => void; info: (m: string) => void };
  /** Resolves to the entered reason ('' if none requested) or null if cancelled. */
  confirm: (o: ConfirmOptions) => Promise<string | null>;
}

const Ctx = createContext<UiCtx | null>(null);

export const UiProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [dlg, setDlg] = useState<(ConfirmOptions & { resolve: (v: string | null) => void }) | null>(null);
  const [reason, setReason] = useState('');
  const idRef = useRef(1);

  const push = useCallback((kind: ToastKind, message: string, hint?: string) => {
    const id = idRef.current++;
    setToasts((t) => [...t, { id, kind, message, hint }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === 'error' ? 9000 : 4500);
  }, []);

  const confirm = useCallback((o: ConfirmOptions) => new Promise<string | null>((resolve) => {
    setReason(o.reasonDefault || '');
    setDlg({ ...o, resolve });
  }), []);

  const close = (v: string | null) => { dlg?.resolve(v); setDlg(null); };
  const need = dlg?.reasonLabel ? (dlg.minReasonLength ?? 5) : 0;
  const reasonOk = reason.trim().length >= need;

  const value: UiCtx = {
    toast: { success: (m) => push('success', m), error: (m, h) => push('error', m, h), info: (m) => push('info', m) },
    confirm,
  };

  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="fixed top-4 right-4 z-[100] space-y-2 w-96 max-w-[92vw]" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`flex items-start space-x-2 p-3 rounded-xl border shadow-lg text-sm bg-white ${
            t.kind === 'success' ? 'border-emerald-300' : t.kind === 'error' ? 'border-red-300' : 'border-sky-300'}`}>
            {t.kind === 'success' ? <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" /> :
              t.kind === 'error' ? <XCircle className="w-5 h-5 text-red-600 shrink-0" /> : <Info className="w-5 h-5 text-sky-600 shrink-0" />}
            <div className="flex-1 min-w-0">
              <p className="text-slate-800 font-medium break-words">{t.message}</p>
              {t.hint && <p className="text-xs text-slate-500 mt-0.5">{t.hint}</p>}
            </div>
            <button aria-label="Dismiss" onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))} className="text-slate-400 hover:text-slate-600"><X className="w-4 h-4" /></button>
          </div>
        ))}
      </div>

      {dlg && (
        <div className="fixed inset-0 z-[90] bg-slate-900/50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label={dlg.title}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg p-6 space-y-4">
            <div className="flex items-start space-x-3">
              {dlg.danger && <AlertTriangle className="w-6 h-6 text-red-600 shrink-0" />}
              <div>
                <h3 className="text-base font-bold text-slate-900">{dlg.title}</h3>
                {dlg.description && <p className="text-sm text-slate-600 mt-1">{dlg.description}</p>}
              </div>
            </div>
            {dlg.lines && dlg.lines.length > 0 && (
              <ul className="text-xs font-mono bg-slate-50 border border-slate-200 rounded-lg p-3 max-h-48 overflow-y-auto space-y-1">
                {dlg.lines.map((l, i) => <li key={i}>{l}</li>)}
              </ul>
            )}
            {dlg.reasonLabel && (
              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-1" htmlFor="confirm-reason">{dlg.reasonLabel} <span className="text-red-600">*</span></label>
                <textarea id="confirm-reason" autoFocus value={reason} onChange={(e) => setReason(e.target.value)} rows={3}
                  className="w-full border border-slate-300 rounded-lg p-2 text-sm focus:ring-2 focus:ring-sky-500 outline-none" />
                {!reasonOk && <p className="text-xs text-red-600 mt-1">A justification of at least {need} characters is required.</p>}
              </div>
            )}
            <div className="flex justify-end space-x-2 pt-1">
              <button onClick={() => close(null)} className="px-4 py-2 text-sm rounded-lg border border-slate-300 text-slate-700 hover:bg-slate-50">Cancel</button>
              <button disabled={!reasonOk} onClick={() => close(reason.trim())}
                className={`px-4 py-2 text-sm rounded-lg font-semibold text-white disabled:opacity-40 ${dlg.danger ? 'bg-red-600 hover:bg-red-700' : 'bg-sky-600 hover:bg-sky-700'}`}>
                {dlg.confirmLabel || 'Confirm'}
              </button>
            </div>
          </div>
        </div>
      )}
    </Ctx.Provider>
  );
};

export const useUi = (): UiCtx => {
  const c = useContext(Ctx);
  if (!c) throw new Error('useUi must be used inside UiProvider');
  return c;
};

export const Skeleton: React.FC<{ rows?: number }> = ({ rows = 3 }) => (
  <div className="space-y-3 animate-pulse" aria-busy="true" aria-label="Loading">
    {Array.from({ length: rows }).map((_, i) => <div key={i} className="h-10 bg-slate-100 rounded-lg" />)}
  </div>
);

export const Empty: React.FC<{ title: string; next?: string }> = ({ title, next }) => (
  <div className="text-center py-10 border border-dashed border-slate-300 rounded-xl bg-slate-50">
    <p className="text-sm font-semibold text-slate-700">{title}</p>
    {next && <p className="text-xs text-slate-500 mt-1">{next}</p>}
  </div>
);

export const RuleChips: React.FC<{ ids?: string[] }> = ({ ids }) => (
  <span className="inline-flex flex-wrap gap-1">
    {(ids || []).map((r) => <span key={r} className="px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 border border-indigo-200 text-[10px] font-mono font-bold">{r}</span>)}
  </span>
);

export const Banner: React.FC<{ kind: 'warn' | 'error' | 'info' | 'ok'; title: string; children?: React.ReactNode }> = ({ kind, title, children }) => {
  const style = { warn: 'bg-amber-50 border-amber-300 text-amber-900', error: 'bg-red-50 border-red-300 text-red-900',
    info: 'bg-sky-50 border-sky-200 text-sky-900', ok: 'bg-emerald-50 border-emerald-300 text-emerald-900' }[kind];
  return (
    <div className={`border rounded-xl p-3 text-sm ${style}`} role={kind === 'error' ? 'alert' : 'note'}>
      <strong className="block">{title}</strong>
      {children && <div className="text-xs mt-1 space-y-1">{children}</div>}
    </div>
  );
};
