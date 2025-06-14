// Main application entry point

import { createRoot } from "react-dom/client";
import { App } from "./App.js";
import type { Config } from "@pants-example/common-types";

// Application configuration
const config: Config = {
  apiUrl: "https://api.example.com",
  timeout: 5000,
  retries: 3,
};

// Initialize the React application
function initializeApp() {
  const container = document.getElementById("root");
  if (!container) {
    throw new Error("Root element not found");
  }

  const root = createRoot(container);
  root.render(App({ config }));
}

// Start the application
document.addEventListener("DOMContentLoaded", initializeApp);
