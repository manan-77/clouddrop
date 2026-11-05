import { HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';

import { provideAuthTesting, USER } from '@core/auth/auth-testing';
import { SessionStore } from '@core/auth/session.store';
import { ThemeService } from '@core/theme/theme.service';
import { AppShellComponent } from './app-shell.component';

describe('AppShellComponent', () => {
  const setup = async (signedIn = false) => {
    TestBed.configureTestingModule({ providers: provideAuthTesting() });
    if (signedIn) {
      const session = TestBed.inject(SessionStore);
      session.setAccessToken('t');
      session.establish(USER);
    }
    vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    const fixture = TestBed.createComponent(AppShellComponent);
    await fixture.whenStable();
    return { fixture, root: fixture.nativeElement as HTMLElement };
  };
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('themeButton_click_cyclesThemeAndUpdatesVisibleLabel', async () => {
    const { fixture, root } = await setup();
    const button = root.querySelector('.actions button:last-child') as HTMLButtonElement;
    expect(button.textContent).toContain('Theme: System');
    button.click();
    await fixture.whenStable();
    expect(TestBed.inject(ThemeService).preference()).toBe('light');
    expect(button.textContent).toContain('Theme: Light');
  });

  it('anonymous_showsSignInLinksAndNoSignOut', async () => {
    const { root } = await setup();
    const links = [...root.querySelectorAll('nav a')].map((a) => a.textContent?.trim());
    expect(links).toEqual(['Sign in', 'Create account']);
    expect(root.textContent).not.toContain('Sign out');
  });

  it('signedIn_showsNameFilesLinkAndSignOutWhichClearsTheSession', async () => {
    const { fixture, root } = await setup(true);
    const session = TestBed.inject(SessionStore);
    expect(root.querySelector('.user')?.textContent).toBe('Ada');
    expect([...root.querySelectorAll('nav a')].map((a) => a.textContent?.trim())).toEqual([
      'Files',
    ]);

    const signOut = [...root.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Sign out'),
    ) as HTMLButtonElement;
    signOut.click();
    await fixture.whenStable();
    expect(signOut.disabled).toBe(true);
    TestBed.inject(HttpTestingController).expectOne('/api/v1/auth/logout').flush(null);
    await fixture.whenStable();
    expect(session.isAuthenticated()).toBe(false);
    expect(session.accessToken()).toBeNull();
  });
});
