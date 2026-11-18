import React from 'react';
import { Empty } from '@/components/ui';

interface Props {
  children: React.ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Catches a render error in one screen so the menu, header and other screens keep working.
 * App.tsx keys it by route, so moving to another screen starts with a clean boundary.
 */
export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('Screen failed to render', error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="body">
        <div className="card" role="alert">
          <Empty
            title="This screen could not be shown"
            action={
              <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
                <button type="button" className="btn bp" onClick={() => this.setState({ error: null })}>
                  Try again
                </button>
                <button type="button" className="btn bs" onClick={() => window.location.reload()}>
                  Reload the page
                </button>
              </div>
            }
          >
            The data from the server was not in the expected shape. Other screens still work from the menu. Details: {error.message}
          </Empty>
        </div>
      </div>
    );
  }
}
