import { imageUrl } from '../api.js';
import { PriorityBadge, ScoreMeter, UnscoredNote } from './Priority.jsx';
import { StatusBadge } from './Status.jsx';

const has = (value) => typeof value === 'string' && value.trim().length > 0;

function Value({ children }) {
  if (has(children)) return <span>{children}</span>;
  return <span className="muted">Not provided</span>;
}

/**
 * Everything shown here is copied from the POST /api/complaints response -
 * nothing is inferred, filled in, or rounded into a friendlier story.
 */
export default function ResultPanel({ complaint, onReset }) {
  const analysis = complaint.analysis;
  const warnings = Array.isArray(complaint.warnings) ? complaint.warnings : [];
  const src = imageUrl(complaint.image_url);
  const unscored = complaint.priority_score == null || complaint.priority_band == null;

  return (
    <section className="result" aria-live="polite">
      <div className="result__head">
        <span className="result__mark" aria-hidden="true">✓</span>
        <div className="result__title">
          <h2>Complaint #{complaint.id} received</h2>
          <p className="muted">
            The backend stored it as <strong>{complaint.status}</strong>.
          </p>
        </div>
        <StatusBadge status={complaint.status} />
      </div>

      <div className="result__grid">
        <figure className="result__media">
          {src ? (
            <img src={src} alt="The photo you uploaded" />
          ) : (
            <div className="thumb thumb--empty">No photo stored</div>
          )}
          <figcaption>{complaint.location}</figcaption>
        </figure>

        <div className="result__body">
          <div className="result__priority">
            <PriorityBadge band={complaint.priority_band} score={complaint.priority_score} />
            <ScoreMeter band={complaint.priority_band} score={complaint.priority_score} />
          </div>
          {unscored ? <UnscoredNote /> : null}

          <dl className="detail-list detail-list--result">
            <div className="detail">
              <dt>Category</dt>
              <dd><Value>{complaint.category}</Value></dd>
            </div>
            <div className="detail">
              <dt>What you reported</dt>
              <dd>{complaint.description}</dd>
            </div>
            <div className="detail">
              <dt>Issue summary</dt>
              <dd><Value>{complaint.issue_summary}</Value></dd>
            </div>
            <div className="detail">
              <dt>Safety risk</dt>
              <dd><Value>{complaint.safety_risk}</Value></dd>
            </div>
            <div className="detail">
              <dt>Functional impact</dt>
              <dd><Value>{complaint.functional_impact}</Value></dd>
            </div>
            <div className="detail">
              <dt>Urgency</dt>
              <dd><Value>{complaint.urgency}</Value></dd>
            </div>
            <div className="detail">
              <dt>Evidence from image</dt>
              <dd><Value>{complaint.evidence_from_image}</Value></dd>
            </div>
          </dl>

          <div className="callout callout--uncertainty">
            <strong>Uncertainty / missing information</strong>
            <p>
              {has(complaint.uncertainty_or_missing_information)
                ? complaint.uncertainty_or_missing_information
                : 'The model reported no additional uncertainty for this complaint.'}
            </p>
          </div>

          {analysis ? (
            <details className="details" open={!analysis.ok}>
              <summary>AI analysis details</summary>
              <dl className="detail-list">
                <div className="detail">
                  <dt>Outcome</dt>
                  <dd>{analysis.ok ? 'Completed' : 'Not completed'}</dd>
                </div>
                <div className="detail">
                  <dt>Model</dt>
                  <dd><Value>{analysis.model}</Value></dd>
                </div>
                <div className="detail">
                  <dt>Elapsed</dt>
                  <dd>
                    {typeof analysis.elapsed_seconds === 'number'
                      ? `${analysis.elapsed_seconds.toFixed(2)} s`
                      : 'Not provided'}
                  </dd>
                </div>
                {analysis.error ? (
                  <div className="detail detail--warn">
                    <dt>Error</dt>
                    <dd>{analysis.error}</dd>
                  </div>
                ) : null}
                {analysis.error_kind ? (
                  <div className="detail">
                    <dt>Error kind</dt>
                    <dd>{analysis.error_kind}</dd>
                  </div>
                ) : null}
              </dl>
            </details>
          ) : (
            <p className="muted small">No analysis outcome was returned with this submission.</p>
          )}

          {warnings.length > 0 ? (
            <div className="callout callout--warning">
              <strong>
                {warnings.length} {warnings.length === 1 ? 'notice' : 'notices'} from the backend
              </strong>
              <ul>
                {warnings.map((warning, index) => (
                  <li key={`${index}-${warning}`}>{warning}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="result__actions">
            <button type="button" className="btn btn--primary" onClick={onReset}>
              Report another problem
            </button>
            <a className="btn btn--ghost" href="#/dashboard">
              View it in the dashboard
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
