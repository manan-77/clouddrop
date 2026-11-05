import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { App } from './app/app';

// shortcut: a bootstrap failure shows text only and is not reported; wire it to the telemetry sink in Phase 8.
bootstrapApplication(App, appConfig).catch(() => {
  document.body.textContent = 'CloudDrop could not start. Please reload the page.';
});
