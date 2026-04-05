import { describe, expect, it } from 'vitest';
import { getThemeToggleLabel, toggleTheme, type ThemeMode } from './theme';

describe('toggleTheme', () => {
  it('switches dark mode to light mode', () => {
    expect(toggleTheme('dark')).toBe('light');
  });

  it('switches light mode to dark mode', () => {
    expect(toggleTheme('light')).toBe('dark');
  });
});

describe('getThemeToggleLabel', () => {
  it('describes the next theme action from dark mode', () => {
    expect(getThemeToggleLabel('dark')).toBe('浅色模式');
  });

  it('describes the next theme action from light mode', () => {
    expect(getThemeToggleLabel('light')).toBe('深色模式');
  });
});
