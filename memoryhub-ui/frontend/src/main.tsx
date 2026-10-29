import React from 'react';
import ReactDOM from 'react-dom/client';
// PatternFly 6 base styles bundle the Red Hat Display, Text and Mono fonts.
import '@patternfly/react-core/dist/styles/base.css';
import App from './App';
// Loaded after PatternFly so the dashboard styles take precedence.
import './styles/app.css';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('Root element #root not found in document');
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
