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
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { finalize, type Observable } from 'rxjs';

import { type GrantRead, type GrantRole, type ShareKind } from '@core/api/models';
import { SharingApi } from '@core/api/sharing-api.service';
import { ErrorResolver } from '@core/error/error-resolver.service';
import { notBlank } from '@shared/forms/validators';
import { validationMessage } from '@shared/forms/validation-messages';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { DialogComponent } from '@shared/ui/dialog/dialog.component';
import { FieldErrorComponent } from '@shared/ui/field-error/field-error.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';

type Listing =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; items: readonly GrantRead[] };

const PAGE_SIZE = 100;

/**
 * Who can open a file or folder. Only the owner sees this dialog's entry point; the server
 * refuses everyone else. Adding someone, changing a role and revoking all run one at a time.
 */
@Component({
  selector: 'cd-share-dialog',
  imports: [
    ReactiveFormsModule,
    ButtonComponent,
    DialogComponent,
    FieldErrorComponent,
    SkeletonComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <cd-dialog
      [heading]="'Share ' + resourceName()"
      [dismissible]="!busy()"
      (dismissed)="dismissed.emit()"
    >
      <form class="cd-form" [formGroup]="form" (ngSubmit)="add()" novalidate>
        <div class="cd-field">
          <label for="share-email">Email of the person</label>
          <input
            id="share-email"
            class="cd-input"
            type="email"
            autocomplete="off"
            aria-describedby="share-email-error"
            formControlName="email"
            [attr.aria-invalid]="emailMessage() ? 'true' : null"
            [readOnly]="busy()"
            (input)="onEdit()"
          />
          <cd-field-error fieldId="share-email-error" [message]="emailMessage()" />
        </div>
        <div class="cd-field">
          <label for="share-role">Can</label>
          <select
            id="share-role"
            class="cd-input"
            formControlName="role"
            [attr.disabled]="busy() ? '' : null"
          >
            <option value="viewer">View</option>
            <option value="editor">Edit</option>
          </select>
        </div>
        <div class="cd-actions">
          <button cd-button type="submit" [busy]="busy() && pending() === 'add'">Share</button>
        </div>
      </form>

      <p class="cd-form-error" role="alert">{{ error() }}</p>
      <p class="notice" role="status">{{ notice() }}</p>

      <h3>People with access</h3>
      @switch (listing().status) {
        @case ('loading') {
          <cd-skeleton [lines]="2" />
        }
        @case ('error') {
          <p class="cd-form-error" role="alert">{{ errorText() }}</p>
          <button cd-button variant="secondary" type="button" (click)="load()">Try again</button>
        }
        @default {
          @if (items().length === 0) {
            <p>Nobody else has access yet.</p>
          } @else {
            <ul class="people">
              @for (grant of items(); track grant.id) {
                <li>
                  <span class="who">{{ grant.display_name }} ({{ grant.email }})</span>
                  <select
                    #roleSelect
                    class="cd-input"
                    [attr.aria-label]="'Access for ' + grant.display_name"
                    [value]="grant.role"
                    [disabled]="busy()"
                    (change)="change(grant, roleSelect.value)"
                  >
                    <option value="viewer">View</option>
                    <option value="editor">Edit</option>
                  </select>
                  <button
                    cd-button
                    variant="danger"
                    type="button"
                    [busy]="pending() === grant.id"
                    [disabled]="busy()"
                    [attr.aria-label]="'Remove access for ' + grant.display_name"
                    (click)="revoke(grant)"
                  >
                    Remove
                  </button>
                </li>
              }
            </ul>
          }
        }
      }
      <div class="cd-actions">
        <button
          cd-button
          variant="secondary"
          type="button"
          [disabled]="busy()"
          (click)="dismissed.emit()"
        >
          Close
        </button>
      </div>
    </cd-dialog>
  `,
  styles: `
    .people {
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: var(--space-2);
    }
    .people li {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--space-2);
    }
    .who {
      flex: 1 1 12rem;
      overflow-wrap: anywhere;
    }
    .notice {
      color: var(--color-text-muted);
      min-height: 1.5em;
    }
  `,
})
export class ShareDialogComponent implements OnInit {
  readonly kind = input.required<ShareKind>();
  readonly resourceId = input.required<string>();
  readonly resourceName = input.required<string>();
  readonly dismissed = output<void>();

  protected readonly listing = signal<Listing>({ status: 'loading' });
  protected readonly items = signal<readonly GrantRead[]>([]);
  protected readonly errorText = signal('');
  protected readonly busy = signal(false);
  /** What is running: 'add' or the id of the grant being changed or removed. */
  protected readonly pending = signal<string | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly notice = signal<string | null>(null);
  protected readonly emailMessage = signal<string | null>(null);

  protected readonly form = inject(NonNullableFormBuilder).group({
    email: ['', [Validators.required, notBlank, Validators.email, Validators.maxLength(320)]],
    role: ['viewer' as GrantRole],
  });

  private readonly api = inject(SharingApi);
  private readonly resolver = inject(ErrorResolver);
  private readonly destroyRef = inject(DestroyRef);

  ngOnInit(): void {
    this.load();
  }

  protected load(): void {
    this.listing.set({ status: 'loading' });
    this.api
      .list(this.kind(), this.resourceId(), 1, PAGE_SIZE)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (page) => {
          this.items.set(page.items);
          this.listing.set({ status: 'ready', items: page.items });
        },
        error: (error: unknown) => {
          this.errorText.set(this.resolver.resolve(error).message);
          this.listing.set({ status: 'error', message: this.errorText() });
        },
      });
  }

  protected onEdit(): void {
    this.emailMessage.set(null);
    this.error.set(null);
  }

  protected add(): void {
    if (this.busy()) {
      return;
    }
    const problem = validationMessage(this.form.controls.email, 'Email');
    this.emailMessage.set(problem);
    if (problem) {
      return;
    }
    const email = this.form.controls.email.value.trim();
    this.run(
      'add',
      this.api.grant(this.kind(), this.resourceId(), email, this.form.controls.role.value),
      () => {
        this.form.controls.email.reset('');
        this.notice.set('Access saved.');
      },
    );
  }

  protected change(grant: GrantRead, role: string): void {
    if (this.busy() || (role !== 'viewer' && role !== 'editor') || role === grant.role) {
      return;
    }
    this.run(grant.id, this.api.changeRole(this.kind(), this.resourceId(), grant.id, role), () =>
      this.notice.set('Access updated.'),
    );
  }

  protected revoke(grant: GrantRead): void {
    if (this.busy()) {
      return;
    }
    this.run(grant.id, this.api.revoke(this.kind(), this.resourceId(), grant.id), () =>
      this.notice.set('Access removed.'),
    );
  }

  /** One write at a time (a second click or Enter is ignored), then the list is read again. */
  private run(id: string, operation: Observable<unknown>, done: () => void): void {
    this.busy.set(true);
    this.pending.set(id);
    this.error.set(null);
    this.notice.set(null);
    operation
      .pipe(
        finalize(() => {
          this.busy.set(false);
          this.pending.set(null);
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: () => {
          done();
          this.load();
        },
        error: (error: unknown) => {
          this.error.set(this.resolver.resolve(error).message);
          this.load();
        },
      });
  }
}
