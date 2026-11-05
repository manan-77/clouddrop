import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/** Inline validation text. Point the field's aria-describedby at the same id. */
@Component({
  selector: 'cd-field-error',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (message()) {
      <p class="field-error" [id]="id()" aria-live="polite">{{ message() }}</p>
    }
  `,
  styleUrl: './field-error.component.scss',
})
export class FieldErrorComponent {
  readonly id = input.required<string>();
  readonly message = input<string | null>(null);
}
