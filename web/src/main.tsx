import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'
import './styles/theme.css'

const client = new QueryClient({
  defaultOptions: {
    queries: {
      // The corpus is local and nothing in it moves without a scan, so asking
      // again on every mount buys nothing. Refocusing the window is different:
      // a sweep may well have finished while you were elsewhere.
      staleTime: 10_000,
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
})

const root = document.getElementById('root')
if (!root) throw new Error('missing #root element')

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
