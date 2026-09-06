import { Factory, Sun, UtilityPole } from 'lucide-react';
import { BatteryNode } from './BatteryNode';
import { EmsNode } from './EmsNode';
import { FlowStream } from './FlowStream';
import { WsTickPayload } from '../../types';

export interface EnergyFlowDiagramProps {
  tick: WsTickPayload | null;
}

export function EnergyFlowDiagram({ tick }: EnergyFlowDiagramProps) {
  // Extract values from tick with sensible fallbacks
  const loadKw = tick?.site?.load_kw ?? 0;
  const pvKw = tick?.site?.pv_kw ?? 0;
  const importKw = tick?.grid?.import_kw ?? 0;
  const exportKw = tick?.grid?.export_kw ?? 0;
  const bessPowerKw = tick?.bess?.power_kw ?? 0;
  const bessSoc = tick?.bess?.soc_pct ?? 50;
  const bessSoh = tick?.bess?.soh_pct ?? 100;
  const bessTemp = tick?.bess?.temp_c ?? 25;
  const bessState = tick?.bess?.state ?? 'STANDBY';

  const emsSetpoint = tick?.ems?.setpoint_kw ?? 0;
  const emsReason = tick?.ems?.reason ?? 'Очікування активного графіка';
  const emsScheduleId = tick?.ems?.schedule_id ?? null;
  const emsState = tick?.ems?.state ?? 'DISPATCHING';

  const isExpensive = tick?.market?.level === 'PEAK' || (tick?.market?.price_dam ?? 0) > 6000;

  // Grid net flow: positive = import, negative = export
  const gridNetKw = importKw > 0 ? importKw : -exportKw;

  // BESS to Site discharge flow
  const bessDischargeKw = bessPowerKw < -0.5 ? Math.abs(bessPowerKw) : 0;
  // Grid to BESS charge flow
  const bessChargeKw = bessPowerKw > 0.5 ? bessPowerKw : 0;

  return (
    <div className="relative w-full rounded-2xl bg-slate-950/80 border border-slate-800/80 p-6 overflow-hidden shadow-2xl backdrop-blur-md">
      {/* Background Subtle Grid Texture */}
      <div
        className="absolute inset-0 opacity-10 pointer-events-none"
        style={{
          backgroundImage:
            'radial-gradient(circle at 1px 1px, rgba(255, 255, 255, 0.25) 1px, transparent 0)',
          backgroundSize: '24px 24px',
        }}
      />

      {/* SVG Canvas for Connections & Particle Streams */}
      <svg
        className="absolute inset-0 w-full h-full pointer-events-none z-0"
        viewBox="0 0 940 460"
        preserveAspectRatio="xMidYMid meet"
      >
        <defs>
          <linearGradient id="gradientGrid" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#38bdf8" />
            <stop offset="100%" stopColor="#818cf8" />
          </linearGradient>
        </defs>

        {/* 1. Grid -> Site Stream (Direct supply) */}
        <FlowStream
          id="grid-to-site"
          pathD="M 230 110 C 290 110, 310 110, 340 110 C 370 110, 570 110, 600 110 C 630 110, 650 110, 710 110"
          powerKw={gridNetKw}
          colorType="grid"
          isExpensiveHour={isExpensive}
        />

        {/* 2. Grid -> BESS Stream (Charging from Grid) */}
        <FlowStream
          id="grid-to-bess"
          pathD="M 170 180 C 170 270, 240 330, 340 330"
          powerKw={bessChargeKw}
          colorType="bess"
        />

        {/* 3. BESS -> Site Stream (Discharging to Facility) */}
        <FlowStream
          id="bess-to-site"
          pathD="M 600 330 C 680 330, 760 270, 760 180"
          powerKw={bessDischargeKw}
          colorType="bess"
        />

        {/* 4. PV -> Site Stream (Solar Onsite generation) */}
        <FlowStream
          id="pv-to-site"
          pathD="M 810 290 L 810 180"
          powerKw={pvKw}
          colorType="pv"
        />
      </svg>

      {/* HTML Layout of Nodes */}
      <div className="relative z-10 grid grid-cols-12 gap-4 h-[410px]">
        {/* Node 1: Grid (Top-Left) */}
        <div className="col-span-3 flex flex-col justify-start">
          <div className="p-4 rounded-2xl bg-slate-900/95 border border-slate-700/60 shadow-lg flex flex-col gap-2">
            <div className="flex items-center justify-between text-xs">
              <span className="font-semibold text-slate-400">Мережа ОЕС</span>
              <UtilityPole className="w-4 h-4 text-sky-400" />
            </div>
            <div className="flex items-baseline gap-1.5">
              <span
                className={`text-2xl font-bold font-mono ${
                  importKw > 0
                    ? isExpensive
                      ? 'text-rose-400'
                      : 'text-sky-300'
                    : exportKw > 0
                    ? 'text-cyan-400'
                    : 'text-slate-400'
                }`}
              >
                {importKw > 0
                  ? `+${importKw.toFixed(0)}`
                  : exportKw > 0
                  ? `-${exportKw.toFixed(0)}`
                  : '0'}
              </span>
              <span className="text-xs text-slate-400 font-semibold">кВт</span>
            </div>
            <div className="flex items-center justify-between text-[11px] pt-1 border-t border-slate-800">
              <span className="text-slate-400">Режим:</span>
              <span
                className={`font-semibold ${
                  importKw > 0
                    ? isExpensive
                      ? 'text-rose-400'
                      : 'text-sky-400'
                    : exportKw > 0
                    ? 'text-cyan-400'
                    : 'text-slate-400'
                }`}
              >
                {importKw > 0 ? (isExpensive ? 'ПІКОВИЙ ІМПОРТ' : 'ІМПОРТ') : exportKw > 0 ? 'ЕКСПОРТ' : 'БАЛАНС'}
              </span>
            </div>
          </div>
        </div>

        {/* Node 2: EMS Brain (Top-Center) */}
        <div className="col-span-6 flex justify-center items-start">
          <EmsNode
            setpointKw={emsSetpoint}
            reason={emsReason}
            scheduleId={emsScheduleId}
            state={emsState}
          />
        </div>

        {/* Node 3: Site (Top-Right) */}
        <div className="col-span-3 flex flex-col justify-start items-end">
          <div className="w-full p-4 rounded-2xl bg-slate-900/95 border border-slate-700/60 shadow-lg flex flex-col gap-2">
            <div className="flex items-center justify-between text-xs">
              <span className="font-semibold text-slate-400">Підприємство</span>
              <Factory className="w-4 h-4 text-indigo-400" />
            </div>
            <div className="flex items-baseline gap-1.5">
              <span className="text-2xl font-bold font-mono text-indigo-300">
                {loadKw.toFixed(0)}
              </span>
              <span className="text-xs text-slate-400 font-semibold">кВт</span>
            </div>
            <div className="flex items-center justify-between text-[11px] pt-1 border-t border-slate-800">
              <span className="text-slate-400">Навантаження:</span>
              <span className="font-semibold text-slate-300">
                {loadKw > 600 ? 'Високе' : loadKw > 200 ? 'Номінальне' : 'Низьке'}
              </span>
            </div>
          </div>
        </div>

        {/* Bottom Row: BESS (Center-Bottom) and PV (Bottom-Right) */}
        <div className="col-span-3" />

        <div className="col-span-6 flex justify-center items-end">
          <BatteryNode
            socPct={bessSoc}
            sohPct={bessSoh}
            powerKw={bessPowerKw}
            tempC={bessTemp}
            state={bessState}
          />
        </div>

        <div className="col-span-3 flex flex-col justify-end items-end">
          <div className="w-full p-3.5 rounded-2xl bg-slate-900/95 border border-slate-700/60 shadow-lg flex flex-col gap-1.5">
            <div className="flex items-center justify-between text-xs">
              <span className="font-semibold text-slate-400">СЕС (PV 200 кВт)</span>
              <Sun className={`w-4 h-4 ${pvKw > 5 ? 'text-amber-400 animate-spin-slow' : 'text-slate-500'}`} />
            </div>
            <div className="flex items-baseline gap-1.5">
              <span className="text-xl font-bold font-mono text-emerald-400">
                {pvKw.toFixed(0)}
              </span>
              <span className="text-xs text-slate-400 font-semibold">кВт</span>
            </div>
            <div className="text-[10px] text-slate-400">
              {pvKw > 10 ? 'Власна сонячна генерація' : 'Ніч / відсутність сонця'}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
