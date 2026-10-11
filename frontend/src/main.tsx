import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { makeQueryClient, Providers } from "@/app/providers";
import { AppRoutes } from "@/app/routes";

import "./index.css";

const queryClient = makeQueryClient();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Providers client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </Providers>
  </StrictMode>,
);
