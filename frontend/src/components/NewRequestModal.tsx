import React, { useState } from 'react';
import { X, Sparkles, AlertCircle } from 'lucide-react';
import { apiRequest } from '../api/client';
import { RequestType } from '../types';

interface NewRequestModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (newReqId: string) => void;
}

export const NewRequestModal: React.FC<NewRequestModalProps> = ({ isOpen, onClose, onSuccess }) => {
  const [type, setType] = useState<RequestType>('ACCESS');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [accountId, setAccountId] = useState('');
  const [relationship, setRelationship] = useState('self');
  const [description, setDescription] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [receivedAt, setReceivedAt] = useState('');
  const [authOnFile, setAuthOnFile] = useState(false);

  if (!isOpen) return null;

  const handlePreFill = (scenarioKey: string) => {
    switch (scenarioKey) {
      case 's1':
        setType('ACCESS');
        setName('John Doe');
        setEmail('john.doe@example.com');
        setAccountId('ACC-1001');
        setRelationship('self');
        setDescription('I would like to receive an export copy of all personal data held across all systems.');
        break;
      case 's2':
        setType('ACCESS');
        setName('Jane Smith');
        setEmail('jane.smith@example.com');
        setAccountId(''); // Intentionally missing account ID for S2!
        setRelationship('self');
        setDescription('Please export my profile and history.');
        break;
      case 's3':
        setType('CORRECTION');
        setName('Robert Taylor');
        setEmail('robert.taylor@example.com');
        setAccountId('ACC-1003');
        setRelationship('self');
        setDescription('Please update my phone number to +1-555-099-7788 in your profile database.');
        break;
      case 's4':
        setType('DELETION');
        setName('Michael Brown');
        setEmail('michael.brown@example.com');
        setAccountId('ACC-1004');
        setRelationship('self');
        setDescription('Please delete all my accounts, support records, and activity logs permanently.');
        break;
      case 's6':
        setType('ACCESS');
        setName('Emily Davis');
        setEmail('emily.davis@example.com');
        setAccountId('ACC-1007');
        setRelationship('self');
        setDescription('Export my support communications and logs.');
        break;
      case 's7':
        setType('DELETION');
        setName('Carlos Gomez');
        setEmail('carlos.gomez@example.com');
        setAccountId('ACC-1008');
        setRelationship('self');
        setDescription('Erase my account details.');
        break;
      case 's8':
        setType('ACCESS');
        setName('Alex Green');
        setEmail('alex.green.work@corp.com'); // verification step: submit name only -> ambiguous (two Alex Greens)
        setAccountId('ACC-1009');
        setRelationship('self');
        setDescription('Export all records for Alex Green.');
        break;
      default:
        break;
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const fe: Record<string, string> = {};
    if (name.trim().length < 2) fe.requester_name = 'Name is required (min. 2 characters).';
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) fe.requester_email = 'Enter a valid e-mail address.';
    if (description.trim().length < 5) fe.description = 'Describe the request (min. 5 characters).';
    if (receivedAt && new Date(receivedAt) > new Date()) fe.received_at = 'Received date cannot be in the future.';
    setFieldErrors(fe);
    if (Object.keys(fe).length) { setError('Please fix the highlighted fields.'); return; }

    setIsSubmitting(true);
    setError(null);

    try {
      const res = await apiRequest('/requests', {
        method: 'POST',
        body: JSON.stringify({
          type,
          requester_name: name,
          requester_email: email,
          account_id: accountId || null,
          relationship,
          description,
          authorization_on_file: relationship === 'authorized_agent' ? authOnFile : false,
          received_at: receivedAt ? new Date(receivedAt + 'T00:00:00Z').toISOString() : null
        })
      });
      onSuccess(res.id);
      onClose();
    } catch (err: any) {
      const m: Record<string, string> = {};
      (err.fields || []).forEach((f: any) => { if (f.field) m[f.field] = f.message; });
      setFieldErrors(m);
      setError(err.message || 'Failed to create request');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/50 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl max-w-2xl w-full shadow-2xl border border-slate-200 overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50">
          <div>
            <h2 className="text-lg font-bold text-slate-900">Create New Privacy Request</h2>
            <p className="text-xs text-slate-500">Initiate intake per Acme Privacy Policy v1.0</p>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-slate-200 text-slate-400 hover:text-slate-600 transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Quick Pre-fill Toolbar */}
        <div className="px-6 py-2.5 bg-sky-50/70 border-b border-sky-100 flex items-center space-x-2 overflow-x-auto text-xs">
          <span className="font-bold text-sky-900 flex items-center space-x-1 shrink-0">
            <Sparkles className="w-3.5 h-3.5 text-sky-600" />
            <span>Pre-fill Scenario:</span>
          </span>
          <button type="button" onClick={() => handlePreFill('s1')} className="px-2 py-1 bg-white hover:bg-sky-100 text-sky-800 rounded border border-sky-200 shrink-0 font-medium">S1 (Access Happy)</button>
          <button type="button" onClick={() => handlePreFill('s2')} className="px-2 py-1 bg-white hover:bg-sky-100 text-sky-800 rounded border border-sky-200 shrink-0 font-medium">S2 (Missing ID)</button>
          <button type="button" onClick={() => handlePreFill('s3')} className="px-2 py-1 bg-white hover:bg-sky-100 text-sky-800 rounded border border-sky-200 shrink-0 font-medium">S3 (Correction)</button>
          <button type="button" onClick={() => handlePreFill('s4')} className="px-2 py-1 bg-white hover:bg-sky-100 text-sky-800 rounded border border-sky-200 shrink-0 font-medium">S4 (Legal Hold)</button>
          <button type="button" onClick={() => handlePreFill('s6')} className="px-2 py-1 bg-white hover:bg-sky-100 text-sky-800 rounded border border-sky-200 shrink-0 font-medium">S6 (3rd Party PII)</button>
          <button type="button" onClick={() => handlePreFill('s7')} className="px-2 py-1 bg-white hover:bg-sky-100 text-sky-800 rounded border border-sky-200 shrink-0 font-medium">S7 (Prompt Inject)</button>
          <button type="button" onClick={() => handlePreFill('s8')} className="px-2 py-1 bg-white hover:bg-sky-100 text-sky-800 rounded border border-sky-200 shrink-0 font-medium">S8 (Ambiguity)</button>
        </div>

        <form noValidate onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-xs flex items-center space-x-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">Request Type *</label>
              <select
                value={type}
                onChange={(e) => setType(e.target.value as RequestType)}
                className="w-full text-xs rounded-lg border-slate-300 focus:ring-sky-500 focus:border-sky-500 p-2.5 bg-white border"
              >
                <option value="ACCESS">ACCESS (Export Data)</option>
                <option value="CORRECTION">CORRECTION (Update Fields)</option>
                <option value="DELETION">DELETION (Erase Data)</option>
                <option value="UNSUPPORTED">UNSUPPORTED (Objection/Portability/Other)</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">Relationship *</label>
              <select
                value={relationship}
                onChange={(e) => setRelationship(e.target.value)}
                className="w-full text-xs rounded-lg border-slate-300 focus:ring-sky-500 focus:border-sky-500 p-2.5 bg-white border"
              >
                <option value="self">Data Subject (Self)</option>
                <option value="authorized_agent">Authorized Agent (Requires Authorization)</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">Requester Full Name *</label>
              <input
                type="text"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. John Doe"
                className="w-full text-xs rounded-lg border-slate-300 focus:ring-sky-500 focus:border-sky-500 p-2.5 border"
              />
              {fieldErrors.requester_name && <p className="text-[11px] text-red-600 mt-1">{fieldErrors.requester_name}</p>}
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">Requester Email *</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="e.g. john.doe@example.com"
                className="w-full text-xs rounded-lg border-slate-300 focus:ring-sky-500 focus:border-sky-500 p-2.5 border"
              />
              {fieldErrors.requester_email && <p className="text-[11px] text-red-600 mt-1">{fieldErrors.requester_email}</p>}
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">Account ID (Optional for intake)</label>
              <input
                type="text"
                value={accountId}
                onChange={(e) => setAccountId(e.target.value)}
                placeholder="e.g. ACC-1001"
                className="w-full text-xs rounded-lg border-slate-300 focus:ring-sky-500 focus:border-sky-500 p-2.5 border"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">Free-text Description / Request Body *</label>
            <textarea
              required
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="State what the subject is requesting..."
              className="w-full text-xs rounded-lg border-slate-300 focus:ring-sky-500 focus:border-sky-500 p-2.5 border"
            />
            {fieldErrors.description && <p className="text-[11px] text-red-600 mt-1">{fieldErrors.description}</p>}
            <p className="text-[11px] text-slate-400 mt-1">AI agent will interpret this free-text prompt to extract true intent, fields, and candidate data sources.</p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="received" className="block text-xs font-semibold text-slate-700 mb-1">Date received (optional, defaults to today)</label>
              <input id="received" type="date" value={receivedAt} max={new Date().toISOString().slice(0, 10)} onChange={(e) => setReceivedAt(e.target.value)}
                className="w-full text-xs rounded-lg border-slate-300 p-2.5 border" />
              {fieldErrors.received_at && <p className="text-[11px] text-red-600 mt-1">{fieldErrors.received_at}</p>}
              <p className="text-[11px] text-slate-400 mt-1">The due date is computed from this date (POL-SLA-1).</p>
            </div>
            {relationship === 'authorized_agent' && (
              <label className="flex items-start space-x-2 text-xs text-slate-700 mt-5">
                <input type="checkbox" checked={authOnFile} onChange={(e) => setAuthOnFile(e.target.checked)} className="mt-0.5" />
                <span>Authorization is on file for this agent (POL-ID-3)</span>
              </label>
            )}
          </div>

          <div className="flex justify-end space-x-3 pt-3 border-t border-slate-100">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 border border-slate-300 text-xs font-semibold rounded-lg text-slate-700 hover:bg-slate-50 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-4 py-2 bg-sky-600 text-xs font-semibold rounded-lg text-white hover:bg-sky-700 disabled:opacity-50 transition-colors shadow-sm"
            >
              {isSubmitting ? 'Creating Request...' : 'Create Request'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
