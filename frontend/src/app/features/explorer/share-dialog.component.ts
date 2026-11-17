import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  type ElementRef,
  inject,
  input,
  type OnInit,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { catchError, EMPTY, finalize, Subject, switchMap, tap, type Observable } from 'rxjs';

import { type GrantRead, type GrantRole, type ShareKind } from '@core/api/models';
import { SharingApi } from '@core/api/sharing-api.service';
import { ErrorResolver } from '@core/error/error-resolver.service';
import { dottedEmail, notBlank } from '@shared/forms/validators';
import { validationMessage } from '@shared/forms/validation-messages';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { DialogComponent } from '@shared/ui/dialog/dialog.component';
import { FieldErrorComponent } from '@shared/ui/field-error/field-error.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';

const PAGE_SIZE = 100;

/**
 * Who can open a file or folder. Only the owner is offered this dialog and the server refuses
 * everyone else. Adding, changing and removing run one at a time, and the list is always the
 * latest response (an older, slower one never overwrites it).
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
  templateUrl: './share-dialog.component.html',
  styleUrl: './share-dialog.component.scss',
})
export class ShareDialogComponent implements OnInit {
  readonly kind = input.required<ShareKind>();
  readonly resourceId = input.required<string>();
  readonly resourceName = input.required<string>();
  readonly dismissed = output<void>();

  protected readonly items = signal<readonly GrantRead[]>([]);
  /** False until the first list arrives, so a reload keeps the list on screen. */
  protected readonly loaded = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly busy = signal(false);
  /** What is running: 'add' or the id of the grant being changed or removed. */
  protected readonly pending = signal<string | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly notice = signal<string | null>(null);
  protected readonly emailMessage = signal<string | null>(null);
  private readonly emailInput = viewChild<ElementRef<HTMLInputElement>>('emailInput');
  private readonly errorBox = viewChild<ElementRef<HTMLElement>>('errorBox');

  protected readonly form = inject(NonNullableFormBuilder).group({
    email: [
      '',
      [Validators.required, notBlank, Validators.email, dottedEmail, Validators.maxLength(320)],
    ],
    role: ['viewer' as GrantRole],
  });

  private readonly api = inject(SharingApi);
  private readonly resolver = inject(ErrorResolver);
  private readonly destroyRef = inject(DestroyRef);
  private readonly reloads = new Subject<void>();

  ngOnInit(): void {
    // switchMap: only the latest list request can update the screen.
    this.reloads
      .pipe(
        tap(() => this.loadError.set(null)),
        switchMap(() =>
          this.api.list(this.kind(), this.resourceId(), 1, PAGE_SIZE).pipe(
            tap({
              next: (page) => {
                this.items.set(page.items);
                this.loaded.set(true);
              },
              error: (error: unknown) => this.loadError.set(this.resolver.resolve(error).message),
            }),
            // A failed list must not end the stream: the user can retry.
            catchError(() => EMPTY),
          ),
        ),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe();
    this.reload();
  }

  protected reload(): void {
    this.reloads.next();
  }

  protected onEdit(): void {
    this.emailMessage.set(null);
    this.error.set(null);
    this.notice.set(null);
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
      undefined,
      true,
    );
  }

  protected change(grant: GrantRead, role: string): void {
    if (role !== 'viewer' && role !== 'editor') {
      return;
    }
    if (this.busy() || role === grant.role) {
      if (role !== grant.role) {
        this.rebuildRows(); // ignored while busy: show the saved role again
      }
      return;
    }
    this.run(
      grant.id,
      this.api.changeRole(this.kind(), this.resourceId(), grant.id, role),
      () => this.notice.set('Access updated.'),
      // A refused change must not leave the control showing a role that was not saved.
      () => this.rebuildRows(),
    );
  }

  /** A select keeps the value the user picked; showing the list as loading rebuilds it from state. */
  private rebuildRows(): void {
    this.loaded.set(false);
  }

  protected revoke(grant: GrantRead): void {
    if (this.busy()) {
      return;
    }
    this.run(
      grant.id,
      this.api.revoke(this.kind(), this.resourceId(), grant.id),
      () => this.notice.set('Access removed.'),
      undefined,
      true,
    );
  }

  /** One write at a time (a second click or Enter is ignored), then the list is read again. */
  private run(
    id: string,
    operation: Observable<unknown>,
    done: () => void,
    failed: (() => void) | undefined = undefined,
    refocus = false,
  ): void {
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
          this.reload();
          // A removed row takes its button with it; keep the keyboard user in the dialog.
          if (refocus) {
            this.emailInput()?.nativeElement.focus();
          }
        },
        error: (error: unknown) => {
          failed?.();
          this.error.set(this.resolver.resolve(error).message);
          // The rebuilt list loses the focused control, so move focus to the message instead.
          this.errorBox()?.nativeElement.focus();
          this.reload();
        },
      });
  }
}
