import { Pipe, type PipeTransform } from '@angular/core';

/** Pure membership test for templates (avoids calling methods in bindings). */
@Pipe({ name: 'isIn' })
export class IsInPipe implements PipeTransform {
  transform(value: string, list: readonly string[]): boolean {
    return list.includes(value);
  }
}
