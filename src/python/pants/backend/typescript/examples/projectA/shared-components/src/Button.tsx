import React from "react";
import type { Status } from "@pants-example/common-types";

export interface ButtonProps {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "primary" | "secondary" | "danger";
  status?: Status;
  type?: "button" | "submit" | "reset";
  "data-testid"?: string;
}

export function Button({
  children,
  onClick,
  disabled = false,
  variant = "primary",
  status,
  type = "button",
  "data-testid": testId,
}: ButtonProps) {
  const getVariantClass = () => {
    switch (variant) {
      case "primary":
        return "bg-blue-500 hover:bg-blue-600 text-white";
      case "secondary":
        return "bg-gray-500 hover:bg-gray-600 text-white";
      case "danger":
        return "bg-red-500 hover:bg-red-600 text-white";
      default:
        return "bg-blue-500 hover:bg-blue-600 text-white";
    }
  };

  const getStatusClass = () => {
    if (!status) return "";
    switch (status) {
      case "pending":
        return "opacity-50 cursor-wait";
      case "error":
        return "border-red-500";
      case "success":
        return "border-green-500";
      default:
        return "";
    }
  };

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || status === "pending"}
      data-testid={testId}
      className={`
        px-4 py-2 rounded font-medium transition-colors
        ${getVariantClass()}
        ${getStatusClass()}
        ${disabled ? "opacity-50 cursor-not-allowed" : ""}
      `.trim()}
    >
      {status === "pending" ? "Loading..." : children}
    </button>
  );
}
