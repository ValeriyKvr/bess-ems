import React, { useEffect, useRef, useState } from 'react';
import * as echarts from 'echarts';
import {
  BrainCircuit,
  Play,
  CheckCircle2,
  TrendingUp,
  Cpu,
  BarChart3,
  Layers,
  Sparkles,
  AlertCircle,
  RefreshCw,
} from 'lucide-react';
import {
  fetchMlModels,
  trainModel,
  activateModel,
  fetchForecasts,
  runForecastNow,
  fetchBacktestResults,
} from '../../api/client';
import { MlModelInfo, ForecastPoint, BacktestResult } from '../../types';
import t from '../../i18n/uk.json';

export function MlPage() {
  const [models, setModels] = useState<MlModelInfo[]>([]);
  const [forecasts, setForecasts] = useState<ForecastPoint[]>([]);
  const [backtest, setBacktest] = useState<BacktestResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [training, setTraining] = useState(false);
  const [trainMsg, setTrainMsg] = useState<string | null>(null);

  // Train form state
  const [target, setTarget] = useState<'price' | 'load'>('price');
  const [modelType, setModelType] = useState<'lightgbm' | 'naive' | 'lstm'>('lightgbm');
  const [version, setVersion] = useState('v1.0.0');
  const [fromDate, setFromDate] = useState('2024-01-01');
  const [toDate, setToDate] = useState('2025-12-31');

  // Chart ref
  const chartRef = useRef<HTMLDivElement | null>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);

  const loadData = async () => {
    try {
      setLoading(true);
      const [modelsData, forecastsData, backtestData] = await Promise.all([
        fetchMlModels().catch(() => []),
        fetchForecasts('price', 48).catch(() => []),
        fetchBacktestResults().catch(() => []),
      ]);
      setModels(modelsData);
      setForecasts(forecastsData);
      setBacktest(backtestData);
    } catch (e) {
      console.error('Failed to load ML page data', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  // Initialize and update ECharts
  useEffect(() => {
    if (chartRef.current && !chartInstance.current) {
      chartInstance.current = echarts.init(chartRef.current, 'dark');
    }

    const handleResize = () => chartInstance.current?.resize();
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chartInstance.current?.dispose();
      chartInstance.current = null;
    };
  }, []);

  useEffect(() => {
    if (!chartInstance.current) return;

    if (forecasts.length === 0) {
      chartInstance.current.clear();
      return;
    }

    // Sort ascending by time
    const sorted = [...forecasts].sort(
      (a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime()
    );

    const categories = sorted.map((f) => {
      const d = new Date(f.ts);
      return `${d.toLocaleDateString('uk-UA', { day: '2-digit', month: '2-digit' })} ${d.toLocaleTimeString('uk-UA', { hour: '2-digit', minute: '2-digit' })}`;
    });

    const values = sorted.map((f) => f.value);
    const p10 = sorted.map((f) => f.p10 ?? f.value * 0.85);
    const p90 = sorted.map((f) => f.p90 ?? f.value * 1.15);
    const pBandDiff = p90.map((high, i) => Math.max(0, high - p10[i]));

    const option: echarts.EChartsOption = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        formatter: (params: any) => {
          if (!Array.isArray(params) || params.length === 0) return '';
          const idx = params[0].dataIndex;
          const pt = sorted[idx];
          return `
            <div style="font-family: sans-serif; font-size: 12px;">
              <div style="font-weight: 600; color: #94a3b8; margin-bottom: 4px;">${categories[idx]} (${pt.model_name})</div>
              <div>Прогноз: <span style="font-weight: 600; color: #38bdf8;">${pt.value.toFixed(1)} грн/МВт·год</span></div>
              ${pt.p10 != null ? `<div style="color: #a855f7;">p10: ${pt.p10.toFixed(1)} грн</div>` : ''}
              ${pt.p90 != null ? `<div style="color: #c084fc;">p90: ${pt.p90.toFixed(1)} грн</div>` : ''}
            </div>
          `;
        },
      },
      legend: {
        top: 10,
        right: 20,
        textStyle: { color: '#94a3b8', fontSize: 11 },
        data: ['Прогноз ціни РДН', 'Довірчий інтервал [p10..p90]'],
      },
      grid: {
        left: 60,
        right: 30,
        top: 45,
        bottom: 40,
      },
      xAxis: {
        type: 'category',
        data: categories,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#94a3b8', fontSize: 10, rotate: categories.length > 24 ? 30 : 0 },
      },
      yAxis: {
        type: 'value',
        name: 'грн/МВт·год',
        nameTextStyle: { color: '#64748b', fontSize: 10 },
        splitLine: { lineStyle: { color: '#1e293b' } },
        axisLabel: { color: '#94a3b8', fontSize: 10 },
      },
      series: [
        {
          name: 'p10',
          type: 'line',
          data: p10,
          lineStyle: { opacity: 0 },
          stack: 'confidence-band',
          symbol: 'none',
        },
        {
          name: 'Довірчий інтервал [p10..p90]',
          type: 'line',
          data: pBandDiff,
          lineStyle: { opacity: 0 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(168, 85, 247, 0.35)' },
              { offset: 1, color: 'rgba(59, 130, 246, 0.15)' },
            ]),
          },
          stack: 'confidence-band',
          symbol: 'none',
        },
        {
          name: 'Прогноз ціни РДН',
          type: 'line',
          data: values,
          smooth: true,
          showSymbol: true,
          symbolSize: 5,
          itemStyle: { color: '#38bdf8' },
          lineStyle: { width: 2.5, color: '#38bdf8' },
        },
      ],
    };

    chartInstance.current.setOption(option);
  }, [forecasts]);

  const handleActivate = async (mName: string, mVer: string) => {
    try {
      await activateModel(mName, mVer);
      await loadData();
    } catch (e) {
      console.error('Failed to activate model', e);
    }
  };

  const handleTrainSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setTraining(true);
      setTrainMsg(null);
      const res = await trainModel({
        target,
        model: modelType,
        version,
        from_date: fromDate,
        to_date: toDate,
      });
      setTrainMsg(res.message || t.ml.train_success);
      setTimeout(loadData, 3000);
    } catch (err: any) {
      setTrainMsg(err.message || t.ml.train_failed);
    } finally {
      setTraining(false);
    }
  };

  const handleRunForecast = async () => {
    try {
      await runForecastNow('price');
      await loadData();
    } catch (e) {
      console.error('Failed to run forecast', e);
    }
  };

  const activeModel = models.find((m) => m.is_active && m.target === 'price');

  return (
    <div className="space-y-6 pb-12">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-slate-900/60 p-5 rounded-2xl border border-slate-800/80 backdrop-blur-sm">
        <div className="flex items-center gap-3.5">
          <div className="p-2.5 bg-gradient-to-br from-purple-600/30 to-blue-600/30 text-purple-400 rounded-xl border border-purple-500/30 shadow-inner">
            <BrainCircuit className="w-7 h-7" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2.5">
              {t.ml.title}
              <span className="text-xs px-2.5 py-0.5 rounded-full bg-purple-950/80 text-purple-300 border border-purple-800/60 font-mono">
                SPEC §8 &middot; ML/DL
              </span>
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">{t.ml.subtitle}</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-950/60 border border-slate-800 text-xs">
            <Sparkles className="w-4 h-4 text-amber-400" />
            <span className="text-slate-400">Активна модель:</span>
            <span className="font-semibold text-emerald-400 font-mono">
              {activeModel ? `${activeModel.name}:${activeModel.version}` : 'Naive fallback'}
            </span>
          </div>
          <button
            onClick={loadData}
            disabled={loading}
            className="p-2 rounded-xl bg-slate-800/80 hover:bg-slate-700/80 text-slate-300 transition-colors"
            title="Оновити дані"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-blue-400' : ''}`} />
          </button>
        </div>
      </div>

      {/* Grid: Models Registry (Left) & Train Form (Right) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Models Table */}
        <div className="lg:col-span-8 bg-slate-900/60 border border-slate-800/80 rounded-2xl p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
              <Layers className="w-4 h-4 text-blue-400" />
              {t.ml.models_title}
            </h3>
            <span className="text-xs text-slate-500 font-mono">Всього моделей: {models.length}</span>
          </div>

          <div className="overflow-x-auto rounded-xl border border-slate-800/80">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="bg-slate-950/70 text-slate-400 border-b border-slate-800/80 font-medium">
                  <th className="py-3 px-3.5">{t.ml.col_name}</th>
                  <th className="py-3 px-3">{t.ml.col_version}</th>
                  <th className="py-3 px-3">{t.ml.col_target}</th>
                  <th className="py-3 px-3 text-right">{t.ml.col_mae}</th>
                  <th className="py-3 px-3 text-right">{t.ml.col_mape}</th>
                  <th className="py-3 px-3 text-right">{t.ml.col_rmse}</th>
                  <th className="py-3 px-3 text-right">{t.ml.col_spearman}</th>
                  <th className="py-3 px-3 text-center">{t.ml.col_status}</th>
                  <th className="py-3 px-3.5 text-center">{t.ml.col_actions}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/50 text-slate-300">
                {models.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="py-6 text-center text-slate-500 italic">
                      Немає зареєстрованих моделей. Запустіть навчання праворуч.
                    </td>
                  </tr>
                ) : (
                  models.map((m) => {
                    const isAct = m.is_active;
                    return (
                      <tr
                        key={`${m.name}-${m.version}`}
                        className={`hover:bg-slate-800/30 transition-colors ${
                          isAct ? 'bg-emerald-950/10' : ''
                        }`}
                      >
                        <td className="py-3 px-3.5 font-semibold text-slate-100 flex items-center gap-2">
                          <Cpu className="w-3.5 h-3.5 text-purple-400" />
                          {m.name}
                        </td>
                        <td className="py-3 px-3 font-mono text-slate-400">{m.version}</td>
                        <td className="py-3 px-3">
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-blue-950 text-blue-300 border border-blue-800/50">
                            {m.target}
                          </span>
                        </td>
                        <td className="py-3 px-3 text-right font-mono text-slate-200">
                          {m.metrics?.mae != null ? m.metrics.mae.toFixed(2) : '-'}
                        </td>
                        <td className="py-3 px-3 text-right font-mono text-slate-200">
                          {m.metrics?.mape != null ? `${m.metrics.mape.toFixed(1)}%` : '-'}
                        </td>
                        <td className="py-3 px-3 text-right font-mono text-slate-200">
                          {m.metrics?.rmse != null ? m.metrics.rmse.toFixed(1) : '-'}
                        </td>
                        <td className="py-3 px-3 text-right font-mono text-slate-200">
                          {m.metrics?.spearman_rank_corr != null
                            ? m.metrics.spearman_rank_corr.toFixed(3)
                            : '-'}
                        </td>
                        <td className="py-3 px-3 text-center">
                          {isAct ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-950 text-emerald-300 border border-emerald-800/60">
                              <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                              {t.ml.active}
                            </span>
                          ) : (
                            <span className="inline-block px-2 py-0.5 rounded-full text-[10px] text-slate-500 bg-slate-950 border border-slate-800">
                              {t.ml.inactive}
                            </span>
                          )}
                        </td>
                        <td className="py-3 px-3.5 text-center">
                          {!isAct && (
                            <button
                              onClick={() => handleActivate(m.name, m.version)}
                              className="px-2.5 py-1 text-[11px] font-medium rounded-lg bg-blue-600/20 hover:bg-blue-600 text-blue-300 hover:text-white border border-blue-500/30 transition-all shadow-sm"
                            >
                              {t.ml.btn_activate}
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
        </div>

        {/* Training Form */}
        <div className="lg:col-span-4 bg-slate-900/60 border border-slate-800/80 rounded-2xl p-5 shadow-sm space-y-4">
          <div className="flex items-center gap-2">
            <Play className="w-4 h-4 text-emerald-400" />
            <h3 className="text-sm font-semibold text-slate-200">{t.ml.train_title}</h3>
          </div>

          <form onSubmit={handleTrainSubmit} className="space-y-3.5 text-xs">
            {/* Target */}
            <div>
              <label className="block text-slate-400 mb-1 font-medium">{t.ml.col_target}</label>
              <select
                value={target}
                onChange={(e) => setTarget(e.target.value as any)}
                className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500"
              >
                <option value="price">{t.ml.target_price}</option>
                <option value="load">{t.ml.target_load}</option>
              </select>
            </div>

            {/* Model Architecture */}
            <div>
              <label className="block text-slate-400 mb-1 font-medium">{t.ml.col_name}</label>
              <select
                value={modelType}
                onChange={(e) => setModelType(e.target.value as any)}
                className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500"
              >
                <option value="lightgbm">{t.ml.model_lightgbm}</option>
                <option value="naive">{t.ml.model_naive}</option>
                <option value="lstm">{t.ml.model_lstm}</option>
              </select>
            </div>

            {/* Version */}
            <div>
              <label className="block text-slate-400 mb-1 font-medium">{t.ml.col_version}</label>
              <input
                type="text"
                value={version}
                onChange={(e) => setVersion(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500 font-mono"
                placeholder="v1.0.0"
                required
              />
            </div>

            {/* Date range */}
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-slate-400 mb-1 font-medium">Початок</label>
                <input
                  type="date"
                  value={fromDate}
                  onChange={(e) => setFromDate(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-2.5 py-2 text-slate-200 focus:outline-none focus:border-blue-500 font-mono"
                />
              </div>
              <div>
                <label className="block text-slate-400 mb-1 font-medium">Кінець</label>
                <input
                  type="date"
                  value={toDate}
                  onChange={(e) => setToDate(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-2.5 py-2 text-slate-200 focus:outline-none focus:border-blue-500 font-mono"
                />
              </div>
            </div>

            {trainMsg && (
              <div className="p-2.5 bg-blue-950/40 border border-blue-800/60 rounded-xl text-blue-300 flex items-center gap-2">
                <AlertCircle className="w-3.5 h-3.5 text-blue-400 flex-shrink-0" />
                <span>{trainMsg}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={training}
              className="w-full mt-2 py-2.5 px-4 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-medium flex items-center justify-center gap-2 shadow-md hover:shadow-blue-500/25 transition-all disabled:opacity-50"
            >
              <Play className={`w-3.5 h-3.5 ${training ? 'animate-spin' : ''}`} />
              {training ? 'Навчання триває...' : t.ml.btn_train}
            </button>
          </form>
        </div>
      </div>

      {/* Forecast Chart Section */}
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-5 shadow-sm space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-cyan-400" />
            <h3 className="text-sm font-semibold text-slate-200">
              {t.ml.forecast_chart_title}
            </h3>
          </div>
          <button
            onClick={handleRunForecast}
            className="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-cyan-300 text-xs font-medium border border-cyan-500/30 flex items-center gap-2 transition-colors self-start"
          >
            <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
            {t.ml.btn_run_forecast}
          </button>
        </div>

        {/* ECharts container */}
        <div ref={chartRef} className="w-full h-80 rounded-xl" />
      </div>

      {/* Economic Backtest Comparison Table (SPEC §8.4) */}
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-5 shadow-sm space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-emerald-400" />
            <h3 className="text-sm font-semibold text-slate-200">{t.ml.backtest_title}</h3>
          </div>
          <span className="text-xs text-slate-400">
            Горизонт тесту: 7 днів &middot; BESS 500 кВт / 1000 кВт·год
          </span>
        </div>

        <div className="overflow-x-auto rounded-xl border border-slate-800/80">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="bg-slate-950/70 text-slate-400 border-b border-slate-800/80 font-medium">
                <th className="py-3 px-3.5">{t.ml.bt_model}</th>
                <th className="py-3 px-3.5 text-right">{t.ml.bt_net}</th>
                <th className="py-3 px-3.5 text-right">{t.ml.bt_revenue}</th>
                <th className="py-3 px-3.5 text-right">{t.ml.bt_cost}</th>
                <th className="py-3 px-3.5 text-right">{t.ml.bt_degradation}</th>
                <th className="py-3 px-3.5 text-right">{t.ml.bt_cycles}</th>
                <th className="py-3 px-4 text-left">{t.ml.bt_pct_perfect}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/50 text-slate-300 font-mono">
              {backtest.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-6 text-center text-slate-500 italic font-sans">
                    Завантаження результатів бектесту...
                  </td>
                </tr>
              ) : (
                backtest.map((bt) => {
                  const isPf = bt.model.includes('PERFECT');
                  return (
                    <tr
                      key={`${bt.model}-${bt.version}`}
                      className={`hover:bg-slate-800/30 transition-colors ${
                        isPf ? 'bg-indigo-950/20 font-semibold' : ''
                      }`}
                    >
                      <td className="py-3 px-3.5 font-sans font-medium text-slate-100 flex items-center gap-2">
                        {isPf ? (
                          <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                        ) : (
                          <Cpu className="w-3.5 h-3.5 text-blue-400" />
                        )}
                        {bt.model}
                        <span className="text-[10px] text-slate-500 font-mono">({bt.version})</span>
                      </td>
                      <td className="py-3 px-3.5 text-right font-bold text-emerald-400">
                        {bt.net_uah.toLocaleString('uk-UA', { minimumFractionDigits: 2 })} грн
                      </td>
                      <td className="py-3 px-3.5 text-right text-slate-300">
                        {bt.revenue_uah.toLocaleString('uk-UA', { minimumFractionDigits: 2 })} грн
                      </td>
                      <td className="py-3 px-3.5 text-right text-rose-300">
                        {bt.cost_uah.toLocaleString('uk-UA', { minimumFractionDigits: 2 })} грн
                      </td>
                      <td className="py-3 px-3.5 text-right text-slate-400">
                        {bt.degradation_uah.toLocaleString('uk-UA', { minimumFractionDigits: 2 })} грн
                      </td>
                      <td className="py-3 px-3.5 text-right text-slate-200">
                        {bt.cycles.toFixed(2)}
                      </td>
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2 w-full max-w-[160px]">
                          <div className="flex-1 h-2 rounded-full bg-slate-800 overflow-hidden">
                            <div
                              className={`h-full rounded-full ${
                                isPf
                                  ? 'bg-amber-400'
                                  : bt.pct_of_perfect_foresight > 70
                                  ? 'bg-emerald-400'
                                  : 'bg-blue-400'
                              }`}
                              style={{ width: `${Math.min(100, Math.max(0, bt.pct_of_perfect_foresight))}%` }}
                            />
                          </div>
                          <span className="text-xs font-semibold text-slate-200 w-12 text-right">
                            {bt.pct_of_perfect_foresight.toFixed(1)}%
                          </span>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

