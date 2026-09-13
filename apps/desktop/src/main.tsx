import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import './styles/tokens.css';
import './styles/app.css';
import './styles/copilot-ux.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

const root = document.getElementById('root');
if (!root) throw new Error('ForgeCAD renderer root is missing');

let catalogStateReported = false;
let readyFrameOne = 0;
let readyFrameTwo = 0;

function reportCatalogState(state: 'ready' | 'failed', detail?: string) {
  if (catalogStateReported) return;
  catalogStateReported = true;
  window.forgeDesktop?.reportComponentCatalogState?.(state, detail);
}

function inspectCatalogStartup() {
  if (catalogStateReported) return;
  if (document.querySelector('[data-testid^="component-"]')) {
    readyFrameOne = window.requestAnimationFrame(() => {
      readyFrameTwo = window.requestAnimationFrame(() => reportCatalogState('ready'));
    });
    return;
  }
  const error = document.querySelector<HTMLElement>('.engine-state.error');
  if (error) reportCatalogState('failed', error.title || error.textContent?.trim() || 'Component catalog failed to load');
}

const catalogObserver = new MutationObserver(inspectCatalogStartup);
catalogObserver.observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'title'] });

ReactDOM.createRoot(root).render(
  <QueryClientProvider client={queryClient}>
    <App />
  </QueryClientProvider>,
);

inspectCatalogStartup();
window.addEventListener('beforeunload', () => {
  catalogObserver.disconnect();
  if (readyFrameOne) window.cancelAnimationFrame(readyFrameOne);
  if (readyFrameTwo) window.cancelAnimationFrame(readyFrameTwo);
});
