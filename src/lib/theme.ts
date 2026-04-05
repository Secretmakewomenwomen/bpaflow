export type ThemeMode = 'dark' | 'light';

export function toggleTheme(theme: ThemeMode): ThemeMode {
  return theme === 'dark' ? 'light' : 'dark';
}

export function getThemeToggleLabel(theme: ThemeMode): string {
  return theme === 'dark' ? '浅色模式' : '深色模式';
}
