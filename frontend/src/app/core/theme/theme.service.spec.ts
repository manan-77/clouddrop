import { TestBed } from '@angular/core/testing';

import { ThemeService } from './theme.service';

const attr = () => document.documentElement.getAttribute('data-theme');
// Node 25 adds its own global localStorage that shadows the browser one in tests and does not work
// without a file path, so the tests install a small in-memory Storage on the window instead.
class MemoryStorage implements Storage {
  private readonly items = new Map<string, string>();
  get length(): number {
    return this.items.size;
  }
  clear(): void {
    this.items.clear();
  }
  getItem(key: string): string | null {
    return this.items.get(key) ?? null;
  }
  key(index: number): string | null {
    return [...this.items.keys()][index] ?? null;
  }
  removeItem(key: string): void {
    this.items.delete(key);
  }
  setItem(key: string, value: string): void {
    this.items.set(key, String(value));
  }
}

let memory = new MemoryStorage();
const storage = (): Storage => memory;

describe('ThemeService', () => {
  afterEach(() => vi.unstubAllGlobals());

  beforeEach(() => {
    memory = new MemoryStorage();
    vi.stubGlobal('localStorage', memory);
    if (document.defaultView) {
      Object.defineProperty(document.defaultView, 'localStorage', {
        value: memory,
        configurable: true,
      });
    }
    document.documentElement.removeAttribute('data-theme');
  });

  it('constructor_nothingStored_defaultsToSystemAndLeavesAttributeUnset', () => {
    const service = TestBed.inject(ThemeService);
    TestBed.tick();
    expect(service.preference()).toBe('system');
    expect(attr()).toBeNull();
  });

  it('setPreference_dark_writesAttributeAndRemembersChoice', () => {
    const service = TestBed.inject(ThemeService);
    service.setPreference('dark');
    TestBed.tick();
    expect(attr()).toBe('dark');
    expect(storage().getItem('cd-theme')).toBe('dark');
  });

  it('cycle_fromSystem_goesLightThenDarkThenSystem', () => {
    const service = TestBed.inject(ThemeService);
    const seen: string[] = [];
    for (let i = 0; i < 3; i++) {
      service.cycle();
      seen.push(service.preference());
    }
    expect(seen).toEqual(['light', 'dark', 'system']);
    TestBed.tick();
    expect(attr()).toBeNull();
  });

  it('constructor_storedValue_isRestored', () => {
    storage().setItem('cd-theme', 'light');
    const service = TestBed.inject(ThemeService);
    TestBed.tick();
    expect(service.preference()).toBe('light');
    expect(attr()).toBe('light');
  });

  it('constructor_corruptStoredValue_fallsBackToSystem', () => {
    storage().setItem('cd-theme', 'neon');
    expect(TestBed.inject(ThemeService).preference()).toBe('system');
  });

  it('storageThrows_constructorAndSetPreference_stillWork', () => {
    vi.stubGlobal('localStorage', undefined);
    const blocked = {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      },
    };
    if (document.defaultView) {
      Object.defineProperty(document.defaultView, 'localStorage', {
        value: blocked,
        configurable: true,
      });
    }
    const service = TestBed.inject(ThemeService);
    expect(service.preference()).toBe('system');
    expect(() => service.setPreference('dark')).not.toThrow();
    expect(service.preference()).toBe('dark');
  });
});
