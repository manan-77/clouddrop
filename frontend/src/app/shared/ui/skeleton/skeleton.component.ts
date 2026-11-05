import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
  numberAttribute,
} from '@angular/core';

const MAX_LINES = 20;

/** Placeholder rows shown while a list loads, so the layout does not jump. */
@Component({
  selector: 'cd-skeleton',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="skeleton" role="status">
      <span class="cd-visually-hidden">Loading</span>
      @for (row of rows(); track row) {
        <span class="line" aria-hidden="true"></span>
      }
    </div>
  `,
  styleUrl: './skeleton.component.scss',
})
export class SkeletonComponent {
  readonly lines = input(3, { transform: numberAttribute });
  protected readonly rows = computed(() => {
    const requested = Math.trunc(this.lines());
    const count = Number.isFinite(requested) ? Math.min(Math.max(requested, 1), MAX_LINES) : 3;
    return Array.from({ length: count }, (_, index) => index);
  });
}
