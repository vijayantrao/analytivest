import { Component, type ErrorInfo, type ReactNode } from 'react'

/**
 * Catches a rendering error in one page so it cannot blank the whole app. Without it, one unexpected value in a
 * single tab (say, a missing field from the data provider) would unmount everything, including the navigation.
 * `resetKey` (the current URL) clears the error when the user navigates elsewhere.
 */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null }> {
  state: { error: Error | null } = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Page crashed:', error, info.componentStack)
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null })
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <div role="alert" className="mx-auto max-w-xl rounded-xl border border-line bg-surface p-5">
        <p className="font-semibold">This page hit an unexpected error</p>
        <p className="mt-1 text-sm text-muted">
          The rest of the app still works. Try again, or go back and open another page. The details are in the browser
          console (F12) if you want to report them.
        </p>
        <p className="mt-3 rounded-md bg-surface-2 px-3 py-2 font-mono text-xs text-ink-2">{error.message}</p>
        <button
          type="button"
          onClick={() => this.setState({ error: null })}
          className="mt-4 rounded-md border border-line px-3 py-1.5 text-sm text-ink hover:bg-surface-2"
        >
          Try again
        </button>
      </div>
    )
  }
}
