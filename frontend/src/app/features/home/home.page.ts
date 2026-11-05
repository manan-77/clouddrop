import { ChangeDetectionStrategy, Component } from '@angular/core';

import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';

@Component({
  selector: 'cd-home-page',
  imports: [EmptyStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h1>Files</h1>
    <cd-empty-state
      title="Your files will appear here"
      description="Sign-in and the file explorer are coming in the next steps."
    />
  `,
})
export class HomePage {}
