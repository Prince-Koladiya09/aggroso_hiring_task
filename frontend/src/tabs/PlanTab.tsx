import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Bot, Play, CheckCircle2, Circle } from 'lucide-react';
import { apiRequest } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { useUi, Banner, Skeleton, Empty, RuleChips } from '../components/Ui';
import type { TabProps } from '../pages/RequestDetail';

const STAGES = ['Interpreting request', 'Selecting sources', 'Searching sources (read-only)', 'Classifying records', 'Planning & validating'];

export const PlanTab: React.FC<TabProps> = ({ req, reload }) => {
  const { user } = useAuth();
  const { toast, confirm } = useUi();
  const [plan, setPlan] = useState<any>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [stage, setStage] = useState(0);
  const timer = useRef<any>(null);

  const load = useCallback(async () => {
    try {
      setPlan(await apiRequest(`/requests/${req.id}/plan`));
      setRuns(await apiRequest(`/requests/${req.id}/llm-runs`));
    } catch (e: any) { toast.error(e.message); } finally { setLoading(false); }
  }, [req.id]);
  useEffect(() => { load(); }, [load, req.status]);
  useEffect(() => () => clearInterval(timer.current), []);

  const canRun = user?.role === 'analyst' && ['VERIFIED', 'PLANNING_FAILED', 'PLAN_REVIEW'].includes(req.status);

  const run = async () => {
    if (req.status === 'PLAN_REVIEW') {
      const ok = await confirm({ title: 'Re-run the agent (request changes)?', lines: ['The current plan is superseded', 'A NEW inventory version is created; reviewer overrides are not carried over', 'Any approval already given is void'], confirmLabel: 'Re-run agent', danger: true });
      if (ok === null) return;
    }
    setRunning(true); setStage(0);
    timer.current = setInterval(() => setStage((s) => Math.min(s + 1, STAGES.length - 1)), 900);
    try {
      const r = await apiRequest(`/requests/${req.id}/agent/run`, { method: 'POST' });
      toast.success(`Plan ready: ${r.inventory_count} records, ${r.proposed_actions_count} proposed action(s)${r.discarded_count ? `, ${r.discarded_count} agent proposal(s) discarded` : ''}`);
      if (r.fallback_used) toast.info('LLM unavailable or invalid: deterministic fallback planner was used.');
    } catch (e: any) {
      toast.error(`Agent run failed: ${e.message}`, e.correlationId ? `Reference: ${e.correlationId}. You can retry from PLANNING_FAILED.` : 'You can retry.');
    } finally { clearInterval(timer.current); setRunning(false); await load(); await reload(); }
  };

  const decide = async (decision: 'APPROVED' | 'REJECTED') => {
    const reason = await confirm({
      title: decision === 'APPROVED' ? 'Approve plan and inventory?' : 'Reject plan?',
      description: 'POL-APR-1. Approving the plan does NOT authorise any correction or deletion; those need their own approval (POL-APR-2).',
      lines: [`Inventory version ${req.inventory_version}`, `${plan.proposed_actions.filter((a: any) => a.status === 'PROPOSED').length} proposed action(s) are not authorised by this step`,
        decision === 'REJECTED' ? 'The request moves to REJECTED (final)' : (req.type === 'ACCESS' ? 'Next: redacted export review' : 'Next: separate action approval')],
      reasonLabel: 'Justification', confirmLabel: decision === 'APPROVED' ? 'Approve plan' : 'Reject plan', danger: decision === 'REJECTED' });
    if (!reason) return;
    try { await apiRequest(`/requests/${req.id}/approvals`, { method: 'POST', body: JSON.stringify({ scope: 'PLAN', decision, reason }) }); toast.success(`Plan ${decision.toLowerCase()}`); await reload(); await load(); }
    catch (e: any) { toast.error(e.message, e.ruleIds?.length ? `Rule: ${e.ruleIds.join(', ')}` : undefined); }
  };

  if (loading) return <Skeleton rows={4} />;

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl border border-slate-200 p-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold text-slate-900 flex items-center"><Bot className="w-4 h-4 mr-2 text-indigo-600" />AI agent plan</h3>
          <p className="text-xs text-slate-500">The agent proposes; deterministic code validates; humans approve. It has read-only tools and no write tool at all.</p>
        </div>
        {canRun && <button disabled={running} onClick={run} className="px-4 py-2 text-xs font-semibold rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 inline-flex items-center"><Play className="w-3.5 h-3.5 mr-1" />{running ? 'Agent running...' : req.status === 'PLAN_REVIEW' ? 'Request changes (re-run)' : req.status === 'PLANNING_FAILED' ? 'Retry planning' : 'Run agent'}</button>}
      </div>

      {running && (
        <ol className="bg-white rounded-2xl border border-indigo-200 p-4 space-y-1.5 text-xs" aria-live="polite">
          {STAGES.map((s, i) => <li key={s} className="flex items-center space-x-2">{i < stage ? <CheckCircle2 className="w-4 h-4 text-emerald-600" /> : i === stage ? <span className="w-4 h-4 rounded-full border-2 border-indigo-500 border-t-transparent animate-spin" /> : <Circle className="w-4 h-4 text-slate-300" />}<span className={i === stage ? 'font-semibold text-indigo-800' : 'text-slate-500'}>{s}</span></li>)}
        </ol>
      )}

      {req.status === 'PLANNING_FAILED' && <Banner kind="error" title="Planning failed">A tool or the agent returned an error (see Audit Trail). Nothing was changed. {canRun ? 'Use Retry planning.' : ''}</Banner>}
      {!plan?.plan && !running && <Empty title="No plan yet" next={req.status === 'VERIFIED' ? 'Run the agent to interpret the request and search the three sources.' : 'Complete identity verification first.'} />}

      {plan?.plan && (
        <>
          {plan.source === 'FALLBACK' && <Banner kind="warn" title="Deterministic fallback planner used (S10)">The LLM was unavailable or returned invalid output after retries. The plan below was produced by rule-based code. Review it as carefully as any other plan.</Banner>}
          {plan.interpretation && !plan.interpretation.type_matches_form && <Banner kind="warn" title={`Type mismatch: description reads as ${plan.interpretation.request_type}, form says ${req.type}`}>Actions follow the form type. Confirm the intended request with the requester before approving.</Banner>}

          <div className="grid lg:grid-cols-3 gap-4">
            <div className="lg:col-span-2 space-y-4">
              <div className="bg-white rounded-2xl border border-slate-200 p-5 text-xs space-y-2">
                <h4 className="text-sm font-bold text-slate-900">Interpretation <span className="text-[10px] font-normal text-slate-400">plan v{plan.version} &middot; source {plan.source} &middot; prompt {plan.prompt_version}</span></h4>
                <p>{plan.interpretation.scope_summary}</p>
                {plan.interpretation.requested_changes?.map((c: any, i: number) => <p key={i}>Requested change: <code className="bg-slate-100 px-1 rounded">{c.field}</code> → <code className="bg-slate-100 px-1 rounded">{c.new_value}</code></p>)}
                {plan.interpretation.ambiguities?.map((a: string, i: number) => <p key={i} className="text-amber-800">&bull; {a}</p>)}
              </div>

              <div className="bg-white rounded-2xl border border-slate-200 p-5">
                <h4 className="text-sm font-bold text-slate-900 mb-2">Sources considered</h4>
                <div className="grid sm:grid-cols-3 gap-2 text-xs">{plan.plan.sources_considered.map((s: any) => (
                  <div key={s.source} className={`border rounded-lg p-2 ${s.decision === 'SEARCH' ? 'border-sky-200 bg-sky-50' : 'border-slate-200 bg-slate-50'}`}>
                    <strong>{s.source}</strong> <span className="text-[10px] font-bold">{s.decision === 'SEARCH' ? 'SEARCHED' : 'NOT SEARCHED'}</span><p className="text-slate-600 mt-0.5">{s.reason}</p></div>))}</div>
              </div>

              <div className="bg-white rounded-2xl border border-slate-200 p-5">
                <h4 className="text-sm font-bold text-slate-900 mb-2">Steps</h4>
                <ol className="space-y-2 text-xs">{plan.plan.steps.map((s: any) => (
                  <li key={s.order} className="border border-slate-100 rounded-lg p-2"><strong>{s.order}. <code>{s.tool}</code></strong> - {s.purpose}<p className="text-slate-500">Risk: {s.risk}</p><RuleChips ids={s.policy_rules} /></li>))}</ol>
              </div>

              {plan.plan.discarded_proposals?.length > 0 && (
                <Banner kind="info" title={`${plan.plan.discarded_proposals.length} agent proposal(s) discarded by deterministic validation`}>
                  <ul className="list-disc ml-4">{plan.plan.discarded_proposals.map((d: any, i: number) => <li key={i}>{d.what} {d.kind || ''} {d.record_id || d.tool || ''}: {d.reason}</li>)}</ul>
                </Banner>
              )}
            </div>

            <div className="space-y-4">
              <div className="bg-white rounded-2xl border border-slate-200 p-5 text-xs">
                <h4 className="text-sm font-bold text-slate-900 mb-2">Risks</h4>
                <ul className="list-disc ml-4 space-y-1">{plan.plan.overall_risks.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
                {plan.plan.questions_for_reviewer?.length > 0 && <><h4 className="text-sm font-bold text-slate-900 mt-3 mb-1">Questions for the reviewer</h4><ul className="list-disc ml-4 space-y-1">{plan.plan.questions_for_reviewer.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul></>}
              </div>
              {req.status === 'PLAN_REVIEW' && (
                <div className="bg-amber-50 border border-amber-300 rounded-2xl p-4 text-xs space-y-2">
                  <p className="font-bold text-amber-900">Plan awaiting Approver sign-off (POL-APR-1)</p>
                  {user?.role === 'approver' ? (
                    <div className="flex gap-2"><button onClick={() => decide('APPROVED')} className="flex-1 bg-emerald-600 text-white rounded-lg py-2 font-semibold">Approve</button><button onClick={() => decide('REJECTED')} className="flex-1 bg-white border border-slate-300 rounded-lg py-2 font-semibold">Reject</button></div>
                  ) : <p className="text-amber-800">Switch to an Approver account to decide.</p>}
                  <p className="text-amber-800">Review the Inventory tab first: unresolved NEEDS_REVIEW items block approval.</p>
                </div>
              )}
            </div>
          </div>

          <div className="bg-white rounded-2xl border border-slate-200 p-5">
            <h4 className="text-sm font-bold text-slate-900 mb-2">LLM runs</h4>
            {runs.length === 0 ? <p className="text-xs text-slate-400">None</p> : (
              <table className="w-full text-xs"><thead><tr className="text-left text-slate-500"><th className="py-1">Stage</th><th>Model</th><th>Valid</th><th>Tokens in/out</th><th>Latency</th><th>Error</th></tr></thead>
                <tbody>{runs.map((r) => <tr key={r.id} className="border-t border-slate-100"><td className="py-1 font-mono">{r.stage}</td><td>{r.model}</td><td className={r.valid ? 'text-emerald-700' : 'text-red-700 font-bold'}>{r.valid ? 'yes' : 'NO'}</td><td>{r.tokens_in}/{r.tokens_out}</td><td>{Math.round(r.latency_ms)} ms</td><td className="text-red-700 truncate max-w-[16rem]">{r.error}</td></tr>)}</tbody></table>
            )}
          </div>
        </>
      )}
    </div>
  );
};
