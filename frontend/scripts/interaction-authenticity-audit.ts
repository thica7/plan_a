import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

type Severity = "error" | "warning";

interface Finding {
  severity: Severity;
  file: string;
  line: number;
  column: number;
  rule: string;
  message: string;
}

interface AllowlistEntry {
  file: string;
  owner: string;
  reason: string;
  expires: string;
}

interface AuditResult {
  findings: Finding[];
  errorCount: number;
  warningCount: number;
  scannedFiles: number;
}

interface AuditOptions {
  frontendRoot?: string;
  allowlist?: AllowlistEntry[];
}

const allowedActionKinds = new Set([
  "primitive",
  "route",
  "local",
  "mutation",
  "submit",
  "disabled",
  "display",
  "external",
  "copy",
  "download",
  "toggle",
]);

const ignoredDirectories = new Set(["dist", "node_modules", "coverage"]);
const ignoredFileSuffixes = [".test.tsx", ".test.ts", ".d.ts"];

function normalizePath(value: string): string {
  return value.replace(/\\/g, "/");
}

function isExpired(expires: string): boolean {
  return Number.isNaN(Date.parse(expires)) || new Date(expires) < new Date();
}

function getLineAndColumn(sourceFile: ts.SourceFile, position: number) {
  const point = sourceFile.getLineAndCharacterOfPosition(position);
  return { line: point.line + 1, column: point.character + 1 };
}

function attrName(attr: ts.JsxAttributeLike): string | null {
  return ts.isJsxAttribute(attr) && ts.isIdentifier(attr.name) ? attr.name.text : null;
}

function getAttribute(node: ts.JsxOpeningLikeElement, name: string): ts.JsxAttribute | undefined {
  return node.attributes.properties.find(
    (attr): attr is ts.JsxAttribute => attrName(attr) === name,
  );
}

function hasAttribute(node: ts.JsxOpeningLikeElement, name: string): boolean {
  return Boolean(getAttribute(node, name));
}

function literalAttribute(node: ts.JsxOpeningLikeElement, name: string): string | null {
  const attr = getAttribute(node, name);
  if (!attr?.initializer) {
    return null;
  }
  if (ts.isStringLiteral(attr.initializer)) {
    return attr.initializer.text;
  }
  if (ts.isJsxExpression(attr.initializer)) {
    const expression = attr.initializer.expression;
    if (expression && ts.isStringLiteralLike(expression)) {
      return expression.text;
    }
  }
  return null;
}

function expressionAttribute(node: ts.JsxOpeningLikeElement, name: string): ts.Expression | null {
  const attr = getAttribute(node, name);
  if (!attr?.initializer || !ts.isJsxExpression(attr.initializer)) {
    return null;
  }
  return attr.initializer.expression ?? null;
}

function tagName(node: ts.JsxOpeningLikeElement): string {
  return node.tagName.getText();
}

function isKnownPrimitive(node: ts.JsxOpeningLikeElement): boolean {
  const name = tagName(node);
  return name === "ActionButton" || name === "ActionLink";
}

function isLinkTag(name: string): boolean {
  return name === "a" || name === "Link" || name === "NavLink";
}

function isNoopHandler(expression: ts.Expression): boolean {
  if (ts.isIdentifier(expression)) {
    return ["noop", "noOp", "NOOP"].includes(expression.text);
  }
  if (ts.isArrowFunction(expression) || ts.isFunctionExpression(expression)) {
    const body = expression.body;
    if (ts.isBlock(body)) {
      const statements = body.statements;
      if (statements.length === 0) {
        return true;
      }
      if (statements.length === 1) {
        const statement = statements[0];
        if (ts.isReturnStatement(statement) && !statement.expression) {
          return true;
        }
        if (ts.isExpressionStatement(statement)) {
          const text = statement.expression.getText();
          return text === "undefined" || text.startsWith("console.log(") || text.startsWith("alert(");
        }
      }
    }
    const text = body.getText();
    return text === "undefined" || text === "void 0" || text.startsWith("console.log(") || text.startsWith("alert(");
  }
  const text = expression.getText();
  return text.startsWith("console.log(") || text.startsWith("alert(");
}

function validAuditKind(node: ts.JsxOpeningLikeElement): boolean {
  const auditKind = literalAttribute(node, "data-action-audit") ?? literalAttribute(node, "data-action-kind");
  return Boolean(auditKind && allowedActionKinds.has(auditKind));
}

function hasActionContract(node: ts.JsxOpeningLikeElement): boolean {
  return isKnownPrimitive(node) || (hasAttribute(node, "data-action-id") && validAuditKind(node));
}

function hasAccessibleName(node: ts.JsxOpeningLikeElement): boolean {
  return hasAttribute(node, "aria-label") || hasAttribute(node, "aria-labelledby") || hasAttribute(node, "title");
}

function isAllowlisted(file: string, allowlist: AllowlistEntry[]): boolean {
  return allowlist.some((entry) => normalizePath(entry.file) === normalizePath(file) && !isExpired(entry.expires));
}

function pushFinding(
  findings: Finding[],
  sourceFile: ts.SourceFile,
  file: string,
  node: ts.Node,
  rule: string,
  message: string,
  severity: Severity = "error",
): void {
  const { line, column } = getLineAndColumn(sourceFile, node.getStart(sourceFile));
  findings.push({ severity, file, line, column, rule, message });
}

export function auditTsxSource(
  sourceText: string,
  file = "fixture.tsx",
  options: AuditOptions = {},
): AuditResult {
  const allowlist = options.allowlist ?? [];
  const sourceFile = ts.createSourceFile(file, sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const findings: Finding[] = [];
  const fileIsAllowlisted = isAllowlisted(file, allowlist);

  function visit(node: ts.Node): void {
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const name = tagName(node);
      const isNativeButton = name === "button";
      const isNativeOrRouterLink = isLinkTag(name);
      const contractPresent = hasActionContract(node);
      const clickHandler = expressionAttribute(node, "onClick");

      if (isNativeButton && !contractPresent && !fileIsAllowlisted) {
        pushFinding(
          findings,
          sourceFile,
          file,
          node,
          "raw-button-contract",
          "Raw button must use ActionButton or include data-action-id plus data-action-audit.",
        );
      }

      if (isNativeButton && !hasAttribute(node, "type") && !fileIsAllowlisted) {
        pushFinding(findings, sourceFile, file, node, "button-type", "Raw button must declare type.");
      }

      if (isNativeButton && hasAttribute(node, "disabled") && !hasAttribute(node, "disabledReason") && !fileIsAllowlisted) {
        pushFinding(
          findings,
          sourceFile,
          file,
          node,
          "disabled-reason",
          "Disabled button must expose an explicit disabled reason contract.",
        );
      }

      if (clickHandler && isNoopHandler(clickHandler)) {
        pushFinding(findings, sourceFile, file, node, "noop-handler", "Click handler is empty or placeholder-only.");
      }

      if (isNativeButton && !hasAccessibleName(node) && node.getText(sourceFile).match(/<button[^>]*>\s*<[^>]+\/>\s*<\/button>/s)) {
        pushFinding(findings, sourceFile, file, node, "icon-only-name", "Icon-only button needs an accessible name.");
      }

      if (isNativeOrRouterLink) {
        const destination = literalAttribute(node, name === "a" ? "href" : "to");
        if (destination !== null) {
          const trimmed = destination.trim().toLowerCase();
          if (!trimmed || trimmed === "#" || trimmed.startsWith("javascript:")) {
            pushFinding(findings, sourceFile, file, node, "fake-link", "Link destination is empty or placeholder.");
          }
        }
      }

      if (literalAttribute(node, "role") === "button") {
        if (!hasAttribute(node, "tabIndex") || !hasAttribute(node, "onKeyDown")) {
          pushFinding(
            findings,
            sourceFile,
            file,
            node,
            "role-button-keyboard",
            "role=button requires tabIndex and keyboard activation.",
          );
        }
      }

      const auditKind = literalAttribute(node, "data-action-audit");
      if (auditKind && !allowedActionKinds.has(auditKind)) {
        pushFinding(findings, sourceFile, file, node, "unknown-audit-kind", `Unknown data-action-audit value "${auditKind}".`);
      }

      if (fileIsAllowlisted && (isNativeButton || isNativeOrRouterLink) && !contractPresent) {
        pushFinding(
          findings,
          sourceFile,
          file,
          node,
          "allowlisted-native-control",
          "Native control is covered by a temporary allowlist entry.",
          "warning",
        );
      }
    }

    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  return {
    findings,
    errorCount: findings.filter((finding) => finding.severity === "error").length,
    warningCount: findings.filter((finding) => finding.severity === "warning").length,
    scannedFiles: 1,
  };
}

function listTsxFiles(root: string): string[] {
  const files: string[] = [];

  function walk(dir: string): void {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        if (!ignoredDirectories.has(entry.name)) {
          walk(path.join(dir, entry.name));
        }
        continue;
      }

      if (!entry.name.endsWith(".tsx")) {
        continue;
      }

      const fullPath = path.join(dir, entry.name);
      if (!ignoredFileSuffixes.some((suffix) => entry.name.endsWith(suffix))) {
        files.push(fullPath);
      }
    }
  }

  walk(root);
  return files;
}

function loadAllowlist(frontendRoot: string): AllowlistEntry[] {
  const allowlistPath = path.join(frontendRoot, "scripts", "interaction-authenticity-allowlist.json");
  const parsed = JSON.parse(fs.readFileSync(allowlistPath, "utf8")) as { entries?: AllowlistEntry[] };
  const entries = parsed.entries ?? [];
  const expired = entries.filter((entry) => isExpired(entry.expires));
  if (expired.length > 0) {
    const labels = expired.map((entry) => `${entry.file} (${entry.expires})`).join(", ");
    throw new Error(`Interaction allowlist contains expired entries: ${labels}`);
  }
  return entries;
}

export function auditProject(frontendRoot: string): AuditResult {
  const srcRoot = path.join(frontendRoot, "src");
  const allowlist = loadAllowlist(frontendRoot);
  const findings: Finding[] = [];
  let scannedFiles = 0;

  for (const fullPath of listTsxFiles(srcRoot)) {
    const relativeFile = normalizePath(path.relative(frontendRoot, fullPath));
    if (relativeFile.startsWith("src/components/interaction/")) {
      continue;
    }
    const source = fs.readFileSync(fullPath, "utf8");
    const result = auditTsxSource(source, relativeFile, { frontendRoot, allowlist });
    findings.push(...result.findings);
    scannedFiles += 1;
  }

  return {
    findings,
    errorCount: findings.filter((finding) => finding.severity === "error").length,
    warningCount: findings.filter((finding) => finding.severity === "warning").length,
    scannedFiles,
  };
}

function printResult(result: AuditResult): void {
  for (const finding of result.findings) {
    const prefix = finding.severity === "error" ? "ERROR" : "WARN";
    console.log(`${prefix} ${finding.file}:${finding.line}:${finding.column} ${finding.rule} - ${finding.message}`);
  }
  console.log(
    `Interaction audit scanned ${result.scannedFiles} files: ${result.errorCount} errors, ${result.warningCount} warnings.`,
  );
}

const isDirectRun = process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]);

if (isDirectRun) {
  const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  try {
    const result = auditProject(frontendRoot);
    printResult(result);
    process.exit(result.errorCount > 0 ? 1 : 0);
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  }
}
