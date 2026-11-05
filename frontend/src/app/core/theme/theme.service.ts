import { DOCUMENT } from '@angular/common';
import { computed, effect, inject, Injectable, signal } from '@angular/core';

export type ThemePreference = 'system' | 'light' | 'dark';

const STORAGE_KEY = 'cd-theme';
const ORDER: readonly ThemePreference[] = ['system', 'light', 'dark'];
const LABELS: Readonly<Record<ThemePreference, string>> = {
  system: 'System',
  light: 'Light',
  dark: 'Dark',
};

/** The only code that writes the theme attribute on the root element. */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly document = inject(DOCUMENT);

  readonly preference = signal<ThemePreference>(this.readStored());
  readonly label = computed(() => LABELS[this.preference()]);

  constructor() {
    effect(() => this.apply(this.preference()));
  }

  setPreference(value: ThemePreference): void {
    this.preference.set(value);
    this.store(value);
  }

  cycle(): void {
    const next = ORDER[(ORDER.indexOf(this.preference()) + 1) % ORDER.length];
    this.setPreference(next);
  }

  private apply(value: ThemePreference): void {
    const root = this.document.documentElement;
    if (value === 'system') {
      root.removeAttribute('data-theme');
    } else {
      root.setAttribute('data-theme', value);
    }
  }

  // Storage can be blocked or throw (private windows, cleared site data); the app works without it.
  private readStored(): ThemePreference {
    try {
      const stored = this.document.defaultView?.localStorage.getItem(STORAGE_KEY);
      return ORDER.find((option) => option === stored) ?? 'system';
    } catch {
      return 'system';
    }
  }

  private store(value: ThemePreference): void {
    try {
      this.document.defaultView?.localStorage.setItem(STORAGE_KEY, value);
    } catch {
      // Preference simply is not remembered.
    }
  }
}
