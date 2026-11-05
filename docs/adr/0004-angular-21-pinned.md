# ADR 0004: Angular 21 pinned (not 22) for now

Status: Accepted

## Context
The latest Angular CLI (22.x) requires Node `^22.22.3`, `^24.15.0` or `>=26`. The development machine runs Node 25, an odd-numbered non-LTS release that none of those ranges accept. Angular CLI 21.2 accepts `^20.19`, `^22.12` and `>=24`, which includes Node 25.

## Decision
Scaffold with Angular 21.2 (standalone components, zoneless change detection, signals, Vitest as the test runner). Record the reason here instead of working around the engine check.

## Consequences
- Upgrading is a deliberate task: move the machine to Node 24 LTS (or 22.22+), then run `ng update` to Angular 22.
- Node 25 is not an LTS release; production images and CI must use an even-numbered LTS Node.
- Node 25 ships a global `localStorage` that is unusable without a file path and shadows the browser one in tests; the theme tests install an in-memory Storage for that reason.
