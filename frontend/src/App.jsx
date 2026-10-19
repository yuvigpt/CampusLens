import { useCallback, useEffect, useState } from 'react';
import { 
  Home, Send, CheckSquare, User, LayoutDashboard, 
  Search, Bell, LogOut, ChevronDown, CheckCircle2, 
  XCircle, Loader2, Info, MapPin, BarChart3, Settings, ShieldCheck, Users, Menu, X, Globe
} from 'lucide-react';

import { fetchHealth, listMyComplaints, onUnauthorized } from './api.js';
import { AuthProvider, useAuth } from './auth.jsx';
import HomePage from './pages/HomePage.jsx';
import SubmitPage from './pages/SubmitPage.jsx';
import MyComplaintsPage from './pages/MyComplaintsPage.jsx';
import ComplaintDetailPage from './pages/ComplaintDetailPage.jsx';
import ProfilePage from './pages/ProfilePage.jsx';
import DashboardPage from './pages/DashboardPage.jsx';
import SignInPage from './pages/SignInPage.jsx';
import CommunityPage from './pages/CommunityPage.jsx';
import NotFoundPage from './pages/NotFoundPage.jsx';
import Footer from './components/Footer.jsx';
import { updatePageMetadata } from './lib/seo.js';
import { CampusLensIcon } from './components/BrandIcons.jsx';
import { CampusMapModal } from './components/CampusModals.jsx';

function useHealth() {
  const [health, setHealth] = useState({ state: 'checking', data: null });

  const check = useCallback(() => {
    fetchHealth()
      .then((data) => setHealth({ state: 'up', data }))
      .catch(() => setHealth({ state: 'down', data: null }));
  }, []);

  useEffect(() => {
    check();
    const timer = setInterval(check, 30000);
    return () => clearInterval(timer);
  }, [check]);

  return [health, check];
}

const HEALTH_LABEL = {
  checking: 'Checking API...',
  up: 'API online',
  down: 'API unreachable',
};

function Shell() {
  const { token, email, signOut, loading, isAdmin, profileError, reloadProfile } = useAuth();
  const [hash, setHash] = useState(() => window.location.hash || '#/');
  const [health, retryHealth] = useHealth();
  const [expired, setExpired] = useState(false);
  const [profileDropdownOpen, setProfileDropdownOpen] = useState(false);
  const [notifDropdownOpen, setNotifDropdownOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [mapOpen, setMapOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [featureNotice, setFeatureNotice] = useState(null);
  const [userComplaints, setUserComplaints] = useState([]);
  const [readNotifIds, setReadNotifIds] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('cl_read_notifs') || '[]');
    } catch {
      return [];
    }
  });

  // When a visitor opens the app without an active session on root/home, default to signup
  useEffect(() => {
    if (!loading && !token && (hash === '' || hash === '#/' || hash === '#/home')) {
      window.location.hash = '#/signup';
    }
  }, [loading, token, hash]);

  // Load real personalized complaints for the logged-in user
  useEffect(() => {
    if (!token) {
      setUserComplaints([]);
      return;
    }
    let active = true;
    listMyComplaints({ limit: 15 }, token)
      .then((res) => {
        if (active && Array.isArray(res)) {
          setUserComplaints(res);
        }
      })
      .catch(() => {});
    return () => { active = false; };
  }, [token, hash]);

  function getRelativeTime(dateStr) {
    if (!dateStr) return 'Recently';
    const diffDays = Math.round((Date.now() - new Date(dateStr).getTime()) / (1000 * 3600 * 24));
    if (diffDays <= 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    return `${diffDays}d ago`;
  }

  // Derive notifications solely from the user's registered complaints
  const notifications = (() => {
    if (!token || userComplaints.length === 0) return [];
    return userComplaints.map((c) => {
      const status = (c.status || 'reported').toLowerCase();
      let title = `Report: ${c.description ? c.description.slice(0, 42) + (c.description.length > 42 ? '...' : '') : 'Campus Issue'}`;
      let message = `Status: ${c.status || 'Reported'} at ${c.location || 'IIT Kanpur'}`;
      if (status === 'resolved') {
        title = `Resolved: ${c.description ? c.description.slice(0, 42) + (c.description.length > 42 ? '...' : '') : 'Issue'}`;
        message = `Your complaint at ${c.location || 'IIT Kanpur'} has been resolved.`;
      } else if (status.includes('progress')) {
        title = `In Progress: ${c.description ? c.description.slice(0, 42) + (c.description.length > 42 ? '...' : '') : 'Issue'}`;
        message = `Operations staff is addressing your report.`;
      }
      return {
        id: `notif-${c.id}-${status}`,
        complaintId: c.id,
        title,
        message,
        time: getRelativeTime(c.updated_at || c.created_at),
        read: readNotifIds.includes(`notif-${c.id}-${status}`),
      };
    });
  })();

  const unreadCount = notifications.filter((n) => !n.read).length;

  function markNotifRead(id) {
    setReadNotifIds((prev) => {
      if (prev.includes(id)) return prev;
      const next = [...prev, id];
      try { localStorage.setItem('cl_read_notifs', JSON.stringify(next)); } catch {}
      return next;
    });
  }

  function markAllNotifsRead() {
    const allIds = notifications.map((n) => n.id);
    setReadNotifIds(allIds);
    try { localStorage.setItem('cl_read_notifs', JSON.stringify(allIds)); } catch {}
  }

  useEffect(() => {
    const onHashChange = () => {
      const current = window.location.hash || '#/';
      setHash(current);
      updatePageMetadata(current.split('?')[0]);
      setMobileMenuOpen(false);
      try {
        window.scrollTo({ top: 0, behavior: 'smooth' });
      } catch {
        // Ignored in environments where scrollTo is unsupported
      }
    };

    // Initial page metadata sync
    updatePageMetadata((window.location.hash || '#/').split('?')[0]);

    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  // Keyboard accessibility: dismiss popovers and dialogs on Escape key
  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        setFeatureNotice(null);
        setMobileMenuOpen(false);
        setNotifDropdownOpen(false);
        setProfileDropdownOpen(false);
        setMapOpen(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  useEffect(() => {
    onUnauthorized(() => setExpired(true));
  }, []);

  // Derive user's display name from stored name, user metadata, or email prefix
  const userName = (() => {
    const stored = localStorage.getItem('cl_user_name') || localStorage.getItem('cl_first_name');
    if (stored && stored.trim()) return stored.trim();
    if (!email) return 'Student';
    const namePart = email.split('@')[0];
    const clean = namePart.replace(/[0-9_.-]/g, ' ').trim();
    if (!clean) return 'Student';
    return clean.charAt(0).toUpperCase() + clean.slice(1);
  })();

  const isSignInView = hash === '#/signin' || hash === '#/signup';

  // Active route matching. The hash may carry a query string
  // (#/triage?q=leak) which is stripped here and parsed into `routeParams`
  // for the pages that consume it.
  const [currentPath, currentQueryString = ''] = (hash || '#/').split('?');
  const routeParams = new URLSearchParams(currentQueryString);
  const isDashboard =
    currentPath.startsWith('#/dashboard') || currentPath.startsWith('#/triage');

  // Student Navigation Items (User Portal)
  const studentNavItems = [
    { label: 'Home', hash: '#/', icon: <Home className="w-4 h-4" /> },
    { label: 'Submit Report', hash: '#/submit', icon: <Send className="w-4 h-4" /> },
    { label: 'My complaints', hash: '#/mine', icon: <CheckSquare className="w-4 h-4" /> },
    { label: 'Community', hash: '#/community', icon: <Globe className="w-4 h-4" /> },
    { label: 'Profile', hash: '#/profile', icon: <User className="w-4 h-4" /> },
    ...(isAdmin ? [{ label: 'Operations dashboard', hash: '#/dashboard', icon: <LayoutDashboard className="w-4 h-4" /> }] : []),
  ];

  // Admin Navigation Items (Operations Dashboard)
  const adminNavItems = [
    { label: 'Overview Dashboard', hash: '#/dashboard', icon: <LayoutDashboard className="w-4 h-4" /> },
    { label: 'Issue Triage', hash: '#/triage', icon: <CheckSquare className="w-4 h-4" /> },
    {
      label: 'Campus Map',
      action: () => setFeatureNotice({
        title: 'Campus Map',
        message: 'The interactive Campus Map feature is currently under active development and will be available in the upcoming release.',
      }),
      icon: <MapPin className="w-4 h-4" />,
      badge: 'Soon',
    },
    {
      label: 'Staff Management',
      action: () => setFeatureNotice({
        title: 'Staff Management',
        message: 'Staff roster management and engineer assignment capabilities are coming soon in the upcoming release.',
      }),
      icon: <Users className="w-4 h-4" />,
      badge: 'Soon',
    },
    {
      label: 'Analytics & Reports',
      action: () => setFeatureNotice({
        title: 'Analytics & Reports',
        message: 'Comprehensive campus analytics, resolution metrics, and exportable reports are coming soon in the upcoming release.',
      }),
      icon: <BarChart3 className="w-4 h-4" />,
      badge: 'Soon',
    },
    {
      label: 'Settings / Audit Log',
      action: () => setFeatureNotice({
        title: 'Settings & Audit Log',
        message: 'System configuration, role management, and audit trail logs are coming soon in the upcoming release.',
      }),
      icon: <Settings className="w-4 h-4" />,
      badge: 'Soon',
    },
  ];

  function renderPage() {
    // Dedicated detail page for one of the student's own complaints.
    if (currentPath.startsWith('#/complaint/')) {
      const complaintId = decodeURIComponent(currentPath.slice('#/complaint/'.length));
      return <ComplaintDetailPage complaintId={complaintId} />;
    }
    switch (currentPath) {
      case '#/':
      case '#/home':
        return <HomePage />;
      case '#/submit':
        return <SubmitPage />;
      case '#/mine':
        return <MyComplaintsPage initialQuery={routeParams.get('q') || ''} />;
      case '#/profile':
        return <ProfilePage />;
      case '#/dashboard':
        return <DashboardPage view="overview" />;
      case '#/triage':
        return <DashboardPage view="triage" initialQuery={routeParams.get('q') || ''} />;
      case '#/community':
        return <CommunityPage />;
      default:
        return <NotFoundPage requestedPath={currentPath} />;
    }
  }

  return (
    <>
      {isSignInView ? (
        <SignInPage />
      ) : (
        <div className="min-h-screen w-full flex bg-[#f8fafc] text-slate-900 font-sans overflow-x-hidden">
          {/* ============================================================ */}
      {/* 1. DESKTOP / LAPTOP SIDEBAR with IIT Kanpur Campus Photo     */}
      {/* ============================================================ */}
      <aside className="relative w-64 shrink-0 bg-[#090f1d] text-white flex flex-col justify-between p-4 hidden md:flex border-r border-slate-800/80 z-30 select-none overflow-hidden">
        {/* IIT Kanpur Campus authentic background photo overlay */}
        <div 
          className="absolute inset-0 z-0 bg-cover bg-bottom opacity-20 pointer-events-none mix-blend-luminosity scale-105"
          style={{ backgroundImage: `url('/iitk_authentic_campus.jpg')` }}
        />
        {/* Deep dark gradient overlay */}
        <div className="absolute inset-0 z-0 bg-gradient-to-b from-[#090f1d]/95 via-[#0b1428]/80 to-[#070c18]/95 pointer-events-none" />

        <div className="relative z-10 flex flex-col gap-6">
          {/* Top Logo */}
          <a href="#/" className="flex items-center gap-3 px-2 pt-2 group">
            <CampusLensIcon className="w-9 h-9" />
            <div className="flex flex-col">
              <span className="font-extrabold text-base tracking-tight text-white leading-tight">
                CampusLens
              </span>
              <span className="text-[11px] font-medium text-indigo-300 tracking-wide">
                {isDashboard ? 'IIT Kanpur - OPERATIONS' : 'Better, Kanpur • Improve'}
              </span>
            </div>
          </a>

          {/* Navigation Links */}
          <nav className="flex flex-col gap-1.5" aria-label="Primary">
            {isDashboard ? (
              // ADMIN NAVIGATION
              <>
                {adminNavItems.map((item, idx) => {
                  // Highlight the item whose route matches the current path -
                  // not a fixed index, so Issue Triage lights up on #/triage.
                  const active = Boolean(item.hash) && currentPath === item.hash;
                  if (item.action) {
                    return (
                      <button
                        key={idx}
                        type="button"
                        onClick={item.action}
                        className="flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-medium text-slate-300 hover:text-white hover:bg-slate-800/60 transition-all text-left w-full"
                      >
                        <div className="flex items-center gap-3">
                          {item.icon}
                          <span>{item.label}</span>
                        </div>
                        {item.badge && (
                          <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700/80">
                            {item.badge}
                          </span>
                        )}
                      </button>
                    );
                  }
                  return (
                    <a
                      key={idx}
                      href={item.hash}
                      className={`flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all ${
                        active
                          ? 'bg-blue-600 text-white shadow-md shadow-blue-600/30'
                          : 'text-slate-300 hover:text-white hover:bg-slate-800/60'
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        {item.icon}
                        <span>{item.label}</span>
                      </div>
                      {item.badge && (
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-200 border border-blue-400/30">
                          {item.badge}
                        </span>
                      )}
                    </a>
                  );
                })}

                <div className="pt-4 mt-2 border-t border-slate-800/80">
                  <a
                    href="#/"
                    className="flex items-center gap-2.5 px-3.5 py-2 rounded-xl text-xs font-semibold text-indigo-300 hover:bg-indigo-950/60 transition-colors"
                  >
                    <span>← Switch to Student View</span>
                  </a>
                </div>
              </>
            ) : (
              // STUDENT NAVIGATION (No Operations Portal)
              <>
                {studentNavItems.map((item) => {
                  const active =
                    (currentPath === item.hash) ||
                    (item.hash === '#/' && currentPath === '#/home') ||
                    (item.hash === '#/mine' && currentPath.startsWith('#/complaint/'));
                  return (
                    <a
                      key={item.label}
                      href={item.hash}
                      className={`flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all ${
                        active
                          ? 'bg-blue-600 text-white shadow-md shadow-blue-600/30'
                          : 'text-slate-300 hover:text-white hover:bg-slate-800/60'
                      }`}
                    >
                      {item.icon}
                      <span>{item.label}</span>
                    </a>
                  );
                })}
              </>
            )}
          </nav>
        </div>

        {/* Bottom Sidebar Footer */}
        <div className="relative z-10 pt-6 border-t border-slate-800/80 px-2 flex flex-col gap-1">
          <div className="flex items-center gap-2 mb-1">
            <img src="/iitk-logo.svg" alt="Seal" className="w-5 h-5 object-contain" />
            <span className="text-xs font-bold text-white tracking-wide">IIT Kanpur</span>
          </div>
          <span className="text-[11px] text-slate-400">Smarter Reports. Better Campus.</span>
        </div>
      </aside>

      {/* ============================================================ */}
      {/* 2. MOBILE DRAWER NAVIGATION (with IIT Kanpur Background)    */}
      {/* ============================================================ */}
      {mobileMenuOpen && (
        <div className="fixed inset-0 z-50 flex md:hidden animate-fade-in">
          {/* Backdrop */}
          <div 
            className="fixed inset-0 bg-slate-950/70 backdrop-blur-sm"
            onClick={() => setMobileMenuOpen(false)}
          />
          {/* Off-canvas sidebar */}
          <aside className="relative w-72 max-w-[85vw] bg-[#090f1d] text-white flex flex-col justify-between p-5 z-50 shadow-2xl overflow-hidden animate-slide-right">
            {/* IIT Kanpur Campus authentic background photo overlay */}
            <div 
              className="absolute inset-0 z-0 bg-cover bg-bottom opacity-20 pointer-events-none mix-blend-luminosity scale-105"
              style={{ backgroundImage: `url('/iitk_authentic_campus.jpg')` }}
            />
            <div className="absolute inset-0 z-0 bg-gradient-to-b from-[#090f1d]/95 via-[#0b1428]/80 to-[#070c18]/95 pointer-events-none" />

            <div className="relative z-10 flex flex-col gap-6">
              {/* Drawer Header */}
              <div className="flex items-center justify-between pb-2 border-b border-slate-800/80">
                <a href="#/" onClick={() => setMobileMenuOpen(false)} className="flex items-center gap-2.5">
                  <CampusLensIcon className="w-8 h-8" />
                  <span className="font-extrabold text-base tracking-tight text-white">CampusLens</span>
                </a>
                <button
                  type="button"
                  onClick={() => setMobileMenuOpen(false)}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Navigation Items */}
              <nav className="flex flex-col gap-2">
                {isDashboard ? (
                  <>
                    {adminNavItems.map((item, idx) => {
                      if (item.action) {
                        return (
                          <button
                            key={idx}
                            type="button"
                            onClick={() => {
                              item.action();
                              setMobileMenuOpen(false);
                            }}
                            className="flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-medium text-slate-300 hover:text-white hover:bg-slate-800/60 text-left w-full"
                          >
                            <div className="flex items-center gap-3">
                              {item.icon}
                              <span>{item.label}</span>
                            </div>
                            {item.badge && (
                              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700/80">
                                {item.badge}
                              </span>
                            )}
                          </button>
                        );
                      }
                      return (
                        <a
                          key={idx}
                          href={item.hash}
                          onClick={() => setMobileMenuOpen(false)}
                          className={`flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all ${
                            item.hash && currentPath === item.hash
                              ? 'bg-blue-600 text-white shadow-md shadow-blue-600/30'
                              : 'text-slate-300 hover:text-white hover:bg-slate-800/60'
                          }`}
                        >
                          <div className="flex items-center gap-3">
                            {item.icon}
                            <span>{item.label}</span>
                          </div>
                          {item.badge && (
                            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-200 border border-blue-400/30">
                              {item.badge}
                            </span>
                          )}
                        </a>
                      );
                    })}
                    <div className="pt-3 border-t border-slate-800">
                      <a
                        href="#/"
                        onClick={() => setMobileMenuOpen(false)}
                        className="text-xs text-indigo-300 block py-1"
                      >
                        ← Switch to Student View
                      </a>
                    </div>
                  </>
                ) : (
                  studentNavItems.map((item) => {
                    const active = (currentPath === item.hash) || (item.hash === '#/' && currentPath === '#/home');
                    return (
                      <a
                        key={item.label}
                        href={item.hash}
                        onClick={() => setMobileMenuOpen(false)}
                        className={`flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all ${
                          active
                            ? 'bg-blue-600 text-white shadow-md shadow-blue-600/30'
                            : 'text-slate-300 hover:text-white hover:bg-slate-800/60'
                        }`}
                      >
                        {item.icon}
                        <span>{item.label}</span>
                      </a>
                    );
                  })
                )}
              </nav>
            </div>

            {/* Bottom Footer */}
            <div className="relative z-10 pt-4 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-400">
              <div className="flex items-center gap-1.5">
                <img src="/iitk-logo.svg" alt="IIT Kanpur" className="w-4 h-4 object-contain" />
                <span>IIT Kanpur Portal</span>
              </div>
              <button
                type="button"
                onClick={() => {
                  setMobileMenuOpen(false);
                  signOut();
                }}
                className="text-rose-400 font-semibold flex items-center gap-1"
              >
                <LogOut className="w-3.5 h-3.5" />
                <span>Sign Out</span>
              </button>
            </div>
          </aside>
        </div>
      )}

      {/* ============================================================ */}
      {/* 3. MAIN CONTENT AREA (Top Bar + Responsive View)             */}
      {/* ============================================================ */}
      <div className="flex-1 flex flex-col min-w-0 min-h-screen">
        {/* TOP BAR */}
        <header className="sticky top-0 z-40 h-16 bg-white/95 backdrop-blur-md border-b border-slate-200 px-4 sm:px-6 lg:px-8 flex items-center justify-between gap-3 sm:gap-4">
          {/* Mobile menu trigger & Mobile clickable logo */}
          <div className="flex items-center gap-1.5 md:hidden shrink-0">
            <button
              type="button"
              onClick={() => setMobileMenuOpen(true)}
              className="p-2 -ml-1 rounded-xl text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition-colors"
              aria-label="Open mobile menu"
              aria-expanded={mobileMenuOpen}
            >
              <Menu className="w-5 h-5" />
            </button>
            <a href="#/" aria-label="CampusLens Home" className="flex items-center gap-1 p-1 rounded-xl hover:bg-slate-100 transition-colors">
              <CampusLensIcon className="w-7 h-7" />
            </a>
          </div>

          {/* Search bar - Enter hands the query to the page that can really
              search: admins go to the Issue Triage workspace, students to
              their own complaints. Both pages read it from #route?q=... */}
          <form
            role="search"
            aria-label="Search complaints"
            className="flex-1 max-w-xs sm:max-w-md"
            onSubmit={(event) => {
              event.preventDefault();
              const query = searchQuery.trim();
              if (!query) return;
              const target = isDashboard ? '#/triage' : '#/mine';
              window.location.hash = `${target}?q=${encodeURIComponent(query)}`;
            }}
          >
            <div className="relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={isDashboard ? "Search ticket ID, location..." : "Search complaints..."}
                aria-label={isDashboard ? "Search ticket ID or location" : "Search complaints"}
                className="w-full pl-3.5 sm:pl-4 pr-9 sm:pr-10 py-1.5 sm:py-2 bg-slate-50 border border-slate-200 rounded-full text-base sm:text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-shadow"
              />
              <div className="absolute inset-y-0 right-0 pr-3 flex items-center pointer-events-none text-slate-400">
                <Search className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
              </div>
            </div>
          </form>

          {/* Right: Notifications & User Profile */}
          <div className="flex items-center gap-2 sm:gap-4 shrink-0">
            {/* Notification Bell */}
            <div className="relative">
              <button
                type="button"
                onClick={() => setNotifDropdownOpen(!notifDropdownOpen)}
                className="relative p-2 rounded-full text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-colors"
                title="Notifications"
              >
                <Bell className="w-5 h-5" />
                {unreadCount > 0 && (
                  <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-rose-500 ring-2 ring-white" />
                )}
              </button>

              {/* Notification Popover */}
              {notifDropdownOpen && (
                <div className="absolute right-0 mt-2 w-80 bg-white rounded-2xl shadow-xl border border-slate-200 p-3 z-50 text-xs animate-scale-in">
                  <div className="font-bold text-slate-900 border-b border-slate-100 pb-2 mb-2 flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <span>Notifications</span>
                      {unreadCount > 0 && (
                        <span className="px-1.5 py-0.5 rounded-full text-[10px] bg-rose-100 text-rose-700 font-bold">
                          {unreadCount}
                        </span>
                      )}
                    </div>
                    {unreadCount > 0 ? (
                      <button
                        type="button"
                        onClick={markAllNotifsRead}
                        className="text-[10px] text-blue-600 hover:text-blue-800 font-semibold cursor-pointer transition-colors"
                      >
                        Mark all read
                      </button>
                    ) : (
                      <span className="text-[10px] text-slate-400 font-medium">All caught up</span>
                    )}
                  </div>
                  <div className="space-y-1.5 max-h-72 overflow-y-auto">
                    {notifications.length === 0 ? (
                      <div className="py-6 px-4 text-center flex flex-col items-center justify-center text-slate-400">
                        <Bell className="w-5 h-5 mb-1.5 opacity-30 text-slate-500" />
                        <p className="font-semibold text-slate-700 text-xs">No notifications yet</p>
                        <p className="text-[11px] text-slate-400 mt-0.5 leading-relaxed">
                          You will receive personalized updates here whenever your complaints are reviewed or resolved.
                        </p>
                      </div>
                    ) : (
                      notifications.map((notif) => (
                        <a
                          key={notif.id}
                          href={`#/complaint/${encodeURIComponent(notif.complaintId)}`}
                          onClick={() => {
                            markNotifRead(notif.id);
                            setNotifDropdownOpen(false);
                          }}
                          className={`p-2.5 rounded-xl cursor-pointer transition-colors flex flex-col gap-0.5 block ${
                            notif.read
                              ? 'bg-slate-50 hover:bg-slate-100/80 text-slate-500'
                              : 'bg-blue-50/70 hover:bg-blue-100/60 text-slate-900 border border-blue-100/80'
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <p className={`font-semibold text-xs leading-snug truncate ${notif.read ? 'text-slate-600' : 'text-slate-900'}`}>
                              {notif.title}
                            </p>
                            {!notif.read && (
                              <span className="w-1.5 h-1.5 rounded-full bg-blue-600 shrink-0" title="Unread" />
                            )}
                          </div>
                          <p className="text-[11px] text-slate-500 line-clamp-1">{notif.message}</p>
                          <span className="text-[10px] text-slate-400 mt-0.5">{notif.time}</span>
                        </a>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* User Profile Badge */}
            <div className="relative">
              <button
                type="button"
                onClick={() => setProfileDropdownOpen(!profileDropdownOpen)}
                className="flex items-center gap-2 p-1 sm:pl-2 rounded-full hover:bg-slate-100 transition-colors text-left"
              >
                <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-indigo-600 to-purple-600 text-white font-bold text-xs flex items-center justify-center border border-indigo-200/50 shadow-sm shrink-0">
                  {(userName || 'S').charAt(0).toUpperCase()}
                </div>
                <div className="hidden sm:flex flex-col">
                  <span className="text-xs font-bold text-slate-900 leading-tight">
                    {isDashboard ? 'Operations Admin' : (userName || 'Student')}
                  </span>
                  <span className="text-[10px] text-slate-500 font-medium">
                    {isDashboard ? '(Support Team)' : (isAdmin ? 'Administrator' : 'Student')}
                  </span>
                </div>
                <ChevronDown className="w-3.5 h-3.5 text-slate-400 hidden sm:inline" />
              </button>

              {/* Profile Dropdown */}
              {profileDropdownOpen && (
                <div className="absolute right-0 mt-2 w-48 bg-white rounded-2xl shadow-xl border border-slate-200 py-2 z-50 text-xs animate-scale-in">
                  <a
                    href="#/profile"
                    onClick={() => setProfileDropdownOpen(false)}
                    className="flex items-center gap-2 px-4 py-2 hover:bg-slate-50 text-slate-700 font-medium"
                  >
                    <User className="w-4 h-4 text-slate-400" />
                    <span>My Profile</span>
                  </a>
                  <a
                    href="#/mine"
                    onClick={() => setProfileDropdownOpen(false)}
                    className="flex items-center gap-2 px-4 py-2 hover:bg-slate-50 text-slate-700 font-medium"
                  >
                    <CheckSquare className="w-4 h-4 text-slate-400" />
                    <span>My Reports</span>
                  </a>
                  <div className="my-1 border-t border-slate-100" />
                  <button
                    type="button"
                    onClick={() => {
                      setProfileDropdownOpen(false);
                      signOut();
                    }}
                    className="w-full flex items-center gap-2 px-4 py-2 hover:bg-rose-50 text-rose-600 font-semibold text-left"
                  >
                    <LogOut className="w-4 h-4" />
                    <span>Sign Out</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        {/* Main Content Area (Extra bottom padding on mobile so content clears the mobile bottom bar) */}
        <main className="flex-1 p-4 sm:p-6 lg:p-8 pb-24 md:pb-8 overflow-y-auto">
          {profileError && (
            <div className="mb-6 bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <Info className="w-5 h-5 text-amber-600 shrink-0" />
                <span className="text-sm text-amber-900">{profileError}</span>
              </div>
              <button
                type="button"
                onClick={reloadProfile}
                className="px-3 py-1.5 bg-amber-100 hover:bg-amber-200 text-amber-900 text-xs font-semibold rounded-lg transition-colors shrink-0"
              >
                Retry
              </button>
            </div>
          )}

          {expired && (
            <div className="mb-6 bg-rose-50 border border-rose-200 rounded-xl p-4 flex items-start gap-3">
              <LogOut className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" />
              <div className="flex-1 text-sm text-rose-800">
                Your session has expired. Please <a href="#/signin" className="font-semibold underline">sign in again</a>.
              </div>
            </div>
          )}

          {renderPage()}
          <Footer onOpenMap={() => setMapOpen(true)} />
        </main>

        {/* ============================================================ */}
        {/* 4. FIXED MOBILE BOTTOM TAB BAR                               */}
        {/* ============================================================ */}
        <nav className="md:hidden fixed bottom-0 inset-x-0 bg-white/95 backdrop-blur-md border-t border-slate-200 z-40 py-2 px-3 flex items-center justify-around shadow-lg" aria-label="Mobile navigation">
          {studentNavItems.map((item) => {
            const active = (currentPath === item.hash) || (item.hash === '#/' && currentPath === '#/home');
            return (
              <a
                key={item.label}
                href={item.hash}
                className={`flex flex-col items-center gap-1 py-1 px-3 rounded-xl text-[11px] font-semibold transition-colors ${
                  active 
                    ? 'text-indigo-600 bg-indigo-50' 
                    : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                {item.icon}
                <span>{item.label.split(' ')[0]}</span>
              </a>
            );
          })}
          </nav>
        </div>
      </div>
      )}

      {/* Global Interactive Modals */}
      <CampusMapModal isOpen={mapOpen} onClose={() => setMapOpen(false)} />

      {/* Feature Announcement / Coming Soon Modal */}
      {featureNotice && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-fade-in"
          role="dialog"
          aria-modal="true"
          aria-labelledby="feature-modal-title"
          onClick={() => setFeatureNotice(null)}
        >
          <div
            className="bg-white rounded-2xl max-w-sm w-full p-6 shadow-2xl border border-slate-200 text-center animate-scale-in"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="w-12 h-12 rounded-2xl bg-blue-50 text-blue-600 mx-auto flex items-center justify-center mb-3.5 shadow-sm">
              <Info className="w-6 h-6" />
            </div>
            <div className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-blue-100 text-blue-700 border border-blue-200 mb-2">
              Coming Soon
            </div>
            <h3 id="feature-modal-title" className="text-base font-bold text-slate-900 mb-1.5">{featureNotice.title}</h3>
            <p className="text-xs text-slate-600 leading-relaxed mb-6">{featureNotice.message}</p>
            <button
              type="button"
              onClick={() => setFeatureNotice(null)}
              className="w-full py-2.5 rounded-xl font-semibold text-white bg-blue-600 hover:bg-blue-700 transition-colors text-xs shadow-md shadow-blue-500/20"
            >
              Got it
            </button>
          </div>
        </div>
      )}
    </>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  );
}
