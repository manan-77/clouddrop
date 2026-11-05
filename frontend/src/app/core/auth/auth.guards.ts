import { inject } from '@angular/core';
import { type CanActivateFn, Router } from '@angular/router';
import { map } from 'rxjs';

import { AuthService } from './auth.service';

/** Redirects are UX only; the server enforces access on every call. */
export const authGuard: CanActivateFn = () => {
  const router = inject(Router);
  return inject(AuthService)
    .ensureSession()
    .pipe(map((signedIn) => signedIn || router.createUrlTree(['/login'])));
};

export const guestGuard: CanActivateFn = () => {
  const router = inject(Router);
  return inject(AuthService)
    .ensureSession()
    .pipe(map((signedIn) => (signedIn ? router.createUrlTree(['/']) : true)));
};
