import { BookOpen, BriefcaseBusiness, Columns3, Filter, Menu, Monitor, Moon, Rocket, Settings, Star, Sun, X } from 'lucide-react'
import { useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useThemeChoice, type ThemeChoice } from '../lib/theme'
import { AlertBell } from '../pages/Alerts'
import { ErrorBoundary } from './ErrorBoundary'
import { SearchBox } from './SearchBox'
import { Disclaimer, cx } from './ui'

const links = [
  { to: '/portfolio', label: 'Portfolio', icon: BriefcaseBusiness },
  { to: '/screener', label: 'Screener', icon: Filter },
  { to: '/ipo', label: 'IPOs', icon: Rocket },
  { to: '/compare', label: 'Compare', icon: Columns3 },
  { to: '/watchlist', label: 'Watchlist', icon: Star },
  { to: '/methodology', label: 'Methodology', icon: BookOpen },
]

function ThemeToggle() {
  const [choice, set] = useThemeChoice()
  const next: Record<ThemeChoice, ThemeChoice> = { system: 'light', light: 'dark', dark: 'system' }
  const Icon = choice === 'light' ? Sun : choice === 'dark' ? Moon : Monitor
  return (
    <button onClick={() => set(next[choice])} className="rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-ink"
      aria-label={`Theme: ${choice}. Switch to ${next[choice]}`} title={`Theme: ${choice}`}>
      <Icon size={18} aria-hidden />
    </button>
  )
}

export function Layout() {
  const [menu, setMenu] = useState(false)
  const loc = useLocation()
  const home = loc.pathname === '/'
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:p-2">Skip to content</a>
      <header className="sticky top-0 z-40 border-b border-line bg-surface/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-4">
          <Link to="/" className="flex shrink-0 items-center gap-2 font-semibold text-ink" aria-label="Analytivest home">
            <img src="/favicon.svg" alt="" className="h-7 w-7" />
            <span className="hidden sm:inline">Analytivest</span>
          </Link>
          {!home && <div className="mx-2 max-w-md flex-1"><SearchBox globalShortcut /></div>}
          {home && <div className="flex-1" />}
          <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
            {links.map((l) => (
              <NavLink key={l.to} to={l.to} className={({ isActive }) => cx('rounded-lg px-3 py-1.5 text-sm', isActive ? 'bg-accent-soft text-accent-ink' : 'text-ink-2 hover:bg-surface-2 hover:text-ink')}>
                {l.label}
              </NavLink>
            ))}
          </nav>
          <AlertBell />
          <NavLink to="/settings" className={({ isActive }) => cx('rounded-lg p-2 hover:bg-surface-2 hover:text-ink', isActive ? 'text-accent' : 'text-muted')}
            aria-label="Data & security settings" title="Data & security">
            <Settings size={18} aria-hidden />
          </NavLink>
          <ThemeToggle />
          <button className="rounded-lg p-2 text-muted hover:bg-surface-2 md:hidden" onClick={() => setMenu((m) => !m)} aria-expanded={menu} aria-label="Menu">
            {menu ? <X size={18} /> : <Menu size={18} />}
          </button>
        </div>
        {menu && (
          <nav aria-label="Main mobile" className="border-t border-line px-4 py-2 md:hidden">
            {links.map((l) => (
              <NavLink key={l.to} to={l.to} onClick={() => setMenu(false)} className="flex items-center gap-2 rounded-lg px-2 py-2 text-sm text-ink-2 hover:bg-surface-2">
                <l.icon size={16} aria-hidden /> {l.label}
              </NavLink>
            ))}
          </nav>
        )}
      </header>
      <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-5">
        <ErrorBoundary resetKey={loc.pathname}>
          <Outlet />
        </ErrorBoundary>
      </main>
      <footer className="border-t border-line">
        <div className="mx-auto max-w-7xl space-y-1 px-4 py-4">
          <Disclaimer />
          <p className="text-xs text-muted">
            Data: Yahoo Finance via yfinance (free, personal use; delayed quotes). <Link to="/glossary" className="underline">Glossary</Link> · <Link to="/methodology" className="underline">How scores are calculated</Link>
          </p>
        </div>
      </footer>
    </div>
  )
}
