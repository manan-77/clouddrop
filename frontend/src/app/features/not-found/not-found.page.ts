import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';

import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';

@Component({
  selector: 'cd-not-found-page',
  imports: [EmptyStateComponent, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h1>Page not found</h1>
    <cd-empty-state title="We could not find that page" description="The link may be broken.">
      <a routerLink="/">Back to files</a>
    </cd-empty-state>
  `,
})
export class NotFoundPage {}
