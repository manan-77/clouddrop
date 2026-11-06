import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { ButtonComponent } from '@shared/ui/button/button.component';
import { DialogComponent } from '@shared/ui/dialog/dialog.component';

@Component({
  selector: 'cd-confirm-dialog',
  imports: [ButtonComponent, DialogComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <cd-dialog [heading]="heading()" [dismissible]="!busy()" (dismissed)="dismissed.emit()">
      <p>{{ message() }}</p>
      @if (error(); as text) {
        <p class="cd-form-error" role="alert">{{ text }}</p>
      }
      <div class="cd-actions">
        <button
          cd-button
          variant="secondary"
          type="button"
          [disabled]="busy()"
          (click)="dismissed.emit()"
        >
          Cancel
        </button>
        <button cd-button variant="danger" type="button" [busy]="busy()" (click)="confirmed.emit()">
          {{ confirmLabel() }}
        </button>
      </div>
    </cd-dialog>
  `,
})
export class ConfirmDialogComponent {
  readonly heading = input.required<string>();
  readonly message = input.required<string>();
  readonly confirmLabel = input.required<string>();
  readonly busy = input(false);
  readonly error = input<string | null>(null);
  readonly confirmed = output<void>();
  readonly dismissed = output<void>();
}
