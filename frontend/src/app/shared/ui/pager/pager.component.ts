import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';

import { ButtonComponent } from '../button/button.component';

@Component({
  selector: 'cd-pager',
  imports: [ButtonComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (pages() > 1) {
      <nav class="pager" [attr.aria-label]="label()">
        <button
          cd-button
          variant="secondary"
          type="button"
          [disabled]="page() <= 1"
          (click)="pageChange.emit(page() - 1)"
        >
          Previous
        </button>
        <span>Page {{ page() }} of {{ pages() }}</span>
        <button
          cd-button
          variant="secondary"
          type="button"
          [disabled]="page() >= pages()"
          (click)="pageChange.emit(page() + 1)"
        >
          Next
        </button>
      </nav>
    }
  `,
  styleUrl: './pager.component.scss',
})
export class PagerComponent {
  readonly page = input.required<number>();
  readonly pageSize = input.required<number>();
  readonly total = input.required<number>();
  readonly label = input('Pagination');
  readonly pageChange = output<number>();

  protected readonly pages = computed(() => Math.max(1, Math.ceil(this.total() / this.pageSize())));
}
