# ADR 0005: Plain SCSS design tokens, no UI kit

Status: Accepted

## Context
The app needs a consistent look, light and dark themes, accessibility and small bundles. A UI kit adds weight and a dependency to track for a small set of screens.

## Decision
All colours, spacing, radii and type sizes are CSS custom properties defined once in `src/styles/_tokens.scss`. Dark mode follows the system setting unless the user chooses a theme; the choice is stored in one `ThemeService`, the only code that sets `data-theme` on the root element. Components own their SCSS and read tokens only. A UI kit, Tailwind or an icon font needs a new ADR.

## Consequences
- Components in `shared/ui` (button, skeleton, empty state, error state, field error) are written in-house and kept small.
- Every new screen must be checked in light and dark.
- Fonts are the system stack; nothing loads from a third-party origin.
- Known trade-off: a stored light preference on a dark system shows dark for a moment until the service runs, because the theme is applied by one service and not by an inline script. Accepted to keep a single writer.
- Control borders use a stronger token (`--cd-border-strong`, at least 3:1) so outlines meet non-text contrast.
