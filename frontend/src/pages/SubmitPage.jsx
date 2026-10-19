import { useEffect, useRef, useState } from 'react';
import { UploadCloud, FileImage, Send, ExternalLink, Loader2, MapPin, ChevronDown, Info, X } from 'lucide-react';

import { submitComplaint } from '../api.js';
import {
  ACCEPTED_IMAGE_EXTENSIONS,
  ACCEPTED_IMAGE_TYPES,
  MAX_IMAGE_MB,
  MAX_IMAGE_BYTES,
} from '../constants.js';
import ResultPanel from '../components/ResultPanel.jsx';
import { useAuth } from '../auth.jsx';
import { ErrorBanner, Notice } from '../components/ui.jsx';

const isEmpty = (value) => value.trim().length === 0;
const humanSize = (bytes) => (bytes / (1024 * 1024)).toFixed(1);

const COMMON_CAMPUS_LOCATIONS = [
  'Block C, Lab 3, 2nd floor',
  'PK Kelkar Library, 1st Floor Reading Room',
  'Hall 12, Block A, 1st Floor',
  'Ganga Hostel, Mess Wing',
  'Hall 4, Common Room',
  'Academic Block (Faculty Building)',
  'Main Auditorium & Outreach Auditorium',
  'Campus Health Centre (HC)',
  'Sports Complex / New SAC Ground',
];

export default function SubmitPage() {
  const { token, loading: authLoading, configured } = useAuth();
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [description, setDescription] = useState('');
  const [location, setLocation] = useState('');
  const [recurrence, setRecurrence] = useState('Continuous (Everyday/Every hour)');
  const [problems, setProblems] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef(null);

  // Object URL lifecycle
  useEffect(() => {
    if (!file) {
      setPreview(null);
      return undefined;
    }
    const objectUrl = URL.createObjectURL(file);
    setPreview(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [file]);

  function validate() {
    const next = {};

    if (file) {
      if (!ACCEPTED_IMAGE_TYPES.includes(file.type)) {
        next.image = `Unsupported image type${file.type ? ` (${file.type})` : ''}. Use JPEG, PNG or WebP.`;
      } else if (file.size === 0) {
        next.image = 'That file is empty.';
      } else if (file.size > MAX_IMAGE_BYTES) {
        next.image = `Image is ${humanSize(file.size)} MB — backend limit is ${MAX_IMAGE_MB} MB.`;
      }
    }

    if (isEmpty(description)) next.description = 'Describe what is wrong.';
    if (isEmpty(location)) next.location = 'Tell us where on campus it is.';

    return next;
  }

  function resetForm() {
    setResult(null);
    setError(null);
    setProblems({});
    setFile(null);
    setDescription('');
    setLocation('');
    setRecurrence('Continuous (Everyday/Every hour)');
    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  function handleFileSelection(selected) {
    if (!selected) return;
    setFile(selected);
    setProblems((prev) => ({ ...prev, image: undefined }));
  }

  async function onSubmit(event) {
    event.preventDefault();
    if (submitting) return;

    const found = validate();
    setProblems(found);
    setError(null);
    if (Object.keys(found).length > 0) return;

    const form = new FormData();
    if (file) form.set('image', file, file.name);
    // Include recurrence context in description for admin clarity
    const fullDesc = recurrence ? `${description.trim()} [Recurrence: ${recurrence}]` : description.trim();
    form.set('description', fullDesc);
    form.set('location', location.trim());

    setSubmitting(true);
    try {
      const created = await submitComplaint(form, token);
      setResult(created);
      setFile(null);
      setDescription('');
      if (fileInputRef.current) fileInputRef.current.value = '';
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (caught) {
      setError(caught.message);
    } finally {
      setSubmitting(false);
    }
  }

  if (result) {
    return <ResultPanel result={result} onReset={resetForm} />;
  }

  if (authLoading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh] text-slate-500 gap-3">
        <Loader2 className="w-5 h-5 animate-spin text-indigo-600" />
        <span className="font-medium text-sm">Verifying your campus session...</span>
      </div>
    );
  }

  if (!token) {
    return (
      <div className="flex flex-col gap-6 max-w-xl mx-auto my-12 bg-white p-8 rounded-2xl border border-slate-200 shadow-sm">
        <h2 className="text-2xl font-bold text-slate-900">Sign in to report a problem</h2>
        <p className="text-sm text-slate-600">
          Sign in with your campus account so you can track your complaints and receive status updates.
        </p>
        <a 
          href="#/signin" 
          className="inline-flex items-center justify-center py-2.5 px-5 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-700 hover:to-indigo-700 text-white font-semibold rounded-xl text-sm shadow-md transition-all"
        >
          Sign In with Campus Account
        </a>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 max-w-6xl mx-auto w-full">
      {/* Page Heading */}
      <div>
        <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">
          Submit a Report
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Describe the issue and add photos (optional) to let the campus admin resolve it faster.
        </p>
      </div>

      <ErrorBanner
        title="Could not submit complaint"
        message={error}
        onRetry={() => setError(null)}
        retryLabel="Dismiss"
      />

      {/* Main Dual-Column Form Card */}
      <form 
        onSubmit={onSubmit} 
        noValidate 
        className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 sm:p-8 flex flex-col md:flex-row gap-8 items-start"
      >
        {/* LEFT COLUMN: Photo Upload & Preview */}
        <div className="w-full md:w-5/12 flex flex-col gap-5">
          {/* Photo upload dropzone */}
          <div>
            <label htmlFor="photo-input" className="block text-xs font-bold uppercase tracking-wider text-slate-800 mb-2 cursor-pointer">
              Photo of the Problem
            </label>
            <div
              onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setIsDragging(false);
                if (e.dataTransfer.files?.[0]) handleFileSelection(e.dataTransfer.files[0]);
              }}
              onClick={() => fileInputRef.current?.click()}
              className={`h-48 rounded-xl border-2 border-dashed flex flex-col items-center justify-center p-6 text-center cursor-pointer transition-colors ${
                isDragging ? 'border-indigo-500 bg-indigo-50/50' : 'border-slate-300 hover:border-indigo-400 bg-slate-50/60'
              }`}
            >
              <input
                id="photo-input"
                ref={fileInputRef}
                type="file"
                className="hidden"
                accept={ACCEPTED_IMAGE_EXTENSIONS}
                onChange={(e) => handleFileSelection(e.target.files?.[0])}
              />
              <div className="w-10 h-10 rounded-full bg-indigo-50 text-indigo-600 flex items-center justify-center mb-2">
                <UploadCloud className="w-5 h-5" />
              </div>
              <p className="text-sm text-slate-700 font-medium">
                Drag &amp; Drop your photo here <br />
                or <span className="text-indigo-600 font-semibold underline">Browse</span>.
              </p>
              <span className="text-[11px] text-slate-400 mt-1">Optional, up to 10MB</span>
            </div>
            {problems.image && <p role="alert" className="text-xs text-rose-600 font-medium mt-1.5">{problems.image}</p>}
          </div>

          {/* Preview Box */}
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-slate-800 mb-2">
              Preview
            </label>
            <div className="h-44 rounded-xl border border-slate-200 bg-slate-50/80 flex items-center justify-center overflow-hidden relative">
              {preview ? (
                <div className="relative w-full h-full group">
                  <img src={preview} alt="Problem preview" className="w-full h-full object-cover" />
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setFile(null);
                      if (fileInputRef.current) fileInputRef.current.value = '';
                    }}
                    className="absolute top-2 right-2 p-1.5 rounded-full bg-slate-900/70 text-white hover:bg-rose-600 transition-colors"
                    title="Remove photo"
                  >
                    <X className="w-4 h-4" />
                  </button>
                  <div className="absolute bottom-0 inset-x-0 bg-slate-900/60 text-white text-[11px] px-3 py-1 truncate">
                    {file?.name}
                  </div>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center text-slate-400 gap-1.5">
                  <FileImage className="w-7 h-7 opacity-40" />
                  <span className="text-xs font-medium">No file uploaded yet.</span>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN: Issue Details */}
        <div className="w-full md:w-7/12 flex flex-col gap-5">
          {/* WHAT IS THE ISSUE? */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-bold uppercase tracking-wider text-slate-800" htmlFor="desc">
              What is wrong?
            </label>
            <span className="text-xs text-slate-500 font-medium -mt-1">Describe the issue in detail...</span>
            <textarea
              id="desc"
              rows={4}
              value={description}
              onChange={(e) => {
                setDescription(e.target.value);
                setProblems(p => ({ ...p, description: undefined }));
              }}
              placeholder="Describe the problem in detail (e.g., broken fan, water leakage, wifi issue)"
              className={`w-full p-3.5 bg-white border rounded-xl text-base sm:text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-shadow resize-y ${
                problems.description ? 'border-rose-400 focus:ring-rose-400' : 'border-slate-300'
              }`}
            />
            {problems.description && <p role="alert" className="text-xs text-rose-600 font-medium">{problems.description}</p>}
          </div>

          {/* WHERE ON CAMPUS? */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-bold uppercase tracking-wider text-slate-800" htmlFor="loc">
              Where on campus?
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-400">
                <MapPin className="w-4 h-4 text-indigo-500" />
              </div>
              <input
                id="loc"
                type="text"
                list="campus-locations"
                value={location}
                onChange={(e) => {
                  setLocation(e.target.value);
                  setProblems(p => ({ ...p, location: undefined }));
                }}
                placeholder="e.g. Block C, Lab 3, 2nd floor"
                className={`w-full pl-10 pr-10 py-2.5 bg-white border rounded-xl text-base sm:text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-shadow ${
                  problems.location ? 'border-rose-400 focus:ring-rose-400' : 'border-slate-300'
                }`}
              />
              <div className="absolute inset-y-0 right-0 pr-3.5 flex items-center pointer-events-none text-slate-400">
                <ChevronDown className="w-4 h-4" />
              </div>
              <datalist id="campus-locations">
                {COMMON_CAMPUS_LOCATIONS.map((loc, i) => (
                  <option key={i} value={loc} />
                ))}
              </datalist>
            </div>
            {problems.location && <p role="alert" className="text-xs text-rose-600 font-medium">{problems.location}</p>}
          </div>

          {/* RECURRENCE */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-bold uppercase tracking-wider text-slate-800" htmlFor="recurrence">
              Recurrence
            </label>
            <div className="relative">
              <select
                id="recurrence"
                value={recurrence}
                onChange={(e) => setRecurrence(e.target.value)}
                className="w-full appearance-none px-4 py-2.5 bg-white border border-slate-300 rounded-xl text-base sm:text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-shadow pr-10 cursor-pointer"
              >
                <option value="Continuous (Everyday/Every hour)">Continuous (Everyday/Every hour)</option>
                <option value="Intermittent (Few times a day)">Intermittent (Few times a day)</option>
                <option value="First-time occurrence">First-time occurrence</option>
                <option value="Recurring after previous repair">Recurring after previous repair</option>
              </select>
              <div className="absolute inset-y-0 right-0 pr-3.5 flex items-center pointer-events-none text-slate-400">
                <ChevronDown className="w-4 h-4" />
              </div>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex flex-wrap items-center gap-4 pt-3">
            <button
              type="submit"
              disabled={submitting}
              aria-label="Submit Complaint"
              className="py-3 px-6 rounded-xl font-semibold text-white bg-gradient-to-r from-purple-600 via-indigo-600 to-indigo-700 hover:from-purple-700 hover:to-indigo-800 shadow-md shadow-indigo-500/25 transition-all flex items-center gap-2 disabled:opacity-50"
            >
              {submitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Submitting...</span>
                </>
              ) : (
                <>
                  <span>Submit Report</span>
                  <Send className="w-4 h-4" />
                </>
              )}
            </button>

            <a
              href="#/mine"
              className="py-3 px-5 rounded-xl font-semibold text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 transition-colors text-sm shadow-sm"
            >
              View My Complaints
            </a>
          </div>
        </div>
      </form>

      {/* Footer Info Pill matching mockup */}
      <div className="flex items-center gap-2.5 p-3.5 px-4 bg-slate-100 border border-slate-200/80 rounded-xl text-xs text-slate-600">
        <Info className="w-4 h-4 text-slate-500 shrink-0" />
        <span>Analysis runs on the server. If it fails, your report is still saved and shown as Unscored</span>
      </div>
    </div>
  );
}
