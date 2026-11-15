import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ErrorBoundary } from '../components/ErrorBoundary'

let broken = true
function Page() {
  if (broken) throw new Error('profile.name is undefined')
  return <p>Page content</p>
}

afterEach(() => {
  cleanup()
  broken = true
  vi.restoreAllMocks()
})

describe('ErrorBoundary', () => {
  it('shows a recoverable message instead of a blank app', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<><nav>Navigation</nav><ErrorBoundary><Page /></ErrorBoundary></>)
    expect(screen.getByRole('alert').textContent).toContain('profile.name is undefined')
    expect(screen.getByText('Navigation')).toBeTruthy() // the rest of the app is still there
    broken = false
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(screen.getByText('Page content')).toBeTruthy()
  })

  it('clears the error when the user navigates to another page', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const { rerender } = render(<ErrorBoundary resetKey="/c/AAA"><Page /></ErrorBoundary>)
    expect(screen.getByRole('alert')).toBeTruthy()
    broken = false
    act(() => rerender(<ErrorBoundary resetKey="/c/BBB"><Page /></ErrorBoundary>))
    expect(screen.getByText('Page content')).toBeTruthy()
  })
})
