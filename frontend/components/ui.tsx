import type { ReactNode } from "react";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export function Card({
  children,
  className,
  as: Tag = "section",
}: {
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "article";
}) {
  return (
    <Tag className={cx("rounded-lg border bg-card", className)}>{children}</Tag>
  );
}

export function SectionHeader({
  title,
  count,
  hint,
  action,
}: {
  title: string;
  count?: number;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b px-5 py-3">
      <div className="flex items-baseline gap-2.5">
        <h2 className="text-[15px] font-semibold tracking-tight">{title}</h2>
        {count !== undefined && (
          <span className="tnum text-[13px] text-muted-foreground">{count}</span>
        )}
      </div>
      {hint && <p className="hidden text-[13px] text-muted-foreground sm:block">{hint}</p>}
      {action}
    </div>
  );
}

/** Neutral action. Never used for approve or reject — see DecisionButtons. */
export function Button({
  children,
  onClick,
  disabled,
  tone = "neutral",
  size = "md",
  type = "button",
  className,
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  tone?: "neutral" | "primary" | "quiet";
  size?: "sm" | "md";
  type?: "button" | "submit";
  className?: string;
  title?: string;
}) {
  const tones = {
    neutral: "border bg-background hover:bg-muted",
    primary: "border border-primary bg-primary text-primary-foreground hover:bg-primary-hover",
    quiet: "border border-transparent hover:bg-muted",
  };
  const sizes = { sm: "px-2.5 py-1 text-[13px]", md: "px-3.5 py-1.5 text-[14px]" };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={cx(
        "rounded-md font-medium transition-colors duration-150",
        tones[tone],
        sizes[size],
        className,
      )}
    >
      {children}
    </button>
  );
}

export function EmptyState({ glyph, title, body }: { glyph: string; title: string; body?: string }) {
  return (
    <div className="px-5 py-10 text-center">
      <div aria-hidden className="text-2xl text-muted-foreground/60">
        {glyph}
      </div>
      <p className="mt-2 text-[15px] font-medium">{title}</p>
      {body && <p className="mx-auto mt-1 max-w-sm text-[14px] text-muted-foreground">{body}</p>}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-deny-border bg-deny-surface px-4 py-3 text-[14px] text-deny-text">
      {message}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded bg-muted", className)} />;
}

/** A label/value pair, aligned so a column of them reads as a record. */
export function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-2 text-[14px] leading-normal">
      <dt className="w-28 shrink-0 text-muted-foreground">{label}</dt>
      <dd className="min-w-0 flex-1">{children}</dd>
    </div>
  );
}
