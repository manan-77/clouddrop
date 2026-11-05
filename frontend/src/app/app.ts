import { DOCUMENT } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';

import { AppShellComponent } from '@shared/layout/app-shell.component';

@Component({
  selector: 'cd-root',
  imports: [RouterOutlet, AppShellComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <a class="skip-link" href="#main" (click)="skipToMain($event)">Skip to main content</a>
    <cd-app-shell>
      <router-outlet />
    </cd-app-shell>
  `,
})
export class App {
  private readonly document = inject(DOCUMENT);

  // A bare #fragment resolves against <base href="/">, so on any route other than "/" the link
  // would reload the page. Move focus directly instead.
  protected skipToMain(event: Event): void {
    event.preventDefault();
    this.document.getElementById('main')?.focus();
  }
}
