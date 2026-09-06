import { describe, it, expect } from 'vitest';
import t from '../src/i18n/locales/ua.json';

describe('Web UI Basic Setup', () => {
  it('loads Ukrainian i18n dictionary correctly', () => {
    expect(t.app.title).toBe('BESS ↔ EMS Симулятор');
    expect(t.app.connected).toBe('Підключено');
  });
});
