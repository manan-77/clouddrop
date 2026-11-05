import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * Inline validation text. Point the control's aria-describedby at `fieldId`. The live region is
 * always in the DOM and only its text changes, so screen readers announce new messages.
 */
@Component({
  selector: 'cd-field-error',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <p class="field-error" [id]="fieldId()" aria-live="polite">
      @if (message(); as text) {
        {{ text }}
      }
    </p>
  `,
  styleUrl: './field-error.component.scss',
})
export class FieldErrorComponent {
  readonly fieldId = input.required<string>();
  readonly message = input<string | null>(null);
}
