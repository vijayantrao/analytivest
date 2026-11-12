import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import './index.css'
import { ApiError } from './lib/api'
import Company from './pages/Company'
import Compare from './pages/Compare'
import Glossary from './pages/Glossary'
import Home from './pages/Home'
import IpoDetail from './pages/IpoDetail'
import IpoForm from './pages/IpoForm'
import IpoUpload from './pages/IpoUpload'
import Ipos from './pages/Ipos'
import Methodology from './pages/Methodology'
import Watchlist from './pages/Watchlist'
import Alerts from './pages/Alerts'
import Settings from './pages/Settings'
import Portfolio from './pages/Portfolio'
import Screener from './pages/Screener'

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 5 * 60_000,
      retry: (n, e) => !(e instanceof ApiError && (e.status === 404 || e.status === 400 || e.status === 422)) && n < 1,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Home />} />
            <Route path="c/:symbol" element={<Company />} />
            <Route path="c/:symbol/:tab" element={<Company />} />
            <Route path="ipo" element={<Ipos />} />
            <Route path="ipo/new" element={<IpoForm />} />
            <Route path="ipo/upload" element={<IpoUpload />} />
            <Route path="ipo/:id/edit" element={<IpoForm />} />
            <Route path="ipo/:id" element={<IpoDetail />} />
            <Route path="compare" element={<Compare />} />
            <Route path="watchlist" element={<Watchlist />} />
            <Route path="portfolio" element={<Portfolio />} />
            <Route path="screener" element={<Screener />} />
            <Route path="alerts" element={<Alerts />} />
            <Route path="settings" element={<Settings />} />
            <Route path="methodology" element={<Methodology />} />
            <Route path="glossary" element={<Glossary />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
