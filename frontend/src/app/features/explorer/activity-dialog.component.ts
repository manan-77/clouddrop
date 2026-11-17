import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  input,
  type OnInit,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { AuditApi } from '@core/api/audit-api.service';
import { type AuditEvent } from '@core/api/models';
import { ErrorResolver } from '@core/error/error-resolver.service';
import { AuditLabelPipe } from '@shared/pipes/audit-label.pipe';
import { DateTimePipe } from '@shared/pipes/date-time.pipe';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { DialogComponent } from '@shared/ui/dialog/dialog.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';

type State =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; events: readonly AuditEvent[]; total: number };

const PAGE_SIZE = 50;

/** Recent activity on one file or folder, newest first. Owners only; the server enforces it. */
@Component({
  selector: 'cd-activity-dialog',
  imports: [AuditLabelPipe, ButtonComponent, DateTimePipe, DialogComponent, SkeletonComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <cd-dialog [heading]="'Activity for ' + resourceName()" (dismissed)="dismissed.emit()">
      @switch (state().status) {
        @case ('loading') {
          <cd-skeleton [lines]="3" />
        }
        @case ('error') {
          <p class="cd-form-error" role="alert">{{ errorText() }}</p>
          <button cd-button variant="secondary" type="button" (click)="load()">Try again</button>
        }
        @default {
          @if (events().length === 0) {
            <p>No activity recorded yet.</p>
          } @else {
            <div class="cd-table-wrap">
              <table class="cd-table">
                <caption class="cd-visually-hidden">
                  Activity
                </caption>
                <thead>
                  <tr>
                    <th scope="col">When</th>
                    <th scope="col">What</th>
                    <th scope="col">Who</th>
                  </tr>
                </thead>
                <tbody>
                  @for (event of events(); track event.id) {
                    <tr>
                      <td>{{ event.created_at | cdDateTime }}</td>
                      <td>{{ event | auditLabel }}</td>
                      <td>{{ event.actor_name ?? 'Removed account' }}</td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
            @if (total() > events().length) {
              <p>Showing the latest {{ events().length }} of {{ total() }}.</p>
            }
          }
        }
      }
      <div class="cd-actions">
        <button cd-button variant="secondary" type="button" (click)="dismissed.emit()">
          Close
        </button>
      </div>
    </cd-dialog>
  `,
})
export class ActivityDialogComponent implements OnInit {
  readonly resourceId = input.required<string>();
  readonly resourceName = input.required<string>();
  readonly dismissed = output<void>();

  protected readonly state = signal<State>({ status: 'loading' });
  protected readonly events = signal<readonly AuditEvent[]>([]);
  protected readonly total = signal(0);
  protected readonly errorText = signal('');

  private readonly api = inject(AuditApi);
  private readonly resolver = inject(ErrorResolver);
  private readonly destroyRef = inject(DestroyRef);

  ngOnInit(): void {
    this.load();
  }

  protected load(): void {
    this.state.set({ status: 'loading' });
    this.api
      .forResource(this.resourceId(), 1, PAGE_SIZE)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (page) => {
          this.events.set(page.items);
          this.total.set(page.total);
          this.state.set({ status: 'ready', events: page.items, total: page.total });
        },
        error: (error: unknown) => {
          this.errorText.set(this.resolver.resolve(error).message);
          this.state.set({ status: 'error', message: this.errorText() });
        },
      });
  }
}
