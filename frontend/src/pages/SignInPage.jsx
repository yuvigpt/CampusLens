import { useState } from 'react';
import { User, Mail, Lock, Eye, EyeOff, ArrowRight, Loader2, ChevronDown, Sparkles } from 'lucide-react';

import { useAuth } from '../auth.jsx';
import { ErrorBanner, Notice } from '../components/ui.jsx';
import { IITKLogo, GoogleLogo, CampusLensIcon } from '../components/BrandIcons.jsx';

// Authorized admin emails that can unlock the Faculty and Campus Administrator portals
const AUTHORIZED_ADMIN_EMAILS = [
  'yuvrajkrgupta87@gmail.com',
  'admin@iitk.ac.in',
  'campuslens.admin@gmail.com',
  'director@iitk.ac.in',
];

export function isAuthorizedAdminEmail(emailStr) {
  if (!emailStr) return false;
  const clean = emailStr.trim().toLowerCase();
  const configuredAdmin = (import.meta.env.VITE_ADMIN_EMAIL || '').trim().toLowerCase();
  if (configuredAdmin && clean === configuredAdmin) return true;
  return (
    AUTHORIZED_ADMIN_EMAILS.includes(clean) ||
    clean.startsWith('admin@') ||
    clean.includes('admin') ||
    clean.startsWith('director@') ||
    clean.startsWith('dean@')
  );
}

/**
 * Sign in / sign up page with clean, non-overlapping IIT Kanpur campus imagery.
 */
export default function SignInPage() {
  const { signIn, signUp, configured, loading } = useAuth();

  const [mode, setMode] = useState(() => (window.location.hash === '#/signin' ? 'signin' : 'signup'));
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [role, setRole] = useState('Student');
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [info, setInfo] = useState(null);

  const isStaffAdmin = isAuthorizedAdminEmail(email);

  function handleEmailChange(e) {
    const val = e.target.value;
    setEmail(val);
    if (!isAuthorizedAdminEmail(val) && role !== 'Student') {
      setRole('Student');
    }
  }

  async function onSubmit(event) {
    event.preventDefault();
    if (busy || loading) return;

    if (!email.trim() || !password) {
      setError('Please enter your campus email address and password.');
      return;
    }

    if (role !== 'Student' && !isAuthorizedAdminEmail(email)) {
      setError('Access restricted: That email is not authorized for Faculty or Campus Administrator access. Please select Student.');
      setRole('Student');
      return;
    }

    if (mode === 'signup' && password !== confirmPassword) {
      setError('Passwords do not match. Please re-enter both passwords.');
      return;
    }

    if (mode === 'signup' && password.length < 6) {
      setError('Password must be at least 6 characters.');
      return;
    }

    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      if (mode === 'signin') {
        const result = await signIn(email, password);
        if (result.error) {
          setError(result.error);
        } else {
          // Store user name from user_metadata or backend profile
          if (result.data?.session?.user) {
            const metaName = result.data.session.user.user_metadata?.full_name || result.me?.full_name;
            if (metaName) {
              localStorage.setItem('cl_user_name', metaName.trim());
              const parts = metaName.trim().split(/\s+/);
              localStorage.setItem('cl_first_name', parts[0] || '');
              localStorage.setItem('cl_last_name', parts.slice(1).join(' ') || '');
            }
          }
          // The backend-confirmed role decides the landing page: admins get
          // the operations dashboard, everyone else the student home.
          window.location.hash = result.me?.role === 'admin' ? '#/dashboard' : '#/';
        }
      } else {
        if (fullName.trim()) {
          localStorage.setItem('cl_user_name', fullName.trim());
          const parts = fullName.trim().split(/\s+/);
          localStorage.setItem('cl_first_name', parts[0] || '');
          localStorage.setItem('cl_last_name', parts.slice(1).join(' ') || '');
        }
        const result = await signUp(email, password, fullName);
        if (result.error) {
          setError(result.error);
        } else if (result.data?.session) {
          setInfo('Account created and signed in successfully!');
          window.location.hash = result.me?.role === 'admin' ? '#/dashboard' : '#/';
        } else {
          setInfo('Account created! Please check your email to confirm, then sign in.');
        }
      }
    } catch (caught) {
      setError(caught?.message || 'Authentication failed.');
    } finally {
      setBusy(false);
    }
  }

  function handleGoogleAuth() {
    setError('Google Single Sign-On for @iitk.ac.in is being enabled by the campus IT center.');
  }

  return (
    <div className="min-h-screen w-full flex flex-col lg:flex-row bg-slate-100 font-sans text-slate-900">
      {/* ============================================================ */}
      {/* LEFT COLUMN: Majestic IIT Kanpur Campus Visual Backdrop       */}
      {/* ============================================================ */}
      <div className="relative w-full lg:w-1/2 min-h-[420px] lg:min-h-screen bg-[#070c18] text-white flex flex-col justify-between p-8 sm:p-12 lg:p-16 overflow-hidden select-none">
        {/* Full-bleed authentic IIT Kanpur Campus photograph */}
        <div 
          className="absolute inset-0 z-0 bg-cover bg-center bg-no-repeat pointer-events-none"
          style={{
            backgroundImage: `url('/iitk_authentic_campus.jpg')`
          }}
        />
        {/* Subtle dark gradient overlay to ensure perfect typography legibility without muddying the image */}
        <div className="absolute inset-0 z-0 bg-gradient-to-t from-[#070c18]/95 via-[#0b1329]/70 to-[#070c18]/85 pointer-events-none" />

        {/* Top: Logo Header */}
        <div className="relative z-10 flex items-center justify-between gap-4">
          <a href="#/" aria-label="CampusLens Home" className="flex items-center gap-3 group">
            <CampusLensIcon className="w-10 h-10 ring-2 ring-indigo-400/40 shadow-lg shadow-indigo-500/30 group-hover:scale-105 transition-transform" />
            <div className="flex flex-col">
              <span className="text-xl font-bold tracking-tight text-white flex items-center gap-1.5 group-hover:text-indigo-200 transition-colors">
                CampusLens
              </span>
              <span className="text-xs text-indigo-300 font-medium tracking-wide">
                Better Campus. Together
              </span>
            </div>
          </a>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-black/40 backdrop-blur-md border border-white/15 text-xs text-slate-200 shadow-sm">
            <img src="/iitk-logo.svg" alt="IITK Seal" className="w-5 h-5 object-contain" />
            <span className="font-semibold">IIT Kanpur</span>
          </div>
        </div>

        {/* Center: Main Tagline & Description */}
        <div className="relative z-10 max-w-lg my-12 lg:my-auto">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/25 text-indigo-200 border border-indigo-400/30 text-xs font-semibold mb-4 backdrop-blur-md">
            <Sparkles className="w-3.5 h-3.5 text-indigo-300" />
            <span>Official Student &amp; Campus Portal</span>
          </div>

          <h1 className="text-3xl sm:text-4xl lg:text-5xl font-black text-white tracking-tight leading-[1.12] mb-4 drop-shadow-md">
            Help make IIT Kanpur <br />
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-white via-indigo-100 to-indigo-300">
              a better place.
            </span>
          </h1>

          <p className="text-slate-200 text-sm sm:text-base font-normal leading-relaxed drop-shadow">
            Report, track, and resolve campus issues efficiently. <br className="hidden sm:inline" />
            Connect with your community today.
          </p>
        </div>

        {/* Bottom: Powered by IIT Kanpur Banner */}
        <div className="relative z-10 flex items-center gap-3 pt-6 border-t border-white/15">
          <img src="/iitk-logo.svg" alt="IIT Kanpur Seal" className="w-9 h-9 object-contain drop-shadow" />
          <div className="flex flex-col text-left">
            <span className="text-[11px] uppercase tracking-wider text-slate-300 font-medium">Powered by</span>
            <span className="text-sm font-semibold text-white tracking-tight">Indian Institute of Technology Kanpur</span>
          </div>
        </div>
      </div>

      {/* ============================================================ */}
      {/* RIGHT COLUMN: Clean, Elegant Account Form                    */}
      {/* ============================================================ */}
      <div className="w-full lg:w-1/2 flex items-center justify-center p-6 sm:p-10 lg:p-14 bg-white overflow-y-auto">
        <div className="w-full max-w-md flex flex-col">
          {/* Header Seal & Brand (Perfect Center Alignment) */}
          <div className="flex flex-col items-center justify-center text-center mb-6">
            <a href="#/" aria-label="Return to CampusLens Home" className="flex items-center justify-center gap-3 mb-2.5 group">
              <img
                src="/campuslens-icon.png"
                alt="CampusLens Logo"
                className="w-12 h-12 object-contain drop-shadow-sm group-hover:scale-105 transition-transform"
              />
              <div className="h-7 w-px bg-slate-200" />
              <img
                src="/iitk-logo.svg"
                alt="IIT Kanpur Seal"
                className="w-11 h-11 object-contain drop-shadow-sm group-hover:scale-105 transition-transform"
              />
            </a>
            <span className="text-xl font-black tracking-tight text-slate-900 leading-tight">CampusLens</span>
            <span className="text-xs font-semibold text-slate-500">Indian Institute of Technology Kanpur</span>
          </div>

          {/* Form Title & Subtitle */}
          <div className="mb-6 text-center">
            <h2 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">
              {mode === 'signup' ? 'Create an account' : 'Welcome back'}
            </h2>
            <p className="text-sm text-slate-500 mt-1 max-w-sm mx-auto">
              {mode === 'signup' 
                ? 'Get started by signing up with your campus email address.' 
                : 'Enter your campus credentials to access your student dashboard.'}
            </p>
          </div>

          {!configured && (
            <div className="mb-4">
              <Notice tone="warning" title="Authentication setup required">
                <p className="text-xs">
                  Configure <code>VITE_SUPABASE_URL</code> in <code>frontend/.env</code> to activate live login.
                </p>
              </Notice>
            </div>
          )}

          <ErrorBanner
            title="Authentication notice"
            message={error}
            onRetry={() => setError(null)}
            retryLabel="Dismiss"
          />

          {info && (
            <div className="mb-4">
              <Notice tone="success">
                <p className="text-sm">{info}</p>
              </Notice>
            </div>
          )}

          <form onSubmit={onSubmit} className="flex flex-col gap-4 mt-1" noValidate>
            {/* FULL NAME (Signup mode) */}
            {mode === 'signup' && (
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-bold uppercase tracking-wider text-slate-700" htmlFor="fullName">
                  Full Name
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-400">
                    <User className="w-4 h-4" />
                  </div>
                  <input
                    id="fullName"
                    type="text"
                    value={fullName}
                    placeholder="e.g., Yuvraj Gupta"
                    className="w-full pl-10 pr-4 py-2.5 bg-white border border-slate-300 rounded-xl text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-shadow"
                    onChange={(e) => setFullName(e.target.value)}
                  />
                </div>
              </div>
            )}

            {/* PORTAL ROLE SELECTION (Student, Faculty, Staff/Admin) */}
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-700">
                  Select Portal Role
                </span>
                {!isStaffAdmin ? (
                  <span className="text-[11px] font-semibold text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-full flex items-center gap-1">
                    <Lock className="w-3 h-3 text-amber-600" />
                    Admin/Faculty Protected
                  </span>
                ) : (
                  <span className="text-[11px] font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-full flex items-center gap-1">
                    Admin Authorized
                  </span>
                )}
              </div>

              <div className="grid grid-cols-3 gap-2 p-1 bg-slate-100 rounded-xl border border-slate-200">
                {/* 1. Student */}
                <button
                  type="button"
                  onClick={() => {
                    setRole('Student');
                    setError(null);
                  }}
                  className={`py-2 px-2 text-xs font-bold rounded-lg transition-all flex items-center justify-center gap-1.5 ${
                    role === 'Student'
                      ? 'bg-white text-indigo-600 shadow-sm border border-slate-200/80'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  <User className="w-3.5 h-3.5" />
                  <span>Student</span>
                </button>

                {/* 2. Faculty */}
                <button
                  type="button"
                  onClick={() => {
                    if (!isStaffAdmin) {
                      setError('Access restricted: Faculty portal requires an authorized administrator or faculty email address.');
                      setRole('Student');
                    } else {
                      setRole('Faculty / Staff');
                      setError(null);
                    }
                  }}
                  title={!isStaffAdmin ? 'Restricted to authorized administrator emails' : 'Faculty Access'}
                  className={`py-2 px-2 text-xs font-bold rounded-lg transition-all flex items-center justify-center gap-1.5 ${
                    role === 'Faculty / Staff' && isStaffAdmin
                      ? 'bg-white text-indigo-600 shadow-sm border border-slate-200/80'
                      : !isStaffAdmin
                      ? 'text-slate-400 bg-slate-200/50 cursor-not-allowed opacity-75'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  <span>Faculty</span>
                  {!isStaffAdmin && <Lock className="w-3 h-3 text-slate-400" />}
                </button>

                {/* 3. Staff / Administrator */}
                <button
                  type="button"
                  onClick={() => {
                    if (!isStaffAdmin) {
                      setError('Access restricted: Campus Administrator portal requires an authorized administrator email.');
                      setRole('Student');
                    } else {
                      setRole('Campus Administrator');
                      setError(null);
                    }
                  }}
                  title={!isStaffAdmin ? 'Restricted to authorized administrator emails' : 'Campus Administrator Access'}
                  className={`py-2 px-2 text-xs font-bold rounded-lg transition-all flex items-center justify-center gap-1.5 ${
                    role === 'Campus Administrator' && isStaffAdmin
                      ? 'bg-white text-indigo-600 shadow-sm border border-slate-200/80'
                      : !isStaffAdmin
                      ? 'text-slate-400 bg-slate-200/50 cursor-not-allowed opacity-75'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  <span className="truncate">Admin / Staff</span>
                  {!isStaffAdmin && <Lock className="w-3 h-3 text-slate-400" />}
                </button>
              </div>
            </div>

            {/* CAMPUS EMAIL ADDRESS */}
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-bold uppercase tracking-wider text-slate-700" htmlFor="email">
                Email address
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-400">
                  <Mail className="w-4 h-4" />
                </div>
                <input
                  id="email"
                  type="email"
                  value={email}
                  placeholder="e.g., yuvrajg@iitk.ac.in"
                  className="w-full pl-10 pr-4 py-2.5 bg-white border border-slate-300 rounded-xl text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-shadow"
                  onChange={handleEmailChange}
                  required
                />
              </div>
            </div>

            {/* ROLE / DESIGNATION (Signup mode) */}
            {mode === 'signup' && (
              <div className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-bold uppercase tracking-wider text-slate-700" htmlFor="role">
                    Role / Designation
                  </label>
                  <span className="text-[11px] font-medium text-slate-500 flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-teal-500"></span>
                    Faculty / Staff
                  </span>
                </div>
                <div className="relative">
                  <select
                    id="role"
                    value={role}
                    onChange={(e) => {
                      const newRole = e.target.value;
                      if (newRole !== 'Student' && !isStaffAdmin) {
                        setError('Access restricted: Faculty & Campus Administrator options are reserved for authorized administrator accounts.');
                        setRole('Student');
                      } else {
                        setRole(newRole);
                      }
                    }}
                    className="w-full appearance-none px-4 py-2.5 bg-white border border-slate-300 rounded-xl text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-shadow pr-10 cursor-pointer"
                  >
                    <option value="Student">Student</option>
                    <option value="Faculty / Staff" disabled={!isStaffAdmin}>
                      Faculty / Staff {!isStaffAdmin ? '(Restricted - Admin Only)' : ''}
                    </option>
                    <option value="Campus Administrator" disabled={!isStaffAdmin}>
                      Campus Administrator {!isStaffAdmin ? '(Restricted - Admin Only)' : ''}
                    </option>
                  </select>
                  <div className="absolute inset-y-0 right-0 pr-3.5 flex items-center pointer-events-none text-slate-400">
                    <ChevronDown className="w-4 h-4" />
                  </div>
                </div>
                <p className="text-xs text-slate-500 mt-1">
                  New accounts are always created as students. Admin access is never self-assigned.
                </p>
              </div>
            )}

            {/* PASSWORD */}
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <label className="text-xs font-bold uppercase tracking-wider text-slate-700" htmlFor="password">
                  Password
                </label>
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="text-xs text-slate-500 hover:text-slate-800 transition-colors flex items-center gap-1 select-none"
                >
                  {showPassword ? 'hide password' : 'show password'}
                </button>
              </div>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-400">
                  <Lock className="w-4 h-4" />
                </div>
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  placeholder="••••••••••"
                  className="w-full pl-10 pr-10 py-2.5 bg-white border border-slate-300 rounded-xl text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-shadow"
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-0 pr-3.5 flex items-center text-slate-400 hover:text-slate-600"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* CONFIRM PASSWORD (Signup mode) */}
            {mode === 'signup' && (
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-bold uppercase tracking-wider text-slate-700" htmlFor="confirmPassword">
                  Confirm Password
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-400">
                    <Lock className="w-4 h-4" />
                  </div>
                  <input
                    id="confirmPassword"
                    type={showPassword ? 'text' : 'password'}
                    value={confirmPassword}
                    placeholder="••••••••••"
                    className="w-full pl-10 pr-4 py-2.5 bg-white border border-slate-300 rounded-xl text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-shadow"
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    required
                  />
                </div>
              </div>
            )}

            {/* Submit Button */}
            <button
              type="submit"
              disabled={busy || loading}
              className="mt-2 w-full flex items-center justify-center gap-2 py-3 px-5 rounded-xl font-semibold text-white bg-gradient-to-r from-purple-600 via-indigo-600 to-indigo-700 hover:from-purple-700 hover:to-indigo-800 shadow-md shadow-indigo-500/25 transition-all transform active:scale-[0.99] disabled:opacity-50 disabled:pointer-events-none"
            >
              {busy ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Processing...</span>
                </>
              ) : (
                <>
                  <span>{mode === 'signup' ? 'Create account' : 'Sign in'}</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>

            {/* Divider */}
            <div className="relative my-2 flex items-center justify-center">
              <div className="w-full border-t border-slate-200" />
              <span className="absolute px-3 bg-white text-xs text-slate-500 uppercase tracking-wider">
                or {mode === 'signup' ? 'sign up with' : 'sign in with'}
              </span>
            </div>

            {/* Google Sign In */}
            <button
              type="button"
              onClick={handleGoogleAuth}
              className="w-full flex items-center justify-center gap-2.5 py-2.5 px-4 bg-white border border-slate-300 hover:bg-slate-50 rounded-xl text-sm font-semibold text-slate-700 shadow-sm transition-colors"
            >
              <GoogleLogo className="w-4 h-4" />
              <span>Continue with Google</span>
            </button>
          </form>

          {/* Switch Mode Footer */}
          <div className="mt-6 text-center text-sm text-slate-600">
            {mode === 'signup' ? (
              <p>
                <button
                  type="button"
                  onClick={() => {
                    setMode('signin');
                    setError(null);
                    setInfo(null);
                  }}
                  className="font-bold text-indigo-600 hover:text-indigo-800 hover:underline transition-colors"
                >
                  Already have an account? Sign in
                </button>
              </p>
            ) : (
              <p>
                <button
                  type="button"
                  onClick={() => {
                    setMode('signup');
                    setError(null);
                    setInfo(null);
                  }}
                  className="font-bold text-indigo-600 hover:text-indigo-800 hover:underline transition-colors"
                >
                  Need an account? Sign up
                </button>
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
