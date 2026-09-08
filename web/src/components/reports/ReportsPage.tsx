import React, { useEffect, useRef, useState } from 'react';
import {
  FileSpreadsheet,
  Download,
  Scale,
  DollarSign,
  TrendingUp,
  BatteryCharging,
  Play,
  Layers,
  Sparkles,
  Calendar,
  Zap,
  BarChart3,
  Sun,
  ShieldCheck,
  RotateCcw,
} from 'lucide-react';
import * as echarts from 'echarts';
import {
  fetchReportSummary,
  downloadReportFile,
  compareStrategies,
  fetchTemplates,
  fetchTemplateReport,
} from '../../api/client';
import {
  ReportSummaryResponse,
  StrategyComparisonItem,
  SimulationTemplate,
  TemplateReportResponse,
} from '../../types';
import ukTranslations from '../../i18n/uk.json';

type MainTab = 'template' | 'historical' | 'strategies';
type PeriodOption = 'today' | 'week' | 'month' | 'custom';

export const fmt = (val: number | undefined | null, fallback = '—'): string => {
  if (val === undefined || val === null || isNaN(val)) return fallback;
  return Number(val).toLocaleString();
};

interface ErrorBoundaryProps {
  children: React.ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class ReportsErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('ReportsPage render error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="p-8 max-w-2xl mx-auto my-12 bg-slate-900 border border-rose-800/60 rounded-2xl text-center space-y-4 shadow-xl">
          <div className="w-12 h-12 rounded-full bg-rose-950/80 border border-rose-700/60 text-rose-400 flex items-center justify-center mx-auto text-xl font-bold">
            !
          </div>
          <h2 className="text-lg font-bold text-slate-100">
            Помилка відображення сторінки звітів
          </h2>
          <p className="text-xs text-slate-400 font-mono bg-slate-950 p-3 rounded-lg border border-slate-800 text-rose-300">
            {this.state.error?.message || 'Невідома помилка під час рендерингу'}
          </p>
          <div className="pt-2 flex justify-center gap-3">
            <button
              onClick={() => {
                this.setState({ hasError: false, error: null });
                window.location.reload();
              }}
              className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 text-white rounded-xl text-xs font-semibold shadow-md transition-all"
            >
              Перезавантажити сторінку
            </button>
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs font-semibold transition-all"
            >
              Спробувати знову
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

const ReportsContent: React.FC = () => {
  const t = ukTranslations.reports;

  const [activeTab, setActiveTab] = useState<MainTab>('template');

  // Template Report state
  const [templates, setTemplates] = useState<SimulationTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>('enterprise_september_2026');
  const [templateDays, setTemplateDays] = useState<number>(9);
  const [templateReport, setTemplateReport] = useState<TemplateReportResponse | null>(null);
  const [isLoadingTemplate, setIsLoadingTemplate] = useState<boolean>(false);

  const templateChartRef = useRef<HTMLDivElement>(null);
  const templateChartInstance = useRef<echarts.ECharts | null>(null);

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

  // Load simulation templates
  useEffect(() => {
    fetchTemplates()
      .then((res) => {
        if (res && res.length > 0) {
          setTemplates(res);
          const def = res.find((x) => x.is_default) || res[0];
          setSelectedTemplateId(def.id);
          setTemplateDays(def.default_loop_days);
        }
      })
      .catch((err) => console.debug('Failed to fetch templates:', err));
  }, []);

  const loadTemplateReport = async (tmplId = selectedTemplateId, days = templateDays) => {
    setIsLoadingTemplate(true);
    try {
      const res = await fetchTemplateReport(tmplId, days);
      setTemplateReport(res);
    } catch (err) {
      console.error('Failed to load template report:', err);
    } finally {
      setIsLoadingTemplate(false);
    }
  };

  useEffect(() => {
    if (selectedTemplateId) {
      loadTemplateReport(selectedTemplateId, templateDays);
    }
  }, [selectedTemplateId, templateDays]);

  const handleExportTemplateCsv = () => {
    if (!templateReport) return;
    const headers = [
      'День',
      'Дата',
      'Базова вартість (грн)',
      'Фактична з BESS (грн)',
      'Деградація BESS (грн)',
      'Чиста економія (грн)',
      'Економія (%)',
      'Заряджено (кВт·год)',
      'Розряджено (кВт·год)',
      'Цикли BESS',
      'Зрізання піку (кВт)',
    ];
    const rows = templateReport.daily.map((d) => [
      d.day_index,
      d.date,
      d.baseline_cost_uah,
      d.actual_cost_uah,
      d.degradation_uah,
      d.net_saving_uah,
      d.saving_pct,
      d.charged_kwh,
      d.discharged_kwh,
      d.cycles,
      d.peak_reduction_kw,
    ]);
    const csvContent = [headers.join(';'), ...rows.map((r) => r.join(';'))].join('\n');
    const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `enterprise_savings_report_${templateReport.template_id}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

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

  // Render Template Performance & Savings Breakdown Chart
  useEffect(() => {
    if (activeTab !== 'template') return;
    if (!templateChartRef.current || !templateReport || !templateReport.daily?.length) return;
    if (!templateChartInstance.current) {
      templateChartInstance.current = echarts.init(templateChartRef.current, 'dark');
    }
    const chart = templateChartInstance.current;

    const dayLabels = (templateReport.daily || []).map(
      (d) => `Д${d.day_index} (${(d.date || '').slice(5)})`
    );
    const baseline = (templateReport.daily || []).map((d) => d.baseline_cost_uah ?? 0);
    const actual = (templateReport.daily || []).map((d) => d.actual_cost_uah ?? 0);
    const savings = (templateReport.daily || []).map((d) => d.net_saving_uah ?? 0);
    const cycles = (templateReport.daily || []).map((d) => d.cycles ?? 0);

    const option: echarts.EChartsOption = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: (params: any) => {
          let s = `${params[0]?.axisValue}<br/>`;
          params.forEach((p: any) => {
            const unit = p.seriesName === 'Цикли' ? ' ц' : ' грн';
            s += `<span style="color:${p.color}">●</span> ${p.seriesName}: ${Number(p.value).toLocaleString()} ${unit}<br/>`;
          });
          return s;
        },
      },
      legend: {
        data: ['Базова вартість', 'Фактична з BESS', 'Чиста економія', 'Цикли'],
        textStyle: { color: '#94a3b8', fontSize: 11 },
        top: 0,
      },
      grid: { left: 60, right: 50, top: 40, bottom: 35 },
      xAxis: {
        type: 'category',
        data: dayLabels,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#cbd5e1', fontSize: 11 },
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
          axisLabel: { color: '#a855f7', fontSize: 10 },
        },
      ],
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
          name: 'Чиста економія',
          type: 'line',
          data: savings,
          smooth: true,
          itemStyle: { color: '#10b981' },
          lineStyle: { width: 3 },
          symbolSize: 6,
        },
        {
          name: 'Цикли',
          type: 'line',
          yAxisIndex: 1,
          data: cycles,
          itemStyle: { color: '#a855f7' },
          lineStyle: { width: 2, type: 'dashed' },
          symbolSize: 6,
        },
      ],
    };

    chart.setOption(option);
    const handleResize = () => chart.resize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [templateReport, activeTab]);

  const kpis = reportData?.summary;
  const tmplKpi = templateReport?.kpi;

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Top Header & Main Tabs */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-5">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-2.5">
            <BarChart3 className="w-6 h-6 text-cyan-400" />
            <span>Аналітичні та економічні звіти</span>
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Аналіз фінансової ефективності BESS, економія підприємства та оптимізація тарифів
          </p>
        </div>

        {/* Tab Switcher */}
        <div className="flex bg-slate-900/90 p-1 rounded-xl border border-slate-800 text-xs self-start">
          <button
            onClick={() => setActiveTab('template')}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg font-medium transition-all ${
              activeTab === 'template'
                ? 'bg-cyan-600 text-white font-semibold shadow-sm shadow-cyan-600/30'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
            }`}
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>Звіт за шаблоном (Економіка)</span>
          </button>
          <button
            onClick={() => setActiveTab('historical')}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg font-medium transition-all ${
              activeTab === 'historical'
                ? 'bg-cyan-600 text-white font-semibold shadow-sm shadow-cyan-600/30'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
            }`}
          >
            <Calendar className="w-3.5 h-3.5" />
            <span>Історичний підсумок</span>
          </button>
          <button
            onClick={() => setActiveTab('strategies')}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg font-medium transition-all ${
              activeTab === 'strategies'
                ? 'bg-cyan-600 text-white font-semibold shadow-sm shadow-cyan-600/30'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
            }`}
          >
            <Scale className="w-3.5 h-3.5" />
            <span>Порівняння стратегій</span>
          </button>
        </div>
      </div>

      {/* ── TAB 1: TEMPLATE SAVINGS REPORT ───────────────────────────────────── */}
      {activeTab === 'template' && (
        <div className="space-y-6 animate-fade-in">
          {/* Controls & Scenario Details Card */}
          <div className="p-5 rounded-2xl bg-slate-900/90 border border-slate-800 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-4">
              {/* Template selection & days buttons */}
              <div className="flex flex-wrap items-center gap-3">
                <div className="flex items-center gap-2 text-slate-300 text-xs">
                  <Layers className="w-4 h-4 text-cyan-400" />
                  <span className="font-semibold text-slate-400">Шаблон моделі:</span>
                  <select
                    value={selectedTemplateId}
                    onChange={(e) => {
                      const newId = e.target.value;
                      setSelectedTemplateId(newId);
                      const t = templates.find((x) => x.id === newId);
                      if (t) setTemplateDays(t.default_loop_days);
                    }}
                    className="bg-slate-950 border border-slate-700 text-slate-100 rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:border-cyan-500 font-medium"
                  >
                    {templates.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="flex items-center gap-1.5 text-slate-400 text-xs">
                  <RotateCcw className="w-3.5 h-3.5 text-blue-400" />
                  <span>Діапазон:</span>
                  <div className="flex items-center gap-1">
                    {[1, 3, 5, 7, 9].map((d) => (
                      <button
                        key={d}
                        onClick={() => setTemplateDays(d)}
                        className={`px-2.5 py-1 rounded text-xs font-mono transition-all ${
                          templateDays === d
                            ? 'bg-blue-600 text-white font-bold shadow-sm shadow-blue-600/30'
                            : 'bg-slate-950 text-slate-400 hover:text-slate-200 border border-slate-800'
                        }`}
                      >
                        {d} днів
                      </button>
                    ))}
                  </div>
                </div>

                <button
                  onClick={() => loadTemplateReport(selectedTemplateId, templateDays)}
                  disabled={isLoadingTemplate}
                  className="px-3 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white text-xs font-semibold flex items-center gap-1.5 transition-all shadow-sm shadow-cyan-600/20"
                >
                  <Sparkles className="w-3.5 h-3.5" />
                  <span>{isLoadingTemplate ? 'Розрахунок...' : 'Оновити розрахунок'}</span>
                </button>
              </div>

              {/* Export CSV */}
              <button
                onClick={handleExportTemplateCsv}
                disabled={!templateReport}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white transition-colors shadow-sm disabled:opacity-50"
              >
                <Download className="w-3.5 h-3.5" />
                <span>Експорт звіту (CSV)</span>
              </button>
            </div>

            {/* Model Setup Parameters Overview */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 pt-3 border-t border-slate-800/80 text-xs">
              <div className="p-2.5 rounded-xl bg-slate-950/60 border border-slate-800/80 flex items-center gap-2.5">
                <Zap className="w-4 h-4 text-amber-400 shrink-0" />
                <div>
                  <div className="text-[10px] text-slate-400">Споживання підприємства</div>
                  <div className="font-semibold text-slate-200">200–300 кВт (день) / 0–100 кВт (ніч)</div>
                </div>
              </div>
              <div className="p-2.5 rounded-xl bg-slate-950/60 border border-slate-800/80 flex items-center gap-2.5">
                <Sun className="w-4 h-4 text-yellow-400 shrink-0" />
                <div>
                  <div className="text-[10px] text-slate-400">Сонячна генерація (СЕС)</div>
                  <div className="font-semibold text-slate-200">50–150 кВт (денний пік)</div>
                </div>
              </div>
              <div className="p-2.5 rounded-xl bg-slate-950/60 border border-slate-800/80 flex items-center gap-2.5">
                <BatteryCharging className="w-4 h-4 text-cyan-400 shrink-0" />
                <div>
                  <div className="text-[10px] text-slate-400">Накопичувач енергії (BESS)</div>
                  <div className="font-semibold text-slate-200">1 000 кВт / 2 000 кВт·год (DoD 10–90%)</div>
                </div>
              </div>
              <div className="p-2.5 rounded-xl bg-slate-950/60 border border-slate-800/80 flex items-center gap-2.5">
                <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0" />
                <div>
                  <div className="text-[10px] text-slate-400">Ринкові тарифи</div>
                  <div className="font-semibold text-slate-200">Реальний РДН України (01–09.09.2026)</div>
                </div>
              </div>
            </div>
          </div>

          {/* 4 Primary Financial KPI Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {/* Baseline Cost */}
            <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-sm">
              <div className="flex items-center justify-between text-xs text-slate-400 mb-1.5">
                <span>Базова вартість (без BESS)</span>
                <DollarSign className="w-4 h-4 text-amber-400" />
              </div>
              <div className="text-2xl font-bold font-mono text-slate-100">
                {tmplKpi ? fmt(tmplKpi.baseline_cost_uah) : '—'}{' '}
                <span className="text-xs font-normal text-slate-400">грн</span>
              </div>
              <p className="text-[11px] text-slate-400 mt-1">Витрати підприємства на імпорт за період</p>
            </div>

            {/* Actual Cost With BESS */}
            <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-sm">
              <div className="flex items-center justify-between text-xs text-slate-400 mb-1.5">
                <span>Фактична вартість (з BESS)</span>
                <Scale className="w-4 h-4 text-cyan-400" />
              </div>
              <div className="text-2xl font-bold font-mono text-cyan-400">
                {tmplKpi ? fmt(tmplKpi.actual_cost_uah) : '—'}{' '}
                <span className="text-xs font-normal text-slate-400">грн</span>
              </div>
              <p className="text-[11px] text-slate-400 mt-1">Оплата з урахуванням оптимізації заряд/розряд</p>
            </div>

            {/* Net Savings */}
            <div className="bg-gradient-to-br from-emerald-950/80 to-slate-900 border border-emerald-700/60 rounded-2xl p-5 shadow-md shadow-emerald-950/30">
              <div className="flex items-center justify-between text-xs text-emerald-300 font-semibold mb-1.5">
                <span>Чиста економія підприємства</span>
                <TrendingUp className="w-4 h-4 text-emerald-400" />
              </div>
              <div className="text-2xl font-black font-mono text-emerald-400">
                {tmplKpi ? `+${fmt(tmplKpi.net_savings_uah)}` : '—'}{' '}
                <span className="text-xs font-semibold text-emerald-300">грн</span>
                {tmplKpi && (
                  <span className="ml-2 text-sm font-bold text-emerald-300 bg-emerald-900/60 px-2 py-0.5 rounded border border-emerald-600/60">
                    +{tmplKpi.savings_pct ?? 0}%
                  </span>
                )}
              </div>
              <p className="text-[11px] text-emerald-300/80 mt-1">
                Чистий економічний ефект за вирахуванням деградації
              </p>
            </div>

            {/* Degradation & Cycles */}
            <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-sm">
              <div className="flex items-center justify-between text-xs text-slate-400 mb-1.5">
                <span>Амортизація BESS (деградація)</span>
                <BatteryCharging className="w-4 h-4 text-purple-400" />
              </div>
              <div className="text-2xl font-bold font-mono text-purple-400">
                {tmplKpi ? fmt(tmplKpi.total_degradation_uah) : '—'}{' '}
                <span className="text-xs font-normal text-slate-400">грн</span>
              </div>
              <p className="text-[11px] text-slate-400 mt-1">
                {tmplKpi ? `${tmplKpi.total_cycles ?? 0} екв. циклів (~${((tmplKpi.total_cycles ?? 0) / (templateDays || 1)).toFixed(1)} ц/добу)` : 'Розрахунок зносу'}
              </p>
            </div>
          </div>

          {/* 4 Financial Projections & Peak Shaving Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-slate-900/70 border border-slate-800/80 rounded-xl p-4">
              <div className="text-xs text-slate-400">Середня економія на добу</div>
              <div className="text-lg font-bold font-mono text-emerald-400 mt-1">
                {tmplKpi ? `+${fmt(tmplKpi.avg_daily_savings_uah)} грн/день` : '—'}
              </div>
            </div>
            <div className="bg-slate-900/70 border border-slate-800/80 rounded-xl p-4">
              <div className="text-xs text-slate-400">Прогноз економії на місяць (30 дн.)</div>
              <div className="text-lg font-bold font-mono text-emerald-400 mt-1">
                {tmplKpi ? `+${fmt((tmplKpi.avg_daily_savings_uah ?? 0) * 30)} грн` : '—'}
              </div>
            </div>
            <div className="bg-slate-900/70 border border-slate-800/80 rounded-xl p-4">
              <div className="text-xs text-slate-400">Прогноз економії на рік (365 дн.)</div>
              <div className="text-lg font-bold font-mono text-emerald-400 mt-1">
                {tmplKpi ? `+${fmt((tmplKpi.avg_daily_savings_uah ?? 0) * 365)} грн` : '—'}
              </div>
            </div>
            <div className="bg-slate-900/70 border border-slate-800/80 rounded-xl p-4">
              <div className="text-xs text-slate-400">Зрізання піку з мережі (Peak Shaving)</div>
              <div className="text-lg font-bold font-mono text-cyan-400 mt-1">
                {tmplKpi ? `-${tmplKpi.peak_shaving_kw ?? 0} кВт (-${tmplKpi.peak_shaving_pct ?? 0}%)` : '—'}
              </div>
            </div>
          </div>

          {/* Chart: Daily Comparison & Cycles */}
          <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-sm space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-base font-semibold text-slate-100">
                  Поденна динаміка витрат та чистої економії
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Порівняння витрат без батареї (базовий тариф) та чистого фінансового ефекту з BESS
                </p>
              </div>
            </div>
            <div ref={templateChartRef} className="w-full h-80" />
          </div>

          {/* Table: Detailed Daily Breakdown */}
          <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
            <h2 className="text-base font-semibold text-slate-100">
              Поденний фінансовий та технологічний звіт
            </h2>
            <div className="overflow-x-auto rounded-xl border border-slate-800">
              <table className="w-full text-xs text-left text-slate-300">
                <thead className="bg-slate-950 text-slate-400 uppercase text-[10px] font-mono">
                  <tr>
                    <th className="px-3 py-3">День</th>
                    <th className="px-3 py-3">Дата</th>
                    <th className="px-3 py-3">Базова вартість</th>
                    <th className="px-3 py-3">Фактична з BESS</th>
                    <th className="px-3 py-3">Деградація</th>
                    <th className="px-3 py-3 text-emerald-400 font-bold">Чиста економія</th>
                    <th className="px-3 py-3 text-emerald-400">%</th>
                    <th className="px-3 py-3">Заряджено</th>
                    <th className="px-3 py-3">Розряджено</th>
                    <th className="px-3 py-3">Цикли</th>
                    <th className="px-3 py-3">Зрізання піку</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-mono">
                  {templateReport?.daily?.map((row) => (
                    <tr key={row.day_index} className="hover:bg-slate-800/30 transition-colors">
                      <td className="px-3 py-2.5 font-bold text-cyan-400">День {row.day_index}</td>
                      <td className="px-3 py-2.5 text-slate-400">{row.date}</td>
                      <td className="px-3 py-2.5">{fmt(row.baseline_cost_uah)} грн</td>
                      <td className="px-3 py-2.5 text-cyan-300">{fmt(row.actual_cost_uah)} грн</td>
                      <td className="px-3 py-2.5 text-purple-400">{fmt(row.degradation_uah)} грн</td>
                      <td className="px-3 py-2.5 font-bold text-emerald-400">
                        +{fmt(row.net_saving_uah)} грн
                      </td>
                      <td className="px-3 py-2.5 text-emerald-300 font-bold">+{row.saving_pct ?? 0}%</td>
                      <td className="px-3 py-2.5">{fmt(row.charged_kwh)} кВт·г</td>
                      <td className="px-3 py-2.5">{fmt(row.discharged_kwh)} кВт·г</td>
                      <td className="px-3 py-2.5 text-slate-300">{row.cycles ?? 0}</td>
                      <td className="px-3 py-2.5 text-slate-400">
                        {(row.peak_reduction_kw ?? 0) > 0 ? `-${row.peak_reduction_kw} кВт` : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
                {tmplKpi && (
                  <tfoot className="bg-slate-950/90 font-mono font-bold text-slate-100 border-t border-slate-700">
                    <tr>
                      <td className="px-3 py-3" colSpan={2}>
                        ВСЬОГО ЗА {templateReport?.analyzed_days ?? templateDays} ДНІВ
                      </td>
                      <td className="px-3 py-3 text-amber-400">
                        {fmt(tmplKpi.baseline_cost_uah)} грн
                      </td>
                      <td className="px-3 py-3 text-cyan-300">
                        {fmt(tmplKpi.actual_cost_uah)} грн
                      </td>
                      <td className="px-3 py-3 text-purple-400">
                        {fmt(tmplKpi.total_degradation_uah)} грн
                      </td>
                      <td className="px-3 py-3 text-emerald-400">
                        +{fmt(tmplKpi.net_savings_uah)} грн
                      </td>
                      <td className="px-3 py-3 text-emerald-300">+{tmplKpi.savings_pct ?? 0}%</td>
                      <td className="px-3 py-3">{fmt(tmplKpi.total_charged_kwh)} кВт·г</td>
                      <td className="px-3 py-3">{fmt(tmplKpi.total_discharged_kwh)} кВт·г</td>
                      <td className="px-3 py-3">{tmplKpi.total_cycles ?? 0} ц</td>
                      <td className="px-3 py-3 text-cyan-300">-{tmplKpi.peak_shaving_kw ?? 0} кВт</td>
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ── TAB 2: HISTORICAL FINANCIAL SUMMARY ─────────────────────────────── */}
      {activeTab === 'historical' && (
        <div className="space-y-6 animate-fade-in">
          {/* Period Selector & Export Buttons */}
          <div className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-xl bg-slate-900 border border-slate-800">
            <div className="flex bg-slate-950 p-0.5 rounded-lg border border-slate-800 text-xs">
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

          {/* KPI Cards Grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 shadow-sm">
              <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                <span>{t.kpi_baseline}</span>
                <DollarSign className="w-3.5 h-3.5 text-amber-400" />
              </div>
              <div className="text-xl font-bold font-mono text-slate-100">
                {kpis ? fmt(kpis.total_cost_baseline_uah) : '—'}{' '}
                <span className="text-xs font-normal text-slate-400">грн</span>
              </div>
              <p className="text-[11px] text-slate-400 mt-1">Витрати без наявності BESS</p>
            </div>

            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 shadow-sm">
              <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                <span>{t.kpi_actual}</span>
                <Scale className="w-3.5 h-3.5 text-cyan-400" />
              </div>
              <div className="text-xl font-bold font-mono text-cyan-400">
                {kpis ? fmt(kpis.total_cost_actual_uah) : '—'}{' '}
                <span className="text-xs font-normal text-slate-400">грн</span>
              </div>
              <p className="text-[11px] text-slate-400 mt-1">Фактична оплата за імпорт</p>
            </div>

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
                {kpis ? fmt(kpis.net_benefit_uah) : '—'}{' '}
                <span className="text-xs font-normal text-slate-400">грн</span>
              </div>
              <p className="text-[11px] text-slate-400 mt-1">Економія + Дохід - Деградація</p>
            </div>

            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 shadow-sm">
              <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                <span>{t.kpi_payback} / {t.kpi_cycles}</span>
                <BatteryCharging className="w-3.5 h-3.5 text-purple-400" />
              </div>
              <div className="text-xl font-bold font-mono text-purple-400">
                {kpis?.payback_years ? `${kpis.payback_years} р.` : 'N/A'}{' '}
                <span className="text-xs font-normal text-slate-400">
                  ({kpis ? fmt(kpis.equivalent_cycles) : '0'} циклів)
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
        </div>
      )}

      {/* ── TAB 3: STRATEGY COMPARISON ───────────────────────────────────────── */}
      {activeTab === 'strategies' && (
        <div className="bg-slate-900/80 border border-slate-800 rounded-2xl p-5 shadow-sm space-y-4 animate-fade-in">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-slate-100">{t.comparison_title}</h2>
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
          <div className="overflow-x-auto rounded-xl border border-slate-800">
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
                {comparisonResults?.map((row) => (
                  <tr key={row.strategy} className="hover:bg-slate-800/30">
                    <td className="px-3 py-2 font-bold text-cyan-300">{row.strategy}</td>
                    <td className="px-3 py-2">{fmt(row.baseline_cost_uah)} грн</td>
                    <td className="px-3 py-2">{fmt(row.actual_cost_uah)} грн</td>
                    <td className="px-3 py-2 font-bold text-emerald-400">
                      +{fmt(row.net_benefit_uah)} грн
                    </td>
                    <td className="px-3 py-2">{fmt(row.export_revenue_uah)} грн</td>
                    <td className="px-3 py-2 text-rose-400">{fmt(row.degradation_uah)} грн</td>
                    <td className="px-3 py-2">{row.equivalent_cycles ?? 0}</td>
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
      )}
    </div>
  );
};

export const ReportsPage: React.FC = () => (
  <ReportsErrorBoundary>
    <ReportsContent />
  </ReportsErrorBoundary>
);

