import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';

import { ThemeService } from '@core/theme/theme.service';
import { ButtonComponent } from '../ui/button/button.component';

@Component({
  selector: 'cd-app-shell',
  imports: [RouterLink, RouterLinkActive, ButtonComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="header">
      <a class="brand" routerLink="/">CloudDrop AI</a>
      <button
        cd-button
        variant="secondary"
        type="button"
        [attr.aria-label]="'Change colour theme, currently ' + theme.label()"
        (click)="theme.cycle()"
      >
        Theme: {{ theme.label() }}
      </button>
    </header>
    <nav class="nav" aria-label="Primary">
      <a routerLink="/" routerLinkActive="active" [routerLinkActiveOptions]="{ exact: true }">
        Files
      </a>
    </nav>
    <main id="main" class="main" tabindex="-1">
      <ng-content />
    </main>
  `,
  styleUrl: './app-shell.component.scss',
})
export class AppShellComponent {
  protected readonly theme = inject(ThemeService);
}
