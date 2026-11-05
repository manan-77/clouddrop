import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { ThemeService } from '@core/theme/theme.service';
import { AppShellComponent } from './app-shell.component';

describe('AppShellComponent', () => {
  it('themeButton_click_cyclesThemeAndUpdatesVisibleLabel', async () => {
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
    const fixture = TestBed.createComponent(AppShellComponent);
    await fixture.whenStable();
    const button = (fixture.nativeElement as HTMLElement).querySelector(
      'button',
    ) as HTMLButtonElement;
    expect(button.textContent).toContain('Theme: System');
    button.click();
    await fixture.whenStable();
    expect(TestBed.inject(ThemeService).preference()).toBe('light');
    expect(button.textContent).toContain('Theme: Light');
  });
});
