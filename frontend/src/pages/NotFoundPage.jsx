import { ArrowLeft, Home, Send, CheckSquare, Search, AlertOctagon } from 'lucide-react';

/**
 * Custom 404 Page Not Found for CampusLens.
 */
export default function NotFoundPage({ requestedPath = '' }) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] max-w-2xl mx-auto px-4 py-12 text-center animate-fade-up">
      {/* 404 Badge */}
      <div className="w-16 h-16 rounded-2xl bg-amber-50 border border-amber-200 text-amber-600 flex items-center justify-center mb-6 shadow-sm">
        <AlertOctagon className="w-8 h-8" />
      </div>

      <span className="text-xs font-bold uppercase tracking-widest text-indigo-600 mb-2">Error 404</span>
      <h1 className="text-3xl sm:text-4xl font-extrabold text-slate-900 tracking-tight mb-3">
        Page Not Found
      </h1>

      <p className="text-slate-600 text-sm sm:text-base max-w-md mb-2 leading-relaxed">
        The page or view <code className="px-2 py-0.5 rounded bg-slate-100 text-slate-800 text-xs font-mono">{requestedPath || window.location.hash || 'requested'}</code> does not exist or has been moved.
      </p>
      <p className="text-xs text-slate-400 mb-8">
        Don&apos;t worry, your reports and account are safe. Choose an option below to return to the portal.
      </p>

      {/* Helpful Quick Links */}
      <div className="flex flex-wrap items-center justify-center gap-3 w-full max-w-md">
        <a
          href="#/"
          className="btn-gradient inline-flex items-center gap-2 px-5 py-2.5 rounded-xl font-semibold text-white text-sm shadow-md"
        >
          <Home className="w-4 h-4" />
          <span>Back to Home</span>
        </a>

        <a
          href="#/submit"
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl font-semibold text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 transition-colors text-sm shadow-sm"
        >
          <Send className="w-4 h-4 text-indigo-600" />
          <span>Report an Issue</span>
        </a>

        <a
          href="#/mine"
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl font-semibold text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 transition-colors text-sm shadow-sm"
        >
          <CheckSquare className="w-4 h-4 text-emerald-600" />
          <span>My Complaints</span>
        </a>
      </div>

      {/* Campus Help line */}
      <div className="mt-12 pt-6 border-t border-slate-200 w-full text-xs text-slate-500">
        Need assistance? Contact CampusLens Operations at{' '}
        <a href="mailto:campuslens-support@iitk.ac.in" className="text-indigo-600 hover:underline font-semibold">
          campuslens-support@iitk.ac.in
        </a>
      </div>
    </div>
  );
}
