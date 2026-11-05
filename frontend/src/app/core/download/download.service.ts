import { DOCUMENT } from '@angular/common';
import { inject, Injectable } from '@angular/core';

/**
 * Starts a browser download from a short-lived signed link. The link is never stored, logged or
 * kept in state; the server marks it as an attachment so the page does not navigate away.
 */
@Injectable({ providedIn: 'root' })
export class DownloadService {
  private readonly document = inject(DOCUMENT);

  start(url: string): void {
    const anchor = this.document.createElement('a');
    anchor.href = url;
    anchor.rel = 'noopener noreferrer';
    this.document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  }
}
