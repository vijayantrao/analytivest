import { useEffect, useState } from 'react'

export type ThemeChoice = 'light' | 'dark' | 'system'

const KEY = 'stockiq-theme'
const EVT = 'stockiq-themechange'

export function getChoice(): ThemeChoice {
  try {
    const t = localStorage.getItem(KEY)
    if (t === 'light' || t === 'dark') return t
  } catch {
    /* storage blocked */
  }
  return 'system'
}

export function setChoice(c: ThemeChoice) {
  try {
    if (c === 'system') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, c)
  } catch {
    /* storage blocked: theme still applies for this session */
  }
  if (c === 'system') delete document.documentElement.dataset.theme
  else document.documentElement.dataset.theme = c
  window.dispatchEvent(new Event(EVT))
}

export function useThemeChoice(): [ThemeChoice, (c: ThemeChoice) => void] {
  const [c, setC] = useState<ThemeChoice>(getChoice)
  useEffect(() => {
    const h = () => setC(getChoice())
    window.addEventListener(EVT, h)
    return () => window.removeEventListener(EVT, h)
  }, [])
  return [c, setChoice]
}

/** Resolved chart colours from CSS tokens; re-read whenever the theme changes. */
export function useChartColors() {
  const read = () => {
    const s = getComputedStyle(document.documentElement)
    const v = (n: string) => s.getPropertyValue(n).trim()
    return {
      s1: v('--series-1'), s2: v('--series-2'), s3: v('--series-3'),
      grid: v('--grid'), axis: v('--axis'), surface: v('--surface'), text: v('--text'), text2: v('--text-2'),
      muted: v('--muted'), border: v('--border-strong'), neg: v('--status-critical'),
    }
  }
  const [c, setC] = useState(read)
  useEffect(() => {
    const h = () => requestAnimationFrame(() => setC(read()))
    window.addEventListener(EVT, h)
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    mq.addEventListener('change', h)
    return () => {
      window.removeEventListener(EVT, h)
      mq.removeEventListener('change', h)
    }
  }, [])
  return c
}
