import React from "react";

export interface ButtonProps {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "primary" | "secondary";
}

export function Button({
  children,
  onClick,
  disabled = false,
  variant = "primary",
}: ButtonProps): React.JSX.Element {
  const className = `btn btn-${variant} ${disabled ? "disabled" : ""}`;

  return (
    <button className={className} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  );
}
