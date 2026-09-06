import { useEffect, useRef } from 'react';

export interface FlowStreamProps {
  id: string;
  pathD: string;
  powerKw: number; // >0 forward, <0 reverse, 0 inactive
  colorType?: 'grid' | 'bess' | 'pv' | 'site';
  isExpensiveHour?: boolean;
}

export function FlowStream({
  id,
  pathD,
  powerKw,
  colorType = 'grid',
  isExpensiveHour = false,
}: FlowStreamProps) {
  const pathRef = useRef<SVGPathElement | null>(null);
  const particleGroupRef = useRef<SVGGElement | null>(null);
  const currentSpeedRef = useRef<number>(0);
  const animOffsetRef = useRef<number>(0);
  const animFrameIdRef = useRef<number | null>(null);

  const absPower = Math.abs(powerKw);
  const isZero = absPower < 1.0;

  // Stroke width proportional to sqrt(|power|)
  const strokeWidth = isZero ? 2 : Math.min(7, Math.max(2.5, Math.sqrt(absPower) * 0.22));

  // Determine line & particle color based on SPEC §10.1
  let strokeColor = '#475569'; // Slate 600 default (zero)
  let particleColor = '#94a3b8';

  if (!isZero) {
    if (colorType === 'pv') {
      strokeColor = '#10b981'; // Emerald (PV)
      particleColor = '#34d399';
    } else if (colorType === 'bess') {
      if (powerKw < 0) {
        // BESS discharge
        strokeColor = '#10b981'; // Green
        particleColor = '#34d399';
      } else {
        // BESS charge
        strokeColor = '#f97316'; // Orange
        particleColor = '#fb923c';
      }
    } else if (colorType === 'grid') {
      if (isExpensiveHour) {
        strokeColor = '#f43f5e'; // Red / Rose for expensive hour
        particleColor = '#fb7185';
      } else if (powerKw < 0) {
        // Export to grid
        strokeColor = '#06b6d4'; // Cyan
        particleColor = '#22d3ee';
      } else {
        // Standard import
        strokeColor = '#38bdf8'; // Sky blue
        particleColor = '#7dd3fc';
      }
    } else {
      // Site
      strokeColor = '#818cf8'; // Indigo
      particleColor = '#a5b4fc';
    }
  }

  // Target speed in pixels per second: sign determines direction
  // Smooth LERP avoids instant flip
  const targetSpeed = isZero ? 0 : (powerKw > 0 ? 1 : -1) * (30 + Math.min(180, Math.log10(absPower + 1) * 60));

  useEffect(() => {
    let lastTime = performance.now();
    const particleCount = 4;

    const animate = (now: number) => {
      const dt = Math.min(0.1, (now - lastTime) / 1000);
      lastTime = now;

      // Smoothly interpolate current speed towards target speed (LERP)
      currentSpeedRef.current += (targetSpeed - currentSpeedRef.current) * Math.min(1, dt * 5);

      if (pathRef.current && particleGroupRef.current) {
        const totalLength = pathRef.current.getTotalLength();
        if (totalLength > 0) {
          animOffsetRef.current = (animOffsetRef.current + currentSpeedRef.current * dt) % totalLength;
          if (animOffsetRef.current < 0) {
            animOffsetRef.current += totalLength;
          }

          const particles = particleGroupRef.current.children;
          const spacing = totalLength / particleCount;

          for (let i = 0; i < particles.length; i++) {
            const circle = particles[i] as SVGCircleElement;
            if (isZero || Math.abs(currentSpeedRef.current) < 0.1) {
              circle.style.opacity = '0';
            } else {
              circle.style.opacity = '1';
              const dist = (animOffsetRef.current + i * spacing) % totalLength;
              const point = pathRef.current.getPointAtLength(dist);
              circle.setAttribute('cx', point.x.toString());
              circle.setAttribute('cy', point.y.toString());
            }
          }
        }
      }

      animFrameIdRef.current = requestAnimationFrame(animate);
    };

    animFrameIdRef.current = requestAnimationFrame(animate);
    return () => {
      if (animFrameIdRef.current) {
        cancelAnimationFrame(animFrameIdRef.current);
      }
    };
  }, [targetSpeed, isZero]);

  return (
    <g id={`flow-stream-${id}`}>
      {/* Background shadow/glow for active high-power lines */}
      {!isZero && (
        <path
          d={pathD}
          fill="none"
          stroke={strokeColor}
          strokeWidth={strokeWidth + 4}
          strokeOpacity={0.2}
          strokeLinecap="round"
        />
      )}

      {/* Main Flow Path */}
      <path
        ref={pathRef}
        d={pathD}
        fill="none"
        stroke={strokeColor}
        strokeWidth={strokeWidth}
        strokeDasharray={isZero ? '5,5' : 'none'}
        strokeOpacity={isZero ? 0.4 : 0.85}
        strokeLinecap="round"
      />

      {/* Animated Particles */}
      <g ref={particleGroupRef}>
        {[0, 1, 2, 3].map((idx) => (
          <circle
            key={idx}
            r={Math.max(2.5, strokeWidth * 0.7)}
            fill={particleColor}
            filter="drop-shadow(0 0 3px rgba(255,255,255,0.7))"
            style={{ opacity: 0, transition: 'opacity 0.2s' }}
          />
        ))}
      </g>
    </g>
  );
}
