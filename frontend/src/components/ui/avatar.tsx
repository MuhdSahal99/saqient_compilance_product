import { cn } from "@/lib/utils";

const TONES = [
  "bg-teal-100 text-teal-800",
  "bg-indigo-100 text-indigo-800",
  "bg-amber-100 text-amber-800",
  "bg-rose-100 text-rose-800",
  "bg-sky-100 text-sky-800",
  "bg-violet-100 text-violet-800",
];

export function initials(name: string | null | undefined): string {
  const parts = (name ?? "").replace(/\(.*?\)/g, "").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : "")).toUpperCase();
}

/** Initials avatar; colour is derived from the name so it stays stable. */
export function Avatar({ name, className }: { name: string | null | undefined; className?: string }) {
  const key = [...(name ?? "")].reduce((acc, c) => acc + c.charCodeAt(0), 0);
  return (
    <span
      className={cn(
        "inline-flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
        TONES[key % TONES.length],
        className,
      )}
      aria-hidden
    >
      {initials(name)}
    </span>
  );
}
