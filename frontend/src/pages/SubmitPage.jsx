import { useEffect, useRef, useState } from 'react';

import { submitComplaint } from '../api.js';
import {
  ACCEPTED_IMAGE_EXTENSIONS,
  ACCEPTED_IMAGE_TYPES,
  MAX_IMAGE_MB,
  MAX_IMAGE_BYTES,
} from '../constants.js';
import ResultPanel from '../components/ResultPanel.jsx';
import { ErrorBanner, Notice } from '../components/ui.jsx';

const isEmpty = (value) => value.trim().length === 0;

const humanSize = (bytes) => (bytes / (1024 * 1024)).toFixed(1);

export default function SubmitPage() {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [description, setDescription] = useState('');
  const [location, setLocation] = useState('');
  const [problems, setProblems] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const fileInputRef = useRef(null);

  // The object URL must be revoked when the file changes or the panel unmounts.
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

    if (!file) {
      next.image = 'Attach a photo of the problem.';
    } else if (!ACCEPTED_IMAGE_TYPES.includes(file.type)) {
      next.image = `Unsupported image type${file.type ? ` (${file.type})` : ''}. Use JPEG, PNG or WebP.`;
    } else if (file.size === 0) {
      next.image = 'That file is empty.';
    } else if (file.size > MAX_IMAGE_BYTES) {
      next.image = `Image is ${humanSize(file.size)} MB — the backend limit is ${MAX_IMAGE_MB} MB.`;
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
    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  async function onSubmit(event) {
    event.preventDefault();
    if (submitting) return;

    const found = validate();
    setProblems(found);
    setError(null);
    if (Object.keys(found).length > 0) return;

    // Multipart fields, matching the backend's Form(...) parameters exactly.
    const form = new FormData();
    form.set('image', file, file.name);
    form.set('description', description.trim());
    form.set('location', location.trim());

    setSubmitting(true);
    try {
      const created = await submitComplaint(form);
      setResult(created);
      setFile(null);
      setDescription('');
      setLocation('');
      if (fileInputRef.current) fileInputRef.current.value = '';
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (caught) {
      setError(caught.message);
    } finally {
      setSubmitting(false);
    }
  }

  if (result) {
    return <ResultPanel complaint={result} onReset={resetForm} />;
  }

  return (
    <div className="page">
      <header className="page__head">
        <p className="eyebrow">Student submission</p>
        <h1>Report a campus problem</h1>
        <p className="page__lede">
          Add a photo and a few words. The backend analyses the image, assigns a
          priority where it can, and stores the complaint either way.
        </p>
      </header>

      <ErrorBanner
        title="The complaint was not submitted"
        message={error}
        onRetry={() => setError(null)}
        retryLabel="Dismiss"
      />

      <form className="panel form" onSubmit={onSubmit} noValidate>
        <div className="form__media">
          <label className="field" htmlFor="image">
            <span>Photo of the problem</span>
            <input
              id="image"
              ref={fileInputRef}
              type="file"
              accept={ACCEPTED_IMAGE_EXTENSIONS}
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setProblems((previous) => ({ ...previous, image: undefined }));
              }}
              aria-describedby="image-hint"
            />
          </label>
          <p className="hint" id="image-hint">
            JPEG, PNG or WebP · up to {MAX_IMAGE_MB} MB
          </p>
          {problems.image ? (
            <p className="field__error" role="alert">{problems.image}</p>
          ) : null}

          {preview ? (
            <figure className="preview">
              <img src={preview} alt="Preview of the photo you selected" />
              <figcaption>{file?.name}</figcaption>
            </figure>
          ) : (
            <div className="preview preview--empty">
              <span aria-hidden="true">＋</span>
              <p>Your photo preview appears here</p>
            </div>
          )}
        </div>

        <div className="form__fields">
          <label className="field" htmlFor="description">
            <span>What is wrong?</span>
            <textarea
              id="description"
              rows={6}
              value={description}
              placeholder="The ceiling light in lab 3 has been flickering since Monday and buzzes when it is on."
              onChange={(event) => {
                setDescription(event.target.value);
                setProblems((previous) => ({ ...previous, description: undefined }));
              }}
              aria-invalid={Boolean(problems.description)}
            />
          </label>
          {problems.description ? (
            <p className="field__error" role="alert">{problems.description}</p>
          ) : null}

          <label className="field" htmlFor="location">
            <span>Where on campus?</span>
            <input
              id="location"
              type="text"
              value={location}
              placeholder="Block C · Lab 3 · 2nd floor"
              onChange={(event) => {
                setLocation(event.target.value);
                setProblems((previous) => ({ ...previous, location: undefined }));
              }}
              aria-invalid={Boolean(problems.location)}
            />
          </label>
          {problems.location ? (
            <p className="field__error" role="alert">{problems.location}</p>
          ) : null}

          <Notice tone="info">
            <p>
              Analysis runs on the server. If it fails, your report is still saved and
              shown as <strong>Unscored</strong> rather than given a guessed priority.
            </p>
          </Notice>

          <div className="form__actions">
            <button type="submit" className="btn btn--primary" disabled={submitting}>
              {submitting ? 'Submitting…' : 'Submit complaint'}
            </button>
            <a className="btn btn--ghost" href="#/dashboard">
              Open the dashboard
            </a>
          </div>

          {submitting ? (
            <p className="spinner spinner--inline" role="status" aria-live="polite">
              <span className="spinner__ring" aria-hidden="true" />
              <span>Sending the photo to the backend for analysis…</span>
            </p>
          ) : null}
        </div>
      </form>
    </div>
  );
}
