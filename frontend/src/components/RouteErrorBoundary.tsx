import React from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import ErrorCard from '@/components/ErrorCard'

type Props = { children: React.ReactNode; resetKey: string; navigate: (path: string) => void; fullScreen?: boolean }
type State = { hasError: boolean; message: string }

/**
 * Catches a crash in a page and shows the themed card in its place.
 * Placed around the page area inside the app shell, so the sidebar and top bar stay.
 * "Reload" tries to draw the page again without a full browser reload (a full
 * reload would sign the desktop app out).
 */
export class RouteErrorBoundaryInner extends React.Component<Props, State> {
  state: State = { hasError: false, message: '' }
  static getDerivedStateFromError(err: Error): State {
    return { hasError: true, message: err?.message ?? 'Unknown error' }
  }
  componentDidUpdate(prev: { resetKey: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.hasError) {
      this.setState({ hasError: false, message: '' })
    }
  }
  render() {
    if (!this.state.hasError) return this.props.children
    return (
      <ErrorCard
        fullScreen={this.props.fullScreen}
        message={this.state.message}
        onDashboard={() => { this.setState({ hasError: false, message: '' }); this.props.navigate('/dashboard') }}
        onReload={() => this.setState({ hasError: false, message: '' })}
      />
    )
  }
}

export default function RouteErrorBoundary({ children, fullScreen }: { children: React.ReactNode; fullScreen?: boolean }) {
  const location = useLocation()
  const navigate = useNavigate()
  return (
    <RouteErrorBoundaryInner resetKey={location.pathname} navigate={navigate} fullScreen={fullScreen}>
      {children}
    </RouteErrorBoundaryInner>
  )
}
