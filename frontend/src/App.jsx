import { useCallback, useEffect, useState } from 'react';

import { fetchHealth } from './api.js';
import DashboardPage from './pages/DashboardPage.jsx';
import SubmitPage from './pages/SubmitPage.jsx';

/**
 * Routing is a tiny hash router (#/submit, #/dashboard). No router dependency
 * is needed, and hash routes survive a static `vite preview` with no server
 * rewrite rules.
 */
const ROUTES = [
  { hash: '#/submit', label: 'Report a problem', short: 'Student' },
  { hash: '#/dashboard', label: 'Operations dashboard', short: 'Admin' },
];

function activeRoute() {
  const { hash } = window.location;
  return ROUTES.some((route) => route.hash === hash) ? hash : ROUTES[0].hash;
}

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
  checking: 'Checking API…',
  up: 'API online',
  down: 'API unreachable',
};

export default function App() {
  const [route, setRoute] = useState(activeRoute);
  const [health, retryHealth] = useHealth();

  useEffect(() => {
    const onHashChange = () => {
      setRoute(activeRoute());
      window.scrollTo({ top: 0, behavior: 'instant' });
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar__inner">
          <a className="brand" href="#/submit">
            <span className="brand__mark" aria-hidden="true">CL</span>
            <span className="brand__text">
              <strong>CampusLens</strong>
              <small>Campus operations</small>
            </span>
          </a>

          <nav className="nav" aria-label="Primary">
            {ROUTES.map((item) => {
              const active = item.hash === route;
              return (
                <a
                  key={item.hash}
                  href={item.hash}
                  className={`nav__link${active ? ' is-active' : ''}`}
                  aria-current={active ? 'page' : undefined}
                >
                  <span className="nav__label">{item.label}</span>
                  <span className="nav__short">{item.short}</span>
                </a>
              );
            })}
          </nav>

          <button
            type="button"
            className={`apipill apipill--${health.state}`}
            onClick={retryHealth}
            title="Re-check the backend"
          >
            <span className={`dot dot--${health.state}`} aria-hidden="true" />
            <span>{HEALTH_LABEL[health.state]}</span>
            {health.state === 'up' && health.data ? (
              <span className="apipill__meta">v{health.data.version}</span>
            ) : null}
          </button>
        </div>
      </header>

      <main className="shell">
        {route === '#/dashboard' ? <DashboardPage /> : <SubmitPage />}
      </main>

      <footer className="footer">
        <p>
          Priority scores, bands and AI findings are produced by the CampusLens
          backend. Complaints without a score are shown as <strong>Unscored</strong> —
          they are never treated as Low priority.
        </p>
      </footer>
    </div>
  );
}
