import { Pipe, type PipeTransform } from '@angular/core';

function toDate(value: string | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

const pad = (n: number): string => n.toString().padStart(2, '0');

function formatDate(date: Date): string {
  return `${pad(date.getDate())}/${pad(date.getMonth() + 1)}/${date.getFullYear()}`;
}

/** One display format everywhere: DD/MM/YYYY HH:mm, 24-hour, local time. The wire stays ISO UTC. */
@Pipe({ name: 'cdDateTime' })
export class DateTimePipe implements PipeTransform {
  transform(value: string | Date | null | undefined): string {
    const date = toDate(value);
    return date ? `${formatDate(date)} ${pad(date.getHours())}:${pad(date.getMinutes())}` : '';
  }
}

@Pipe({ name: 'cdDate' })
export class DateOnlyPipe implements PipeTransform {
  transform(value: string | Date | null | undefined): string {
    const date = toDate(value);
    return date ? formatDate(date) : '';
  }
}
