import { type CallerRole } from './models';

/** Only what the UI should offer. The server re-checks every request. */
export const canWrite = (role: CallerRole): boolean => role === 'owner' || role === 'editor';
export const canManage = (role: CallerRole): boolean => role === 'owner';
