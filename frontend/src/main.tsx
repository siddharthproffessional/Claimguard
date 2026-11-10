import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "@/components/layout/Layout";
import { LiveProvider } from "@/hooks/useLive";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-sans/700.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@/index.css";
import AgentRoom from "@/pages/AgentRoom";
import Analytics from "@/pages/Analytics";
import Audit from "@/pages/Audit";
import ClaimDetail from "@/pages/ClaimDetail";
import Claims from "@/pages/Claims";
import CommandCentre from "@/pages/CommandCentre";
import Corrections from "@/pages/Corrections";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <LiveProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<CommandCentre />} />
            <Route path="claims" element={<Claims />} />
            <Route path="claims/:id" element={<ClaimDetail />} />
            <Route path="agents" element={<AgentRoom />} />
            <Route path="corrections" element={<Corrections />} />
            <Route path="analytics" element={<Analytics />} />
            <Route path="audit" element={<Audit />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </LiveProvider>
  </React.StrictMode>
);
