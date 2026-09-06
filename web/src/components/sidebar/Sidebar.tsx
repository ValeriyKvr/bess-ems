import React, { useState } from 'react';
import {
  LayoutDashboard,
  TrendingUp,
  Settings,
  Database,
  BarChart3,
  ScrollText,
  ChevronLeft,
  ChevronRight,
  BatteryCharging,
} from 'lucide-react';
import ukTranslations from '../../i18n/uk.json';

export type NavView = 'dashboard' | 'ml' | 'settings' | 'data' | 'reports' | 'logs';

interface SidebarProps {
  currentView: NavView;
  onSelectView: (view: NavView) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ currentView, onSelectView }) => {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const t = ukTranslations.nav;

  const navItems: { id: NavView; label: string; icon: React.ReactNode }[] = [
    { id: 'dashboard', label: t.dashboard, icon: <LayoutDashboard className="w-5 h-5" /> },
    { id: 'ml', label: t.ml, icon: <TrendingUp className="w-5 h-5" /> },
    { id: 'settings', label: t.settings, icon: <Settings className="w-5 h-5" /> },
    { id: 'data', label: t.data, icon: <Database className="w-5 h-5" /> },
    { id: 'reports', label: t.reports, icon: <BarChart3 className="w-5 h-5" /> },
    { id: 'logs', label: t.logs, icon: <ScrollText className="w-5 h-5" /> },
  ];

  return (
    <aside
      className={`h-screen sticky top-0 flex flex-col bg-slate-950 border-r border-slate-800 transition-all duration-300 z-30 ${
        isCollapsed ? 'w-16' : 'w-60'
      }`}
    >
      {/* Brand Header */}
      <div className="flex items-center gap-3 p-4 border-b border-slate-800/80 overflow-hidden">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-cyan-500/20 text-cyan-400 shrink-0">
          <BatteryCharging className="w-5 h-5" />
        </div>
        {!isCollapsed && (
          <div className="truncate">
            <h1 className="text-sm font-bold text-slate-100 tracking-wide">BESS ↔ EMS</h1>
            <p className="text-[11px] text-cyan-400/80 font-mono">SPEC v1.0 • OES</p>
          </div>
        )}
      </div>

      {/* Navigation List */}
      <nav className="flex-1 p-2 space-y-1.5 overflow-y-auto">
        {navItems.map((item) => {
          const isActive = currentView === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onSelectView(item.id)}
              title={isCollapsed ? item.label : undefined}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-cyan-950/60 text-cyan-300 border border-cyan-500/40 shadow-sm shadow-cyan-950'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/60'
              } ${isCollapsed ? 'justify-center' : ''}`}
            >
              <div className={isActive ? 'text-cyan-400' : 'text-slate-400'}>{item.icon}</div>
              {!isCollapsed && <span className="truncate">{item.label}</span>}
            </button>
          );
        })}
      </nav>

      {/* Collapse Toggle Footer */}
      <div className="p-3 border-t border-slate-800/80">
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="w-full flex items-center justify-center p-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-900 transition-colors"
          title={isCollapsed ? 'Розгорнути' : 'Згорнути'}
        >
          {isCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>
    </aside>
  );
};
