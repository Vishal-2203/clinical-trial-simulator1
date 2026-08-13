import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { AnimatePresence, motion } from 'framer-motion';
import {
  Activity,
  BarChart2,
  Beaker,
  BookOpen,
  Building2,
  ChevronRight,
  DollarSign,
  FileCheck,
  FlaskConical,
  Globe,
  History,
  Pause,
  Pill,
  Play,
  Shield,
  ShieldCheck,
  Sliders,
  Terminal,
  TrendingUp,
  Users,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { useTrialStore } from './store';
import AgentAnalysis from './views/AgentAnalysis';
import ConfigModal from './components/ConfigModal';
import DrugComposition from './views/DrugComposition';
import DSMBConsole from './views/DSMBConsole';
import EconomicsDashboard from './views/EconomicsDashboard';
import HindsightReplay from './views/HindsightReplay';
import InteractiveTrial from './views/InteractiveTrial';
import LandingPage from './LandingPage';
import MedicalEvidence from './views/MedicalEvidence';
import NovelPathogenAnalyzer from './views/NovelPathogenAnalyzer';
import PatientCohort from './views/PatientCohort';
import PatientSimulator from './views/PatientSimulator';
import PKPDDashboard from './views/PKPDDashboard';
import PolicyBenchmarks from './views/PolicyBenchmarks';
import RegulatoryTimeline from './views/RegulatoryTimeline';
import SiteOperations from './views/SiteOperations';
import StatisticalEngine from './views/StatisticalEngine';
import SystemLogs from './views/SystemLogs';
import WorldMedicalNews from './views/WorldMedicalNews';

const API_BASE = 'http://localhost:8000';

const NAV_ITEMS = [
  { id: 'patient_simulator', label: 'Patient Simulator', icon: Activity, desc: 'Interactive Vitals', group: 'Trial Workspace' },
  { id: 'trial', label: 'Interactive Trial', icon: FlaskConical, desc: 'Control Room', group: 'Trial Workspace' },
  { id: 'novel_pathogen', label: 'Novel Pathogen', icon: Beaker, desc: 'DTI Predictor', group: 'Trial Workspace' },
  { id: 'patients', label: 'Patient Cohort', icon: Users, desc: 'Subject Data', group: 'Patient & Therapy' },
  { id: 'composition', label: 'Drug Composition', icon: Pill, desc: 'Ratios A/B/C', group: 'Patient & Therapy' },
  { id: 'pkpd', label: 'PK/PD Dashboard', icon: Activity, desc: '2-Compartment', group: 'Science & Safety' },
  { id: 'statistics', label: 'Statistical Engine', icon: BarChart2, desc: 'Power & Tests', group: 'Science & Safety' },
  { id: 'dsmb', label: 'DSMB Console', icon: Shield, desc: 'Safety Board', group: 'Science & Safety' },
  { id: 'sites', label: 'Site Operations', icon: Building2, desc: 'Multi-Site', group: 'Operations' },
  { id: 'regulatory', label: 'Regulatory', icon: FileCheck, desc: 'IND to NDA', group: 'Operations' },
  { id: 'economics', label: 'Pharmacoeconomics', icon: DollarSign, desc: 'ICER & QALY', group: 'Operations' },
  { id: 'evidence', label: 'Medical Evidence', icon: BookOpen, desc: 'PubMed / FDA', group: 'Intelligence' },
  { id: 'agents', label: 'Agent Analysis', icon: ShieldCheck, desc: 'CMO Briefing', group: 'Intelligence' },
  { id: 'worldnews', label: 'Global Med News', icon: Globe, desc: 'Live World Map', group: 'Intelligence' },
  { id: 'benchmarks', label: 'Policy Benchmarks', icon: TrendingUp, desc: 'Analytics', group: 'Intelligence' },
  { id: 'hindsight', label: 'Hindsight Replay', icon: History, desc: 'Counterfactuals', group: 'Development' },
  { id: 'logs', label: 'System Logs', icon: Terminal, desc: 'Audit Trail', group: 'Development' },
];

const NAV_GROUPS = ['Trial Workspace', 'Patient & Therapy', 'Science & Safety', 'Operations', 'Intelligence', 'Development'];

const VIEW_MAP = {
  trial: InteractiveTrial,
  patient_simulator: PatientSimulator,
  patients: PatientCohort,
  evidence: MedicalEvidence,
  novel_pathogen: NovelPathogenAnalyzer,
  composition: DrugComposition,
  benchmarks: PolicyBenchmarks,
  agents: AgentAnalysis,
  worldnews: WorldMedicalNews,
  hindsight: HindsightReplay,
  logs: SystemLogs,
  pkpd: PKPDDashboard,
  sites: SiteOperations,
  statistics: StatisticalEngine,
  dsmb: DSMBConsole,
  regulatory: RegulatoryTimeline,
  economics: EconomicsDashboard,
};

function Sidebar({ active, setActive, onConfig, connected, isAutoRunning, setIsAutoRunning }) {
  return (
    <aside className="app-sidebar liquid-panel">
      <div className="brand-lockup">
        <div className="brand-mark">
          <Activity size={16} color="#ffffff" />
        </div>
        <div>
          <div className="brand-title">ClinicalSim</div>
          <div className="brand-subtitle">v3.0 · Clinical RL Suite</div>
        </div>
      </div>

      <nav className="app-nav" aria-label="Clinical simulator sections">
        {NAV_GROUPS.map((group) => {
          const items = NAV_ITEMS.filter((item) => item.group === group);
          if (!items.length) return null;

          return (
            <div key={group} className="nav-group">
              <div className="nav-group-label">{group}</div>
              {items.map((item) => {
                const Icon = item.icon;
                const isActive = active === item.id;

                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setActive(item.id)}
                    className={`nav-item ${isActive ? 'is-active' : ''}`}
                    aria-current={isActive ? 'page' : undefined}
                  >
                    <span className="nav-icon">
                      <Icon size={15} />
                    </span>
                    <span className="nav-copy">
                      <span className="nav-title">{item.label}</span>
                      <span className="nav-desc">{item.desc}</span>
                    </span>
                    {isActive && <ChevronRight size={14} className="nav-chevron" />}
                  </button>
                );
              })}
            </div>
          );
        })}
      </nav>

      <div className="sidebar-actions">
        <motion.button
          id="btn-config"
          type="button"
          onClick={onConfig}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.97 }}
          className="glass-button secondary"
        >
          <Sliders size={14} />
          Configuration
        </motion.button>

        <motion.button
          type="button"
          onClick={() => setIsAutoRunning(!isAutoRunning)}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.97 }}
          className={`glass-button primary ${isAutoRunning ? 'danger' : ''}`}
        >
          {isAutoRunning ? <><Pause size={14} /> STOP AGENT</> : <><Play size={14} /> START AGENT</>}
        </motion.button>

        <div className={`connection-pill ${connected ? 'connected' : 'offline'}`}>
          {connected ? <Wifi size={12} /> : <WifiOff size={12} />}
          <span>{connected ? 'Backend Connected' : 'Offline / Mock Mode'}</span>
        </div>
      </div>
    </aside>
  );
}

export default function App() {
  const [showLanding, setShowLanding] = useState(true);
  const [activeView, setActiveView] = useState('trial');
  const [showConfig, setShowConfig] = useState(false);
  const { initialize, loading, error, sessionId, takeAction } = useTrialStore();
  const [isAutoRunning, setIsAutoRunning] = useState(false);
  const autoRunTimer = React.useRef(null);

  useEffect(() => { initialize(); }, []);

  const runAutoStep = React.useCallback(async () => {
    if (!sessionId || sessionId === 'offline-demo' || !isAutoRunning) return;
    try {
      const actionRes = await axios.post(`${API_BASE}/policy/action`, { session_id: sessionId });
      const { action_type, magnitude } = actionRes.data;
      await takeAction({ action_type, magnitude });
    } catch {
      setIsAutoRunning(false);
    }
  }, [sessionId, isAutoRunning, takeAction]);

  useEffect(() => {
    if (isAutoRunning) {
      autoRunTimer.current = setInterval(runAutoStep, 2000);
    } else {
      clearInterval(autoRunTimer.current);
    }
    return () => clearInterval(autoRunTimer.current);
  }, [isAutoRunning, runAutoStep]);

  const ActiveView = VIEW_MAP[activeView];
  const connected = !!sessionId && sessionId !== 'offline-demo';
  const activeMeta = NAV_ITEMS.find((item) => item.id === activeView) || NAV_ITEMS[0];

  if (showLanding) {
    return <LandingPage onStart={(view = 'trial') => { setActiveView(view); setShowLanding(false); }} />;
  }

  if (loading) {
    return (
      <div className="loading-screen">
        <motion.div animate={{ rotate: 360 }} transition={{ duration: 1.5, repeat: Infinity, ease: 'linear' }}>
          <Activity size={40} />
        </motion.div>
        <motion.p animate={{ opacity: [0.45, 1, 0.45] }} transition={{ duration: 1.5, repeat: Infinity }}>
          Initializing Neural Environment...
        </motion.p>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <Sidebar
        active={activeView}
        setActive={setActiveView}
        onConfig={() => setShowConfig(true)}
        connected={connected}
        isAutoRunning={isAutoRunning}
        setIsAutoRunning={setIsAutoRunning}
      />

      <main className="main-stage">
        <header className="topbar liquid-panel">
          <div className="topbar-copy">
            <span className="section-kicker">{activeMeta.group}</span>
            <h1>{activeMeta.label}</h1>
          </div>
          <div className="topbar-status">
            <span className={`status-dot ${connected ? 'live' : 'mock'}`} />
            <span>{connected ? 'Live backend' : 'Mock mode'}</span>
          </div>
        </header>

        <AnimatePresence mode="wait">
          <motion.div
            key={activeView}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.25 }}
            className="view-transition"
          >
            {error && (
              <div className="app-alert">
                Backend unreachable. Running in mock/demo mode. Start the API server on port 8000 for live data.
              </div>
            )}
            <ActiveView />
          </motion.div>
        </AnimatePresence>
      </main>

      {showConfig && <ConfigModal onClose={() => setShowConfig(false)} />}
    </div>
  );
}
