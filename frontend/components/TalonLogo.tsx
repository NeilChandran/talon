/** Talon brand — bold italic wordmark + yellow wing mark (inspired by Talon Guitars, adapted for outreach). */

type TalonLogoProps = {
  /** lockup = icon + wordmark (sidebar), mark = favicon square, wordmark = text only */
  variant?: "lockup" | "mark" | "wordmark";
  /** Height in px for mark / wordmark; lockup scales both */
  size?: number;
  className?: string;
};

export function TalonMark({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      className={className}
      aria-hidden
    >
      <rect width="32" height="32" rx="7" fill="#FFD400" />
      <g
        fill="none"
        stroke="#111"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M7 23 L13 11" />
        <path d="M13 11 L19 17" />
        <path d="M19 17 L25 9" />
      </g>
    </svg>
  );
}

/** Custom SVG wordmark: sharp T, tight italic alon, n-tail swoosh */
export function TalonWordmark({
  height = 20,
  className,
}: {
  height?: number;
  className?: string;
}) {
  const width = Math.round(height * (148 / 36));
  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 148 36"
      className={className}
      aria-label="Talon"
      role="img"
    >
      <g fill="currentColor">
        {/* T — wide top bar + talon point */}
        <path d="M0 4 H34 V9 H19 V10 H21.5 L12 35 L2.5 10 H6 V9 H0 V4 Z" />
        {/* a */}
        <path d="M37 16 C37 11 45 10 49 12 V15 C46 13 41 13 41 17 C41 21 47 22 49 19 V28 H44 V22 C41 24 37 22 37 16 Z" />
        {/* l */}
        <path d="M53 11 H58 V28 H53 V11 Z" />
        {/* o */}
        <path d="M62 19.5 C62 15 68 13 72 16 C76 19 76 25 72 27.5 C68 30 62 28 62 23.5 C62 20.5 64.5 18 68 18.5 V21.5 C65.5 21 64 22.5 64 24.5 C64 27 67.5 28 70 26.5 V28 H65 V26 C63 27.5 62 25 62 19.5 Z" />
        {/* n */}
        <path d="M78 11 H83 V18.5 C83 14 88 13 91 16.5 C94 13 99 14 99 18.5 V28 H94 V18 C94 15.5 91 15.5 89 17.5 V28 H84 V11 H78 Z" />
        {/* Swoosh — speed underline under alo */}
        <path d="M100 24 C115 29 130 28 145 22 L147 25 C128 32 106 33 92 27 C78 23 62 26 48 24 L50 21 C64 24 78 21 92 24 C104 27 118 25 100 24 Z" />
      </g>
    </svg>
  );
}

export default function TalonLogo({
  variant = "lockup",
  size = 28,
  className = "",
}: TalonLogoProps) {
  const wordH = Math.max(16, Math.round(size * 0.72));

  if (variant === "mark") {
    return <TalonMark size={size} className={className} />;
  }

  if (variant === "wordmark") {
    return <TalonWordmark height={wordH} className={className} />;
  }

  return (
    <span className={`talon-logo-lockup ${className}`.trim()}>
      <TalonMark size={size} />
      <TalonWordmark height={wordH} />
    </span>
  );
}
