import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  input,
  type OnInit,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DOCUMENT } from '@angular/common';
import { catchError, defer, EMPTY, finalize, from, Subject, switchMap, tap } from 'rxjs';

import { type ShareLink } from '@core/api/models';
import { ShareLinksApi } from '@core/api/share-links-api.service';
import { ErrorResolver } from '@core/error/error-resolver.service';
import { DateTimePipe } from '@shared/pipes/date-time.pipe';
import { ButtonComponent } from '@shared/ui/button/button.component';

const PAGE_SIZE = 50;
const DAY_CHOICES = [1, 7, 30] as const;

/**
 * View-only links to one file. The address is shown once, right after it is made: only a hash is
 * kept on the server, so it can never be shown again. The token sits in the URL fragment, which a
 * browser never sends to any server.
 */
@Component({
  selector: 'cd-share-links',
  imports: [ButtonComponent, DateTimePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h3>Link anyone can open</h3>
    <p class="hint">Anyone with the link can view and download this file until it expires.</p>
    <div class="make">
      <label for="link-days">Expires in</label>
      <select
        #days
        id="link-days"
        class="cd-input"
        [value]="expiresInDays()"
        (change)="expiresInDays.set(+days.value)"
      >
        @for (choice of dayChoices; track choice) {
          <option [value]="choice">{{ choice === 1 ? '1 day' : choice + ' days' }}</option>
        }
      </select>
      <button cd-button type="button" [busy]="busy()" (click)="create()">Create link</button>
    </div>

    <p class="cd-form-error" role="alert">{{ error() }}</p>
    @if (created(); as address) {
      <div class="created" role="status">
        <p>Copy this link now. It is not shown again.</p>
        <input class="cd-input" type="text" readonly aria-label="Link address" [value]="address" />
        <button cd-button variant="secondary" type="button" (click)="copy(address)">Copy</button>
        <span class="copied">{{ copied() }}</span>
      </div>
    }

    @if (links().length > 0) {
      <ul class="links">
        @for (link of links(); track link.id) {
          <li>
            <span>
              {{ link.revoked_at ? 'Turned off' : 'Active' }}, expires
              {{ link.expires_at | cdDateTime }}
            </span>
            @if (!link.revoked_at) {
              <button
                cd-button
                variant="danger"
                type="button"
                [busy]="revoking() === link.id"
                [attr.aria-label]="
                  'Turn off the link that expires ' + (link.expires_at | cdDateTime)
                "
                (click)="revoke(link)"
              >
                Turn off
              </button>
            }
          </li>
        }
      </ul>
    }
  `,
  styles: `
    .hint {
      color: var(--cd-text-muted);
    }
    .make,
    .created {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--cd-space-2);
    }
    .created input {
      flex: 1 1 14rem;
    }
    .links {
      list-style: none;
      margin: var(--cd-space-3) 0 0;
      padding: 0;
      display: grid;
      gap: var(--cd-space-2);
    }
    .links li {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: var(--cd-space-2);
    }
    .copied {
      color: var(--cd-text-muted);
    }
  `,
})
export class ShareLinksComponent implements OnInit {
  readonly fileId = input.required<string>();

  protected readonly dayChoices = DAY_CHOICES;
  protected readonly expiresInDays = signal<number>(7);
  protected readonly links = signal<readonly ShareLink[]>([]);
  protected readonly busy = signal(false);
  protected readonly revoking = signal<string | null>(null);
  protected readonly error = signal<string | null>(null);
  /** The full address of the link just made; held in memory only, never stored or logged. */
  protected readonly created = signal<string | null>(null);
  protected readonly copied = signal('');

  private readonly api = inject(ShareLinksApi);
  private readonly resolver = inject(ErrorResolver);
  private readonly document = inject(DOCUMENT);
  private readonly destroyRef = inject(DestroyRef);
  private readonly reloads = new Subject<void>();

  ngOnInit(): void {
    this.reloads
      .pipe(
        switchMap(() =>
          this.api.list(this.fileId(), 1, PAGE_SIZE).pipe(
            tap((page) => this.links.set(page.items)),
            catchError((error: unknown) => {
              this.error.set(this.resolver.resolve(error).message);
              return EMPTY;
            }),
          ),
        ),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe();
    this.reloads.next();
  }

  protected create(): void {
    if (this.busy()) {
      return;
    }
    this.busy.set(true);
    this.error.set(null);
    this.copied.set('');
    this.api
      .create(this.fileId(), this.expiresInDays())
      .pipe(
        finalize(() => this.busy.set(false)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (link) => {
          this.created.set(`${this.document.location.origin}/s#${link.token}`);
          this.reloads.next();
        },
        error: (error: unknown) => this.error.set(this.resolver.resolve(error).message),
      });
  }

  protected revoke(link: ShareLink): void {
    if (this.revoking() !== null) {
      return;
    }
    this.revoking.set(link.id);
    this.error.set(null);
    this.api
      .revoke(this.fileId(), link.id)
      .pipe(
        finalize(() => this.revoking.set(null)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: () => this.reloads.next(),
        error: (error: unknown) => this.error.set(this.resolver.resolve(error).message),
      });
  }

  protected copy(address: string): void {
    const clipboard = this.document.defaultView?.navigator.clipboard;
    if (!clipboard) {
      this.copied.set('Select the address and copy it.');
      return;
    }
    // The clipboard API is promise-only, so it is wrapped at the boundary.
    defer(() => from(clipboard.writeText(address)))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => this.copied.set('Copied.'),
        error: () => this.copied.set('Could not copy. Select the address and copy it.'),
      });
  }
}
