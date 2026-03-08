import { Component, type ReactNode } from "react";
import { type Location } from "react-router-dom";

type Props = {
    location: Location;
    children: ReactNode;
};

type State = {
    hasError: boolean;
};

export class RouteErrorBoundary extends Component<Props, State> {
    constructor(props: Props) {
        super(props);
        this.state = { hasError: false };
    }

    static getDerivedStateFromError(): State {
        return { hasError: true };
    }

    componentDidUpdate(prevProps: Readonly<Props>) {
        if (this.state.hasError && prevProps.location !== this.props.location) {
            this.setState({ hasError: false });
        }
    }

    render() {
        if (this.state.hasError) {
            return (
                <div className="mx-auto max-w-xl py-16 text-center">
                    <h2 className="font-display text-2xl font-bold text-slate-800">
                        Something went wrong
                    </h2>
                    <p className="mt-3 text-sm text-slate-600">
                        An unexpected error occurred while rendering this page. Try
                        reloading or navigating to another tab.
                    </p>
                    <button
                        className="mt-6 rounded-xl bg-slate-800 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-700"
                        type="button"
                        onClick={() => window.location.reload()}
                    >
                        Reload Page
                    </button>
                </div>
            );
        }
        return this.props.children;
    }
}
