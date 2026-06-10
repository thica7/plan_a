import { isValidElement, type AnchorHTMLAttributes, type MouseEventHandler, type ReactNode } from "react";
import { useId } from "react";
import { Link, type To } from "react-router-dom";
import {
  assertAuthenticityMetadata,
  shouldAssertInteractionContracts,
  type AuthenticityMetadata,
} from "./types";

function stringifyDestination(destination: To | string | undefined): string {
  if (typeof destination === "string") {
    return destination;
  }
  if (!destination) {
    return "";
  }
  return `${destination.pathname ?? ""}${destination.search ?? ""}${destination.hash ?? ""}`;
}

function assertDestination(actionId: string, destination: string): void {
  const trimmed = destination.trim();
  if (!trimmed || trimmed === "#" || trimmed.toLowerCase().startsWith("javascript:")) {
    throw new Error(`ActionLink "${actionId}" has an empty or placeholder destination.`);
  }
}

function nodeHasText(node: ReactNode): boolean {
  if (typeof node === "string") {
    return node.trim().length > 0;
  }
  if (typeof node === "number") {
    return true;
  }
  if (Array.isArray(node)) {
    return node.some(nodeHasText);
  }
  if (isValidElement<{ children?: ReactNode }>(node)) {
    return nodeHasText(node.props.children);
  }
  return false;
}

export interface ActionLinkProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> {
  authenticity: AuthenticityMetadata;
  children: ReactNode;
  to?: To;
  href?: string;
  external?: boolean;
  disabled?: boolean;
  disabledReason?: string;
  onClick?: MouseEventHandler<HTMLAnchorElement | HTMLButtonElement>;
}

export function ActionLink({
  authenticity,
  children,
  to,
  href,
  external = false,
  disabled = false,
  disabledReason,
  onClick,
  target,
  rel,
  "aria-describedby": ariaDescribedBy,
  className = "",
  ...anchorProps
}: ActionLinkProps) {
  const reasonId = useId();
  const reason = disabledReason?.trim();
  const destination = stringifyDestination(to ?? href);

  if (shouldAssertInteractionContracts()) {
    assertAuthenticityMetadata(authenticity);

    if (!nodeHasText(children) && !anchorProps["aria-label"] && !anchorProps["aria-labelledby"]) {
      throw new Error(
        `ActionLink "${authenticity.actionId}" is icon-only but missing an accessible name.`,
      );
    }

    if (disabled && !reason) {
      throw new Error(`ActionLink "${authenticity.actionId}" is disabled but missing disabledReason.`);
    }

    if (!disabled && !to && !href && !onClick) {
      throw new Error(`ActionLink "${authenticity.actionId}" requires to, href, or onClick.`);
    }

    if (!disabled && (to || href)) {
      assertDestination(authenticity.actionId, destination);
    }
  }

  if (disabled) {
    return (
      <>
        <button
          type="button"
          disabled
          aria-describedby={
            reason ? [ariaDescribedBy, reasonId].filter(Boolean).join(" ") : ariaDescribedBy
          }
          data-action-id={authenticity.actionId}
          data-action-kind={authenticity.kind}
          data-action-state="disabled"
          className={className}
        >
          {children}
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

  const commonProps = {
    ...anchorProps,
    className,
    "data-action-id": authenticity.actionId,
    "data-action-kind": authenticity.kind,
    "data-action-state": "ready",
    onClick,
  };

  if (to) {
    return (
      <Link {...commonProps} to={to}>
        {children}
      </Link>
    );
  }

  if (href) {
    return (
      <a
        {...commonProps}
        href={href}
        target={external ? target ?? "_blank" : target}
        rel={external ? rel ?? "noreferrer" : rel}
      >
        {children}
      </a>
    );
  }

  return (
    <button
      type="button"
      data-action-id={authenticity.actionId}
      data-action-kind={authenticity.kind}
      data-action-state="ready"
      className={className}
      onClick={onClick as MouseEventHandler<HTMLButtonElement>}
    >
      {children}
    </button>
  );
}
