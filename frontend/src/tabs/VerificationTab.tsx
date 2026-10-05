import React, { useCallback, useEffect, useState } from 'react';
import { Lock, Unlock, Send, Bot } from 'lucide-react';
import { apiRequest } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { useUi, Banner, Skeleton, Empty } from '../components/Ui';
import type { TabProps } from '../pages/RequestDetail';

const VERIFIABLE = ['NEW', 'AWAITING_INFO', 'VERIFICATION_PENDING', 'VERIFICATION_FAILED'];

export const VerificationTab: React.FC<TabProps> = ({ req, reload }) => {
  const { user } = useAuth();
  const { toast, confirm } = useUi();
  const [data, setData] = useState<any>(null);
  const [busy, setBusy] = useState('');
  const [name, setName] = useState(req.requester_name);
  const [email, setEmail] = useState(req.requester_email);
  const [acc, setAcc] = useState(req.account_id || '');
  const [otp, setOtp] = useState('');
  const [auth, setAuth] = useState(!!req.authorization_on_file);
  const [result, setResult] = useState<any>(null);
  const [interp, setInterp] = useState<any>(null);

  const load = useCallback(async () => {
    try { setData(await apiRequest(`/requests/${req.id}/verification`)); } catch (e: any) { toast.error(e.message); }
  }, [req.id]);
  useEffect(() => { load(); }, [load, req.status]);

  const run = async (key: string, fn: () => Promise<any>, ok?: string) => {
    setBusy(key);
    try { const r = await fn(); if (ok) toast.success(ok); return r; }
    catch (e: any) { toast.error(e.message, e.ruleIds?.length ? `Rule: ${e.ruleIds.join(', ')}` : undefined); }
    finally { setBusy(''); await load(); await reload(); }
  };

  const verify = async () => {
    const r = await run('verify', () => apiRequest(`/requests/${req.id}/verification`, { method: 'POST',
      body: JSON.stringify({ name, email: email || null, account_id: acc || null, otp: otp || null, authorization_on_file: auth }) }));
    if (r) {
      setResult(r);
      if (r.result === 'PASSED') toast.success(`Level ${r.level} verification passed`);
      else toast.error(`Verification ${r.result.toLowerCase().replace('_', ' ')}: ${r.failed_fields.join(', ')}`);
    }
  };
  const sendOtp = () => run('otp', () => apiRequest(`/requests/${req.id}/verification/send-otp`, { method: 'POST' }), 'One-time code sent to the simulated outbox');
  const interpret = async () => { const r = await run('interp', () => apiRequest(`/requests/${req.id}/agent/interpret`, { method: 'POST' })); if (r) setInterp(r); };
  const unlock = async () => {
    const ok = await confirm({ title: 'Unlock verification?', lines: ['Resets the failed-code counter', 'A new one-time code must be sent'], confirmLabel: 'Unlock' });
    if (ok !== null) run('unlock', () => apiRequest(`/requests/${req.id}/verification/unlock`, { method: 'POST' }), 'Verification unlocked');
  };
  const closeReq = async () => {
    const reason = await confirm({ title: 'Reject this request?', lines: ['Request moves to REJECTED (final)', 'No data is accessed'], reasonLabel: 'Reason', confirmLabel: 'Reject request', danger: true });
    if (reason) run('rej', () => apiRequest(`/requests/${req.id}/reject`, { method: 'POST', body: JSON.stringify({ reason }) }), 'Request rejected');
  };
  const supply = async () => {
    run('info', () => apiRequest(`/requests/${req.id}/info`, { method: 'PATCH', body: JSON.stringify({ account_id: acc || undefined, authorization_on_file: auth }) }), 'Information saved');
  };

  if (!data) return <Skeleton rows={3} />;
  const canAct = user?.role === 'analyst' && VERIFIABLE.includes(req.status);
  const level2 = data.required_level >= 2;
  const missing = interp?.missing_verification ?? data.missing_verification;

  return (
    <div className="grid lg:grid-cols-3 gap-6">
      <div className="lg:col-span-2 space-y-4">
        {data.locked && (
          <Banner kind="error" title="Verification is LOCKED (3 incorrect one-time codes, POL-ID-2)">
            An Approver must unlock it. {user?.role === 'approver' && <button onClick={unlock} className="ml-2 underline font-semibold inline-flex items-center"><Unlock className="w-3 h-3 mr-1" />Unlock</button>}
          </Banner>
        )}
        {req.status === 'VERIFIED' && <Banner kind="ok" title={`Level ${data.required_level} verification passed`}>The agent may now search data sources.</Banner>}

        <div className="bg-white rounded-2xl border border-slate-200 p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-900">Mock identity verification - Level {data.required_level} {level2 ? '(Level 1 + one-time code, POL-ID-2)' : '(name, e-mail, account ID, POL-ID-1)'}</h3>
          </div>
          <p className="text-xs text-slate-500">Enter what the requester supplied. Submitted values are compared with the profile database; failures list field names only, never stored values.</p>
          <div className="grid sm:grid-cols-3 gap-3 text-xs">
            <label className="block"><span className="font-semibold text-slate-600">Name</span><input disabled={!canAct} value={name} onChange={(e) => setName(e.target.value)} className="mt-1 w-full border border-slate-300 rounded-lg p-2 disabled:bg-slate-50" /></label>
            <label className="block"><span className="font-semibold text-slate-600">Registered e-mail</span><input disabled={!canAct} value={email} onChange={(e) => setEmail(e.target.value)} className="mt-1 w-full border border-slate-300 rounded-lg p-2 disabled:bg-slate-50" /></label>
            <label className="block"><span className="font-semibold text-slate-600">Account ID</span><input disabled={!canAct} value={acc} onChange={(e) => setAcc(e.target.value)} className="mt-1 w-full border border-slate-300 rounded-lg p-2 disabled:bg-slate-50" /></label>
          </div>
          {level2 && (
            <label className="block text-xs max-w-xs"><span className="font-semibold text-slate-600">One-time code</span>
              <input disabled={!canAct || data.locked} value={otp} onChange={(e) => setOtp(e.target.value)} inputMode="numeric" maxLength={6} className="mt-1 w-full border border-slate-300 rounded-lg p-2 font-mono tracking-widest disabled:bg-slate-50" /></label>
          )}
          {req.relationship === 'authorized_agent' && (
            <label className="flex items-center space-x-2 text-xs"><input type="checkbox" disabled={!canAct} checked={auth} onChange={(e) => setAuth(e.target.checked)} /><span>Authorization is on file (POL-ID-3)</span></label>
          )}
          {!canAct && <p className="text-xs text-slate-500">{user?.role !== 'analyst' ? 'Only an Analyst can run verification.' : `Verification is not available in status ${req.status}.`}</p>}
          <div className="flex flex-wrap gap-2 pt-1">
            {level2 && <button disabled={!canAct || data.locked || busy !== ''} onClick={sendOtp} className="px-3 py-2 text-xs font-semibold rounded-lg border border-slate-300 hover:bg-slate-50 disabled:opacity-40 inline-flex items-center"><Send className="w-3.5 h-3.5 mr-1" />{busy === 'otp' ? 'Sending...' : 'Send one-time code'}</button>}
            {req.status === 'AWAITING_INFO' && <button disabled={!canAct || busy !== ''} onClick={supply} className="px-3 py-2 text-xs font-semibold rounded-lg border border-amber-300 text-amber-900 bg-amber-50 disabled:opacity-40">Save supplied info</button>}
            <button disabled={!canAct || data.locked || busy !== ''} onClick={verify} className="px-4 py-2 text-xs font-semibold rounded-lg bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-40">{busy === 'verify' ? 'Verifying...' : 'Run verification'}</button>
            {req.status === 'VERIFICATION_FAILED' && user?.role === 'analyst' && <button onClick={closeReq} className="px-3 py-2 text-xs font-semibold rounded-lg border border-red-300 text-red-700 hover:bg-red-50">Reject request</button>}
          </div>
          {result && result.result !== 'PASSED' && (
            <Banner kind={result.result === 'AWAITING_INFO' ? 'warn' : 'error'} title={result.result === 'AWAITING_INFO' ? 'More information is required' : 'Verification failed'}>
              <p>Failing: {result.failed_fields.map((f: string) => <code key={f} className="mx-1 px-1 bg-white/60 rounded">{f}</code>)}</p>
              {result.failed_fields.includes('ambiguous_match') && <p>Several profiles match. Nothing was auto-selected: add the e-mail and account ID.</p>}
            </Banner>
          )}
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 p-5">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-bold text-slate-900">Missing-information check</h3>
            {user?.role === 'analyst' && <button disabled={busy !== ''} onClick={interpret} className="text-xs font-semibold inline-flex items-center text-indigo-700 border border-indigo-200 rounded-lg px-2.5 py-1.5 hover:bg-indigo-50 disabled:opacity-40"><Bot className="w-3.5 h-3.5 mr-1" />{busy === 'interp' ? 'Asking agent...' : 'Ask agent to interpret'}</button>}
          </div>
          {missing?.length ? (
            <ul className="space-y-2 text-xs">{missing.map((m: any) => <li key={m.item} className="border border-amber-200 bg-amber-50 rounded-lg p-2"><strong>{m.item}</strong> <span className="font-mono text-indigo-700">{m.policy_rule}</span><br />{m.reason}</li>)}</ul>
          ) : <p className="text-xs text-emerald-700 font-semibold">Nothing missing for this request type.</p>}
          {interp && (
            <div className="mt-3 text-xs space-y-1 border-t border-slate-100 pt-3">
              <p><strong>Agent reading:</strong> {interp.scope_summary}</p>
              {!interp.type_matches_form && <Banner kind="warn" title={`Type mismatch: description reads as ${interp.request_type}, form says ${req.type}`}>Confirm the intended type with the requester.</Banner>}
              {interp.ambiguities?.map((a: string, i: number) => <p key={i} className="text-amber-800">&bull; {a}</p>)}
              {interp.agent_disagreed_on_missing_info?.length > 0 && <p className="text-slate-500">The deterministic checker overrode the agent on: {interp.agent_disagreed_on_missing_info.join(', ')}.</p>}
            </div>
          )}
        </div>
      </div>

      <div className="space-y-4">
        {level2 && (
          <div className="bg-slate-900 text-slate-100 rounded-2xl p-4 text-xs font-mono" aria-label="Simulated outbox">
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-2">Simulated outbox (no real message is sent)</p>
            {data.outbox ? (<><p>To: {data.outbox.recipient}</p><p>Channel: {data.outbox.channel}</p><p className="mt-2 text-lg tracking-[0.3em] text-emerald-300">{data.outbox.otp_code}</p></>) : <p className="text-slate-400">No code sent yet.</p>}
            <p className="mt-2 text-slate-400">Failed code attempts: {data.otp_attempts}/3 {data.locked && <Lock className="inline w-3 h-3 text-red-400" />}</p>
          </div>
        )}
        <div className="bg-white rounded-2xl border border-slate-200 p-4">
          <h3 className="text-xs font-bold text-slate-900 mb-2">Check history</h3>
          {data.checks.length === 0 ? <Empty title="No checks yet" next="Run verification to start." /> : (
            <ul className="space-y-2 text-xs">{[...data.checks].reverse().map((c: any) => (
              <li key={c.id} className="border border-slate-100 rounded-lg p-2">
                <span className={`font-bold ${c.result === 'PASSED' ? 'text-emerald-700' : c.result === 'PENDING' || c.result === 'UNLOCKED' ? 'text-slate-600' : 'text-red-700'}`}>{c.result}</span> L{c.level}
                {c.failed_fields?.length > 0 && <span className="text-slate-500"> - {c.failed_fields.join(', ')}</span>}
                <span className="block text-slate-400">{new Date(c.at).toLocaleString()}</span>
              </li>))}</ul>
          )}
        </div>
      </div>
    </div>
  );
};
