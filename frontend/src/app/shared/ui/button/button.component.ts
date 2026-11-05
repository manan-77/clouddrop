import { booleanAttribute, ChangeDetectionStrategy, Component, input } from '@angular/core';

export type ButtonVariant = 'primary' | 'secondary' | 'danger';

/** Native button with an in-flight state: shows a spinner and is disabled while busy. */
@Component({
  selector: 'button[cd-button]',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (busy()) {
      <span class="spinner" aria-hidden="true"></span>
    }
    <ng-content />
  `,
  styleUrl: './button.component.scss',
  host: {
    '[attr.data-variant]': 'variant()',
    '[attr.aria-busy]': 'busy() ? "true" : null',
    '[disabled]': 'busy() || disabled()',
  },
})
export class ButtonComponent {
  readonly variant = input<ButtonVariant>('primary');
  readonly busy = input(false, { transform: booleanAttribute });
  readonly disabled = input(false, { transform: booleanAttribute });
}
