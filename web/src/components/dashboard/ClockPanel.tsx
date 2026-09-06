import { Clock, Play, Pause, StepForward, TrendingUp, TrendingDown } from 'lucide-react';
import { useTelemetryStore } from '../../stores/telemetryStore';

export function ClockPanel() {
  const { currentTick, setSpeed, pauseSim, resumeSim, stepSim } = useTelemetryStore();

  const clock = currentTick?.clock;
  const isPaused = clock?.is_paused ?? false;
  const currentSpeed = clock?.speed ?? 60;
  const rawSimTime = clock?.ts_sim ?? '2026-03-01T00:00:00Z';

  // Format UTC date & time
  let formattedDate = '01.03.2026';
  let formattedTime = '00:00:00';
  try {
    const d = new Date(rawSimTime);
    if (!isNaN(d.getTime())) {
      formattedDate = d.toLocaleDateString('uk-UA', {
        timeZone: 'UTC',
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
      });
      formattedTime = d.toLocaleTimeString('uk-UA', {
        timeZone: 'UTC',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });
    }
  } catch {
    // fallback
  }

  // Market tariffs
  const market = currentTick?.market;
  const priceDam = market?.price_dam ?? 4500;
  const priceBuy = market?.price_buy ?? (priceDam + 1928.57);
  const priceSell = market?.price_sell ?? (priceDam * 0.9);

  // Price level badge
  let priceBadgeText = 'СЕРЕДНЬО';
  let priceBadgeClass = 'bg-amber-950 text-amber-300 border-amber-800';

  if (priceDam < 3000) {
    priceBadgeText = 'ДЕШЕВО';
    priceBadgeClass = 'bg-emerald-950 text-emerald-300 border-emerald-800';
  } else if (priceDam >= 6000) {
    priceBadgeText = 'ПІК';
    priceBadgeClass = 'bg-rose-950 text-rose-300 border-rose-800 animate-pulse';
  }

  const speedOptions = [1, 10, 60, 600, 3600];

  return (
    <div className="w-full p-4 rounded-2xl bg-slate-900/90 border border-slate-800/90 shadow-xl flex flex-col md:flex-row items-center justify-between gap-4">
      {/* 1. Time & Clock display */}
      <div className="flex items-center gap-3">
        <div className="p-3 bg-blue-600/10 text-blue-400 rounded-xl border border-blue-500/20">
          <Clock className="w-6 h-6 animate-spin-slow" />
        </div>
        <div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-slate-100 tracking-tight">
              {formattedTime}
            </span>
            <span className="text-xs font-semibold text-slate-400">UTC</span>
          </div>
          <div className="text-xs text-slate-400 font-medium">{formattedDate} (Сим-час)</div>
        </div>
      </div>

      {/* 2. Speed & Control Buttons */}
      <div className="flex items-center gap-1.5 p-1.5 rounded-xl bg-slate-950 border border-slate-800">
        {/* Play/Pause toggle */}
        <button
          onClick={() => (isPaused ? resumeSim() : pauseSim())}
          className={`p-2 rounded-lg text-xs font-semibold flex items-center gap-1 transition-all ${
            isPaused
              ? 'bg-amber-600 text-white hover:bg-amber-500 shadow-md shadow-amber-600/20'
              : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
          }`}
          title={isPaused ? 'Продовжити симуляцію' : 'Поставити на паузу'}
        >
          {isPaused ? <Play className="w-4 h-4 fill-current" /> : <Pause className="w-4 h-4 fill-current" />}
        </button>

        {/* Speed multiplier buttons */}
        {speedOptions.map((s) => {
          const isActive = !isPaused && currentSpeed === s;
          return (
            <button
              key={s}
              onClick={() => {
                if (isPaused) {
                  resumeSim(s);
                } else {
                  setSpeed(s);
                }
              }}
              className={`px-2.5 py-1.5 rounded-lg text-xs font-mono font-bold transition-all ${
                isActive
                  ? 'bg-blue-600 text-white shadow-md shadow-blue-600/30'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
              }`}
            >
              {s}x
            </button>
          );
        })}

        {/* Step Forward button */}
        <button
          onClick={() => stepSim(60)}
          className="p-2 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-800 transition-all ml-1"
          title="Крок вперед (+1 сим-хвилина)"
        >
          <StepForward className="w-4 h-4" />
        </button>
      </div>

      {/* 3. Live Price / Tariffs info */}
      <div className="flex items-center gap-4 border-t md:border-t-0 md:border-l border-slate-800 pt-3 md:pt-0 md:pl-4">
        {/* DAM Price */}
        <div className="flex flex-col">
          <div className="flex items-center gap-1.5 text-xs text-slate-400">
            <span>Ціна РДН</span>
            <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold border ${priceBadgeClass}`}>
              {priceBadgeText}
            </span>
          </div>
          <div className="flex items-baseline gap-1 mt-0.5">
            <span className="text-xl font-bold font-mono text-slate-100">
              {priceDam.toFixed(0)}
            </span>
            <span className="text-[10px] text-slate-400">грн/МВт·год</span>
          </div>
        </div>

        {/* Effective Buy & Sell */}
        <div className="hidden lg:flex flex-col text-xs text-slate-400 border-l border-slate-800/80 pl-3">
          <div className="flex items-center gap-1">
            <TrendingUp className="w-3 h-3 text-rose-400" />
            <span>Купівля:</span>
            <span className="font-mono font-semibold text-slate-200">{priceBuy.toFixed(0)}</span>
          </div>
          <div className="flex items-center gap-1 mt-0.5">
            <TrendingDown className="w-3 h-3 text-cyan-400" />
            <span>Продаж:</span>
            <span className="font-mono font-semibold text-slate-200">{priceSell.toFixed(0)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
