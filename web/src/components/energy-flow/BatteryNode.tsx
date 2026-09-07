import { useEffect, useRef, useState } from 'react';
import { Zap, Thermometer, ShieldAlert, HeartPulse, RotateCcw } from 'lucide-react';
import { sendBessCommand } from '../../api/client';

export interface BatteryNodeProps {
  socPct: number;
  sohPct: number;
  powerKw: number;
  tempC: number;
  state: string;
}

export function BatteryNode({
  socPct = 50,
  sohPct = 100,
  powerKw = 0,
  tempC = 25,
  state = 'STANDBY',
}: BatteryNodeProps) {
  const waveCanvasRef = useRef<SVGSVGElement | null>(null);
  const wavePathRef = useRef<SVGPathElement | null>(null);
  const phaseRef = useRef<number>(0);
  const animFrameRef = useRef<number | null>(null);
  const [isResetting, setIsResetting] = useState(false);

  const isCharging = powerKw > 1.0;
  const isDischarging = powerKw < -1.0;
  const isFault = state === 'FAULT' || tempC > 50 || socPct < 5 || socPct > 95;
  const isWarning = !isFault && (socPct < 20 || socPct > 85 || tempC > 40);

  // Dynamic colors based on battery status and SoC
  let liquidGradientFrom = '#059669';
  let liquidGradientTo = '#10b981';
  let glowColor = 'rgba(16, 185, 129, 0.3)';

  if (isFault) {
    liquidGradientFrom = '#b91c1c';
    liquidGradientTo = '#ef4444';
    glowColor = 'rgba(239, 68, 68, 0.4)';
  } else if (isWarning) {
    liquidGradientFrom = '#d97706';
    liquidGradientTo = '#f59e0b';
    glowColor = 'rgba(245, 158, 11, 0.3)';
  } else if (isDischarging) {
    liquidGradientFrom = '#0d9488'; // Teal
    liquidGradientTo = '#14b8a6';
    glowColor = 'rgba(20, 184, 166, 0.35)';
  }

  // Liquid tank dimensions
  const tankWidth = 140;
  const tankHeight = 110;
  const clampedSoc = Math.min(100, Math.max(0, socPct));
  // Y coordinate of liquid surface (0% = bottom, 100% = top)
  const surfaceY = tankHeight - (clampedSoc / 100) * tankHeight;

  useEffect(() => {
    let lastTime = performance.now();
    const waveAmplitude = isCharging || isDischarging ? 4.5 : 1.5;
    const waveFrequency = 0.05;
    const waveSpeed = isCharging || isDischarging ? 3.0 : 1.0;

    const renderWave = (time: number) => {
      const dt = (time - lastTime) / 1000;
      lastTime = time;
      phaseRef.current += dt * waveSpeed;

      if (wavePathRef.current) {
        let path = `M 0 ${tankHeight} L 0 ${surfaceY}`;
        const step = 4;
        for (let x = 0; x <= tankWidth; x += step) {
          const y =
            surfaceY +
            Math.sin(x * waveFrequency + phaseRef.current) * waveAmplitude +
            Math.cos(x * waveFrequency * 1.5 - phaseRef.current * 0.8) * (waveAmplitude * 0.4);
          path += ` L ${x} ${Math.min(tankHeight, Math.max(0, y))}`;
        }
        path += ` L ${tankWidth} ${tankHeight} Z`;
        wavePathRef.current.setAttribute('d', path);
      }

      animFrameRef.current = requestAnimationFrame(renderWave);
    };

    animFrameRef.current = requestAnimationFrame(renderWave);
    return () => {
      if (animFrameRef.current) {
        cancelAnimationFrame(animFrameRef.current);
      }
    };
  }, [surfaceY, isCharging, isDischarging]);

  return (
    <div
      className={`relative w-64 p-4 rounded-2xl bg-slate-900/90 border transition-all duration-300 shadow-xl flex flex-col items-center ${
        isFault
          ? 'border-red-500/60 shadow-red-500/20'
          : isCharging
          ? 'border-emerald-500/50 shadow-emerald-500/20'
          : isDischarging
          ? 'border-teal-500/50 shadow-teal-500/20'
          : 'border-slate-700/60 shadow-black/40'
      }`}
      style={{
        boxShadow: isCharging || isDischarging || isFault ? `0 0 20px ${glowColor}` : undefined,
      }}
    >
      {/* Top Terminal Cap of the Battery */}
      <div className="absolute -top-2 left-1/2 -translate-x-1/2 w-16 h-2 bg-slate-700 rounded-t-md border border-slate-600 border-b-0" />

      {/* Header Info */}
      <div className="w-full flex items-center justify-between text-xs mb-2">
        <div className="flex items-center gap-1.5 font-bold tracking-wider text-slate-200">
          <Zap
            className={`w-4 h-4 ${
              isCharging
                ? 'text-emerald-400 animate-bounce'
                : isDischarging
                ? 'text-teal-400 animate-pulse'
                : 'text-slate-400'
            }`}
          />
          <span>BESS 2 МВт·год</span>
        </div>
        <span
          className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider ${
            isFault
              ? 'bg-red-950 text-red-300 border border-red-800'
              : isCharging
              ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
              : isDischarging
              ? 'bg-teal-950 text-teal-300 border border-teal-800'
              : 'bg-slate-800 text-slate-300 border border-slate-700'
          }`}
        >
          {state}
        </span>
      </div>

      {/* Battery Tank (Liquid Container) */}
      <div className="relative w-44 h-28 rounded-xl overflow-hidden bg-slate-950/80 border border-slate-700/80 p-1 flex items-center justify-center shadow-inner">
        {/* SVG Liquid Fill */}
        <svg
          ref={waveCanvasRef}
          viewBox={`0 0 ${tankWidth} ${tankHeight}`}
          className="absolute inset-0 w-full h-full pointer-events-none"
          preserveAspectRatio="none"
        >
          <defs>
            <linearGradient id="batteryLiquidGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={liquidGradientTo} stopOpacity="0.85" />
              <stop offset="100%" stopColor={liquidGradientFrom} stopOpacity="0.95" />
            </linearGradient>
          </defs>
          <path ref={wavePathRef} fill="url(#batteryLiquidGradient)" />
        </svg>

        {/* Center SoC Big Badge */}
        <div className="relative z-10 flex flex-col items-center justify-center text-center">
          <span className="text-3xl font-black tracking-tight text-white drop-shadow-[0_2px_4px_rgba(0,0,0,0.8)]">
            {socPct.toFixed(1)}%
          </span>
          <span className="text-[11px] font-semibold text-slate-100/90 drop-shadow">
            {powerKw > 0 ? `+${powerKw.toFixed(0)} кВт` : `${powerKw.toFixed(0)} кВт`}
          </span>
        </div>

        {/* Subtle Horizontal grid lines inside tank */}
        <div className="absolute inset-0 flex flex-col justify-between pointer-events-none opacity-20 py-2">
          <div className="border-b border-dashed border-white w-full" />
          <div className="border-b border-dashed border-white w-full" />
          <div className="border-b border-dashed border-white w-full" />
        </div>
      </div>

      {/* Diagnostics / Telemetry Pills */}
      <div className="w-full grid grid-cols-2 gap-2 mt-3 text-xs">
        <div className="p-2 rounded-lg bg-slate-950/60 border border-slate-800/80 flex items-center gap-2">
          <Thermometer className="w-3.5 h-3.5 text-amber-400 flex-shrink-0" />
          <div className="flex flex-col leading-tight">
            <span className="text-[10px] text-slate-400">Темп.</span>
            <span className="font-semibold text-slate-200">{tempC.toFixed(1)} °C</span>
          </div>
        </div>

        <div className="p-2 rounded-lg bg-slate-950/60 border border-slate-800/80 flex items-center gap-2">
          <HeartPulse className="w-3.5 h-3.5 text-pink-400 flex-shrink-0" />
          <div className="flex flex-col leading-tight">
            <span className="text-[10px] text-slate-400">Здоров'я</span>
            <span className="font-semibold text-slate-200">{sohPct.toFixed(1)}%</span>
          </div>
        </div>
      </div>

      {isFault && (
        <div className="w-full mt-2 flex flex-col gap-1.5">
          <div className="py-1 px-2 rounded-md bg-red-900/40 border border-red-700/60 flex items-center gap-1.5 text-[11px] text-red-200">
            <ShieldAlert className="w-3.5 h-3.5 text-red-400 flex-shrink-0" />
            <span>Спрацював аварійний захист</span>
          </div>
          <button
            type="button"
            disabled={isResetting}
            onClick={async () => {
              try {
                setIsResetting(true);
                await sendBessCommand('reset_alarm');
              } catch (e) {
                console.error('Failed to reset alarm:', e);
              } finally {
                setIsResetting(false);
              }
            }}
            className="w-full flex items-center justify-center gap-1.5 py-1 px-2 rounded-md bg-red-800 hover:bg-red-700 active:bg-red-900 text-white text-[11px] font-semibold transition-colors shadow"
          >
            <RotateCcw className={`w-3 h-3 ${isResetting ? 'animate-spin' : ''}`} />
            <span>{isResetting ? 'Скидання...' : 'Скинути аварію'}</span>
          </button>
        </div>
      )}
    </div>
  );
}
