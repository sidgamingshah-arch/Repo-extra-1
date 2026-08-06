import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { ApiError } from "./lib/api";
import { useUI } from "./store";
import "./index.css";

const isUnauthorized = (err: unknown) => err instanceof ApiError && err.status === 401;

// Any 401 (from /me OR any data query — e.g. a session that expires mid-screen) clears
// the session token, which returns the whole app to the login screen. 401s are never
// retried; other errors get a couple of retries.
const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (err) => {
      if (isUnauthorized(err)) useUI.getState().setToken(null);
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: (count, err) => !isUnauthorized(err) && count < 2,
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
