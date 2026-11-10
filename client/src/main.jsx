import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import { ProjectProvider } from './context/ProjectContext.jsx'
import './index.css'
import './theme.css'
import { ThemeProvider } from './theme/ThemeContext.jsx'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ThemeProvider><ProjectProvider>
      <App />
    </ProjectProvider></ThemeProvider>
  </React.StrictMode>,
)
