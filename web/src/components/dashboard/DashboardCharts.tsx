import { useEffect, useRef } from 'react';
import * as echarts from 'echarts';
import { useTelemetryStore } from '../../stores/telemetryStore';

export function DashboardCharts() {
  const { history, activeSchedule, currentTick } = useTelemetryStore();

  const priceChartRef = useRef<HTMLDivElement | null>(null);
  const powerChartRef = useRef<HTMLDivElement | null>(null);
  const socChartRef = useRef<HTMLDivElement | null>(null);
  const ganttChartRef = useRef<HTMLDivElement | null>(null);

  const priceInstance = useRef<echarts.ECharts | null>(null);
  const powerInstance = useRef<echarts.ECharts | null>(null);
  const socInstance = useRef<echarts.ECharts | null>(null);
  const ganttInstance = useRef<echarts.ECharts | null>(null);

  // Initialize ECharts instances
  useEffect(() => {
    if (priceChartRef.current && !priceInstance.current) {
      priceInstance.current = echarts.init(priceChartRef.current, 'dark');
    }
    if (powerChartRef.current && !powerInstance.current) {
      powerInstance.current = echarts.init(powerChartRef.current, 'dark');
    }
    if (socChartRef.current && !socInstance.current) {
      socInstance.current = echarts.init(socChartRef.current, 'dark');
    }
    if (ganttChartRef.current && !ganttInstance.current) {
      ganttInstance.current = echarts.init(ganttChartRef.current, 'dark');
    }

    const handleResize = () => {
      priceInstance.current?.resize();
      powerInstance.current?.resize();
      socInstance.current?.resize();
      ganttInstance.current?.resize();
    };

    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      priceInstance.current?.dispose();
      powerInstance.current?.dispose();
      socInstance.current?.dispose();
      ganttInstance.current?.dispose();
      priceInstance.current = null;
      powerInstance.current = null;
      socInstance.current = null;
      ganttInstance.current = null;
    };
  }, []);

  // Update Charts when history or activeSchedule changes
  useEffect(() => {
    // If no history yet, create placeholder data or use current tick
    const ticks = history.length > 0 ? history : currentTick ? [currentTick] : [];

    // Sample ticks if too many to keep rendering fast (max 120 points for display)
    const step = Math.max(1, Math.floor(ticks.length / 120));
    const sampledTicks = ticks.filter((_, i) => i % step === 0);

    const timeLabels = sampledTicks.map((t) => {
      try {
        const d = new Date(t.clock?.ts_sim || '');
        return d.toLocaleTimeString('uk-UA', { timeZone: 'UTC', hour: '2-digit', minute: '2-digit' });
      } catch {
        return '';
      }
    });

    // ──────────────────────────────── 1. Price Chart ────────────────────────────────
    if (priceInstance.current) {
      const priceData = sampledTicks.map((t) => t.market?.price_dam ?? 4500);
      priceInstance.current.setOption({
        backgroundColor: 'transparent',
        title: {
          text: 'Ціна РДН (грн/МВт·год)',
          left: 10,
          top: 10,
          textStyle: { fontSize: 13, color: '#e2e8f0', fontWeight: '600' },
        },
        tooltip: {
          trigger: 'axis',
          backgroundColor: '#0f172a',
          borderColor: '#334155',
          textStyle: { color: '#f8fafc', fontSize: 12 },
        },
        grid: { left: 55, right: 20, top: 45, bottom: 25 },
        xAxis: {
          type: 'category',
          data: timeLabels,
          axisLine: { lineStyle: { color: '#334155' } },
          axisLabel: { color: '#94a3b8', fontSize: 10 },
        },
        yAxis: {
          type: 'value',
          axisLine: { lineStyle: { color: '#334155' } },
          splitLine: { lineStyle: { color: '#1e293b' } },
          axisLabel: { color: '#94a3b8', fontSize: 10 },
        },
        series: [
          {
            name: 'Ціна РДН',
            type: 'line',
            smooth: true,
            showSymbol: false,
            data: priceData,
            lineStyle: { color: '#38bdf8', width: 2 },
            areaStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: 'rgba(56, 189, 248, 0.35)' },
                { offset: 1, color: 'rgba(56, 189, 248, 0.02)' },
              ]),
            },
            markLine: {
              silent: true,
              symbol: 'none',
              data: [
                { yAxis: 9000, lineStyle: { color: '#ef4444', type: 'dashed' }, label: { formatter: 'Cap Max' } },
                { yAxis: 3000, lineStyle: { color: '#10b981', type: 'dashed' }, label: { formatter: 'Ніч' } },
              ],
            },
          },
        ],
      });
    }

    // ──────────────────────────────── 2. Power Balance Chart ────────────────────────────────
    if (powerInstance.current) {
      const loadData = sampledTicks.map((t) => t.site?.load_kw ?? 0);
      const importData = sampledTicks.map((t) => t.grid?.import_kw ?? 0);
      const bessPowerData = sampledTicks.map((t) => t.bess?.power_kw ?? 0);

      powerInstance.current.setOption({
        backgroundColor: 'transparent',
        title: {
          text: 'Баланс потужності (кВт)',
          left: 10,
          top: 10,
          textStyle: { fontSize: 13, color: '#e2e8f0', fontWeight: '600' },
        },
        tooltip: {
          trigger: 'axis',
          backgroundColor: '#0f172a',
          borderColor: '#334155',
          textStyle: { color: '#f8fafc', fontSize: 12 },
        },
        legend: {
          data: ['Навантаження', 'Імпорт', 'BESS (+Заряд/-Розряд)'],
          right: 10,
          top: 10,
          textStyle: { color: '#94a3b8', fontSize: 11 },
        },
        grid: { left: 55, right: 20, top: 45, bottom: 25 },
        xAxis: {
          type: 'category',
          data: timeLabels,
          axisLine: { lineStyle: { color: '#334155' } },
          axisLabel: { color: '#94a3b8', fontSize: 10 },
        },
        yAxis: {
          type: 'value',
          axisLine: { lineStyle: { color: '#334155' } },
          splitLine: { lineStyle: { color: '#1e293b' } },
          axisLabel: { color: '#94a3b8', fontSize: 10 },
        },
        series: [
          {
            name: 'Навантаження',
            type: 'line',
            smooth: true,
            showSymbol: false,
            data: loadData,
            lineStyle: { color: '#818cf8', width: 2 },
          },
          {
            name: 'Імпорт',
            type: 'line',
            smooth: true,
            showSymbol: false,
            data: importData,
            lineStyle: { color: '#f43f5e', width: 2 },
            areaStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: 'rgba(244, 63, 94, 0.25)' },
                { offset: 1, color: 'rgba(244, 63, 94, 0.01)' },
              ]),
            },
          },
          {
            name: 'BESS (+Заряд/-Розряд)',
            type: 'bar',
            data: bessPowerData,
            itemStyle: {
              color: (params: { value: number }) => (params.value >= 0 ? '#fb923c' : '#34d399'),
            },
          },
        ],
      });
    }

    // ──────────────────────────────── 3. SoC Chart ────────────────────────────────
    if (socInstance.current) {
      const socActual = sampledTicks.map((t) => t.bess?.soc_pct ?? 50);

      socInstance.current.setOption({
        backgroundColor: 'transparent',
        title: {
          text: 'SoC акумулятора (%)',
          left: 10,
          top: 10,
          textStyle: { fontSize: 13, color: '#e2e8f0', fontWeight: '600' },
        },
        tooltip: {
          trigger: 'axis',
          backgroundColor: '#0f172a',
          borderColor: '#334155',
          textStyle: { color: '#f8fafc', fontSize: 12 },
        },
        grid: { left: 45, right: 20, top: 45, bottom: 25 },
        xAxis: {
          type: 'category',
          data: timeLabels,
          axisLine: { lineStyle: { color: '#334155' } },
          axisLabel: { color: '#94a3b8', fontSize: 10 },
        },
        yAxis: {
          type: 'value',
          min: 0,
          max: 100,
          axisLine: { lineStyle: { color: '#334155' } },
          splitLine: { lineStyle: { color: '#1e293b' } },
          axisLabel: { color: '#94a3b8', fontSize: 10 },
        },
        series: [
          {
            name: 'SoC факт',
            type: 'line',
            smooth: true,
            showSymbol: false,
            data: socActual,
            lineStyle: { color: '#10b981', width: 2.5 },
            areaStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: 'rgba(16, 185, 129, 0.3)' },
                { offset: 1, color: 'rgba(16, 185, 129, 0.02)' },
              ]),
            },
            markLine: {
              silent: true,
              symbol: 'none',
              data: [
                { yAxis: 90, lineStyle: { color: '#f59e0b', type: 'dashed' }, label: { formatter: 'SoC max (90%)' } },
                { yAxis: 10, lineStyle: { color: '#ef4444', type: 'dashed' }, label: { formatter: 'SoC min (10%)' } },
              ],
            },
          },
        ],
      });
    }

    // ──────────────────────────────── 4. Gantt Timeline ────────────────────────────────
    if (ganttInstance.current) {
      // Build 24-hour timeline from activeSchedule items if present
      const scheduleItems = activeSchedule?.items || [];
      const hours = Array.from({ length: 24 }, (_, i) => `${i.toString().padStart(2, '0')}:00`);
      const ganttValues = hours.map((_, h) => {
        const item = scheduleItems.find((it) => {
          try {
            return new Date(it.ts).getUTCHours() === h;
          } catch {
            return false;
          }
        });
        if (!item) return 0;
        if (item.setpoint_kw > 10) return 1; // Charge
        if (item.setpoint_kw < -10) return -1; // Discharge
        return 0; // Idle
      });

      // Highlight current simulation hour
      let currentHour = 0;
      try {
        if (currentTick?.clock?.ts_sim) {
          currentHour = new Date(currentTick.clock.ts_sim).getUTCHours();
        }
      } catch {
        // fallback
      }

      ganttInstance.current.setOption({
        backgroundColor: 'transparent',
        title: {
          text: `Таймлайн графіка диспетчеризації (${activeSchedule?.strategy ? 'TOU_SIMPLE' : 'Очікування'})`,
          left: 10,
          top: 8,
          textStyle: { fontSize: 13, color: '#e2e8f0', fontWeight: '600' },
        },
        tooltip: {
          trigger: 'item',
          formatter: (params: { dataIndex: number; value: number }) => {
            const h = params.dataIndex;
            const stateText = params.value === 1 ? 'Заряд (+500 кВт)' : params.value === -1 ? 'Розряд (-500 кВт)' : 'Очікування (0 кВт)';
            return `Година ${h}:00 — ${stateText}`;
          },
          backgroundColor: '#0f172a',
          borderColor: '#334155',
          textStyle: { color: '#f8fafc', fontSize: 12 },
        },
        grid: { left: 35, right: 20, top: 40, bottom: 25 },
        xAxis: {
          type: 'category',
          data: hours,
          axisLine: { lineStyle: { color: '#334155' } },
          axisLabel: { color: '#94a3b8', fontSize: 9, interval: 1 },
        },
        yAxis: {
          type: 'value',
          min: -1.2,
          max: 1.2,
          show: false,
        },
        series: [
          {
            name: 'Режим',
            type: 'bar',
            data: ganttValues,
            barWidth: '75%',
            itemStyle: {
              color: (params: { dataIndex: number; value: number }) => {
                const isNow = params.dataIndex === currentHour;
                if (params.value === 1) return isNow ? '#ea580c' : '#fb923c'; // Orange (Charge)
                if (params.value === -1) return isNow ? '#059669' : '#34d399'; // Green (Discharge)
                return isNow ? '#475569' : '#1e293b'; // Slate (Idle)
              },
              borderRadius: [4, 4, 4, 4],
            },
            markLine: {
              silent: true,
              symbol: 'none',
              data: [
                {
                  xAxis: currentHour,
                  lineStyle: { color: '#38bdf8', width: 2, type: 'solid' },
                  label: { formatter: 'Зараз', color: '#38bdf8' },
                },
              ],
            },
          },
        ],
      });
    }
  }, [history, activeSchedule, currentTick]);

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 w-full">
      {/* Chart 1: DAM Price */}
      <div className="p-3 rounded-2xl bg-slate-900/90 border border-slate-800 shadow-xl h-[260px] flex flex-col">
        <div ref={priceChartRef} className="w-full h-full" />
      </div>

      {/* Chart 2: Power Balance */}
      <div className="p-3 rounded-2xl bg-slate-900/90 border border-slate-800 shadow-xl h-[260px] flex flex-col">
        <div ref={powerChartRef} className="w-full h-full" />
      </div>

      {/* Chart 3: Battery SoC */}
      <div className="p-3 rounded-2xl bg-slate-900/90 border border-slate-800 shadow-xl h-[240px] flex flex-col">
        <div ref={socChartRef} className="w-full h-full" />
      </div>

      {/* Chart 4: Gantt Schedule Timeline */}
      <div className="p-3 rounded-2xl bg-slate-900/90 border border-slate-800 shadow-xl h-[240px] flex flex-col">
        <div ref={ganttChartRef} className="w-full h-full" />
      </div>
    </div>
  );
}
