import { useState, useEffect } from 'react';
import {
  Radio,
  Server,
  Database,
  Activity,
  AlertCircle,
} from 'lucide-react';
import { useTelemetryStore } from './stores/telemetryStore';
import { ClockPanel } from './components/dashboard/ClockPanel';
import { MoneyCounter } from './components/dashboard/MoneyCounter';
import { EnergyFlowDiagram } from './components/energy-flow/EnergyFlowDiagram';
import { DashboardCharts } from './components/dashboard/DashboardCharts';
import { EventFeed } from './components/dashboard/EventFeed';
import { MlPage } from './components/ml/MlPage';
import { Sidebar, NavView } from './components/sidebar/Sidebar';
import { SettingsPage } from './components/settings/SettingsPage';
import { DataPage } from './components/data/DataPage';
import { ReportsPage } from './components/reports/ReportsPage';
import { LogsPage } from './components/logs/LogsPage';
import t from './i18n/uk.json';

export function App() {
  const [currentView, setCurrentView] = useState<NavView>(() => {
    const h = (typeof window !== 'undefined' ? window.location.hash.replace('#', '') : '') as NavView;
    return ['dashboard', 'settings', 'data', 'ml', 'reports', 'logs'].includes(h) ? h : 'dashboard';
  });
  const { connected, isConnecting, currentTick, connectWebSocket, disconnectWebSocket } =
    useTelemetryStore();

  useEffect(() => {
    const handleHashChange = () => {
      const h = window.location.hash.replace('#', '') as NavView;
      if (['dashboard', 'settings', 'data', 'ml', 'reports', 'logs'].includes(h)) {
        setCurrentView(h);
      }
    };
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  const handleSelectView = (view: NavView) => {
    setCurrentView(view);
    window.location.hash = view;
  };

  useEffect(() => {
    connectWebSocket();
    return () => disconnectWebSocket();
  }, [connectWebSocket, disconnectWebSocket]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex font-sans selection:bg-cyan-600 selection:text-white">
      {/* Collapsible Sidebar */}
      <Sidebar currentView={currentView} onSelectView={handleSelectView} />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 min-h-screen">
        {/* Header */}
        <header className="border-b border-slate-800/80 bg-slate-900/60 backdrop-blur-md px-6 py-3 sticky top-0 z-40 flex items-center justify-between shadow-sm">
          <div className="flex items-center gap-4">
            <h1 className="text-base font-bold text-slate-100 tracking-tight flex items-center gap-2">
              {t.app.title}
              <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800/60">
                v1.0.0
              </span>
            </h1>
            <span className="text-xs text-slate-400 hidden sm:inline">{t.app.subtitle}</span>
          </div>

          {/* System & Connection Status Badges */}
          <div className="flex items-center gap-3">
            <div className="hidden lg:flex items-center gap-2 text-xs text-slate-400 mr-2">
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-900 border border-slate-800">
                <Server className="w-3.5 h-3.5 text-blue-400" />
                <span>EMS Core</span>
              </div>
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-900 border border-slate-800">
                <Database className="w-3.5 h-3.5 text-emerald-400" />
                <span>TimescaleDB</span>
              </div>
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-900 border border-slate-800">
                <Radio className="w-3.5 h-3.5 text-indigo-400" />
                <span>MQTT</span>
              </div>
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-900 border border-slate-800">
                <Activity className="w-3.5 h-3.5 text-cyan-400" />
                <span>BESS Sim</span>
              </div>
            </div>

            {/* Stage Badge */}
            <span className="px-3 py-1 text-xs font-semibold rounded-full bg-cyan-900/40 text-cyan-300 border border-cyan-700/50">
              Етап 8: Реліз (DoD 100%)
            </span>

            {/* WS Live Status */}
            <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-slate-900 border border-slate-700/80 text-xs">
              <span
                className={`w-2 h-2 rounded-full ${
                  connected
                    ? 'bg-emerald-400 animate-pulse shadow-[0_0_8px_#34d399]'
                    : isConnecting
                    ? 'bg-amber-400 animate-ping'
                    : 'bg-rose-500'
                }`}
              />
              <span className="font-medium">
                {connected
                  ? t.app.connected
                  : isConnecting
                  ? t.app.connecting
                  : t.app.disconnected}
              </span>
            </div>
          </div>
        </header>

        {/* View Content */}
        <main className="flex-1 p-5 max-w-[1680px] mx-auto w-full space-y-4">
          {!connected && !isConnecting && (
            <div className="p-3.5 bg-amber-950/40 border border-amber-800/60 text-amber-200 rounded-xl flex items-center gap-3 text-xs">
              <AlertCircle className="w-4 h-4 text-amber-400 flex-shrink-0" />
              <span>
                Втрачено з'єднання з WebSocket сервером телеметрії. Автоматичне перепідключення...
              </span>
            </div>
          )}

          {currentView === 'dashboard' && (
            <>
              {/* 1. Simulation Clock and Speed Controls */}
              <ClockPanel />

              {/* 2. Live Money Counter (Financial Benefit) */}
              <MoneyCounter />

              {/* 3. Central Interactive Section: Energy Flow Diagram & Event Feed */}
              <div className="grid grid-cols-1 xl:grid-cols-12 gap-4 items-start">
                <div className="xl:col-span-8 2xl:col-span-9 w-full">
                  <EnergyFlowDiagram tick={currentTick} />
                </div>
                <div className="xl:col-span-4 2xl:col-span-3 w-full h-[460px]">
                  <EventFeed />
                </div>
              </div>

              {/* 4. Realtime Analytics & Graphs */}
              <div className="pt-2">
                <DashboardCharts />
              </div>
            </>
          )}

          {currentView === 'ml' && <MlPage />}
          {currentView === 'settings' && <SettingsPage />}
          {currentView === 'data' && <DataPage />}
          {currentView === 'reports' && <ReportsPage />}
          {currentView === 'logs' && <LogsPage />}
        </main>

        {/* Footer */}
        <footer className="border-t border-slate-900/80 px-6 py-3 text-center text-xs text-slate-600 bg-slate-950">
          BESS ↔ EMS Simulator &middot; Ринок електричної енергії України &middot; 2026
        </footer>
      </div>
    </div>
  );
}

export default App;

