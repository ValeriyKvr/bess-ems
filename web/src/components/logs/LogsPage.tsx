import React, { useEffect, useState } from 'react';
import {
  Search,
  Filter,
  ChevronLeft,
  ChevronRight,
  Eye,
  X,
  Sliders,
} from 'lucide-react';
import { fetchPaginatedDispatchLog, fetchScheduleById } from '../../api/client';
import { DispatchLogItem, ScheduleResponse } from '../../types';
import ukTranslations from '../../i18n/uk.json';

export const LogsPage: React.FC = () => {
  const t = ukTranslations.logs;

  const [logs, setLogs] = useState<DispatchLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [limit, setLimit] = useState(25);
  const [reasonFilter, setReasonFilter] = useState('');
  const [overrideFilter, setOverrideFilter] = useState<'all' | 'true' | 'false'>('all');
  const [isLoading, setIsLoading] = useState(false);

  // Inspector Modal State
  const [selectedScheduleId, setSelectedScheduleId] = useState<string | null>(null);
  const [inspectorSchedule, setInspectorSchedule] = useState<ScheduleResponse | null>(null);
  const [isInspectorLoading, setIsInspectorLoading] = useState(false);

  const loadLogs = async () => {
    setIsLoading(true);
    try {
      const overrideVal = overrideFilter === 'all' ? undefined : overrideFilter === 'true';
      const res = await fetchPaginatedDispatchLog(page, limit, reasonFilter || undefined, overrideVal);
      setLogs(res.items);
      setTotal(res.total);
    } catch (err) {
      console.error('Failed to load dispatch logs', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadLogs();
  }, [page, limit, overrideFilter]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    loadLogs();
  };

  const handleOpenInspector = async (scheduleId: string) => {
    setSelectedScheduleId(scheduleId);
    setIsInspectorLoading(true);
    try {
      const sched = await fetchScheduleById(scheduleId);
      setInspectorSchedule(sched);
    } catch (err) {
      console.error('Failed to load schedule inspector', err);
    } finally {
      setIsInspectorLoading(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / limit));

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-100">{t.title}</h1>
        <p className="text-sm text-slate-400 mt-1">{t.subtitle}</p>
      </div>

      {/* Filter and Search Bar */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 shadow-sm">
        <form onSubmit={handleSearchSubmit} className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3 flex-1 min-w-[280px]">
            {/* Search Input */}
            <div className="relative flex-1 max-w-md">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
              <input
                type="text"
                value={reasonFilter}
                onChange={(e) => setReasonFilter(e.target.value)}
                placeholder={t.filter_reason}
                className="w-full pl-9 pr-3 py-1.5 bg-slate-950 border border-slate-700 rounded-lg text-xs text-slate-200 focus:outline-none focus:border-cyan-500"
              />
            </div>

            {/* Override Filter Dropdown */}
            <div className="flex items-center gap-1.5 bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-1 text-xs text-slate-300">
              <Filter className="w-3.5 h-3.5 text-slate-400" />
              <select
                value={overrideFilter}
                onChange={(e) => {
                  setOverrideFilter(e.target.value as any);
                  setPage(1);
                }}
                className="bg-transparent focus:outline-none cursor-pointer"
              >
                <option value="all" className="bg-slate-900 text-slate-200">
                  {t.filter_all}
                </option>
                <option value="true" className="bg-slate-900 text-slate-200">
                  {t.filter_override}
                </option>
                <option value="false" className="bg-slate-900 text-slate-200">
                  Тільки автоматичні (Auto)
                </option>
              </select>
            </div>

            <button
              type="submit"
              className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-cyan-500 hover:bg-cyan-400 text-slate-950 transition-colors"
            >
              Знайти
            </button>
          </div>

          {/* Records Counter & Limit Selector */}
          <div className="flex items-center gap-3 text-xs text-slate-400">
            <span>
              {t.total_records} <strong className="text-slate-200 font-mono">{total}</strong>
            </span>
            <select
              value={limit}
              onChange={(e) => {
                setLimit(Number(e.target.value));
                setPage(1);
              }}
              className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-slate-300 focus:outline-none"
            >
              <option value={25}>25 / стор.</option>
              <option value={50}>50 / стор.</option>
              <option value={100}>100 / стор.</option>
            </select>
          </div>
        </form>
      </div>

      {/* Logs Table Card */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-xs text-left text-slate-300">
            <thead className="bg-slate-950 text-slate-400 uppercase text-[10px] font-mono border-b border-slate-800">
              <tr>
                <th className="px-3.5 py-2.5">{t.col_time}</th>
                <th className="px-3.5 py-2.5">{t.col_setpoint}</th>
                <th className="px-3.5 py-2.5">{t.col_actual}</th>
                <th className="px-3.5 py-2.5">{t.col_reason}</th>
                <th className="px-3.5 py-2.5">{t.col_schedule}</th>
                <th className="px-3.5 py-2.5 text-center">{t.col_override}</th>
                <th className="px-3.5 py-2.5 text-right">Дії</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono">
              {isLoading ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-slate-500 animate-pulse">
                    Завантаження записів логу...
                  </td>
                </tr>
              ) : logs.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-slate-500 font-sans">
                    Записів рішень диспетчера не знайдено
                  </td>
                </tr>
              ) : (
                logs.map((log, idx) => {
                  const setpoint = log.setpoint_kw;
                  const isDischarge = setpoint < 0;
                  const isCharge = setpoint > 0;

                  return (
                    <tr key={idx} className="hover:bg-slate-800/30 transition-colors">
                      {/* Timestamp */}
                      <td className="px-3.5 py-2 whitespace-nowrap text-slate-400">
                        {log.ts ? log.ts.replace('T', ' ').replace('Z', '') : '—'}
                      </td>

                      {/* Setpoint kW */}
                      <td className="px-3.5 py-2 font-bold whitespace-nowrap">
                        <span
                          className={
                            isCharge
                              ? 'text-cyan-400'
                              : isDischarge
                              ? 'text-amber-400'
                              : 'text-slate-400'
                          }
                        >
                          {setpoint > 0 ? `+${setpoint}` : setpoint} кВт
                        </span>
                      </td>

                      {/* Actual kW */}
                      <td className="px-3.5 py-2 whitespace-nowrap text-slate-400">
                        {log.actual_kw !== null && log.actual_kw !== undefined
                          ? `${log.actual_kw > 0 ? `+${log.actual_kw}` : log.actual_kw} кВт`
                          : '—'}
                      </td>

                      {/* Reason */}
                      <td className="px-3.5 py-2 font-sans text-slate-200 max-w-md truncate" title={log.reason || ''}>
                        {log.reason || '—'}
                      </td>

                      {/* Schedule ID */}
                      <td className="px-3.5 py-2 whitespace-nowrap">
                        {log.schedule_id ? (
                          <button
                            onClick={() => handleOpenInspector(log.schedule_id!)}
                            className="font-mono text-cyan-400 hover:text-cyan-300 underline decoration-cyan-500/40 cursor-pointer"
                          >
                            {log.schedule_id}
                          </button>
                        ) : (
                          <span className="text-slate-600">—</span>
                        )}
                      </td>

                      {/* Override */}
                      <td className="px-3.5 py-2 text-center whitespace-nowrap">
                        {log.override ? (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-sans font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                            MANUAL
                          </span>
                        ) : (
                          <span className="text-slate-600 text-[10px]">AUTO</span>
                        )}
                      </td>

                      {/* Action */}
                      <td className="px-3.5 py-2 text-right whitespace-nowrap">
                        {log.schedule_id && (
                          <button
                            onClick={() => handleOpenInspector(log.schedule_id!)}
                            className="p-1 rounded text-slate-400 hover:text-cyan-400 hover:bg-slate-800 transition-colors"
                            title={t.btn_view_schedule}
                          >
                            <Eye className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Footer */}
        <div className="flex items-center justify-between px-4 py-3 border-t border-slate-800 bg-slate-950/50 text-xs">
          <span className="text-slate-400 font-sans">
            {t.page} <strong className="text-slate-200 font-mono">{page}</strong> {t.of}{' '}
            <strong className="text-slate-200 font-mono">{totalPages}</strong>
          </span>

          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="p-1.5 rounded-lg border border-slate-700 hover:bg-slate-800 text-slate-300 disabled:opacity-30 disabled:hover:bg-transparent"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="p-1.5 rounded-lg border border-slate-700 hover:bg-slate-800 text-slate-300 disabled:opacity-30 disabled:hover:bg-transparent"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Schedule Inspector Slideout / Modal */}
      {selectedScheduleId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden">
            {/* Modal Header */}
            <div className="flex items-center justify-between p-5 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <Sliders className="w-5 h-5 text-cyan-400" />
                <div>
                  <h2 className="text-base font-bold text-slate-100">{t.inspector_title}</h2>
                  <p className="text-xs text-cyan-400/80 font-mono">{selectedScheduleId}</p>
                </div>
              </div>
              <button
                onClick={() => {
                  setSelectedScheduleId(null);
                  setInspectorSchedule(null);
                }}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Content */}
            <div className="p-6 overflow-y-auto space-y-6 flex-1">
              {isInspectorLoading ? (
                <div className="py-16 text-center text-slate-400 text-sm animate-pulse">
                  Завантаження графіка...
                </div>
              ) : inspectorSchedule ? (
                <>
                  {/* Schedule Meta Badges */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                      <span className="text-[11px] text-slate-400">Стратегія:</span>
                      <p className="text-sm font-bold text-cyan-300 font-mono mt-0.5">
                        {typeof inspectorSchedule.strategy === 'object'
                          ? inspectorSchedule.strategy.name
                          : inspectorSchedule.strategy}
                      </p>
                    </div>
                    <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                      <span className="text-[11px] text-slate-400">Ємність батареї:</span>
                      <p className="text-sm font-bold text-slate-200 font-mono mt-0.5">
                        {typeof inspectorSchedule.strategy === 'object' && inspectorSchedule.strategy.capacity_kwh
                          ? `${inspectorSchedule.strategy.capacity_kwh} кВт·год`
                          : '1000 кВт·год'}
                      </p>
                    </div>
                    <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                      <span className="text-[11px] text-slate-400">Очікуваний прибуток:</span>
                      <p className="text-sm font-bold text-emerald-400 font-mono mt-0.5">
                        +{inspectorSchedule.expected_profit_uah?.toLocaleString() || 0} грн
                      </p>
                    </div>
                    <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                      <span className="text-[11px] text-slate-400">Час розв'язку:</span>
                      <p className="text-sm font-bold text-slate-300 font-mono mt-0.5">
                        {inspectorSchedule.solve_time_ms ?? 0} ms ({inspectorSchedule.solver_status || 'OK'})
                      </p>
                    </div>
                  </div>

                  {/* 24h Items Table */}
                  <div className="border border-slate-800 rounded-xl overflow-hidden">
                    <div className="bg-slate-950 px-4 py-2.5 border-b border-slate-800 text-xs font-semibold text-slate-300">
                      Погодинний графік уставок (24 години)
                    </div>
                    <div className="max-h-72 overflow-y-auto">
                      <table className="w-full text-xs text-left text-slate-300">
                        <thead className="bg-slate-950 text-slate-400 uppercase text-[10px] font-mono sticky top-0">
                          <tr>
                            <th className="px-3 py-2">Час інтервалу</th>
                            <th className="px-3 py-2">Уставка</th>
                            <th className="px-3 py-2">Призначення / Режим</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800/60 font-mono">
                          {inspectorSchedule.items.map((item, i) => {
                            const p = item.setpoint_kw;
                            return (
                              <tr key={i} className="hover:bg-slate-800/30">
                                <td className="px-3 py-1.5 text-slate-400 whitespace-nowrap">
                                  {item.ts.replace('T', ' ').slice(0, 16)}
                                </td>
                                <td className="px-3 py-1.5 font-bold whitespace-nowrap">
                                  <span
                                    className={
                                      p > 0
                                        ? 'text-cyan-400'
                                        : p < 0
                                        ? 'text-amber-400'
                                        : 'text-slate-400'
                                    }
                                  >
                                    {p > 0 ? `+${p}` : p} кВт
                                  </span>
                                </td>
                                <td className="px-3 py-1.5 font-sans text-slate-200">
                                  {item.reason || 'За графіком'}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </>
              ) : (
                <div className="py-12 text-center text-slate-400 text-sm">{t.inspector_empty}</div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
