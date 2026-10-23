import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./styles.css";

const apiUrl = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

function App() {
  return (
    <main className="shell">
      <p className="eyebrow">BLACKOUT / FOUNDATION</p>
      <h1>Infrastructure under stress.</h1>
      <p className="intro">
        A deterministic decision-support system for understanding what fails
        next, what matters most, and which interventions help.
      </p>
      <a href={`${apiUrl}/api/health`} target="_blank" rel="noreferrer">
        Check backend health
      </a>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
