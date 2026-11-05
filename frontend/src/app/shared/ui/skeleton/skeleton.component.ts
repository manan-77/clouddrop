import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
  numberAttribute,
} from '@angular/core';

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
  protected readonly rows = computed(() =>
    Array.from({ length: this.lines() }, (_, index) => index),
  );
}
