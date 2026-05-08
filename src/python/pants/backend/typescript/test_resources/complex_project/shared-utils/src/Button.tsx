import React from "react";
import type { User } from "@test/common-types";

export interface ButtonProps {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "primary" | "secondary";
  user?: User;
}

export function Button({
  children,
  onClick,
  disabled = false,
  variant = "primary",
  user,
}: ButtonProps): React.JSX.Element {
  const className = `btn btn-${variant} ${disabled ? "disabled" : ""}`;

  return (
    <button
      className={className}
      onClick={onClick}
      disabled={disabled}
      title={user ? `Button for ${user.name}` : undefined}
    >
      {children}
    </button>
  );
}

export function UserCard({ user }: { user: User }): React.JSX.Element {
  return (
    <div className="user-card">
      <h3>{user.name}</h3>
      <p>{user.email}</p>
    </div>
  );
}
