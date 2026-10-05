import React, { useState } from 'react';
import { AuthProvider, useAuth } from './context/AuthContext';
import { UiProvider } from './components/Ui';
import { Login } from './pages/Login';
import { Header } from './components/Header';
import { Footer } from './components/Footer';
import { Dashboard } from './pages/Dashboard';
import { RequestDetail } from './pages/RequestDetail';
import { ApprovalsQueue } from './pages/ApprovalsQueue';
import { PolicyViewer } from './pages/PolicyViewer';

export const AppContent: React.FC = () => {
  const { user, isLoading } = useAuth();
  const [currentTab, setCurrentTab] = useState<'dashboard' | 'approvals' | 'policy' | 'detail'>('dashboard');
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>(null);

  const handleSelectRequest = (id: string) => {
    setSelectedRequestId(id);
    setCurrentTab('detail');
  };

  const handleBackToDashboard = () => {
    setSelectedRequestId(null);
    setCurrentTab('dashboard');
  };

  if (!user) return isLoading ? <div className="min-h-screen flex items-center justify-center text-sm text-slate-500">Loading...</div> : <Login />;

  return (
    <div className="min-h-screen flex flex-col bg-slate-50">
      <Header
        currentTab={currentTab}
        setCurrentTab={(tab) => {
          setSelectedRequestId(null);
          setCurrentTab(tab as any);
        }}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {currentTab === 'dashboard' && <Dashboard onSelectRequest={handleSelectRequest} />}
        {currentTab === 'approvals' && <ApprovalsQueue onSelectRequest={handleSelectRequest} />}
        {currentTab === 'policy' && <PolicyViewer />}
        {currentTab === 'detail' && selectedRequestId && (
          <RequestDetail requestId={selectedRequestId} onBack={handleBackToDashboard} />
        )}
      </main>

      <Footer />
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <AuthProvider>
      <UiProvider>
        <AppContent />
      </UiProvider>
    </AuthProvider>
  );
};

export default App;
