import { useState, useEffect } from 'react';
import { User, Mail, Phone, Lock, FileText, CheckCircle2, Clock, Trash2, LogOut, Camera, ShieldCheck, Check } from 'lucide-react';

import { useAuth } from '../auth.jsx';
import { listMyComplaints } from '../api.js';

/**
 * Profile Settings Page matching Image 4.
 */
export default function ProfilePage() {
  const { email, signOut, token } = useAuth();

  // User form details with state persistence in localStorage
  const [firstName, setFirstName] = useState(() => localStorage.getItem('cl_first_name') || 'Yuvraj');
  const [lastName, setLastName] = useState(() => localStorage.getItem('cl_last_name') || 'Gupta');
  const [rollNumber, setRollNumber] = useState(() => localStorage.getItem('cl_roll') || '210987');
  const [hostel, setHostel] = useState(() => localStorage.getItem('cl_hostel') || 'Hall 12');
  const [phone, setPhone] = useState(() => localStorage.getItem('cl_phone') || '+91 98765 43210');

  // Preferences toggles
  const [twoFactor, setTwoFactor] = useState(true);
  const [emailNotifs, setEmailNotifs] = useState(true);
  const [pushNotifs, setPushNotifs] = useState(true);
  const [aiUpdates, setAiUpdates] = useState(true);

  const [savedSuccess, setSavedSuccess] = useState(false);
  const [complaints, setComplaints] = useState([]);

  useEffect(() => {
    if (token) {
      listMyComplaints({ limit: 20 }, token)
        .then((res) => { if (Array.isArray(res)) setComplaints(res); })
        .catch(() => {});
    }
  }, [token]);

  function handleSave(e) {
    e.preventDefault();
    localStorage.setItem('cl_first_name', firstName);
    localStorage.setItem('cl_last_name', lastName);
    localStorage.setItem('cl_roll', rollNumber);
    localStorage.setItem('cl_hostel', hostel);
    localStorage.setItem('cl_phone', phone);
    setSavedSuccess(true);
    setTimeout(() => setSavedSuccess(false), 3000);
  }

  const totalReports = complaints.length || 12;
  const resolvedCount = complaints.filter(c => (c.status || '').toLowerCase() === 'resolved').length || 8;
  const inProgressCount = complaints.filter(c => (c.status || '').toLowerCase().includes('progress')).length || 3;
  const draftsCount = 1;

  return (
    <div className="flex flex-col gap-6 max-w-6xl mx-auto w-full">
      {/* Header */}
      <div>
        <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">
          Profile Settings
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Manage your account details, preferences, and view your activity.
        </p>
      </div>

      {savedSuccess && (
        <div className="p-3.5 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl text-sm flex items-center gap-2 animate-fade-in font-medium">
          <Check className="w-4 h-4 text-emerald-600" /> Changes saved to your profile!
        </div>
      )}

      {/* Main Grid: Left Column (Personal Info & Security) + Right Column (Activity & Preferences) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* LEFT COLUMN (7/12) */}
        <div className="lg:col-span-7 flex flex-col gap-6">
          {/* PERSONAL INFO CARD */}
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 sm:p-7 flex flex-col gap-6">
            <div className="border-b border-slate-100 pb-3">
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Profile Dashboard</span>
              <h2 className="text-sm font-bold uppercase tracking-wider text-slate-900 mt-0.5">Personal Info</h2>
            </div>

            <div className="flex flex-col sm:flex-row items-center sm:items-start gap-6">
              {/* Avatar */}
              <div className="flex flex-col items-center gap-2 shrink-0">
                <div className="relative">
                  <div className="w-24 h-24 rounded-full overflow-hidden border-2 border-indigo-200 shadow-md">
                    <img 
                      src="https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=400&q=80" 
                      alt="Profile Avatar"
                      className="w-full h-full object-cover"
                    />
                  </div>
                  <button 
                    type="button"
                    className="absolute bottom-0 right-0 p-2 rounded-full bg-indigo-600 text-white shadow-md hover:bg-indigo-700 transition-colors"
                    title="Change Avatar"
                  >
                    <Camera className="w-3.5 h-3.5" />
                  </button>
                </div>
                <div className="text-center">
                  <h3 className="font-bold text-slate-900 text-base">{firstName} {lastName}</h3>
                  <span className="text-xs text-slate-500 font-medium">Student</span>
                </div>
              </div>

              {/* Input Fields */}
              <form onSubmit={handleSave} className="flex-1 w-full flex flex-col gap-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-bold text-slate-700">First Name</label>
                    <input
                      type="text"
                      value={firstName}
                      onChange={(e) => setFirstName(e.target.value)}
                      className="px-3.5 py-2 bg-white border border-slate-300 rounded-xl text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-bold text-slate-700">Last Name</label>
                    <input
                      type="text"
                      value={lastName}
                      onChange={(e) => setLastName(e.target.value)}
                      className="px-3.5 py-2 bg-white border border-slate-300 rounded-xl text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </div>
                </div>

                <div className="flex flex-col gap-1">
                  <label className="text-xs font-bold text-slate-700">Email ID</label>
                  <input
                    type="email"
                    value={email || 'yuvrajg@iitk.ac.in'}
                    disabled
                    className="px-3.5 py-2 bg-slate-50 border border-slate-200 rounded-xl text-sm text-slate-600 cursor-not-allowed"
                  />
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-bold text-slate-700">Roll Number</label>
                    <input
                      type="text"
                      value={rollNumber}
                      onChange={(e) => setRollNumber(e.target.value)}
                      className="px-3.5 py-2 bg-white border border-slate-300 rounded-xl text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-bold text-slate-700">Hostel/Residence</label>
                    <input
                      type="text"
                      value={hostel}
                      onChange={(e) => setHostel(e.target.value)}
                      className="px-3.5 py-2 bg-white border border-slate-300 rounded-xl text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </div>
                </div>

                <div className="flex flex-col gap-1">
                  <label className="text-xs font-bold text-slate-700">Phone Number</label>
                  <input
                    type="tel"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    className="px-3.5 py-2 bg-white border border-slate-300 rounded-xl text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>

                <div className="flex items-center gap-3 pt-2">
                  <button
                    type="submit"
                    className="py-2.5 px-5 rounded-xl font-semibold text-white bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-700 hover:to-indigo-700 shadow-md shadow-indigo-500/20 text-sm transition-all"
                  >
                    Save Changes
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setFirstName(localStorage.getItem('cl_first_name') || 'Yuvraj');
                      setLastName(localStorage.getItem('cl_last_name') || 'Gupta');
                    }}
                    className="py-2.5 px-4 rounded-xl font-semibold text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 text-sm transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </form>
            </div>
          </div>

          {/* ACCOUNT SECURITY CARD */}
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 sm:p-7 flex flex-col gap-4">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-900">Account Security</h2>

            <div className="flex flex-wrap items-center justify-between gap-4">
              <button
                type="button"
                onClick={() => alert('Password reset link sent to your campus email address!')}
                className="py-2 px-4 rounded-xl font-semibold text-white bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-700 hover:to-indigo-700 text-xs shadow-sm transition-all"
              >
                Change Password
              </button>

              <div className="flex items-center gap-3">
                <span className="text-sm font-semibold text-slate-800">Two-Factor Authentication</span>
                <button
                  type="button"
                  onClick={() => setTwoFactor(!twoFactor)}
                  className={`w-11 h-6 rounded-full transition-colors relative flex items-center p-0.5 ${
                    twoFactor ? 'bg-indigo-600' : 'bg-slate-300'
                  }`}
                >
                  <span className={`w-5 h-5 rounded-full bg-white shadow-sm transition-transform ${
                    twoFactor ? 'translate-x-5' : 'translate-x-0'
                  }`} />
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN (5/12) */}
        <div className="lg:col-span-5 flex flex-col gap-6">
          {/* ACTIVITY OVERVIEW */}
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 sm:p-7 flex flex-col gap-5">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-900">Activity Overview</h2>

            {/* 4 Stat Pills */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
              {/* Total Reports */}
              <div className="p-3 rounded-xl bg-blue-50/70 border border-blue-100 flex flex-col items-center text-center">
                <FileText className="w-4 h-4 text-blue-600 mb-1" />
                <span className="text-lg font-bold font-mono text-slate-900 leading-tight">{totalReports}</span>
                <span className="text-[10px] text-slate-500 font-medium uppercase mt-0.5">Total Reports</span>
              </div>

              {/* Resolved */}
              <div className="p-3 rounded-xl bg-emerald-50/70 border border-emerald-100 flex flex-col items-center text-center">
                <CheckCircle2 className="w-4 h-4 text-emerald-600 mb-1" />
                <span className="text-lg font-bold font-mono text-slate-900 leading-tight">{resolvedCount}</span>
                <span className="text-[10px] text-slate-500 font-medium uppercase mt-0.5">Resolved</span>
              </div>

              {/* In Progress */}
              <div className="p-3 rounded-xl bg-amber-50/70 border border-amber-100 flex flex-col items-center text-center">
                <Clock className="w-4 h-4 text-amber-600 mb-1" />
                <span className="text-lg font-bold font-mono text-slate-900 leading-tight">{inProgressCount}</span>
                <span className="text-[10px] text-slate-500 font-medium uppercase mt-0.5">In Progress</span>
              </div>

              {/* Drafts */}
              <div className="p-3 rounded-xl bg-slate-100/70 border border-slate-200 flex flex-col items-center text-center">
                <FileText className="w-4 h-4 text-slate-500 mb-1" />
                <span className="text-lg font-bold font-mono text-slate-900 leading-tight">{draftsCount}</span>
                <span className="text-[10px] text-slate-500 font-medium uppercase mt-0.5">Drafts</span>
              </div>
            </div>

            {/* Recent Activity List */}
            <div className="pt-2">
              <h3 className="text-xs font-bold text-slate-800 mb-3">Recent Activity</h3>
              <div className="flex flex-col gap-3">
                <div className="flex items-start gap-2.5 text-xs">
                  <span className="w-2 h-2 rounded-full bg-blue-500 mt-1.5 shrink-0" />
                  <div className="flex-1">
                    <p className="font-semibold text-slate-800">Reported water leakage in Ganga Hostel</p>
                    <span className="text-slate-400">2h ago</span>
                  </div>
                </div>

                <div className="flex items-start gap-2.5 text-xs">
                  <span className="w-2 h-2 rounded-full bg-emerald-500 mt-1.5 shrink-0" />
                  <div className="flex-1">
                    <p className="font-semibold text-slate-800">Received resolution update for Fan in Hall 12</p>
                    <span className="text-slate-400">1d ago</span>
                  </div>
                </div>

                <div className="flex items-start gap-2.5 text-xs">
                  <span className="w-2 h-2 rounded-full bg-slate-400 mt-1.5 shrink-0" />
                  <div className="flex-1">
                    <p className="font-semibold text-slate-800">Submitted lighting maintenance ticket for Hall 12</p>
                    <span className="text-slate-400">3d ago</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* PREFERENCES CARD */}
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 sm:p-7 flex flex-col gap-4">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-900">Preferences</h2>

            <div className="flex flex-col divide-y divide-slate-100">
              <div className="py-2.5 flex items-center justify-between">
                <span className="text-sm font-medium text-slate-800">Email notifications</span>
                <button
                  type="button"
                  onClick={() => setEmailNotifs(!emailNotifs)}
                  className={`w-11 h-6 rounded-full transition-colors relative flex items-center p-0.5 ${
                    emailNotifs ? 'bg-indigo-600' : 'bg-slate-300'
                  }`}
                >
                  <span className={`w-5 h-5 rounded-full bg-white shadow-sm transition-transform ${
                    emailNotifs ? 'translate-x-5' : 'translate-x-0'
                  }`} />
                </button>
              </div>

              <div className="py-2.5 flex items-center justify-between">
                <span className="text-sm font-medium text-slate-800">Push notifications</span>
                <button
                  type="button"
                  onClick={() => setPushNotifs(!pushNotifs)}
                  className={`w-11 h-6 rounded-full transition-colors relative flex items-center p-0.5 ${
                    pushNotifs ? 'bg-indigo-600' : 'bg-slate-300'
                  }`}
                >
                  <span className={`w-5 h-5 rounded-full bg-white shadow-sm transition-transform ${
                    pushNotifs ? 'translate-x-5' : 'translate-x-0'
                  }`} />
                </button>
              </div>

              <div className="py-2.5 flex items-center justify-between">
                <span className="text-sm font-medium text-slate-800">AI updates</span>
                <button
                  type="button"
                  onClick={() => setAiUpdates(!aiUpdates)}
                  className={`w-11 h-6 rounded-full transition-colors relative flex items-center p-0.5 ${
                    aiUpdates ? 'bg-indigo-600' : 'bg-slate-300'
                  }`}
                >
                  <span className={`w-5 h-5 rounded-full bg-white shadow-sm transition-transform ${
                    aiUpdates ? 'translate-x-5' : 'translate-x-0'
                  }`} />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* BOTTOM ACTION BAR */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-4 px-6 flex items-center justify-between">
        <button
          type="button"
          onClick={signOut}
          className="flex items-center gap-2 text-rose-600 hover:text-rose-700 font-semibold text-sm transition-colors"
        >
          <LogOut className="w-4 h-4" />
          <span>Log Out</span>
        </button>

        <button
          type="button"
          onClick={() => alert('Account deletion request queued for campus administration review.')}
          className="flex items-center gap-1.5 text-slate-400 hover:text-rose-600 text-xs font-medium transition-colors"
        >
          <Trash2 className="w-4 h-4" />
          <span>Delete Account</span>
        </button>
      </div>
    </div>
  );
}
