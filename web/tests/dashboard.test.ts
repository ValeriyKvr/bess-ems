import { describe, it, expect } from 'vitest';
import t from '../src/i18n/uk.json';
import { useTelemetryStore } from '../src/stores/telemetryStore';

describe('Dashboard i18n Dictionary', () => {
  it('contains complete Ukrainian translations for all Dashboard components', () => {
    expect(t.app.title).toBe('BESS ↔ EMS Симулятор');
    expect(t.app.stage).toContain('Етап');
    expect(t.clock.price_dam).toBe('Ціна РДН');
    expect(t.clock.level_peak).toBe('ПІК');
    expect(t.flow.bess).toBe('BESS Накопичувач');
    expect(t.battery.soc).toContain('SoC');
    expect(t.ems.safe_mode).toBe('БЕЗПЕЧНИЙ РЕЖИМ');
    expect(t.finance.net_today).toBe('Економічний ефект сьогодні');
    expect(t.charts.dam_price_title).toContain('Ціна РДН');
    expect(t.ml.title).toContain('Машинне навчання');
    expect(t.ml.models_title).toBe('Реєстр навчених моделей');
  });
});


describe('Telemetry Store', () => {
  it('initializes with default disconnected state and empty buffers', () => {
    const state = useTelemetryStore.getState();
    expect(state.connected).toBe(false);
    expect(state.currentTick).toBeNull();
    expect(state.history).toEqual([]);
    expect(state.events).toEqual([]);
    expect(state.activeSchedule).toBeNull();
    expect(typeof state.connectWebSocket).toBe('function');
    expect(typeof state.setSpeed).toBe('function');
    expect(typeof state.pauseSim).toBe('function');
  });
});
