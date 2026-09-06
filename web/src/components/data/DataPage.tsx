import React, { useEffect, useRef, useState } from 'react';
import {
  UploadCloud,
  Database,
  CheckCircle2,
  AlertTriangle,
  FileSpreadsheet,
  Play,
  Calendar,
  Grid,
} from 'lucide-react';
import * as echarts from 'echarts';
import {
  previewCsvData,
  importCsvData,
  generateSyntheticData,
  fetchHeatmapData,
  fetchTimeSeries,
} from '../../api/client';
import { CsvPreviewResponse, HeatmapDataResponse, TimeSeriesDataPoint } from '../../types';
import ukTranslations from '../../i18n/uk.json';

export const DataPage: React.FC = () => {
  const t = ukTranslations.data;

  // CSV Import State
  const [dragActive, setDragActive] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewData, setPreviewData] = useState<CsvPreviewResponse | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [importResult, setImportResult] = useState<{ status: 'success' | 'error'; message: string } | null>(null);

  // Synthetic Generator State
  const [startDate, setStartDate] = useState('2026-03-01T00:00:00Z');
  const [endDate, setEndDate] = useState('2026-03-07T23:00:00Z');
  const [seed, setSeed] = useState(42);
  const [overwrite, setOverwrite] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [genResult, setGenResult] = useState<string | null>(null);

  // Time Series State
  const [seriesType, setSeriesType] = useState<'price' | 'load' | 'pv'>('price');
  const [seriesFrom, setSeriesFrom] = useState('2026-03-01T00:00:00Z');
  const [seriesTo, setSeriesTo] = useState('2026-03-07T23:00:00Z');
  const [seriesPoints, setSeriesPoints] = useState<TimeSeriesDataPoint[]>([]);
  const timeSeriesChartRef = useRef<HTMLDivElement>(null);
  const timeSeriesChartInstance = useRef<echarts.ECharts | null>(null);

  // Heatmap State
  const [heatmapType, setHeatmapType] = useState<'price' | 'load'>('price');
  const [heatmapData, setHeatmapData] = useState<HeatmapDataResponse | null>(null);
  const heatmapChartRef = useRef<HTMLDivElement>(null);
  const heatmapChartInstance = useRef<echarts.ECharts | null>(null);

  // Handle Drag & Drop
  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') setDragActive(true);
    else if (e.type === 'dragleave') setDragActive(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileSelected(e.dataTransfer.files[0]);
    }
  };

  const handleFileSelected = async (file: File) => {
    setSelectedFile(file);
    setImportResult(null);
    try {
      const res = await previewCsvData(file);
      setPreviewData(res);
    } catch (err: any) {
      setImportResult({ status: 'error', message: err.message || 'Помилка читання файлу' });
    }
  };

  const handleConfirmImport = async () => {
    if (!selectedFile || !previewData) return;
    const detected = (previewData.detected_type === 'load' ? 'load' : 'price') as 'price' | 'load';
    setIsImporting(true);
    setImportResult(null);
    try {
      const res = await importCsvData(selectedFile, detected);
      setImportResult({
        status: 'success',
        message: `${t.import_success} ${res.imported_rows}`,
      });
      // Refresh charts
      loadTimeSeries();
      loadHeatmap();
    } catch (err: any) {
      setImportResult({ status: 'error', message: err.message || 'Помилка імпорту' });
    } finally {
      setIsImporting(false);
    }
  };

  const handleGenerateSynthetic = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsGenerating(true);
    setGenResult(null);
    try {
      const res = await generateSyntheticData({
        start_date: startDate,
        end_date: endDate,
        seed,
        overwrite,
      });
      setGenResult(`Згенеровано: ${res.prices_count} цін РДН, ${res.load_count} інтервалів навантаження`);
      loadTimeSeries();
      loadHeatmap();
    } catch (err: any) {
      setGenResult(`Помилка: ${err.message}`);
    } finally {
      setIsGenerating(false);
    }
  };

  // Load Time Series
  const loadTimeSeries = async () => {
    try {
      const res = await fetchTimeSeries(seriesType, seriesFrom, seriesTo);
      setSeriesPoints(res.data);
    } catch (err) {
      console.error('Failed to load series', err);
    }
  };

  useEffect(() => {
    loadTimeSeries();
  }, [seriesType, seriesFrom, seriesTo]);

  // Render Time Series EChart
  useEffect(() => {
    if (!timeSeriesChartRef.current) return;
    if (!timeSeriesChartInstance.current) {
      timeSeriesChartInstance.current = echarts.init(timeSeriesChartRef.current, 'dark');
    }
    const chart = timeSeriesChartInstance.current;

    const timestamps = seriesPoints.map((p) => p.ts.replace('T', ' ').replace('Z', ''));
    const values = seriesPoints.map((p) => p.value);

    const isPrice = seriesType === 'price';
    const unit = isPrice ? 'грн/МВт·год' : 'кВт';
    const lineColor = isPrice ? '#06b6d4' : seriesType === 'load' ? '#f59e0b' : '#10b981';

    const option: echarts.EChartsOption = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        formatter: (params: any) => {
          if (!params || !params[0]) return '';
          return `${params[0].axisValue}<br/><span style="color:${lineColor}">●</span> ${params[0].value} ${unit}`;
        },
      },
      grid: { left: 55, right: 20, top: 30, bottom: 65 },
      xAxis: {
        type: 'category',
        data: timestamps,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#94a3b8', fontSize: 10 },
      },
      yAxis: {
        type: 'value',
        name: unit,
        nameTextStyle: { color: '#64748b', fontSize: 10 },
        splitLine: { lineStyle: { color: '#1e293b' } },
        axisLabel: { color: '#94a3b8', fontSize: 10 },
      },
      dataZoom: [
        { type: 'slider', bottom: 10, height: 20, borderColor: '#334155', textStyle: { color: '#64748b' } },
        { type: 'inside' },
      ],
      series: [
        {
          name: seriesType,
          type: 'line',
          showSymbol: false,
          smooth: true,
          lineStyle: { color: lineColor, width: 2 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: `${lineColor}40` },
              { offset: 1, color: `${lineColor}00` },
            ]),
          },
          data: values,
        },
      ],
    };

    chart.setOption(option);

    const handleResize = () => chart.resize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [seriesPoints, seriesType]);

  // Load Heatmap Data
  const loadHeatmap = async () => {
    try {
      const res = await fetchHeatmapData(heatmapType);
      setHeatmapData(res);
    } catch (err) {
      console.error('Failed to load heatmap', err);
    }
  };

  useEffect(() => {
    loadHeatmap();
  }, [heatmapType]);

  // Render Heatmap EChart
  useEffect(() => {
    if (!heatmapChartRef.current || !heatmapData) return;
    if (!heatmapChartInstance.current) {
      heatmapChartInstance.current = echarts.init(heatmapChartRef.current, 'dark');
    }
    const chart = heatmapChartInstance.current;

    const option: echarts.EChartsOption = {
      backgroundColor: 'transparent',
      tooltip: {
        position: 'top',
        formatter: (params: any) => {
          const [hourIdx, dowIdx, val] = params.data;
          const dow = heatmapData.y_categories[dowIdx];
          const hr = heatmapData.x_categories[hourIdx];
          return `${dow} ${hr}<br/><strong>${val} ${heatmapData.unit}</strong>`;
        },
      },
      grid: { left: 45, right: 30, top: 20, bottom: 50 },
      xAxis: {
        type: 'category',
        data: heatmapData.x_categories,
        splitArea: { show: true },
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#94a3b8', fontSize: 10, interval: 1 },
      },
      yAxis: {
        type: 'category',
        data: heatmapData.y_categories,
        splitArea: { show: true },
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#94a3b8', fontSize: 11 },
      },
      visualMap: {
        min: heatmapData.min_value || 0,
        max: heatmapData.max_value || 100,
        calculable: true,
        orient: 'horizontal',
        left: 'center',
        bottom: 0,
        inRange: {
          color: ['#0f172a', '#1e3a8a', '#0284c7', '#38bdf8', '#fbbf24', '#ef4444'],
        },
        textStyle: { color: '#94a3b8', fontSize: 10 },
      },
      series: [
        {
          name: heatmapType,
          type: 'heatmap',
          data: heatmapData.data,
          label: { show: false },
          emphasis: {
            itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0, 0, 0, 0.5)' },
          },
        },
      ],
    };

    chart.setOption(option);

    const handleResize = () => chart.resize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [heatmapData, heatmapType]);

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-100">{t.title}</h1>
        <p className="text-sm text-slate-400 mt-1">{t.subtitle}</p>
      </div>

      {/* Top Grid: CSV Uploader + Synthetic Generator */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* CSV Drag & Drop Card */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <UploadCloud className="w-5 h-5 text-cyan-400" />
              <h2 className="text-sm font-semibold text-slate-200">{t.upload_title}</h2>
            </div>
            <p className="text-xs text-slate-400 mb-4">{t.upload_types}</p>

            <div
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              className={`border-2 border-dashed rounded-lg p-6 text-center transition-colors cursor-pointer ${
                dragActive
                  ? 'border-cyan-400 bg-cyan-950/20'
                  : 'border-slate-700 hover:border-slate-500 bg-slate-950/40'
              }`}
              onClick={() => document.getElementById('csv-file-input')?.click()}
            >
              <input
                id="csv-file-input"
                type="file"
                accept=".csv"
                className="hidden"
                onChange={(e) => e.target.files?.[0] && handleFileSelected(e.target.files[0])}
              />
              <FileSpreadsheet className="w-8 h-8 text-slate-400 mx-auto mb-2" />
              <p className="text-xs font-medium text-slate-300">
                {selectedFile ? selectedFile.name : t.upload_drag}
              </p>
              <p className="text-[11px] text-slate-400 mt-1">.csv (макс. 50 MB)</p>
            </div>

            {importResult && (
              <div
                className={`mt-3 p-3 rounded-lg text-xs flex items-center gap-2 ${
                  importResult.status === 'success'
                    ? 'bg-emerald-950/60 border border-emerald-500/40 text-emerald-300'
                    : 'bg-rose-950/60 border border-rose-500/40 text-rose-300'
                }`}
              >
                {importResult.status === 'success' ? (
                  <CheckCircle2 className="w-4 h-4 shrink-0" />
                ) : (
                  <AlertTriangle className="w-4 h-4 shrink-0" />
                )}
                <span>{importResult.message}</span>
              </div>
            )}
          </div>

          {previewData && (
            <div className="mt-4 pt-3 border-t border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs">
                <span className="text-slate-400">{t.detected_type}:</span>
                <span className="font-mono px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-500/30">
                  {previewData.detected_type}
                </span>
                <span className="text-slate-400">({previewData.total_rows} рядків)</span>
              </div>
              <button
                onClick={handleConfirmImport}
                disabled={!previewData.is_valid || isImporting}
                className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-cyan-500 hover:bg-cyan-400 text-slate-950 transition-colors disabled:opacity-40"
              >
                {isImporting ? t.importing : t.btn_confirm_import}
              </button>
            </div>
          )}
        </div>

        {/* Synthetic Generator Card */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Database className="w-5 h-5 text-amber-400" />
              <h2 className="text-sm font-semibold text-slate-200">{t.synthetic_title}</h2>
            </div>
            <p className="text-xs text-slate-400 mb-4">
              Генерація синтетичних цін РДН та промислового навантаження за математичними моделями (SPEC §6.1)
            </p>

            <form onSubmit={handleGenerateSynthetic} className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[11px] font-semibold text-slate-400">{t.start_date}</label>
                  <input
                    type="text"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="w-full mt-1 bg-slate-950 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-200 font-mono"
                  />
                </div>
                <div>
                  <label className="text-[11px] font-semibold text-slate-400">{t.end_date}</label>
                  <input
                    type="text"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="w-full mt-1 bg-slate-950 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-200 font-mono"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 items-center pt-1">
                <div>
                  <label className="text-[11px] font-semibold text-slate-400">{t.seed}</label>
                  <input
                    type="number"
                    value={seed}
                    onChange={(e) => setSeed(Number(e.target.value))}
                    className="w-full mt-1 bg-slate-950 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-200 font-mono"
                  />
                </div>
                <div className="flex items-center gap-2 pt-4">
                  <input
                    type="checkbox"
                    id="overwrite-check"
                    checked={overwrite}
                    onChange={(e) => setOverwrite(e.target.checked)}
                    className="w-4 h-4 rounded border-slate-700 text-cyan-600 bg-slate-950"
                  />
                  <label htmlFor="overwrite-check" className="text-xs text-slate-300 cursor-pointer">
                    {t.overwrite}
                  </label>
                </div>
              </div>

              {genResult && (
                <div className="p-2.5 rounded bg-slate-950 border border-slate-800 text-[11px] font-mono text-cyan-300">
                  {genResult}
                </div>
              )}

              <button
                type="submit"
                disabled={isGenerating}
                className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold text-slate-950 bg-amber-400 hover:bg-amber-300 transition-colors disabled:opacity-50"
              >
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>{isGenerating ? t.generating : t.btn_generate}</span>
              </button>
            </form>
          </div>
        </div>
      </div>

      {/* CSV Preview Table (if file loaded) */}
      {previewData && (
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-200">{t.preview_title}</h3>
            <span
              className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded ${
                previewData.is_valid
                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                  : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
              }`}
            >
              {previewData.is_valid ? t.valid_format : t.invalid_format}
            </span>
          </div>

          {previewData.errors.length > 0 && (
            <div className="p-2.5 rounded bg-rose-950/40 border border-rose-500/30 text-xs text-rose-300 space-y-1">
              {previewData.errors.map((err, i) => (
                <div key={i}>• {err}</div>
              ))}
            </div>
          )}

          <div className="overflow-x-auto max-h-60 rounded border border-slate-800">
            <table className="w-full text-xs text-left text-slate-300">
              <thead className="bg-slate-950 text-slate-400 font-mono uppercase text-[10px] sticky top-0">
                <tr>
                  {previewData.columns.map((c) => (
                    <th key={c} className="px-3 py-2 border-b border-slate-800">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono">
                {previewData.preview_rows.map((row, idx) => (
                  <tr key={idx} className="hover:bg-slate-800/40">
                    {previewData.columns.map((c) => (
                      <td key={c} className="px-3 py-1.5 whitespace-nowrap">
                        {String(row[c] ?? '')}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Time Series Viewer Card */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Calendar className="w-4 h-4 text-cyan-400" />
            <h2 className="text-sm font-semibold text-slate-200">{t.chart_title}</h2>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-1.5 text-xs text-slate-400">
              <input
                type="text"
                value={seriesFrom}
                onChange={(e) => setSeriesFrom(e.target.value)}
                placeholder="From"
                className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 font-mono w-44"
              />
              <span>—</span>
              <input
                type="text"
                value={seriesTo}
                onChange={(e) => setSeriesTo(e.target.value)}
                placeholder="To"
                className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 font-mono w-44"
              />
            </div>

            <div className="flex bg-slate-950 p-0.5 rounded border border-slate-800 text-xs font-medium">
              <button
                onClick={() => setSeriesType('price')}
                className={`px-3 py-1 rounded transition-colors ${
                  seriesType === 'price' ? 'bg-cyan-500/20 text-cyan-400 font-semibold' : 'text-slate-400'
                }`}
              >
                {t.series_price}
              </button>
              <button
                onClick={() => setSeriesType('load')}
                className={`px-3 py-1 rounded transition-colors ${
                  seriesType === 'load' ? 'bg-amber-500/20 text-amber-400 font-semibold' : 'text-slate-400'
                }`}
              >
                {t.series_load}
              </button>
              <button
                onClick={() => setSeriesType('pv')}
                className={`px-3 py-1 rounded transition-colors ${
                  seriesType === 'pv' ? 'bg-emerald-500/20 text-emerald-400 font-semibold' : 'text-slate-400'
                }`}
              >
                {t.series_pv}
              </button>
            </div>
          </div>
        </div>

        <div ref={timeSeriesChartRef} className="w-full h-72" />
      </div>

      {/* Heatmap Card */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Grid className="w-4 h-4 text-purple-400" />
            <div>
              <h2 className="text-sm font-semibold text-slate-200">{t.heatmap_title}</h2>
              <p className="text-xs text-slate-400 mt-0.5">{t.heatmap_subtitle}</p>
            </div>
          </div>

          <div className="flex bg-slate-950 p-0.5 rounded border border-slate-800 text-xs font-medium">
            <button
              onClick={() => setHeatmapType('price')}
              className={`px-3 py-1 rounded transition-colors ${
                heatmapType === 'price' ? 'bg-cyan-500/20 text-cyan-400 font-semibold' : 'text-slate-400'
              }`}
            >
              {t.heatmap_price}
            </button>
            <button
              onClick={() => setHeatmapType('load')}
              className={`px-3 py-1 rounded transition-colors ${
                heatmapType === 'load' ? 'bg-amber-500/20 text-amber-400 font-semibold' : 'text-slate-400'
              }`}
            >
              {t.heatmap_load}
            </button>
          </div>
        </div>

        <div ref={heatmapChartRef} className="w-full h-80" />
      </div>
    </div>
  );
};
