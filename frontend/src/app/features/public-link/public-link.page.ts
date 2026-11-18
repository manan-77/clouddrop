import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  type OnInit,
  signal,
} from '@angular/core';
import { DOCUMENT } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { finalize } from 'rxjs';

import { type PublicLink } from '@core/api/models';
import { ShareLinksApi } from '@core/api/share-links-api.service';
import { DownloadService } from '@core/download/download.service';
import { ErrorResolver } from '@core/error/error-resolver.service';
import { DateTimePipe } from '@shared/pipes/date-time.pipe';
import { FileSizePipe } from '@shared/pipes/file-size.pipe';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';

const UNAVAILABLE = 'This link is not available. It may have expired or been turned off.';

/**
 * Opens a file shared by link, for anyone (no sign-in). The token is read from the URL fragment,
 * which a browser never sends to a server, and is only ever kept in memory.
 */
@Component({
  selector: 'cd-public-link-page',
  imports: [ButtonComponent, DateTimePipe, FileSizePipe, SkeletonComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h1>Shared file</h1>
    @if (loading()) {
      <cd-skeleton [lines]="3" />
    } @else if (error(); as message) {
      <p class="cd-form-error" role="alert">{{ message }}</p>
    } @else if (link(); as file) {
      <p class="name">{{ file.file_name }}</p>
      <p class="meta">
        {{ file.size_bytes | fileSize }} · link expires {{ file.expires_at | cdDateTime }}
      </p>
      <p class="cd-form-error" role="alert">{{ downloadError() }}</p>
      <button cd-button type="button" [busy]="downloading()" (click)="download()">Download</button>
    }
  `,
  styles: `
    .name {
      font-size: 1.25rem;
      overflow-wrap: anywhere;
    }
    .meta {
      color: var(--cd-text-muted);
    }
  `,
})
export class PublicLinkPage implements OnInit {
  protected readonly loading = signal(true);
  protected readonly link = signal<PublicLink | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly downloading = signal(false);
  protected readonly downloadError = signal<string | null>(null);

  private readonly api = inject(ShareLinksApi);
  private readonly downloads = inject(DownloadService);
  private readonly resolver = inject(ErrorResolver);
  private readonly document = inject(DOCUMENT);
  private readonly destroyRef = inject(DestroyRef);
  private token = '';

  ngOnInit(): void {
    this.token = this.document.location.hash.slice(1);
    if (!this.token) {
      this.error.set(UNAVAILABLE);
      this.loading.set(false);
      return;
    }
    this.api
      .resolve(this.token)
      .pipe(
        finalize(() => this.loading.set(false)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (result) => this.link.set(result),
        error: (error: unknown) => this.error.set(this.resolver.resolve(error).message),
      });
  }

  protected download(): void {
    if (this.downloading()) {
      return;
    }
    this.downloading.set(true);
    this.downloadError.set(null);
    this.api
      .download(this.token)
      .pipe(
        finalize(() => this.downloading.set(false)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (result) => {
          try {
            this.downloads.start(result.url);
          } catch {
            // The service refuses a link that is not plain http(s); say so instead of doing nothing.
            this.downloadError.set('The download could not be started. Please try again.');
          }
        },
        error: (error: unknown) => this.downloadError.set(this.resolver.resolve(error).message),
      });
  }
}
