import { NavLink, Route, Routes } from 'react-router-dom'
import Library from './pages/Library'
import Generate from './pages/Generate'
import Learn from './pages/Learn'
import EpicsHome from './pages/epics/EpicsHome'
import Kandas from './pages/epics/Kandas'
import Sargas from './pages/epics/Sargas'
import SargaView from './pages/epics/SargaView'
import Settings from './pages/Settings'
import Terminal from './pages/Terminal'

export default function App() {
  return (
    <>
      <nav className="app-nav">
        <span className="brand">Sanskrit Śloka Studio</span>
        <NavLink to="/library">Library</NavLink>
        <NavLink to="/generate">Generate</NavLink>
        <NavLink to="/epics">Epics</NavLink>
        <NavLink to="/terminal">EC2 Terminal</NavLink>
        <NavLink to="/settings">Settings</NavLink>
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<Library />} />
          <Route path="/library" element={<Library />} />
          <Route path="/generate" element={<Generate />} />
          <Route path="/learn/:jobId" element={<Learn />} />
          <Route path="/epics" element={<EpicsHome />} />
          <Route path="/epics/:epic" element={<Kandas />} />
          <Route path="/epics/:epic/:kanda" element={<Sargas />} />
          <Route path="/epics/:epic/:kanda/:sarga" element={<SargaView />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/terminal" element={<Terminal />} />
        </Routes>
      </main>
    </>
  )
}
