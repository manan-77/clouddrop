import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { finalize } from 'rxjs';

import { AuthService } from '@core/auth/auth.service';
import { SessionStore } from '@core/auth/session.store';
import { ThemeService } from '@core/theme/theme.service';
import { ButtonComponent } from '@shared/ui/button/button.component';

@Component({
  selector: 'cd-app-shell',
  imports: [RouterLink, RouterLinkActive, ButtonComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="header">
      <a class="brand" routerLink="/">CloudDrop AI</a>
      <div class="actions">
        @if (session.user(); as user) {
          <span class="user">{{ user.display_name }}</span>
          <button
            cd-button
            variant="secondary"
            type="button"
            [busy]="signingOut()"
            (click)="signOut()"
          >
            {{ signingOut() ? 'Signing out…' : 'Sign out' }}
          </button>
        }
        <button cd-button variant="secondary" type="button" (click)="theme.cycle()">
          Theme: {{ theme.label() }}
        </button>
      </div>
    </header>
    <nav class="nav" aria-label="Primary">
      @if (session.isAuthenticated()) {
        <a
          routerLink="/"
          routerLinkActive="active"
          ariaCurrentWhenActive="page"
          [routerLinkActiveOptions]="{ exact: true }"
        >
          Files
        </a>
      } @else if (session.status() === 'anonymous') {
        <a routerLink="/login" routerLinkActive="active" ariaCurrentWhenActive="page">Sign in</a>
        <a routerLink="/register" routerLinkActive="active" ariaCurrentWhenActive="page">
          Create account
        </a>
      }
    </nav>
    <main id="main" class="main" tabindex="-1">
      <ng-content />
    </main>
  `,
  styleUrl: './app-shell.component.scss',
})
export class AppShellComponent {
  protected readonly theme = inject(ThemeService);
  protected readonly session = inject(SessionStore);
  protected readonly signingOut = signal(false);
  private readonly auth = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);

  protected signOut(): void {
    if (this.signingOut()) {
      return;
    }
    this.signingOut.set(true);
    this.auth
      .logout()
      .pipe(
        finalize(() => this.signingOut.set(false)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe();
  }
}
