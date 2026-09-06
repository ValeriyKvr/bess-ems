import React, { useEffect, useState } from 'react';
import {
  Save,
  RotateCcw,
  AlertTriangle,
  Flame,
  WifiOff,
  Activity,
  CheckCircle2,
  Sliders,
  Battery,
  ShoppingBag,
  Cpu,
  RefreshCw,
} from 'lucide-react';
import {
  fetchSettingsSchema,
  fetchSettingsSection,
  updateSettingsSection,
  injectFault,
  fetchHealth,
} from '../../api/client';
import { SettingsSchemaResponse } from '../../types';
import ukTranslations from '../../i18n/uk.json';

type SectionKey = 'battery' | 'market' | 'strategy' | 'simulation' | 'ems';

export const SettingsPage: React.FC = () => {
  const t = ukTranslations.settings;
  const [activeTab, setActiveTab] = useState<SectionKey>('battery');
  const [schemaData, setSchemaData] = useState<SettingsSchemaResponse | null>(null);
  const [formData, setFormData] = useState<Record<string, any>>({});
  const [originalData, setOriginalData] = useState<Record<string, any>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [faultStatus, setFaultStatus] = useState<string | null>(null);
  const [dbOnline, setDbOnline] = useState<boolean>(true);

  const tabs: { key: SectionKey; label: string; icon: React.ReactNode }[] = [
    { key: 'battery', label: t.tab_battery, icon: <Battery className="w-4 h-4" /> },
    { key: 'market', label: t.tab_market, icon: <ShoppingBag className="w-4 h-4" /> },
    { key: 'strategy', label: t.tab_strategy, icon: <Sliders className="w-4 h-4" /> },
    { key: 'simulation', label: t.tab_simulation, icon: <RefreshCw className="w-4 h-4" /> },
    { key: 'ems', label: t.tab_ems, icon: <Cpu className="w-4 h-4" /> },
  ];

  const loadSection = async (section: SectionKey) => {
    setIsLoading(true);
    setSaveMessage(null);
    try {
      const [schemaRes, valuesRes] = await Promise.all([
        fetchSettingsSchema(section),
        fetchSettingsSection(section),
      ]);
      setSchemaData(schemaRes);
      setFormData(valuesRes);
      setOriginalData(valuesRes);
    } catch (err: any) {
      setSaveMessage({ type: 'error', text: err.message || 'Помилка завантаження' });
    } finally {
      setIsLoading(false);
    }

    // A degraded database still serves defaults, but saving would fail — warn explicitly
    // instead of letting the user think the values on screen are persisted.
    try {
      const health = await fetchHealth();
      setDbOnline(Boolean(health.database));
    } catch {
      setDbOnline(false);
    }
  };

  useEffect(() => {
    loadSection(activeTab);
  }, [activeTab]);

  const handleChange = (key: string, val: any) => {
    setFormData((prev) => ({ ...prev, [key]: val }));
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    setSaveMessage(null);
    try {
      const res = await updateSettingsSection(activeTab, formData);
      setFormData(res.settings);
      setOriginalData(res.settings);
      setSaveMessage({ type: 'success', text: t.save_success });
    } catch (err: any) {
      setSaveMessage({ type: 'error', text: err.message || t.save_error });
    } finally {
      setIsSaving(false);
    }
  };

  const handleReset = () => {
    setFormData({ ...originalData });
    setSaveMessage(null);
  };

  const handleInjectFault = async (type: string) => {
    setFaultStatus(`Запуск: ${type}...`);
    try {
      await injectFault(type);
      setFaultStatus(`Аварія ${type} активована успішно`);
    } catch (err: any) {
      setFaultStatus(`Помилка: ${err.message}`);
    }
  };

  const properties = schemaData?.schema?.properties || {};
  const requiresRestartList = schemaData?.requires_restart || [];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-100">{t.title}</h1>
        <p className="text-sm text-slate-400 mt-1">{t.subtitle}</p>
      </div>

      {!dbOnline && (
        <div className="p-3.5 rounded-lg text-sm flex items-center gap-2.5 bg-amber-950/60 border border-amber-500/40 text-amber-300">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>
            База даних недоступна. Показані значення за замовчуванням, збереження не працюватиме.
            Перевірте <span className="font-mono">DATABASE_URL</span> та стан PostgreSQL.
          </span>
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-slate-800 gap-2">
        {tabs.map((tab) => {
          const isActive = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                isActive
                  ? 'border-cyan-500 text-cyan-400 bg-slate-900/40 rounded-t-lg'
                  : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-900/20'
              }`}
            >
              {tab.icon}
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Main Content Area */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left 2 Cols: Form Generator */}
        <div className="lg:col-span-2 bg-slate-900/80 border border-slate-800 rounded-xl p-6 shadow-sm">
          {isLoading ? (
            <div className="py-16 text-center text-slate-400 text-sm animate-pulse">
              Завантаження параметрів...
            </div>
          ) : (
            <form onSubmit={handleSave} className="space-y-5">
              {saveMessage && (
                <div
                  className={`p-3.5 rounded-lg text-sm flex items-center gap-2.5 ${
                    saveMessage.type === 'success'
                      ? 'bg-emerald-950/60 border border-emerald-500/40 text-emerald-300'
                      : 'bg-rose-950/60 border border-rose-500/40 text-rose-300'
                  }`}
                >
                  {saveMessage.type === 'success' ? (
                    <CheckCircle2 className="w-4 h-4 shrink-0" />
                  ) : (
                    <AlertTriangle className="w-4 h-4 shrink-0" />
                  )}
                  <span>{saveMessage.text}</span>
                </div>
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {Object.entries(properties).map(([propKey, propDef]: [string, any]) => {
                  const val = formData[propKey] ?? propDef.default ?? '';
                  const needsRestart = requiresRestartList.includes(propKey);
                  const title = propDef.title || propKey;
                  const isBoolean = propDef.type === 'boolean';
                  const isNumber = propDef.type === 'number' || propDef.type === 'integer';

                  return (
                    <div
                      key={propKey}
                      className={`p-3.5 rounded-lg bg-slate-950/50 border border-slate-800/80 flex flex-col justify-between ${
                        isBoolean ? 'md:col-span-1' : ''
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2 mb-1.5">
                        <label className="text-xs font-semibold text-slate-300 tracking-wide">
                          {title}
                        </label>
                        {needsRestart && (
                          <span
                            title={t.restart_warning}
                            className="inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 shrink-0"
                          >
                            <AlertTriangle className="w-2.5 h-2.5" />
                            Перезапуск
                          </span>
                        )}
                      </div>

                      {propDef.description && (
                        <p className="text-[11px] text-slate-400 mb-2 leading-relaxed">
                          {propDef.description}
                        </p>
                      )}

                      {isBoolean ? (
                        <div className="flex items-center gap-3 mt-1">
                          <input
                            type="checkbox"
                            checked={Boolean(val)}
                            onChange={(e) => handleChange(propKey, e.target.checked)}
                            className="w-4 h-4 rounded border-slate-700 text-cyan-600 focus:ring-cyan-500/40 bg-slate-900 cursor-pointer"
                          />
                          <span className="text-xs text-slate-300">
                            {val ? 'Увімкнено (True)' : 'Вимкнено (False)'}
                          </span>
                        </div>
                      ) : propDef.enum ? (
                        <select
                          value={val}
                          onChange={(e) => handleChange(propKey, e.target.value)}
                          className="w-full bg-slate-900 border border-slate-700 rounded-md px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-cyan-500"
                        >
                          {propDef.enum.map((opt: any) => (
                            <option key={String(opt)} value={opt}>
                              {String(opt)}
                            </option>
                          ))}
                        </select>
                      ) : isNumber ? (
                        <input
                          type="number"
                          step="any"
                          min={propDef.minimum}
                          max={propDef.maximum}
                          value={val}
                          onChange={(e) =>
                            handleChange(
                              propKey,
                              e.target.value === '' ? '' : Number(e.target.value)
                            )
                          }
                          className="w-full bg-slate-900 border border-slate-700 rounded-md px-2.5 py-1.5 text-xs text-slate-200 font-mono focus:outline-none focus:border-cyan-500"
                        />
                      ) : (
                        <input
                          type="text"
                          value={val}
                          onChange={(e) => handleChange(propKey, e.target.value)}
                          className="w-full bg-slate-900 border border-slate-700 rounded-md px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-cyan-500"
                        />
                      )}
                    </div>
                  );
                })}
              </div>

              {/* Action Buttons */}
              <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-800">
                <button
                  type="button"
                  onClick={handleReset}
                  disabled={isSaving}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 transition-colors"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                  <span>{t.btn_reset}</span>
                </button>
                <button
                  type="submit"
                  disabled={isSaving}
                  className="flex items-center gap-2 px-5 py-2 rounded-lg text-xs font-semibold text-slate-950 bg-cyan-400 hover:bg-cyan-300 transition-colors shadow-sm shadow-cyan-900/50 disabled:opacity-50"
                >
                  <Save className="w-3.5 h-3.5" />
                  <span>{isSaving ? t.saving : t.btn_save}</span>
                </button>
              </div>
            </form>
          )}
        </div>

        {/* Right 1 Col: Info Card & Fault Injection */}
        <div className="space-y-6">
          {/* Section Info Card */}
          <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 shadow-sm">
            <h3 className="text-sm font-semibold text-slate-200 mb-2">Про секцію</h3>
            <p className="text-xs text-slate-400 leading-relaxed">
              Параметри цієї секції конфігурації зберігаються в базі даних та автоматично застосовуються
              при наступних ітераціях симуляції та оптимізації. Поля з міткою{' '}
              <span className="text-amber-400 font-mono">Перезапуск</span> фіксуються в фізичній моделі
              BESS під час ініціалізації процесу.
            </p>
          </div>

          {/* Fault Injection Panel */}
          <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
            <div>
              <h3 className="text-sm font-semibold text-rose-400 flex items-center gap-2">
                <Flame className="w-4 h-4 text-rose-400" />
                <span>{t.fault_injection_title}</span>
              </h3>
              <p className="text-xs text-slate-400 mt-1">{t.fault_injection_subtitle}</p>
            </div>

            {faultStatus && (
              <div className="p-2.5 rounded bg-slate-950 border border-slate-800 text-[11px] font-mono text-cyan-300">
                {faultStatus}
              </div>
            )}

            <div className="grid grid-cols-1 gap-2">
              <button
                type="button"
                onClick={() => handleInjectFault('comms_dropout')}
                className="flex items-center justify-between p-2.5 rounded-lg bg-slate-950 border border-slate-800 hover:border-amber-500/50 text-xs text-slate-300 hover:text-amber-300 transition-colors"
              >
                <span className="flex items-center gap-2">
                  <WifiOff className="w-3.5 h-3.5 text-amber-400" />
                  {t.fault_comms}
                </span>
                <span className="text-[10px] text-slate-400">60s</span>
              </button>

              <button
                type="button"
                onClick={() => handleInjectFault('force_overheat')}
                className="flex items-center justify-between p-2.5 rounded-lg bg-slate-950 border border-slate-800 hover:border-rose-500/50 text-xs text-slate-300 hover:text-rose-300 transition-colors"
              >
                <span className="flex items-center gap-2">
                  <Flame className="w-3.5 h-3.5 text-rose-400" />
                  {t.fault_overheat}
                </span>
                <span className="text-[10px] text-slate-400">48°C</span>
              </button>

              <button
                type="button"
                onClick={() => handleInjectFault('soc_noise')}
                className="flex items-center justify-between p-2.5 rounded-lg bg-slate-950 border border-slate-800 hover:border-cyan-500/50 text-xs text-slate-300 hover:text-cyan-300 transition-colors"
              >
                <span className="flex items-center gap-2">
                  <Activity className="w-3.5 h-3.5 text-cyan-400" />
                  {t.fault_soc_noise}
                </span>
                <span className="text-[10px] text-slate-400">±5%</span>
              </button>

              <button
                type="button"
                onClick={() => handleInjectFault('power_limit_50')}
                className="flex items-center justify-between p-2.5 rounded-lg bg-slate-950 border border-slate-800 hover:border-yellow-500/50 text-xs text-slate-300 hover:text-yellow-300 transition-colors"
              >
                <span className="flex items-center gap-2">
                  <AlertTriangle className="w-3.5 h-3.5 text-yellow-400" />
                  {t.fault_derate}
                </span>
                <span className="text-[10px] text-slate-400">50%</span>
              </button>

              <button
                type="button"
                onClick={() => handleInjectFault('clear_all')}
                className="flex items-center justify-center gap-2 mt-2 p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-emerald-400 transition-colors"
              >
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                {t.fault_clear}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
