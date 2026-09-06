import { useEffect, useRef, useState } from 'react';
import { Coins, TrendingUp, ShieldCheck } from 'lucide-react';
import { useTelemetryStore } from '../../stores/telemetryStore';

export function MoneyCounter() {
  const { currentTick } = useTelemetryStore();

  const targetNet = currentTick?.finance?.today_net_uah ?? 0;
  const targetBaseline = currentTick?.finance?.today_baseline_uah ?? 0;

  const [displayedNet, setDisplayedNet] = useState<number>(targetNet);
  const [displayedBaseline, setDisplayedBaseline] = useState<number>(targetBaseline);

  const netRef = useRef<number>(targetNet);
  const baselineRef = useRef<number>(targetBaseline);

  // Smooth numeric counter animation with rAF
  useEffect(() => {
    let animId: number;
    let lastTime = performance.now();

    const updateCounter = (now: number) => {
      const dt = Math.min(0.1, (now - lastTime) / 1000);
      lastTime = now;

      // Exponential moving average towards target
      const netDiff = targetNet - netRef.current;
      const baseDiff = targetBaseline - baselineRef.current;

      if (Math.abs(netDiff) > 0.5) {
        netRef.current += netDiff * Math.min(1, dt * 8);
        setDisplayedNet(Math.round(netRef.current));
      } else {
        netRef.current = targetNet;
        setDisplayedNet(targetNet);
      }

      if (Math.abs(baseDiff) > 0.5) {
        baselineRef.current += baseDiff * Math.min(1, dt * 8);
        setDisplayedBaseline(Math.round(baselineRef.current));
      } else {
        baselineRef.current = targetBaseline;
        setDisplayedBaseline(targetBaseline);
      }

      animId = requestAnimationFrame(updateCounter);
    };

    animId = requestAnimationFrame(updateCounter);
    return () => cancelAnimationFrame(animId);
  }, [targetNet, targetBaseline]);

  const isPositive = displayedNet >= 0;

  return (
    <div className="w-full p-4 rounded-2xl bg-gradient-to-br from-slate-900/95 via-slate-900/90 to-slate-950 border border-slate-800 shadow-xl flex items-center justify-between gap-4">
      {/* Net Benefit Counter */}
      <div className="flex items-center gap-3">
        <div
          className={`p-3 rounded-xl border ${
            isPositive
              ? 'bg-emerald-950/60 border-emerald-500/30 text-emerald-400'
              : 'bg-amber-950/60 border-amber-500/30 text-amber-400'
          }`}
        >
          <Coins className="w-6 h-6" />
        </div>
        <div>
          <div className="text-xs font-semibold text-slate-400 flex items-center gap-1.5">
            <span>Економічний ефект за добу</span>
            <span
              title={
                isPositive
                  ? 'Чиста економія підприємства з урахуванням зносу BESS'
                  : 'Нічний заряд формує тимчасові витрати на закупівлю енергії — чиста вигода фіксується після вечірнього пікового розряду (18:00–22:00)'
              }
              className={`px-1.5 py-0.5 rounded text-[10px] font-bold cursor-help ${
                isPositive
                  ? 'bg-emerald-950 text-emerald-300 border border-emerald-500/30'
                  : 'bg-amber-950 text-amber-300 border border-amber-500/30'
              }`}
            >
              {isPositive ? '+ВИГОДА' : 'ЗАРЯД / НАКОПИЧЕННЯ'}
            </span>
          </div>
          <div className="flex items-baseline gap-1.5 mt-0.5">
            <span
              className={`text-2xl lg:text-3xl font-black font-mono tracking-tight transition-colors ${
                isPositive ? 'text-emerald-400' : 'text-amber-400'
              }`}
            >
              {isPositive ? `+${displayedNet.toLocaleString('uk-UA')}` : displayedNet.toLocaleString('uk-UA')}
            </span>
            <span className="text-sm font-semibold text-slate-400">грн</span>
          </div>
        </div>
      </div>

      {/* Baseline comparison */}
      <div className="flex items-center gap-6 border-l border-slate-800/80 pl-4 text-xs">
        <div className="flex flex-col">
          <span className="text-slate-400 flex items-center gap-1">
            <ShieldCheck className="w-3.5 h-3.5 text-slate-400" />
            Базові витрати (без BESS):
          </span>
          <div className="flex items-baseline gap-1 mt-0.5">
            <span className="text-lg font-bold font-mono text-slate-300">
              {displayedBaseline.toLocaleString('uk-UA')}
            </span>
            <span className="text-xs text-slate-400">грн</span>
          </div>
        </div>

        <div className="hidden sm:flex flex-col">
          <span className="text-slate-400 flex items-center gap-1">
            <TrendingUp className="w-3.5 h-3.5 text-blue-400" />
            Зниження витрат:
          </span>
          <div className="flex items-baseline gap-1 mt-0.5">
            <span className="text-lg font-bold font-mono text-blue-300">
              {displayedBaseline > 0
                ? `${((displayedNet / displayedBaseline) * 100).toFixed(1)}%`
                : '0.0%'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
