import { useCallback, useEffect, useState } from 'react';
import { Camera, CheckSquare, MapPin, ChevronRight, ArrowRight, FileText, CheckCircle2, Clock } from 'lucide-react';

import { listMyComplaints, fetchPublicComplaints, imageUrl } from '../api.js';
import { useAuth } from '../auth.jsx';
import { RobotAvatar } from '../components/BrandIcons.jsx';
import { CampusMapModal, AIAnalysisModal } from '../components/CampusModals.jsx';

/**
 * Main Home / Student Overview Dashboard matching Image 2.
 */
export default function HomePage() {
  const { token, email, loading: authLoading } = useAuth();
  const [complaints, setComplaints] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [mapNotice, setMapNotice] = useState(false);
  const [aiModalOpen, setAiModalOpen] = useState(false);

  // Derive user's display name from saved name, user metadata, or email
  const displayName = (() => {
    const saved = localStorage.getItem('cl_first_name') || localStorage.getItem('cl_user_name');
    if (saved && saved.trim()) return saved.trim();
    if (!email) return 'Student';
    const namePart = email.split('@')[0];
    const clean = namePart.replace(/[0-9_.-]/g, ' ').trim();
    if (!clean) return 'Student';
    return clean.charAt(0).toUpperCase() + clean.slice(1);
  })();

  const loadData = useCallback(async () => {
    if (authLoading) return;
    setLoading(true);
    setError(null);
    try {
      if (token) {
        const myRows = await listMyComplaints({ limit: 10, sort: 'newest' }, token);
        setComplaints(Array.isArray(myRows) ? myRows : []);
        return;
      }
      // Fallback to public rows only when not signed in
      const publicRows = await fetchPublicComplaints({ limit: 5 });
      setComplaints(Array.isArray(publicRows) ? publicRows : []);
    } catch (err) {
      setError(err?.message || 'Error in backend service.');
    } finally {
      setLoading(false);
    }
  }, [token, authLoading]);

  useEffect(() => {
    loadData();
    const onFocus = () => { if (token) loadData(); };
    const onHash = () => {
      if (window.location.hash === '#/' || window.location.hash === '#/home' || !window.location.hash) {
        if (token) loadData();
      }
    };
    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        setMapNotice(false);
        setAiModalOpen(false);
      }
    };
    window.addEventListener('focus', onFocus);
    window.addEventListener('hashchange', onHash);
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('focus', onFocus);
      window.removeEventListener('hashchange', onHash);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [loadData, token]);

  // Display only real registered complaints for this user (never hardcoded mock items)
  const displayItems = complaints;
  const totalCount = displayItems.length;
  const resolvedCount = displayItems.filter(i => (i.status || '').toLowerCase() === 'resolved').length;

  function getStatusBadge(status) {
    const s = (status || '').toLowerCase();
    if (s.includes('resolve')) {
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
          <CheckCircle2 className="w-3 h-3 text-emerald-600" /> Resolved
        </span>
      );
    }
    if (s.includes('progress')) {
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" /> In Progress
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-200">
        <Clock className="w-3 h-3 text-blue-600" /> Under Review
      </span>
    );
  }

  function getRelativeTime(dateStr) {
    if (!dateStr) return 'Recently';
    const diffDays = Math.round((Date.now() - new Date(dateStr).getTime()) / (1000 * 3600 * 24));
    if (diffDays <= 0) return 'Today';
    if (diffDays === 1) return '1 day ago';
    return `${diffDays} days ago`;
  }

  return (
    <div className="flex flex-col gap-6 w-full max-w-7xl mx-auto">
      {/* 1. HERO BANNER */}
      <div className="relative rounded-2xl overflow-hidden shadow-sm border border-slate-200 bg-slate-900 text-white min-h-[220px] sm:min-h-[260px] flex flex-col justify-between p-6 sm:p-8">
        {/* Background photo of IIT Kanpur (Authentic architectural representation of PK Kelkar Library and campus grounds) */}
        <div 
          className="absolute inset-0 bg-cover bg-center opacity-70"
          style={{
            backgroundImage: `url('/iitk_authentic_campus.jpg')`
          }}
        />
        {/* Soft gradient veil for text contrast */}
        <div className="absolute inset-0 bg-gradient-to-r from-slate-950/90 via-slate-900/65 to-transparent" />

        {/* Top Header Badge: Official IIT Kanpur Portal */}
        <div className="relative z-10 flex items-center justify-between gap-3 mb-2">
          <div className="inline-flex items-center gap-2.5 px-3 py-1.5 rounded-full bg-black/40 backdrop-blur-md border border-white/20 text-xs text-white shadow-sm">
            <img src="/iitk-logo.svg" alt="IIT Kanpur Seal" className="w-5 h-5 object-contain shrink-0" />
            <span className="font-semibold tracking-wide">IIT Kanpur Official Student Portal</span>
          </div>
        </div>

        {/* Hero Text */}
        <div className="relative z-10 max-w-xl">
          <h1 className="text-2xl sm:text-3xl lg:text-4xl font-extrabold tracking-tight text-white mb-2">
            Hello, {displayName}!
          </h1>
          <p className="text-sm sm:text-base text-slate-200 font-normal">
            Help us make IIT Kanpur a better place.
          </p>
        </div>

        {/* Bottom Floating Stats Pill & Doodle */}
        <div className="relative z-10 flex flex-wrap items-end justify-between gap-4 mt-6">
          {/* Glassmorphic Stat Pill */}
          <div className="flex items-center gap-6 bg-white/95 backdrop-blur-md rounded-2xl px-5 py-3 shadow-lg border border-white/50 text-slate-900">
            {/* Total Complaints */}
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-blue-100 flex items-center justify-center text-blue-600">
                <FileText className="w-5 h-5" />
              </div>
              <div className="flex flex-col">
                <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Total Complaints</span>
                <span className="text-xl font-bold font-mono text-slate-900 leading-tight">{totalCount}</span>
              </div>
            </div>

            <div className="w-px h-8 bg-slate-200" />

            {/* Resolved */}
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-emerald-100 flex items-center justify-center text-emerald-600">
                <CheckCircle2 className="w-5 h-5" />
              </div>
              <div className="flex flex-col">
                <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Resolved</span>
                <span className="text-xl font-bold font-mono text-slate-900 leading-tight">{resolvedCount}</span>
              </div>
            </div>
          </div>

          {/* Hand-drawn style note (desktop) */}
          <div className="hidden md:flex flex-col items-end text-white/90 select-none mr-4">
            <span className="text-sm font-handwriting italic tracking-wide font-medium">Your voice builds a better campus</span>
            <svg className="w-12 h-6 text-white/80 -rotate-12 mt-1" viewBox="0 0 100 50" fill="none" stroke="currentColor">
              <path d="M10 10 Q 50 40 85 25" strokeWidth="2.5" strokeLinecap="round" />
              <path d="M75 15 L 85 25 L 75 35" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
        </div>
      </div>

      {/* 2. THREE QUICK ACTION CARDS */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Card 1: Report an Issue */}
        <a 
          href="#/submit" 
          className="group bg-white p-5 rounded-2xl border border-slate-200 shadow-sm hover:shadow-md hover:border-indigo-200 transition-all flex items-center justify-between"
        >
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-tr from-purple-600 to-indigo-500 flex items-center justify-center text-white shadow-md shadow-indigo-500/20">
              <Camera className="w-6 h-6" />
            </div>
            <div>
              <h3 className="font-bold text-slate-900 group-hover:text-indigo-600 transition-colors">Report an Issue</h3>
              <p className="text-xs text-slate-500 mt-0.5">Upload a photo or describe the problem</p>
            </div>
          </div>
          <div className="w-8 h-8 rounded-full bg-purple-50 text-purple-600 group-hover:bg-purple-600 group-hover:text-white flex items-center justify-center transition-all shrink-0">
            <ArrowRight className="w-4 h-4" />
          </div>
        </a>

        {/* Card 2: View My Complaints */}
        <a 
          href="#/mine" 
          className="group bg-white p-5 rounded-2xl border border-slate-200 shadow-sm hover:shadow-md hover:border-emerald-200 transition-all flex items-center justify-between"
        >
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-tr from-emerald-600 to-teal-500 flex items-center justify-center text-white shadow-md shadow-emerald-500/20">
              <CheckSquare className="w-6 h-6" />
            </div>
            <div>
              <h3 className="font-bold text-slate-900 group-hover:text-emerald-600 transition-colors">View My Complaints</h3>
              <p className="text-xs text-slate-500 mt-0.5">Track status and AI analysis of your reports</p>
            </div>
          </div>
          <div className="w-8 h-8 rounded-full bg-emerald-50 text-emerald-600 group-hover:bg-emerald-600 group-hover:text-white flex items-center justify-center transition-all shrink-0">
            <ArrowRight className="w-4 h-4" />
          </div>
        </a>

        {/* Card 3: Campus Map */}
        <button 
          type="button" 
          onClick={() => setMapNotice(true)}
          className="group bg-white p-5 rounded-2xl border border-slate-200 shadow-sm hover:shadow-md hover:border-blue-200 transition-all flex items-center justify-between text-left"
        >
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-tr from-blue-600 to-sky-500 flex items-center justify-center text-white shadow-md shadow-blue-500/20">
              <MapPin className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <h3 className="font-bold text-slate-900 group-hover:text-blue-600 transition-colors">Campus Map</h3>
                <span className="px-1.5 py-0.5 text-[10px] font-bold rounded-full bg-blue-100 text-blue-700 border border-blue-200">Soon</span>
              </div>
              <p className="text-xs text-slate-500 mt-0.5">Explore issues by location on campus</p>
            </div>
          </div>
          <div className="w-8 h-8 rounded-full bg-blue-50 text-blue-600 group-hover:bg-blue-600 group-hover:text-white flex items-center justify-center transition-all shrink-0">
            <ArrowRight className="w-4 h-4" />
          </div>
        </button>
      </div>

      {/* 3. TWO COLUMNS: Recent Complaints & AI Analysis Preview */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Recent Complaints (7/12) */}
        <div className="lg:col-span-8 bg-white rounded-2xl border border-slate-200 shadow-sm p-6 flex flex-col">
          <div className="flex items-center justify-between pb-4 border-b border-slate-100 mb-4">
            <h3 className="text-base font-bold text-slate-900">Recent Complaints</h3>
            <a href="#/mine" className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 flex items-center gap-1 transition-colors">
              View all <ArrowRight className="w-3.5 h-3.5" />
            </a>
          </div>

          {error && (
            <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-xl flex items-center justify-between text-xs text-amber-800 animate-fade-in">
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-amber-600 shrink-0" />
                <span>{error}</span>
              </div>
              <button
                type="button"
                onClick={loadData}
                className="px-2.5 py-1 bg-amber-200/60 hover:bg-amber-200 rounded-lg font-semibold text-amber-900 transition-colors shrink-0"
              >
                Retry
              </button>
            </div>
          )}

          {loading && displayItems.length === 0 ? (
            <div className="py-12 text-center flex flex-col items-center justify-center">
              <div className="w-6 h-6 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin mb-2" />
              <p className="text-xs text-slate-400">Loading your complaints...</p>
            </div>
          ) : displayItems.length === 0 ? (
            <div className="py-10 text-center flex flex-col items-center justify-center">
              <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center text-slate-400 mb-2.5">
                <CheckSquare className="w-6 h-6" />
              </div>
              <p className="text-sm font-semibold text-slate-800">No complaints registered yet</p>
              <p className="text-xs text-slate-400 max-w-xs mt-1 mb-4">
                You have not registered any reports yet. When you submit a complaint, it will appear here.
              </p>
              <a
                href="#/submit"
                className="btn-gradient inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold text-white shadow-sm"
              >
                Report an Issue <ArrowRight className="w-3.5 h-3.5" />
              </a>
            </div>
          ) : (
            <div className="flex flex-col divide-y divide-slate-100">
              {displayItems.slice(0, 3).map((item) => {
                const src = item.image_url ? imageUrl(item.image_url) : null;
                return (
                  <a 
                    key={item.id} 
                    href={`#/complaint/${encodeURIComponent(item.id)}`}
                    className="py-3.5 first:pt-0 last:pb-0 flex items-center justify-between gap-4 group hover:bg-slate-50/70 -mx-3 px-3 rounded-xl transition-colors"
                  >
                    <div className="flex items-center gap-3.5 min-w-0">
                      {/* Thumbnail */}
                      <div className="w-12 h-12 rounded-xl bg-slate-100 border border-slate-200 overflow-hidden shrink-0 flex items-center justify-center text-slate-400">
                        {src ? (
                          <img src={src} alt="Complaint thumbnail" className="w-full h-full object-cover" />
                        ) : (
                          <div className="w-full h-full bg-slate-200/80 flex items-center justify-center">
                            <Camera className="w-5 h-5 opacity-40 text-slate-600" />
                          </div>
                        )}
                      </div>
                      {/* Details */}
                      <div className="min-w-0">
                        <h4 className="text-sm font-semibold text-slate-900 group-hover:text-indigo-600 transition-colors truncate">
                          {item.description || item.public_summary || 'Campus Issue'}
                        </h4>
                        <p className="text-xs text-slate-500 flex items-center gap-1 mt-0.5">
                          <MapPin className="w-3 h-3 text-slate-400" />
                          {item.location || item.public_location || 'IIT Kanpur'}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-4 shrink-0">
                      {getStatusBadge(item.status)}
                      <span className="hidden sm:inline text-xs text-slate-400 font-medium">
                        {getRelativeTime(item.created_at)}
                      </span>
                      <ChevronRight className="w-4 h-4 text-slate-400 group-hover:text-slate-700 transition-colors" />
                    </div>
                  </a>
                );
              })}
            </div>
          )}
        </div>

        {/* Right Column: AI Analysis Preview (5/12) */}
        <div className="lg:col-span-4 bg-gradient-to-b from-indigo-50/60 to-purple-50/40 rounded-2xl border border-indigo-100/80 p-6 flex flex-col items-center text-center shadow-sm">
          <div className="self-start text-xs font-bold uppercase tracking-wider text-slate-500 mb-4">
            AI Analysis Preview
          </div>

          <RobotAvatar className="w-16 h-16 mb-3 ring-4 ring-white" />

          <h3 className="text-lg font-bold text-slate-900 mb-1">AI Analysis</h3>
          <p className="text-xs font-semibold text-indigo-600 mb-2">Smarter reports, faster action.</p>

          <p className="text-xs text-slate-600 leading-relaxed max-w-xs mb-6">
            Get AI-powered categorisation, priority and impact analysis for your complaint automatically.
          </p>

          <button
            type="button"
            onClick={() => setAiModalOpen(true)}
            className="w-full max-w-xs py-2.5 px-4 rounded-xl text-xs font-semibold text-white bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-700 hover:to-indigo-700 shadow-md shadow-indigo-500/20 transition-all flex items-center justify-center gap-1.5"
          >
            <span>View Example</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Feature Announcement / Coming Soon Modal for Campus Map */}
      {mapNotice && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-fade-in"
          role="dialog"
          aria-modal="true"
          aria-labelledby="home-map-notice-title"
          onClick={() => setMapNotice(false)}
        >
          <div
            className="bg-white rounded-2xl p-6 sm:p-7 max-w-sm w-full shadow-2xl border border-slate-100 flex flex-col items-center text-center animate-scale-up"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="w-12 h-12 rounded-2xl bg-blue-50 text-blue-600 flex items-center justify-center mb-4 border border-blue-100 shadow-sm">
              <MapPin className="w-6 h-6" />
            </div>
            <div className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-blue-100 text-blue-700 border border-blue-200 mb-2">
              Coming Soon
            </div>
            <h3 id="home-map-notice-title" className="text-base font-bold text-slate-900 mb-1.5">Campus Map</h3>
            <p className="text-xs text-slate-600 leading-relaxed mb-6">
              The interactive Campus Map feature is currently under active development and will be available in the upcoming release. Stay tuned!
            </p>
            <button
              type="button"
              className="w-full py-2.5 px-4 rounded-xl text-xs font-bold text-white bg-slate-900 hover:bg-slate-800 transition-colors shadow-sm"
              onClick={() => setMapNotice(false)}
            >
              Got it
            </button>
          </div>
        </div>
      )}

      {/* AI Analysis Preview Modal */}
      <AIAnalysisModal isOpen={aiModalOpen} onClose={() => setAiModalOpen(false)} />
    </div>
  );
}

