import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { STATUS_LABELS } from '@core/api/file-status';
import { type FileStatus } from '@core/api/models';

@Component({
  selector: 'cd-status-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<span class="badge" [attr.data-status]="status()">{{ label() }}</span>`,
  styleUrl: './status-badge.component.scss',
})
export class StatusBadgeComponent {
  readonly status = input.required<FileStatus>();
  protected readonly label = computed(() => STATUS_LABELS[this.status()]);
}
