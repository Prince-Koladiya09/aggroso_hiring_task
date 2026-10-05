import React, { useEffect, useState } from 'react';
import { useUi } from './Ui';
import { useAuth } from '../context/AuthContext';
import { Shield, User, RefreshCw, AlertTriangle, CheckCircle, ExternalLink, Settings } from 'lucide-react';
import { apiRequest } from '../api/client';

interface HeaderProps {
  currentTab: string;
  setCurrentTab: (tab: string) => void;
}

export const Header: React.FC<HeaderProps> = ({ currentTab, setCurrentTab }) => {
  const { user, testAccounts, switchAccount, logout } = useAuth();
  const { toast, confirm } = useUi();
  const [faultInjection, setFaultInjection] = useState(false);
  const [llmOutage, setLlmOutage] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [showRoleMenu, setShowRoleMenu] = useState(false);

  useEffect(() => {
    apiRequest('/system/flags').then((f: any) => {
      setFaultInjection(!!f.fault_injection_enabled);
      setLlmOutage(!!f.simulate_llm_outage);
    }).catch(() => {});
  }, [user?.id]);

  const canToggle = user?.role === 'analyst' || user?.role === 'approver';

  const handleToggleFault = async () => {
    try {
      const next = !faultInjection;
      await apiRequest(`/system/toggle-fault-injection?enabled=${next}`, { method: 'POST' });
      setFaultInjection(next);
      toast.info(next ? 'Fault simulation ON: the next execution will fail once so you can demonstrate safe retry.' : 'Fault simulation OFF.');
    } catch (e: any) {
      toast.error(`Could not toggle fault simulation: ${e.message}`);
    }
  };

  const handleToggleOutage = async () => {
    try {
      const next = !llmOutage;
      await apiRequest(`/system/toggle-llm-outage?enabled=${next}`, { method: 'POST' });
      setLlmOutage(next);
      toast.info(next ? 'LLM outage simulated: planning will use the deterministic fallback planner (S10).' : 'LLM available again.');
    } catch (e: any) {
      toast.error(`Could not toggle LLM outage: ${e.message}`);
    }
  };

  const handleResetDemo = async () => {
    const ok = await confirm({
      title: 'Reset demo data?',
      description: 'This is a demo-only control available to Approvers.',
      lines: ['All requests, plans, approvals, actions and audit events are deleted', 'Mock profiles, tickets and activity logs are re-seeded (scenarios S1-S10)', 'The audit hash chain restarts from a new genesis event'],
      confirmLabel: 'Reset demo data', danger: true,
    });
    if (ok === null) return;
    setResetting(true);
    try {
      await apiRequest('/system/reset-demo', { method: 'POST' });
      toast.success('Demo dataset reset.');
      setTimeout(() => window.location.reload(), 600);
    } catch (e: any) {
      toast.error(`Reset failed: ${e.message}`);
    } finally {
      setResetting(false);
    }
  };

  return (
    <header className="bg-white border-b border-slate-200 sticky top-0 z-30 shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo & Navigation */}
          <div className="flex items-center space-x-8">
            <div className="flex items-center space-x-3 cursor-pointer" onClick={() => setCurrentTab('dashboard')}>
              <div className="w-10 h-10 rounded-lg bg-sky-600 flex items-center justify-center text-white shadow-md">
                <Shield className="w-6 h-6" />
              </div>
              <div>
                <span className="text-lg font-bold text-slate-900 tracking-tight block">Privacy Fulfilment</span>
                <span className="text-xs text-sky-600 font-semibold tracking-wider uppercase block">Acme Policy v1.0</span>
              </div>
            </div>

            <nav className="hidden md:flex space-x-1">
              <button
                onClick={() => setCurrentTab('dashboard')}
                className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  currentTab === 'dashboard'
                    ? 'bg-sky-50 text-sky-700'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
                }`}
              >
                Requests Dashboard
              </button>

              <button
                onClick={() => setCurrentTab('approvals')}
                className={`px-3 py-2 rounded-md text-sm font-medium transition-colors flex items-center space-x-1 ${
                  currentTab === 'approvals'
                    ? 'bg-sky-50 text-sky-700'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
                }`}
              >
                <span>Approvals Queue</span>
                {user?.role === 'approver' && (
                  <span className="w-2 h-2 rounded-full bg-amber-500 inline-block ml-1"></span>
                )}
              </button>

              <button
                onClick={() => setCurrentTab('policy')}
                className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  currentTab === 'policy'
                    ? 'bg-sky-50 text-sky-700'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
                }`}
              >
                Organizational Policy
              </button>
            </nav>
          </div>

          {/* Right Tools & Role Switcher */}
          <div className="flex items-center space-x-3">
            {/* Demo Controls */}
            <div className="hidden sm:flex items-center space-x-2 bg-slate-50 border border-slate-200 rounded-lg px-2.5 py-1 text-xs">
              <button
                onClick={handleToggleFault}
                title="Simulates hardware or network fault on next execution to test idempotent retry"
                className={`flex items-center space-x-1 px-2 py-1 rounded font-medium transition-colors ${
                  faultInjection
                    ? 'bg-amber-100 text-amber-800 border border-amber-300'
                    : 'bg-white text-slate-600 hover:bg-slate-100 border border-slate-200'
                }`}
              >
                <AlertTriangle className="w-3.5 h-3.5" />
                <span>Fault Sim: {faultInjection ? 'ON' : 'OFF'}</span>
              </button>

              <button
                onClick={handleToggleOutage}
                disabled={!canToggle}
                title="Simulates the LLM being unavailable so the deterministic fallback planner is used (S10)"
                className={`flex items-center space-x-1 px-2 py-1 rounded font-medium transition-colors ${
                  llmOutage ? 'bg-amber-100 text-amber-800 border border-amber-300' : 'bg-white text-slate-600 hover:bg-slate-100 border border-slate-200'
                }`}
              >
                <AlertTriangle className="w-3.5 h-3.5" />
                <span>LLM Outage: {llmOutage ? 'ON' : 'OFF'}</span>
              </button>

              {user?.role === 'approver' && (
                <button
                  onClick={handleResetDemo}
                  disabled={resetting}
                  title="Resets database to initial seed scenarios (S1-S10)"
                  className="flex items-center space-x-1 px-2 py-1 rounded bg-white text-slate-600 hover:bg-slate-100 border border-slate-200 font-medium"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${resetting ? 'animate-spin' : ''}`} />
                  <span>Reset Demo</span>
                </button>
              )}
            </div>

            {/* User & Role Switcher */}
            <div className="relative">
              <button
                onClick={() => setShowRoleMenu(!showRoleMenu)}
                className="flex items-center space-x-2 pl-3 pr-2 py-1.5 rounded-lg border border-slate-200 hover:border-slate-300 bg-white transition-all text-left shadow-sm"
              >
                <div className="w-7 h-7 rounded-full bg-slate-100 flex items-center justify-center text-slate-600 font-semibold text-xs border border-slate-200">
                  {user ? user.username.charAt(0).toUpperCase() : '?'}
                </div>
                <div className="hidden md:block">
                  <span className="text-xs font-semibold text-slate-900 block leading-tight">
                    {user?.full_name || 'Not logged in'}
                  </span>
                  <span className={`text-[10px] uppercase font-bold tracking-wider inline-block px-1.5 py-0.2 rounded ${
                    user?.role === 'approver' ? 'bg-amber-100 text-amber-800' :
                    user?.role === 'auditor' ? 'bg-purple-100 text-purple-800' :
                    'bg-sky-100 text-sky-800'
                  }`}>
                    {user?.role || 'Guest'}
                  </span>
                </div>
              </button>

              {/* Role Switcher Dropdown */}
              {showRoleMenu && (
                <div className="absolute right-0 mt-2 w-64 bg-white rounded-xl shadow-xl border border-slate-200 py-2 z-50 animate-in fade-in slide-in-from-top-1 duration-150">
                  <div className="px-3 py-2 border-b border-slate-100">
                    <p className="text-xs font-bold text-slate-500 uppercase tracking-wider">Fast Role Switcher (Reviewer)</p>
                    <p className="text-[11px] text-slate-400 mt-0.5">Switch persona to test permissions & four-eyes rule</p>
                  </div>
                  <div className="py-1">
                    {testAccounts.map((acc) => (
                      <button
                        key={acc.id}
                        onClick={() => {
                          switchAccount(acc);
                          setShowRoleMenu(false);
                        }}
                        className={`w-full text-left px-3 py-2 flex items-center justify-between hover:bg-slate-50 text-xs transition-colors ${
                          user?.username === acc.username ? 'bg-sky-50 font-bold text-sky-900' : 'text-slate-700'
                        }`}
                      >
                        <div>
                          <span className="block font-medium">{acc.full_name}</span>
                          <span className="text-[11px] text-slate-500 font-mono">{acc.username}</span>
                        </div>
                        <span className={`text-[10px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded ${
                          acc.role === 'approver' ? 'bg-amber-100 text-amber-800' :
                          acc.role === 'auditor' ? 'bg-purple-100 text-purple-800' :
                          'bg-sky-100 text-sky-800'
                        }`}>
                          {acc.role}
                        </span>
                      </button>
                    ))}
                  </div>
                  <div className="border-t border-slate-100 px-3 py-2">
                    <button onClick={() => { setShowRoleMenu(false); logout(); }} className="text-xs font-semibold text-red-600 hover:underline">Sign out</button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </header>
  );
};
