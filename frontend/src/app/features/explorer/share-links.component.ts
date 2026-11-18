import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  input,
  type OnInit,
  signal,
} from '@angular/core';
import { DOCUMENT } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { catchError, EMPTY, finalize, Subject, switchMap, tap } from 'rxjs';

import { type ShareLink } from '@core/api/models';
import { ShareLinksApi } from '@core/api/share-links-api.service';
import { ErrorResolver } from '@core/error/error-resolver.service';
import { DateTimePipe } from '@shared/pipes/date-time.pipe';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { LinkAddressComponent } from './link-address.component';

const PAGE_SIZE = 50;
const DAY_CHOICES = [1, 7, 30] as const;

/**
 * View-only links to one file. The address is shown once, right after it is made: only a hash is
 * kept on the server, so it can never be shown again. The token sits in the URL fragment, which a
 * browser never sends to any server.
 */
@Component({
  selector: 'cd-share-links',
  imports: [ButtonComponent, DateTimePipe, LinkAddressComponent],
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
    <p class="cd-visually-hidden" role="status">{{ announcement() }}</p>
    @if (created(); as made) {
      <cd-link-address [address]="made.address" />
    }

    @if (!loaded() && !listError()) {
      <p class="hint">Loading links…</p>
    } @else if (listError(); as message) {
      <p class="cd-form-error" role="alert">{{ message }}</p>
    } @else if (links().length === 0) {
      <p class="hint">No links yet.</p>
    } @else {
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
    .make {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--cd-space-2);
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
  `,
})
export class ShareLinksComponent implements OnInit {
  readonly fileId = input.required<string>();

  protected readonly dayChoices = DAY_CHOICES;
  protected readonly expiresInDays = signal<number>(7);
  protected readonly links = signal<readonly ShareLink[]>([]);
  protected readonly loaded = signal(false);
  protected readonly listError = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected readonly revoking = signal<string | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly announcement = signal('');
  /** The link just made and its full address; memory only, dropped when that link is turned off. */
  protected readonly created = signal<{ id: string; address: string } | null>(null);

  private readonly api = inject(ShareLinksApi);
  private readonly resolver = inject(ErrorResolver);
  private readonly router = inject(Router);
  private readonly document = inject(DOCUMENT);
  private readonly destroyRef = inject(DestroyRef);
  private readonly reloads = new Subject<void>();

  ngOnInit(): void {
    this.reloads
      .pipe(
        tap(() => this.listError.set(null)),
        switchMap(() =>
          this.api.list(this.fileId(), 1, PAGE_SIZE).pipe(
            tap((page) => {
              this.links.set(page.items);
              this.loaded.set(true);
            }),
            catchError((error: unknown) => {
              this.listError.set(this.resolver.resolve(error).message);
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
    this.created.set(null);
    this.api
      .create(this.fileId(), this.expiresInDays())
      .pipe(
        finalize(() => this.busy.set(false)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (link) => {
          // The page route builds the address; the token rides in the fragment.
          const path = this.router.serializeUrl(
            this.router.createUrlTree(['/s'], { fragment: link.token }),
          );
          this.created.set({ id: link.id, address: `${this.document.location.origin}${path}` });
          this.announcement.set('Link created. Copy it now.');
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
        next: () => {
          if (this.created()?.id === link.id) {
            this.created.set(null); // a turned-off link's address must not stay on screen
          }
          this.announcement.set('Link turned off.');
          this.reloads.next();
        },
        error: (error: unknown) => this.error.set(this.resolver.resolve(error).message),
      });
  }
}
