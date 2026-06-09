import type { ButtonHTMLAttributes, MouseEventHandler, ReactNode } from "react";
import { useId } from "react";
import {
  assertAuthenticityMetadata,
  shouldAssertInteractionContracts,
  type AuthenticityMetadata,
} from "./types";

export interface ActionButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "disabled"> {
  authenticity: AuthenticityMetadata;
  children: ReactNode;
  disabled?: boolean;
  disabledReason?: string;
  isLoading?: boolean;
  loadingLabel?: string;
  onClick?: MouseEventHandler<HTMLButtonElement>;
}

export function ActionButton({
  authenticity,
  children,
  disabled = false,
  disabledReason,
  isLoading = false,
  loadingLabel,
  onClick,
  type = "button",
  "aria-describedby": ariaDescribedBy,
  className = "",
  ...buttonProps
}: ActionButtonProps) {
  const reasonId = useId();
  const reason = disabledReason?.trim();
  const isUnavailable = disabled || isLoading;
  const state = isLoading ? "loading" : disabled ? "disabled" : "ready";
  const accessibleDescription = reason
    ? [ariaDescribedBy, reasonId].filter(Boolean).join(" ")
    : ariaDescribedBy;

  if (shouldAssertInteractionContracts()) {
    assertAuthenticityMetadata(authenticity);

    if (!isUnavailable && type !== "submit" && !onClick) {
      throw new Error(
        `ActionButton "${authenticity.actionId}" requires onClick when enabled and not a submit button.`,
      );
    }

    if (disabled && !reason) {
      throw new Error(
        `ActionButton "${authenticity.actionId}" is disabled but missing disabledReason.`,
      );
    }

    if (isLoading && !loadingLabel?.trim()) {
      throw new Error(
        `ActionButton "${authenticity.actionId}" is loading but missing loadingLabel.`,
      );
    }
  }

  const handleClick: MouseEventHandler<HTMLButtonElement> = (event) => {
    if (isUnavailable) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    onClick?.(event);
  };

  return (
    <>
      <button
        {...buttonProps}
        type={type}
        disabled={isUnavailable}
        aria-describedby={accessibleDescription || undefined}
        data-action-id={authenticity.actionId}
        data-action-kind={authenticity.kind}
        data-action-state={state}
        className={className}
        onClick={handleClick}
      >
        {isLoading ? loadingLabel : children}
      </button>
      {reason && (
        <span
          id={reasonId}
          className="action-disabled-reason"
          data-action-disabled-reason={authenticity.actionId}
        >
          {reason}
        </span>
      )}
    </>
  );
}
