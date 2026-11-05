import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

import { AppShellComponent } from '@shared/layout/app-shell.component';

@Component({
  selector: 'cd-root',
  imports: [RouterOutlet, AppShellComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <a class="skip-link" href="#main">Skip to main content</a>
    <cd-app-shell>
      <router-outlet />
    </cd-app-shell>
  `,
})
export class App {}
