import { useState } from 'react';
import { MapPin, Image as ImageIcon, ChevronDown, Globe, Clock, FileText } from 'lucide-react';

import {
  approveForPublic,
  imageUrl,
  revokeForPublic,
} from '../api.js';
import { PriorityBadge, ScoreMeter, UnscoredNote } from './Priority.jsx';
import { StatusBadge, StatusSelect } from './Status.jsx';

const has = (value) => typeof value === 'string' && value.trim().length > 0;

function Detail({ term, value }) {
  return (
    <div className="flex flex-col sm:flex-row sm:justify-between py-2 border-b border-slate-100 last:border-0 gap-1">
      <dt className="text-xs font-semibold uppercase tracking-wider text-slate-500">{term}</dt>
      <dd className="text-sm font-medium text-slate-800 text-right">
        {has(value) ? value : <span className="text-slate-400 italic">Not provided</span>}
      </dd>
    </div>
  );
}

export default function ComplaintCard({ complaint, onStatusChange, busy, token, index = 0 }) {
  const {
    id,
    description,
    location,
    image_url: imageUrlValue,
    image_path: imagePath,
    status,
    created_at: createdAt,
    priority_score: score,
    ai_category: aiCategory,
    ai_summary: aiSummary,
    ai_evidence: aiEvidence,
    ai_uncertainty: aiUncertainty,
    ai_urgency: aiUrgency,
    ai_impact: aiImpact,
    ai_safety: aiSafety,
  } = complaint;

  const [published, setPublished] = useState(false);
  const [pubSummary, setPubSummary] = useState('');
  const [pubCategory, setPubCategory] = useState('');
  const [pubLocation, setPubLocation] = useState('');
  const [pubBusy, setPubBusy] = useState(false);
  const [pubError, setPubError] = useState(null);

  // The photo only exists when the row stored an object path. A missing signed
  // URL (a transient sign failure) must NOT be reported as "No photo" - the
  // admin would wrongly think the student never attached one. When a path is
  // present but no URL came back, say so explicitly instead of guessing.
  const src = imageUrl(imageUrlValue);
  const hasPhotoPath = Boolean(imagePath);
  const unscored = score == null;

  async function publish() {
    setPubError(null);
    if (pubSummary.trim().length < 10) {
      setPubError('The public summary must be at least 10 characters.');
      return;
    }
    if (pubCategory.trim().length < 2 || pubLocation.trim().length < 2) {
      setPubError('A public category and location are both required.');
      return;
    }
    setPubBusy(true);
    try {
      await approveForPublic(
        id,
        {
          public_summary: pubSummary.trim(),
          public_category: pubCategory.trim(),
          public_location: pubLocation.trim(),
        },
        token,
      );
      setPublished(true);
    } catch (caught) {
      setPubError(caught.message);
    } finally {
      setPubBusy(false);
    }
  }

  async function unpublish() {
    setPubError(null);
    setPubBusy(true);
    try {
      await revokeForPublic(id, token);
      setPublished(false);
    } catch (caught) {
      setPubError(caught.message);
    } finally {
      setPubBusy(false);
    }
  }

  return (
    <article
      className="bg-white rounded-xl border border-slate-200 shadow-sm card-lift overflow-hidden flex flex-col animate-fade-up"
      style={{ animationDelay: `${Math.min(index, 6) * 50}ms` }}
      aria-labelledby={`complaint-${id}`}
    >
      <header className="bg-gradient-to-r from-indigo-50/70 via-slate-50/80 to-slate-50/80 border-b border-slate-200 px-5 py-4 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3 flex-wrap">
          <span className="font-mono font-bold text-slate-800 bg-white px-2 py-1 rounded shadow-sm text-sm border border-slate-200">#{id}</span>
          <StatusBadge status={status} />
          {createdAt && (
            <span className="text-xs text-slate-500 font-medium flex items-center gap-1">
              <Clock className="w-3.5 h-3.5" />
              {new Date(createdAt).toLocaleString()}
            </span>
          )}
        </div>
        <PriorityBadge band={complaint.band} score={score} />
      </header>

      <div className="p-5 flex-1 flex flex-col md:flex-row gap-6">
        <div className="flex-1 min-w-0 space-y-5">
          <div>
            <p className="text-base text-slate-900 font-medium leading-relaxed mb-2">{description}</p>
            <p className="text-sm text-slate-600 flex items-center gap-1.5">
              <MapPin className="w-4 h-4 text-indigo-500" />
              {location}
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            <span className={`inline-flex items-center px-2.5 py-1 rounded-md text-xs font-bold border ${aiCategory ? 'bg-indigo-50 text-indigo-700 border-indigo-100' : 'bg-slate-100 text-slate-500 border-slate-200'}`}>
              {aiCategory || 'Unclassified'}
            </span>
            {aiSafety && <span className="inline-flex items-center px-2 py-1 rounded-md text-xs font-semibold bg-slate-50 text-slate-600 border border-slate-200">AI safety: {aiSafety}</span>}
            {aiUrgency && <span className="inline-flex items-center px-2 py-1 rounded-md text-xs font-semibold bg-slate-50 text-slate-600 border border-slate-200">AI urgency: {aiUrgency}</span>}
            {aiImpact && <span className="inline-flex items-center px-2 py-1 rounded-md text-xs font-semibold bg-slate-50 text-slate-600 border border-slate-200">AI impact: {aiImpact}</span>}
          </div>

          {has(aiSummary) && (
            <div className="bg-slate-50 rounded-lg p-3 border border-slate-100">
              <p className="text-sm text-slate-700 leading-relaxed"><span className="font-semibold text-slate-900 mr-1">AI Summary:</span>{aiSummary}</p>
            </div>
          )}

          {has(aiUncertainty) && (
            <div className="bg-amber-50 rounded-lg p-4 border border-amber-200">
              <strong className="text-sm text-amber-800 font-bold block mb-1">AI uncertainty / missing information</strong>
              <p className="text-sm text-amber-900">{aiUncertainty}</p>
            </div>
          )}

          {unscored && <UnscoredNote />}

          <div className="space-y-3 pt-2">
            <details className="group border border-slate-200 rounded-lg overflow-hidden [&_summary::-webkit-details-marker]:hidden">
              <summary className="flex items-center justify-between p-4 bg-slate-50 cursor-pointer font-medium text-sm text-slate-800 select-none hover:bg-slate-100 transition-colors">
                <span className="flex items-center gap-2"><FileText className="w-4 h-4 text-slate-500"/> Full AI assessment</span>
                <ChevronDown className="w-4 h-4 text-slate-500 transition-transform group-open:-rotate-180" />
              </summary>
              <div className="p-4 border-t border-slate-200 bg-white">
                <dl className="flex flex-col">
                  <Detail term="Category" value={aiCategory} />
                  <Detail term="Issue summary" value={aiSummary} />
                  <Detail term="Safety" value={aiSafety} />
                  <Detail term="Impact" value={aiImpact} />
                  <Detail term="Urgency" value={aiUrgency} />
                  <Detail term="Evidence from image" value={aiEvidence} />
                  <Detail term="Uncertainty" value={aiUncertainty} />
                </dl>
              </div>
            </details>

            <details className="group border border-slate-200 rounded-lg overflow-hidden [&_summary::-webkit-details-marker]:hidden">
              <summary className="flex items-center justify-between p-4 bg-slate-50 cursor-pointer font-medium text-sm text-slate-800 select-none hover:bg-slate-100 transition-colors">
                <span className="flex items-center gap-2"><Globe className="w-4 h-4 text-blue-500"/> {published ? 'Published to community feed' : 'Publish to community feed'}</span>
                <ChevronDown className="w-4 h-4 text-slate-500 transition-transform group-open:-rotate-180" />
              </summary>
              <div className="p-4 border-t border-slate-200 bg-white space-y-4">
                <p className="text-xs text-slate-500">
                  A complaint stays private until you publish it. The public entry is
                  never built from the reporter&apos;s own words - write the public
                  wording yourself.
                </p>
                {pubError && <p className="text-sm font-semibold text-rose-600" role="alert">{pubError}</p>}
                
                {published ? (
                  <p className="text-sm font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg p-3">This complaint is visible on the public feed.</p>
                ) : (
                  <div className="space-y-3">
                    <label className="flex flex-col gap-1.5" htmlFor={`pub-summary-${id}`}>
                      <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Public summary</span>
                      <textarea
                        id={`pub-summary-${id}`}
                        rows={3}
                        className="bg-white border border-slate-300 text-slate-900 text-sm rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 block w-full p-2.5"
                        value={pubSummary}
                        placeholder="Lighting fault reported on the main stairwell."
                        onChange={(event) => setPubSummary(event.target.value)}
                      />
                    </label>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <label className="flex flex-col gap-1.5" htmlFor={`pub-category-${id}`}>
                        <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Public category</span>
                        <input
                          id={`pub-category-${id}`}
                          type="text"
                          className="bg-white border border-slate-300 text-slate-900 text-sm rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 block w-full p-2.5"
                          value={pubCategory}
                          placeholder="Electrical"
                          onChange={(event) => setPubCategory(event.target.value)}
                        />
                      </label>
                      <label className="flex flex-col gap-1.5" htmlFor={`pub-location-${id}`}>
                        <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Public location</span>
                        <input
                          id={`pub-location-${id}`}
                          type="text"
                          className="bg-white border border-slate-300 text-slate-900 text-sm rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 block w-full p-2.5"
                          value={pubLocation}
                          placeholder="Science Block, ground floor"
                          onChange={(event) => setPubLocation(event.target.value)}
                        />
                      </label>
                    </div>
                  </div>
                )}
                <div className="pt-2">
                  {published ? (
                    <button
                      type="button"
                      className="px-4 py-2 border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 font-medium rounded-lg text-sm shadow-sm transition-colors disabled:opacity-50"
                      onClick={unpublish}
                      disabled={pubBusy}
                    >
                      {pubBusy ? 'Withdrawing...' : 'Withdraw from feed'}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="btn-gradient px-4 py-2 font-medium rounded-lg text-sm disabled:opacity-50"
                      onClick={publish}
                      disabled={pubBusy}
                    >
                      {pubBusy ? 'Publishing...' : 'Publish sanitized summary'}
                    </button>
                  )}
                </div>
              </div>
            </details>
          </div>
        </div>

        <aside className="w-full md:w-64 flex flex-col gap-5 shrink-0">
          <div className="rounded-xl overflow-hidden border border-slate-200 bg-slate-50 flex items-center justify-center">
            {src ? (
              <a href={src} target="_blank" rel="noopener noreferrer" className="block w-full h-full relative group">
                <img src={src} alt={`Photo uploaded with complaint ${id}`} loading="lazy" decoding="async" className="w-full h-48 object-cover group-hover:scale-105 transition-transform duration-300" />
                <div className="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-colors" />
              </a>
            ) : hasPhotoPath ? (
              <div className="flex flex-col items-center justify-center h-48 text-amber-600 gap-2 border-2 border-dashed border-amber-300 w-full m-1 rounded-lg bg-amber-50">
                <ImageIcon className="w-8 h-8 opacity-70" />
                <span className="text-sm font-medium text-center px-2">Photo attached — couldn&apos;t load preview</span>
                <span className="text-xs text-amber-700/80 px-3 text-center">A photo is stored for this complaint but its temporary link expired. Refresh the page to generate a new one.</span>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-48 text-slate-400 gap-2 border-2 border-dashed border-slate-200 w-full m-1 rounded-lg">
                <ImageIcon className="w-8 h-8 opacity-50" />
                <span className="text-sm font-medium">No photo</span>
              </div>
            )}
          </div>

          <div className="p-4 rounded-xl border border-slate-200 bg-slate-50/50">
            <ScoreMeter band={complaint.band} score={score} />
          </div>

          <div className="p-4 rounded-xl border border-slate-200 bg-slate-50/50">
            <label className="flex flex-col gap-1.5" htmlFor={`status-${id}`}>
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Status</span>
              <StatusSelect
                id={`status-${id}`}
                complaintId={id}
                value={status}
                disabled={busy}
                onChange={(next) => onStatusChange(complaint, next)}
              />
            </label>
            {busy && <p className="text-xs text-indigo-600 font-medium mt-2 animate-pulse">Saving status...</p>}
          </div>
        </aside>
      </div>
    </article>
  );
}
