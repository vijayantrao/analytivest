import { useQuery } from '@tanstack/react-query'
import { Loader2, Search } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type SearchGroup } from '../lib/api'
import { cx } from './ui'

function useDebounced<T>(v: T, ms: number) {
  const [d, setD] = useState(v)
  useEffect(() => {
    const t = setTimeout(() => setD(v), ms)
    return () => clearTimeout(t)
  }, [v, ms])
  return d
}

const SYMBOL_LIKE = /^[A-Za-z0-9&-]+\.(NS|BO)$/i

export function SearchBox({ size = 'md', autoFocus, globalShortcut, onSelect, placeholder }: {
  size?: 'md' | 'lg'; autoFocus?: boolean; globalShortcut?: boolean; onSelect?: (symbol: string) => void; placeholder?: string
}) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const dq = useDebounced(q.trim(), 250)
  const nav = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const listId = useId()
  const { data, isFetching, isError, error } = useQuery({
    queryKey: ['search', dq], queryFn: () => api.search(dq), enabled: dq.length >= 1, staleTime: 5 * 60_000,
  })
  const results: SearchGroup[] = data?.results || []

  useEffect(() => {
    if (!globalShortcut) return
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName)) {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [globalShortcut])

  useEffect(() => setActive(0), [dq])

  const go = (symbol: string) => {
    setOpen(false)
    setQ('')
    inputRef.current?.blur()
    if (onSelect) onSelect(symbol.toUpperCase())
    else nav(`/c/${encodeURIComponent(symbol.toUpperCase())}`)
  }

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setActive((a) => Math.min(a + 1, results.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
    else if (e.key === 'Escape') { setOpen(false) }
    else if (e.key === 'Enter') {
      e.preventDefault()
      if (results[active]) go(results[active].primary_symbol)
      else if (SYMBOL_LIKE.test(q.trim())) go(q.trim())
    }
  }

  const big = size === 'lg'
  return (
    <div className="relative w-full">
      <div className={cx('flex items-center gap-2 rounded-xl border border-line bg-surface focus-within:border-accent', big ? 'px-4 py-3' : 'px-3 py-1.5')}>
        <Search size={big ? 20 : 16} className="shrink-0 text-muted" aria-hidden />
        <input ref={inputRef} value={q} autoFocus={autoFocus}
          onChange={(e) => { setQ(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)} onKeyDown={onKey}
          role="combobox" aria-expanded={open && results.length > 0} aria-controls={listId} aria-autocomplete="list"
          aria-activedescendant={results[active] ? `${listId}-${active}` : undefined}
          aria-label="Search company name, NSE/BSE symbol or ticker"
          placeholder={placeholder || (big ? 'Company name or symbol, e.g. "TCS", "HDFC Bank", "RELIANCE.NS"' : 'Search company or symbol…')}
          className={cx('w-full bg-transparent text-ink outline-none placeholder:text-muted', big ? 'text-base' : 'text-sm')} />
        {isFetching ? <Loader2 size={16} className="animate-spin text-muted" aria-label="Searching" />
          : globalShortcut && <kbd className="hidden rounded border border-line px-1.5 text-[11px] text-muted sm:inline">/</kbd>}
      </div>
      {open && dq.length >= 1 && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 overflow-hidden rounded-xl border border-line bg-surface shadow-xl">
          {isError ? (
            <p className="p-3 text-sm text-neg">{(error as Error).message}</p>
          ) : results.length === 0 && !isFetching ? (
            <p className="p-3 text-sm text-muted">No listed equities found for “{dq}”. Try the NSE symbol (e.g. INFY) or full name.</p>
          ) : (
            <ul id={listId} role="listbox" className="max-h-96 overflow-y-auto py-1">
              {results.map((r, i) => (
                <li key={r.primary_symbol} id={`${listId}-${i}`} role="option" aria-selected={i === active}
                  onMouseDown={(e) => { e.preventDefault(); go(r.primary_symbol) }} onMouseEnter={() => setActive(i)}
                  className={cx('cursor-pointer px-3 py-2', i === active && 'bg-surface-2')}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium text-ink">{r.name}</span>
                    <span className="flex shrink-0 gap-1">
                      {r.listings.slice(0, 3).map((l) => (
                        <button key={l.symbol} tabIndex={-1}
                          onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); go(l.symbol) }}
                          className="rounded border border-line px-1.5 py-0.5 text-[11px] text-ink-2 hover:border-accent hover:text-accent"
                          title={`Open ${l.symbol}`}>
                          {l.exchange || '?'} · {l.symbol}
                        </button>
                      ))}
                    </span>
                  </div>
                  <div className="mt-0.5 text-xs text-muted">
                    {[r.industry || r.sector, r.is_sample ? 'Sample data' : null, r.duplicate_listings ? 'Listed on multiple exchanges (NSE shown by default)' : null].filter(Boolean).join(' · ')}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
