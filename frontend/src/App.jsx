import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import Runbook from './pages/Runbook'; // Make sure this matches your new component name
import EngineerDetail from './pages/EngineerDetail';

function App() {
  return (
    <Router>
      <div className="min-h-screen">
        <Routes>
          {/* The main executive dashboard */}
          <Route path="/" element={<Dashboard />} />
          
          {/* The generalized SOP page. The :severity part acts as our variable ('critical', 'moderate', 'low') */}
          <Route path="/runbook/:severity/:userId" element={<Runbook />} />

          {/* Detailed engineer analytics view */}
          <Route path="/engineer/:userId" element={<EngineerDetail />} />
        </Routes>
      </div>
    </Router>
  );
}

export default App;