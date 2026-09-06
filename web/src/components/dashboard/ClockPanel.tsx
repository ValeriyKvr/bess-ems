import { Clock, Play, Pause, StepForward, TrendingUp, TrendingDown, Sun, Moon, Zap, Activity } from 'lucide-react';
import { useTelemetryStore } from '../../stores/telemetryStore';

export function ClockPanel() {
  const { currentTick, setSpeed, pauseSim, resumeSim, stepSim, seekTime } = useTelemetryStore();

  const clock = currentTick?.clock;
  const isPaused = clock?.is_paused ?? false;
  const currentSpeed = clock?.speed ?? 60;
  const rawSimTime = clock?.ts_sim ?? '2026-03-02T08:15:00Z';

  // Format UTC date & time
  let formattedDate = '02.03.2026';
  let formattedTime = '08:15:00';
  let currentMinutes = 8 * 60 + 15;

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
      currentMinutes = d.getUTCHours() * 60 + d.getUTCMinutes();
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

  if (priceDam < 3200) {
    priceBadgeText = 'ДЕШЕВО';
    priceBadgeClass = 'bg-emerald-950 text-emerald-300 border-emerald-800';
  } else if (priceDam >= 5500) {
    priceBadgeText = 'ПІК';
    priceBadgeClass = 'bg-rose-950 text-rose-300 border-rose-800 animate-pulse';
  }

  const speedOptions = [1, 10, 60, 600, 3600];

  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = parseInt(e.target.value, 10);
    const h = Math.floor(val / 60);
    const m = val % 60;
    seekTime(h, m);
  };

  const presets = [
    { label: '03:00 Заряд', icon: Moon, hour: 3, minute: 0, color: 'text-emerald-400 hover:border-emerald-500/50' },
    { label: '08:30 Ранковий пік', icon: Activity, hour: 8, minute: 30, color: 'text-amber-400 hover:border-amber-500/50' },
    { label: '13:00 Пік СЕС', icon: Sun, hour: 13, minute: 0, color: 'text-yellow-400 hover:border-yellow-500/50' },
    { label: '19:30 Вечірній розряд', icon: Zap, hour: 19, minute: 30, color: 'text-rose-400 hover:border-rose-500/50' },
  ];

  return (
    <div className="w-full p-4 rounded-2xl bg-slate-900/95 border border-slate-800/90 shadow-xl flex flex-col gap-3">
      {/* Top row: Clock display, Speed controls, Price tickers */}
      <div className="flex flex-col md:flex-row items-center justify-between gap-4">
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

      {/* Interactive 24-Hour Time Slider & Quick-Jumps */}
      <div className="pt-2 border-t border-slate-800/80 flex flex-col gap-2">
        <div className="flex items-center justify-between text-xs text-slate-400">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-300">Швидка навігація по добі:</span>
            <span className="font-mono text-blue-400 bg-blue-950/60 px-2 py-0.5 rounded border border-blue-800/60">
              {Math.floor(currentMinutes / 60).toString().padStart(2, '0')}:
              {(currentMinutes % 60).toString().padStart(2, '0')} UTC
            </span>
          </div>
          <div className="hidden sm:flex items-center gap-1.5">
            {presets.map((p) => {
              const Icon = p.icon;
              return (
                <button
                  key={p.label}
                  onClick={() => seekTime(p.hour, p.minute)}
                  className={`px-2 py-1 rounded-lg text-[11px] font-medium bg-slate-950/80 border border-slate-800 transition-all flex items-center gap-1 ${p.color}`}
                >
                  <Icon className="w-3 h-3" />
                  <span>{p.label}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Range Slider */}
        <div className="relative flex flex-col justify-center">
          <input
            type="range"
            min={0}
            max={1439}
            step={5}
            value={currentMinutes}
            onChange={handleSliderChange}
            className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-blue-500 focus:outline-none transition-all"
            style={{
              background: `linear-gradient(to right,
                #10b981 0%, #10b981 25%,
                #f59e0b 25%, #f59e0b 45%,
                #38bdf8 45%, #38bdf8 65%,
                #f43f5e 65%, #f43f5e 92%,
                #10b981 92%, #10b981 100%)`,
            }}
          />

          {/* Time tick labels */}
          <div className="flex justify-between text-[10px] text-slate-500 font-mono mt-1 px-1">
            <span>00:00 (Ніч)</span>
            <span>04:00</span>
            <span>08:00 (Ранок)</span>
            <span>12:00 (Сонце)</span>
            <span>16:00</span>
            <span>20:00 (Пік)</span>
            <span>23:59</span>
          </div>
        </div>
      </div>
    </div>
  );
}
