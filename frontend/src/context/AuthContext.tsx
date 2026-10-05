import React, { createContext, useContext, useState, useEffect } from 'react';
import { UserProfile } from '../types';
import { apiRequest } from '../api/client';

interface AuthContextType {
  user: UserProfile | null;
  token: string | null;
  testAccounts: UserProfile[];
  login: (username: string, password: string) => Promise<void>;
  switchAccount: (account: UserProfile) => Promise<void>;
  logout: () => void;
  isLoading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [token, setToken] = useState<string | null>(localStorage.getItem('token'));
  const [testAccounts, setTestAccounts] = useState<UserProfile[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  useEffect(() => {
    const onExpired = () => { setToken(null); setUser(null); };
    window.addEventListener('auth-expired', onExpired);
    return () => window.removeEventListener('auth-expired', onExpired);
  }, []);

  useEffect(() => {
    fetchTestAccounts();
    if (token) {
      fetchCurrentUser();
    } else {
      setIsLoading(false);
    }
  }, [token]);

  const fetchTestAccounts = async () => {
    try {
      const accounts = await apiRequest<UserProfile[]>('/auth/test-accounts');
      setTestAccounts(accounts);
    } catch (e) {
      console.error('Failed to fetch test accounts', e);
    }
  };

  const fetchCurrentUser = async () => {
    try {
      const me = await apiRequest<UserProfile>('/auth/me');
      setUser(me);
    } catch {
      logout();
    } finally {
      setIsLoading(false);
    }
  };

  const login = async (username: string, password: string) => {
    setIsLoading(true);
    try {
      const res = await apiRequest<{ access_token: string; user: UserProfile }>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password })
      });
      localStorage.setItem('token', res.access_token);
      setToken(res.access_token);
      setUser(res.user);
    } finally {
      setIsLoading(false);
    }
  };

  const switchAccount = async (target: UserProfile) => {
    await login(target.username, target.sample_password || '');
  };

  const logout = () => {
    localStorage.removeItem('token');
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, token, testAccounts, login, switchAccount, logout, isLoading }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
};
