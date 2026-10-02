import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import App from './App.jsx';
import './styles.css';

// Reloads always start at the top of the page so the page heading and intro
// are fully visible; otherwise the browser restores the previous scroll
// offset and the heading appears cut off at the top of the viewport.
if ('scrollRestoration' in history) {
  history.scrollRestoration = 'manual';
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
