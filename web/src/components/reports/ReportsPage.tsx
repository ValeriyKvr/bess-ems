import React, { useEffect, useRef, useState } from 'react';
import {
  FileSpreadsheet,
  Download,
  Scale,
  DollarSign,
  TrendingUp,
  BatteryCharging,
  Play,
} from 'lucide-react';
import * as echarts from 'echarts';
import {
  fetchReportSummary,
  downloadReportFile,
  compareStrategies,
} from '../../api/client';
import { ReportSummaryResponse, StrategyComparisonItem } from '../../types';
import ukTranslations from '../../i18n/uk.json';

type PeriodOption = 'today' | 'week' | 'month' | 'custom';

export const ReportsPage: React.FC = () => {
  const t = ukTranslations.reports;

  const [period, setPeriod] = useState<PeriodOption>('week');
  const [customFrom, setCustomFrom] = useState('');
  const [customTo, setCustomTo] = useState('');
  const [reportData, setReportData] = useState<ReportSummaryResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isExporting, setIsExporting] = useState<'xlsx' | 'csv' | null>(null);

  // Strategy Comparison state
  const [compareDate, setCompareDate] = useState('2026-03-01');
  const [comparisonResults, setComparisonResults] = useState<StrategyComparisonItem[]>([]);
  const [isComparing, setIsComparing] = useState(false);

  const hourlyChartRef = useRef<HTMLDivElement>(null);
  const hourlyChartInstance = useRef<echarts.ECharts | null>(null);

  const compareChartRef = useRef<HTMLDivElement>(null);
  const compareChartInstance = useRef<echarts.ECharts | null>(null);

  const getDateRange = () => {
    const now = new Date();
    const endIso = now.toISOString();
    if (period === 'today') {
      const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      return { from: start.toISOString(), to: endIso };
    } else if (period === 'week') {
      const start = new Date(now.getTime() - 7 * 24 * 3600 * 1000);
      return { from: start.toISOString(), to: endIso };
    } else if (period === 'month') {
      const start = new Date(now.getTime() - 30 * 24 * 3600 * 1000);
      return { from: start.toISOString(), to: endIso };
    } else {
      return {
        from: customFrom ? new Date(customFrom).toISOString() : undefined,
        to: customTo ? new Date(customTo).toISOString() : undefined,
      };
    }
  };

  const loadReport = async () => {
    setIsLoading(true);
    const range = getDateRange();
    try {
      const res = await fetchReportSummary(range.from, range.to);
      setReportData(res);
    } catch (err) {
      console.error('Failed to load report summary', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (period !== 'custom') {
      loadReport();
    }
  }, [period]);

  const handleExport = async (format: 'xlsx' | 'csv') => {
    setIsExporting(format);
    const range = getDateRange();
    try {
      await downloadReportFile(format, range.from, range.to);
    } catch (err) {
      console.error('Failed to download report', err);
    } finally {
      setIsExporting(null);
    }
  };

  const handleRunComparison = async () => {
    setIsComparing(true);
    try {
      const res = await compareStrategies(compareDate);
      setComparisonResults(res.comparison);
    } catch (err) {
      console.error('Failed to compare strategies', err);
    } finally {
      setIsComparing(false);
    }
  };

  useEffect(() => {
    handleRunComparison();
  }, []);

  // Render Hourly Financial Breakdown Chart
  useEffect(() => {
    if (!hourlyChartRef.current || !reportData || !reportData.hourly) return;
    if (!hourlyChartInstance.current) {
      hourlyChartInstance.current = echarts.init(hourlyChartRef.current, 'dark');
    }
    const chart = hourlyChartInstance.current;

    const timestamps = reportData.hourly.map((h) => h.ts.replace('T', ' ').replace('Z', ''));
    const baseline = reportData.hourly.map((h) => h.cost_baseline_uah);
    const actual = reportData.hourly.map((h) => h.cost_actual_uah);
    const net = reportData.hourly.map((h) => h.net_uah);

    const option: echarts.EChartsOption = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        formatter: (params: any) => {
          let s = `${params[0]?.axisValue}<br/>`;
          params.forEach((p: any) => {
            s += `<span style="color:${p.color}">●</span> ${p.seriesName}: ${p.value.toLocaleString()} грн<br/>`;
          });
          return s;
        },
      },
      legend: {
        data: ['Базова вартість', 'Фактична з BESS', 'Чистий ефект (Net)'],
        textStyle: { color: '#94a3b8', fontSize: 11 },
        top: 0,
      },
      grid: { left: 55, right: 20, top: 40, bottom: 35 },
      xAxis: {
        type: 'category',
        data: timestamps,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#94a3b8', fontSize: 10 },
      },
      yAxis: {
        type: 'value',
        name: 'грн',
        nameTextStyle: { color: '#64748b', fontSize: 10 },
        splitLine: { lineStyle: { color: '#1e293b' } },
        axisLabel: { color: '#94a3b8', fontSize: 10 },
      },
      series: [
        {
          name: 'Базова вартість',
          type: 'bar',
          data: baseline,
          itemStyle: { color: '#f59e0b' },
        },
        {
          name: 'Фактична з BESS',
          type: 'bar',
          data: actual,
          itemStyle: { color: '#06b6d4' },
        },
        {
          name: 'Чистий ефект (Net)',
          type: 'line',
          data: net,
          smooth: true,
          itemStyle: { color: '#10b981' },
          lineStyle: { width: 2 },
        },
      ],
    };

    chart.setOption(option);

    const handleResize = () => chart.resize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [reportData]);

  // Render Strategy Comparison Chart
  useEffect(() => {
    if (!compareChartRef.current || !comparisonResults.length) return;
    if (!compareChartInstance.current) {
      compareChartInstance.current = echarts.init(compareChartRef.current, 'dark');
    }
    const chart = compareChartInstance.current;

    const names = comparisonResults.map((c) => c.strategy);
    const savings = comparisonResults.map((c) => c.net_benefit_uah);
    const cycles = comparisonResults.map((c) => c.equivalent_cycles);

    const option: echarts.EChartsOption = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
      },
      legend: {
        data: ['Чистий ефект (грн)', 'Цикли'],
        textStyle: { color: '#94a3b8', fontSize: 11 },
        top: 0,
      },
      grid: { left: 55, right: 55, top: 40, bottom: 35 },
      xAxis: {
        type: 'category',
        data: names,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#cbd5e1', fontSize: 11, fontWeight: 'bold' },
      },
      yAxis: [
        {
          type: 'value',
          name: 'грн',
          nameTextStyle: { color: '#64748b', fontSize: 10 },
          splitLine: { lineStyle: { color: '#1e293b' } },
          axisLabel: { color: '#94a3b8', fontSize: 10 },
        },
        {
          type: 'value',
          name: 'цикли',
          nameTextStyle: { color: '#64748b', fontSize: 10 },
          splitLine: { show: false },
          axisLabel: { color: '#94a3b8', fontSize: 10 },
        },
      ],
      series: [
        {
          name: 'Чистий ефект (грн)',
          type: 'bar',
          data: savings,
          itemStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: '#38bdf8' },
              { offset: 1, color: '#0284c7' },
            ]),
            borderRadius: [4, 4, 0, 0],
          },
        },
        {
          name: 'Цикли',
          type: 'line',
          yAxisIndex: 1,
          data: cycles,
          itemStyle: { color: '#f59e0b' },
          lineStyle: { width: 3 },
          symbolSize: 8,
        },
      ],
    };

    chart.setOption(option);

    const handleResize = () => chart.resize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [comparisonResults]);

  const kpis = reportData?.summary;

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header & Period Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">{t.title}</h1>
          <p className="text-sm text-slate-400 mt-1">{t.subtitle}</p>
        </div>

        {/* Period Selector & Export Buttons */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex bg-slate-900 p-0.5 rounded-lg border border-slate-800 text-xs">
            <button
              onClick={() => setPeriod('today')}
              className={`px-3 py-1.5 rounded-md transition-colors ${
                period === 'today' ? 'bg-cyan-500/20 text-cyan-400 font-semibold' : 'text-slate-400'
              }`}
            >
              {t.period_today}
            </button>
            <button
              onClick={() => setPeriod('week')}
              className={`px-3 py-1.5 rounded-md transition-colors ${
                period === 'week' ? 'bg-cyan-500/20 text-cyan-400 font-semibold' : 'text-slate-400'
              }`}
            >
              {t.period_week}
            </button>
            <button
              onClick={() => setPeriod('month')}
              className={`px-3 py-1.5 rounded-md transition-colors ${
                period === 'month' ? 'bg-cyan-500/20 text-cyan-400 font-semibold' : 'text-slate-400'
              }`}
            >
              {t.period_month}
            </button>
            <button
              onClick={() => setPeriod('custom')}
              className={`px-3 py-1.5 rounded-md transition-colors ${
                period === 'custom' ? 'bg-cyan-500/20 text-cyan-400 font-semibold' : 'text-slate-400'
              }`}
            >
              {t.period_custom}
            </button>
          </div>

          {period === 'custom' && (
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={customFrom}
                onChange={(e) => setCustomFrom(e.target.value)}
                className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 font-mono"
              />
              <span className="text-slate-500 text-xs">—</span>
              <input
                type="date"
                value={customTo}
                onChange={(e) => setCustomTo(e.target.value)}
                className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 font-mono"
              />
              <button
                onClick={loadReport}
                disabled={isLoading}
                className="px-2.5 py-1 text-xs bg-cyan-600 hover:bg-cyan-500 text-slate-950 font-semibold rounded"
              >
                {isLoading ? '...' : 'OK'}
              </button>
            </div>
          )}

          <div className="flex items-center gap-2">
            <button
              onClick={() => handleExport('xlsx')}
              disabled={isExporting !== null}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-500 hover:bg-emerald-400 text-slate-950 transition-colors shadow-sm disabled:opacity-50"
            >
              <FileSpreadsheet className="w-3.5 h-3.5" />
              <span>{isExporting === 'xlsx' ? 'XLSX...' : t.btn_export_xlsx}</span>
            </button>
            <button
              onClick={() => handleExport('csv')}
              disabled={isExporting !== null}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition-colors disabled:opacity-50"
            >
              <Download className="w-3.5 h-3.5" />
              <span>{isExporting === 'csv' ? 'CSV...' : t.btn_export_csv}</span>
            </button>
          </div>
        </div>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {/* Baseline Cost */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 shadow-sm">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
            <span>{t.kpi_baseline}</span>
            <DollarSign className="w-3.5 h-3.5 text-amber-400" />
          </div>
          <div className="text-xl font-bold font-mono text-slate-100">
            {kpis ? kpis.total_cost_baseline_uah.toLocaleString() : '—'}{' '}
            <span className="text-xs font-normal text-slate-400">грн</span>
          </div>
          <p className="text-[11px] text-slate-400 mt-1">Витрати без наявності BESS</p>
        </div>

        {/* Cost With BESS */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 shadow-sm">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
            <span>{t.kpi_actual}</span>
            <Scale className="w-3.5 h-3.5 text-cyan-400" />
          </div>
          <div className="text-xl font-bold font-mono text-cyan-400">
            {kpis ? kpis.total_cost_actual_uah.toLocaleString() : '—'}{' '}
            <span className="text-xs font-normal text-slate-400">грн</span>
          </div>
          <p className="text-[11px] text-slate-400 mt-1">Фактична оплата за імпорт</p>
        </div>

        {/* Net Financial Effect */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 shadow-sm">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
            <span>{t.kpi_net}</span>
            <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
          </div>
          <div
            className={`text-xl font-bold font-mono ${
              (kpis?.net_benefit_uah || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'
            }`}
          >
            {kpis ? kpis.net_benefit_uah.toLocaleString() : '—'}{' '}
            <span className="text-xs font-normal text-slate-400">грн</span>
          </div>
          <p className="text-[11px] text-slate-400 mt-1">Економія + Дохід - Деградація</p>
        </div>

        {/* Cycles & Payback */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 shadow-sm">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
            <span>{t.kpi_payback} / {t.kpi_cycles}</span>
            <BatteryCharging className="w-3.5 h-3.5 text-purple-400" />
          </div>
          <div className="text-xl font-bold font-mono text-purple-400">
            {kpis?.payback_years ? `${kpis.payback_years} р.` : 'N/A'}{' '}
            <span className="text-xs font-normal text-slate-400">
              ({kpis ? kpis.equivalent_cycles : '0'} циклів)
            </span>
          </div>
          <p className="text-[11px] text-slate-400 mt-1">Розрахунок від CAPEX BESS</p>
        </div>
      </div>

      {/* Hourly Breakdown Chart */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 shadow-sm space-y-3">
        <h2 className="text-sm font-semibold text-slate-200">
          Погодинна динаміка витрат та економічного ефекту
        </h2>
        <div ref={hourlyChartRef} className="w-full h-72" />
      </div>

      {/* Strategy Comparison Section */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-200">{t.comparison_title}</h2>
            <p className="text-xs text-slate-400 mt-0.5">{t.comparison_subtitle}</p>
          </div>

          <div className="flex items-center gap-2">
            <input
              type="date"
              value={compareDate}
              onChange={(e) => setCompareDate(e.target.value)}
              className="bg-slate-950 border border-slate-700 rounded px-2.5 py-1 text-xs text-slate-200 font-mono"
            />
            <button
              onClick={handleRunComparison}
              disabled={isComparing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-cyan-500 hover:bg-cyan-400 text-slate-950 transition-colors disabled:opacity-50"
            >
              <Play className="w-3 h-3 fill-current" />
              <span>{isComparing ? t.comparing : t.btn_run_comparison}</span>
            </button>
          </div>
        </div>

        {/* Comparison Chart */}
        <div ref={compareChartRef} className="w-full h-64" />

        {/* Comparison Table */}
        <div className="overflow-x-auto rounded border border-slate-800">
          <table className="w-full text-xs text-left text-slate-300">
            <thead className="bg-slate-950 text-slate-400 uppercase text-[10px] font-mono">
              <tr>
                <th className="px-3 py-2.5">{t.strategy_name}</th>
                <th className="px-3 py-2.5">Базова вартість</th>
                <th className="px-3 py-2.5">Фактична вартість</th>
                <th className="px-3 py-2.5 text-emerald-400">{t.col_profit}</th>
                <th className="px-3 py-2.5">Дохід експорт</th>
                <th className="px-3 py-2.5">Деградація</th>
                <th className="px-3 py-2.5">{t.col_cycles}</th>
                <th className="px-3 py-2.5">{t.col_status}</th>
                <th className="px-3 py-2.5">{t.col_time}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono">
              {comparisonResults.map((row) => (
                <tr key={row.strategy} className="hover:bg-slate-800/30">
                  <td className="px-3 py-2 font-bold text-cyan-300">{row.strategy}</td>
                  <td className="px-3 py-2">{row.baseline_cost_uah.toLocaleString()} грн</td>
                  <td className="px-3 py-2">{row.actual_cost_uah.toLocaleString()} грн</td>
                  <td className="px-3 py-2 font-bold text-emerald-400">
                    +{row.net_benefit_uah.toLocaleString()} грн
                  </td>
                  <td className="px-3 py-2">{row.export_revenue_uah.toLocaleString()} грн</td>
                  <td className="px-3 py-2 text-rose-400">{row.degradation_uah.toLocaleString()} грн</td>
                  <td className="px-3 py-2">{row.equivalent_cycles}</td>
                  <td className="px-3 py-2">
                    <span className="px-1.5 py-0.5 rounded bg-slate-800 text-[10px] text-slate-300">
                      {row.solver_status || 'OK'}
                    </span>
                  </td>
                  <td className="px-3 py-2">{row.solve_time_ms ?? 0} ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
