import React, { useState } from 'react';
import { Shield, LogIn } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useUi } from '../components/Ui';

export const Login: React.FC = () => {
  const { login, testAccounts, isLoading } = useAuth();
  const { toast } = useUi();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState('');

  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setErr('');
    if (!username.trim() || !password) { setErr('Username and password are required.'); return; }
    try { await login(username.trim(), password); toast.success('Signed in'); }
    catch (ex: any) { setErr(ex.message || 'Sign-in failed'); }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
      <div className="w-full max-w-3xl grid md:grid-cols-2 gap-6">
        <form onSubmit={submit} className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 space-y-4" noValidate>
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-lg bg-sky-600 flex items-center justify-center text-white"><Shield className="w-6 h-6" /></div>
            <div><h1 className="text-lg font-bold text-slate-900">Privacy Request Workbench</h1><p className="text-xs text-sky-600 font-semibold uppercase tracking-wider">Acme Policy v1.0 (mock)</p></div>
          </div>
          <div>
            <label htmlFor="u" className="block text-xs font-semibold text-slate-600 mb-1">Username</label>
            <input id="u" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username"
              className="w-full border border-slate-300 rounded-lg p-2 text-sm focus:ring-2 focus:ring-sky-500 outline-none" />
          </div>
          <div>
            <label htmlFor="p" className="block text-xs font-semibold text-slate-600 mb-1">Password</label>
            <input id="p" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password"
              className="w-full border border-slate-300 rounded-lg p-2 text-sm focus:ring-2 focus:ring-sky-500 outline-none" />
          </div>
          {err && <p className="text-xs text-red-600" role="alert">{err}</p>}
          <button disabled={isLoading} className="w-full flex items-center justify-center space-x-2 bg-sky-600 hover:bg-sky-700 disabled:opacity-50 text-white font-semibold text-sm rounded-lg py-2.5">
            <LogIn className="w-4 h-4" /><span>{isLoading ? 'Signing in...' : 'Sign in'}</span>
          </button>
          <p className="text-[11px] text-slate-500 leading-snug">This tool supports internal handling of privacy requests according to the supplied organizational policy. It does not provide legal advice and does not certify legal compliance. All outcomes require human review.</p>
        </form>

        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6">
          <h2 className="text-sm font-bold text-slate-900">Reviewer test accounts</h2>
          <p className="text-xs text-slate-500 mb-3">Seeded mock accounts only. Click to fill the form.</p>
          <div className="space-y-2">
            {testAccounts.length === 0 && <p className="text-xs text-slate-400">No test accounts listed.</p>}
            {testAccounts.map((a) => (
              <button key={a.id} type="button" onClick={() => { setUsername(a.username); setPassword(a.sample_password || ''); }}
                className="w-full text-left border border-slate-200 hover:border-sky-400 rounded-lg p-2.5 text-xs">
                <span className="font-semibold text-slate-800">{a.full_name}</span>
                <span className="ml-2 px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 uppercase font-bold text-[10px]">{a.role}</span>
                <span className="block font-mono text-slate-500 mt-0.5">{a.username}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
