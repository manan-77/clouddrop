import { type Routes } from '@angular/router';

import { authGuard, guestGuard } from '@core/auth/auth.guards';

const explorer = () => import('./features/explorer/explorer.page').then((m) => m.ExplorerPage);

export const routes: Routes = [
  { path: '', pathMatch: 'full', canActivate: [authGuard], loadComponent: explorer },
  { path: 'folders/:folderId', canActivate: [authGuard], loadComponent: explorer },
  {
    path: 'shared',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./features/shared-with-me/shared-with-me.page').then((m) => m.SharedWithMePage),
  },
  {
    // No guard: anyone with a link can open it. The token is in the URL fragment.
    path: 's',
    loadComponent: () =>
      import('./features/public-link/public-link.page').then((m) => m.PublicLinkPage),
  },
  {
    path: 'login',
    canActivate: [guestGuard],
    loadComponent: () => import('./features/auth/login.page').then((m) => m.LoginPage),
  },
  {
    path: 'register',
    canActivate: [guestGuard],
    loadComponent: () => import('./features/auth/register.page').then((m) => m.RegisterPage),
  },
  {
    path: '**',
    loadComponent: () => import('./features/not-found/not-found.page').then((m) => m.NotFoundPage),
  },
];
