import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MotionConfig } from 'framer-motion'
import './index.css'
import App from './App.jsx'
import { LanguageProvider } from './i18n.jsx'

// reducedMotion="user": TODAS las animaciones de framer-motion (modales,
// menús, whileHover/whileTap) respetan la preferencia "reducir movimiento"
// del SO (WCAG 2.3.3). Complementa la media query CSS de index.css, que solo
// cubre animaciones CSS.
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <MotionConfig reducedMotion="user">
      <LanguageProvider>
        <App />
      </LanguageProvider>
    </MotionConfig>
  </StrictMode>,
)
