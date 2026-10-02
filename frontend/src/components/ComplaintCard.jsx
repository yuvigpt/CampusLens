import { imageUrl } from '../api.js';
import { UNCLASSIFIED_LABEL } from '../constants.js';
import { PriorityBadge, ScoreMeter, UnscoredNote } from './Priority.jsx';
import { StatusBadge, StatusSelect } from './Status.jsx';

const has = (value) => typeof value === 'string' && value.trim().length > 0;

function Detail({ term, value }) {
  return (
    <div className="detail">
      <dt>{term}</dt>
      <dd>{has(value) ? value : <span className="muted">Not reported by the model</span>}</dd>
    </div>
  );
}

/**
 * One complaint in the admin list.
 *
 * `analysis` and `warnings` are only present on the POST /api/complaints
 * response - list and detail endpoints always return analysis: null. The
 * persisted AI fields (category, summary, risk, impact, urgency, evidence,
 * uncertainty) are what we show here.
 */
export default function ComplaintCard({ complaint, onStatusChange, busy }) {
  const {
    id,
    description,
    location,
    image_url: imageUrlValue,
    category,
    issue_summary: issueSummary,
    safety_risk: safetyRisk,
    functional_impact: functionalImpact,
    urgency,
    evidence_from_image: evidence,
    uncertainty_or_missing_information: uncertainty,
    priority_score: score,
    priority_band: band,
    status,
    created_at: createdAt,
  } = complaint;

  const src = imageUrl(imageUrlValue);
  const unscored = score == null || band == null;

  return (
    <article className="card" aria-labelledby={`complaint-${id}`}>
      <header className="card__head">
        <div className="card__idline">
          <span className="card__number">#{id}</span>
          <StatusBadge status={status} />
          {createdAt ? <span className="card__time">{createdAt} UTC</span> : null}
        </div>
        <PriorityBadge band={band} score={score} />
      </header>

      <div className="card__grid">
        <div className="card__main">
          <p className="card__description">{description}</p>
          <p className="card__location">
            <span aria-hidden="true">⌖</span> {location}
          </p>

          <div className="chips">
            <span className={`chip${category ? '' : ' chip--muted'}`}>
              {category || `${UNCLASSIFIED_LABEL} · no category`}
            </span>
            {safetyRisk ? <span className="chip chip--soft">Safety: {safetyRisk}</span> : null}
            {urgency ? <span className="chip chip--soft">Urgency: {urgency}</span> : null}
            {functionalImpact ? (
              <span className="chip chip--soft">Impact: {functionalImpact}</span>
            ) : null}
          </div>

          {has(issueSummary) ? <p className="card__summary">{issueSummary}</p> : null}

          {has(uncertainty) ? (
            <div className="callout callout--uncertainty">
              <strong>Uncertainty / missing information</strong>
              <p>{uncertainty}</p>
            </div>
          ) : null}

          {unscored ? <UnscoredNote /> : null}

          <details className="details">
            <summary>Full AI assessment</summary>
            <dl className="detail-list">
              <Detail term="Issue summary" value={issueSummary} />
              <Detail term="Safety risk" value={safetyRisk} />
              <Detail term="Functional impact" value={functionalImpact} />
              <Detail term="Urgency" value={urgency} />
              <Detail term="Evidence from image" value={evidence} />
              <Detail term="Uncertainty / missing information" value={uncertainty} />
            </dl>
          </details>
        </div>

        <aside className="card__side">
          {src ? (
            <a className="thumb" href={src} target="_blank" rel="noreferrer">
              <img src={src} alt={`Photo uploaded with complaint ${id}`} loading="lazy" />
            </a>
          ) : (
            <div className="thumb thumb--empty">No photo</div>
          )}

          <ScoreMeter band={band} score={score} />

          <label className="field field--compact" htmlFor={`status-${id}`}>
            <span>Status</span>
            <StatusSelect
              id={`status-${id}`}
              complaintId={id}
              value={status}
              disabled={busy}
              onChange={(next) => onStatusChange(complaint, next)}
            />
          </label>
          {busy ? <p className="muted small">Saving status…</p> : null}
        </aside>
      </div>
    </article>
  );
}
