# Frontend instructions

Read the root `CLAUDE.md` first. This file adds frontend specifics.

## Stack

React 19, TypeScript (strict), Vite, Tailwind CSS v4, shadcn/ui-style components
vendored in `src/components/ui`, React Router, TanStack Query, React Hook Form
+ Zod, Lucide icons, Recharts, i18next (en + ar).

## Conventions

- API access only through `src/lib/api.ts` (adds credentials and the
  `X-CSRF-Token` header, normalises errors). Never put secrets in the frontend;
  everything in `import.meta.env` is public.
- Query keys live next to their hooks in `src/lib/queries.ts`.
- Every page handles loading, empty and error (with retry) states.
- Destructive actions use `ConfirmDialog`. Forms with edits warn on navigation
  (`useUnsavedChangesWarning`).
- All text through `t()`; add keys to both `src/i18n/en.json` and `src/i18n/ar.json`.
- Use logical spacing utilities (`ms-*`, `pe-*`, `start-*`, `text-start`) and
  `rtl:` variants where icons need mirroring. `document.dir` is set from the language.
- Demo/synthetic data must be visibly labelled (the `SyntheticBadge` component).
- No fabricated metrics, certification badges, customer logos or
  "compliance score". Checklist coverage, if shown, is defined as
  "The proportion of checklist items reviewed."
- Do not add UI for features that are not implemented in the backend.

## Palette

Navy (`--color-navy-*`), teal (`--color-teal-*`), slate and white, defined in
`src/index.css` under `@theme`. Light theme first.

## Commands

`pnpm dev`, `pnpm lint`, `pnpm typecheck`, `pnpm test` (Vitest + Testing Library),
`pnpm build`, `pnpm e2e` (Playwright; needs backend, worker and seeded demo data).
