import { Cpu, RefreshCw, AlertTriangle, ShieldCheck } from 'lucide-react';

export interface EmsNodeProps {
  setpointKw: number;
  reason: string;
  scheduleId?: string | null;
  state: string; // 'DISPATCHING' | 'SAFE_MODE' | 'NO_SCHEDULE'
  isOptimizing?: boolean;
}

export function EmsNode({
  setpointKw = 0,
  reason = 'Очікування графіка',
  scheduleId,
  state = 'DISPATCHING',
  isOptimizing = false,
}: EmsNodeProps) {
  const isSafeMode = state === 'SAFE_MODE';
  const isDispatching = state === 'DISPATCHING';

  return (
    <div
      className={`relative w-64 p-4 rounded-2xl bg-slate-900/90 border transition-all duration-300 shadow-xl flex flex-col justify-between ${
        isSafeMode
          ? 'border-amber-500/60 shadow-amber-500/20'
          : isDispatching
          ? 'border-indigo-500/50 shadow-indigo-500/20'
          : 'border-slate-800 shadow-black/40'
      }`}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-indigo-950 border border-indigo-700/60 text-indigo-400">
            <Cpu className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-xs font-bold text-slate-100 uppercase tracking-wider">
              EMS Мозок
            </h3>
            <span className="text-[10px] text-slate-400 font-mono">
              {scheduleId ? `ID: ${scheduleId.slice(0, 8)}` : 'TOU_SIMPLE'}
            </span>
          </div>
        </div>

        {/* State Badge */}
        <span
          className={`px-2 py-0.5 rounded-full text-[10px] font-semibold tracking-wider flex items-center gap-1 ${
            isSafeMode
              ? 'bg-amber-950 text-amber-300 border border-amber-800 animate-pulse'
              : isDispatching
              ? 'bg-indigo-950 text-indigo-300 border border-indigo-800'
              : 'bg-slate-800 text-slate-400 border border-slate-700'
          }`}
        >
          {isSafeMode ? (
            <>
              <AlertTriangle className="w-3 h-3" />
              SAFE_MODE
            </>
          ) : (
            <>
              <ShieldCheck className="w-3 h-3 text-indigo-400" />
              {state}
            </>
          )}
        </span>
      </div>

      {/* Target Setpoint Display */}
      <div className="my-2 p-2.5 rounded-xl bg-slate-950/70 border border-slate-800 flex items-center justify-between">
        <span className="text-xs text-slate-400">Завдання:</span>
        <div className="flex items-baseline gap-1">
          <span
            className={`text-lg font-bold font-mono ${
              setpointKw > 0
                ? 'text-orange-400'
                : setpointKw < 0
                ? 'text-emerald-400'
                : 'text-slate-400'
            }`}
          >
            {setpointKw > 0 ? `+${setpointKw.toFixed(0)}` : setpointKw.toFixed(0)}
          </span>
          <span className="text-xs text-slate-500 font-semibold">кВт</span>
        </div>
      </div>

      {/* Decision Reason */}
      <div className="text-[11px] text-slate-300/90 leading-tight line-clamp-2 bg-slate-950/40 p-2 rounded-lg border border-slate-900 min-h-[36px] flex items-center">
        <span className="italic">{reason || 'Диспетчеризація за активним графіком'}</span>
      </div>

      {/* Optimizing Indicator */}
      {isOptimizing && (
        <div className="mt-2 flex items-center justify-center gap-1.5 py-1 px-2 rounded-md bg-blue-950/60 border border-blue-700/50 text-[11px] text-blue-300">
          <RefreshCw className="w-3 h-3 animate-spin text-blue-400" />
          <span>Оптимізація графіку...</span>
        </div>
      )}
    </div>
  );
}
