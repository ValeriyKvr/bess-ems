import { AlertOctagon, AlertTriangle, Info, BellRing } from 'lucide-react';
import { useTelemetryStore } from '../../stores/telemetryStore';
import { WsEventPayload } from '../../types';

export function EventFeed() {
  const { events } = useTelemetryStore();

  return (
    <div className="w-full h-full p-4 rounded-2xl bg-slate-900/90 border border-slate-800 shadow-xl flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b border-slate-800 mb-3">
        <div className="flex items-center gap-2">
          <BellRing className="w-4 h-4 text-blue-400" />
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200">
            Стрічка подій ({events.length})
          </h3>
        </div>
        <span className="text-[10px] text-slate-500 font-mono">Останні 50</span>
      </div>

      {/* Events List */}
      <div className="flex-1 overflow-y-auto space-y-2 pr-1 max-h-[360px] scrollbar-thin scrollbar-thumb-slate-700">
        {events.length === 0 ? (
          <div className="h-40 flex flex-col items-center justify-center text-slate-500 text-xs gap-1">
            <Info className="w-5 h-5 text-slate-600" />
            <span>Немає нових подій у системі</span>
          </div>
        ) : (
          events.map((ev: WsEventPayload, idx: number) => {
            const isAlarm = ev.severity === 'ALARM' || ev.event.includes('FAULT') || ev.event.includes('SAFE_MODE');
            const isWarning = ev.severity === 'WARNING';

            let timeStr = '';
            try {
              const d = new Date(ev.ts);
              if (!isNaN(d.getTime())) {
                timeStr = d.toLocaleTimeString('uk-UA', {
                  timeZone: 'UTC',
                  hour: '2-digit',
                  minute: '2-digit',
                  second: '2-digit',
                });
              }
            } catch {
              timeStr = ev.ts;
            }

            return (
              <div
                key={`${ev.ts}-${idx}`}
                className={`p-2.5 rounded-xl border text-xs transition-all flex items-start gap-2.5 ${
                  isAlarm
                    ? 'bg-red-950/40 border-red-800/60 text-red-200'
                    : isWarning
                    ? 'bg-amber-950/40 border-amber-800/60 text-amber-200'
                    : 'bg-slate-950/60 border-slate-800 text-slate-300'
                }`}
              >
                <div className="mt-0.5 flex-shrink-0">
                  {isAlarm ? (
                    <AlertOctagon className="w-4 h-4 text-rose-400" />
                  ) : isWarning ? (
                    <AlertTriangle className="w-4 h-4 text-amber-400" />
                  ) : (
                    <Info className="w-4 h-4 text-sky-400" />
                  )}
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-bold tracking-tight text-[11px] truncate">
                      {ev.event}
                    </span>
                    <span className="text-[10px] text-slate-400 font-mono flex-shrink-0">
                      {timeStr}
                    </span>
                  </div>
                  {ev.reason && (
                    <p className="text-[11px] text-slate-300/80 mt-0.5 break-words">
                      {ev.reason}
                    </p>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
