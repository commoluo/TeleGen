#!/usr/bin/env node
"use strict";

const fs = require("fs/promises");
const path = require("path");

function requireOrExit(pkg) {
  try {
    return require(pkg);
  } catch (err) {
    console.error(`[ERROR] Missing dependency: ${pkg}`);
    console.error(
      "Install required packages: npm install @babel/core @babel/parser @babel/traverse @babel/generator @babel/types glob"
    );
    process.exit(1);
  }
}

// Required dependencies in the specification.
requireOrExit("@babel/core");

const parser = requireOrExit("@babel/parser");
const traverse = requireOrExit("@babel/traverse").default;
const generate = requireOrExit("@babel/generator").default;
const t = requireOrExit("@babel/types");

const globPkg = requireOrExit("glob");
const globSync = globPkg.globSync || globPkg.sync;

if (typeof globSync !== "function") {
  console.error("[ERROR] Could not resolve glob sync function.");
  process.exit(1);
}

const PARSER_OPTIONS = {
  sourceType: "module",
  plugins: ["jsx", "typescript"],
};

const IGNORE_PATTERNS = [
  "**/node_modules/**",
  "**/.git/**",
  "**/dist/**",
  "**/build/**",
  "**/coverage/**",
  "**/.next/**",
  "**/.turbo/**",
  "**/out/**",
  "**/.cache/**",
  "**/vendor/**",
  "**/venv/**",
  "**/__pycache__/**",
];

// Navigation-related state variable names — track these with useEffect monitors
const NAVIGATION_STATE_RE = /tab|page|view|route|active|screen|step|section|current|selected|mode/i;

function collectSourceFiles(workspaceRoot) {
  // Resolve symlinks so glob can traverse symlinked project directories.
  const resolvedRoot = require("fs").realpathSync(workspaceRoot);
  return globSync("**/*.{js,jsx,ts,tsx}", {
    cwd: resolvedRoot,
    absolute: true,
    nodir: true,
    follow: true,
    ignore: IGNORE_PATTERNS,
  });
}

function isConsoleLogCall(node) {
  return (
    t.isExpressionStatement(node) &&
    t.isCallExpression(node.expression) &&
    t.isMemberExpression(node.expression.callee) &&
    t.isIdentifier(node.expression.callee.object, { name: "console" }) &&
    t.isIdentifier(node.expression.callee.property, { name: "log" })
  );
}

function getFirstConsoleLogStringArg(node) {
  if (!isConsoleLogCall(node)) {
    return null;
  }

  const args = node.expression.arguments || [];
  if (args.length === 0) {
    return null;
  }

  if (t.isStringLiteral(args[0])) {
    return args[0].value;
  }

  return null;
}

function isTelemetryLog(node, kindKeyword) {
  const text = getFirstConsoleLogStringArg(node);
  return typeof text === "string" && text.includes("[Telemetry]") && text.includes(kindKeyword);
}

function hasTelemetryLogInBlock(blockNode, kindKeyword) {
  if (!t.isBlockStatement(blockNode)) {
    return false;
  }

  return blockNode.body.some((stmt) => isTelemetryLog(stmt, kindKeyword));
}

function ensureArrowFunctionBlock(fnNode) {
  if (!t.isArrowFunctionExpression(fnNode)) {
    return false;
  }

  if (t.isBlockStatement(fnNode.body)) {
    return false;
  }

  const originalBody = fnNode.body;
  fnNode.body = t.blockStatement([t.returnStatement(originalBody)]);
  return true;
}

function getFunctionBlock(fnNode) {
  if (t.isArrowFunctionExpression(fnNode)) {
    ensureArrowFunctionBlock(fnNode);
  }

  if (t.isFunctionExpression(fnNode) || t.isFunctionDeclaration(fnNode) || t.isArrowFunctionExpression(fnNode)) {
    return t.isBlockStatement(fnNode.body) ? fnNode.body : null;
  }

  return null;
}

function makeInteractionLogStatement(eventName, elementName, textContent) {
  const props = [
    t.objectProperty(t.identifier("event"), t.stringLiteral(eventName)),
    t.objectProperty(t.identifier("element"), t.stringLiteral(elementName)),
  ];
  if (textContent) {
    props.push(t.objectProperty(t.identifier("label"), t.stringLiteral(textContent)));
  }
  const payload = t.objectExpression(props);

  return t.expressionStatement(
    t.callExpression(
      t.memberExpression(t.identifier("console"), t.identifier("log")),
      [
        t.stringLiteral("[Telemetry] Interaction:"),
        makeSafeStringifyExpression(payload),
      ]
    )
  );
}

function getStaticJSXAttributeValue(valueNode) {
  if (!valueNode) {
    return null;
  }

  if (t.isStringLiteral(valueNode)) {
    return valueNode.value;
  }

  if (t.isJSXExpressionContainer(valueNode)) {
    const expr = valueNode.expression;
    if (t.isStringLiteral(expr)) {
      return expr.value;
    }
    if (t.isNumericLiteral(expr) || t.isBooleanLiteral(expr)) {
      return String(expr.value);
    }
    if (t.isTemplateLiteral(expr) && expr.expressions.length === 0 && expr.quasis.length > 0) {
      return expr.quasis[0].value.cooked || "";
    }
  }

  return null;
}

function jsxNameToString(nameNode) {
  if (t.isJSXIdentifier(nameNode)) {
    return nameNode.name;
  }

  if (t.isJSXMemberExpression(nameNode)) {
    return `${jsxNameToString(nameNode.object)}.${jsxNameToString(nameNode.property)}`;
  }

  if (t.isJSXNamespacedName(nameNode)) {
    return `${jsxNameToString(nameNode.namespace)}:${jsxNameToString(nameNode.name)}`;
  }

  return "unknown";
}

function resolveElementLabelFromJSXAttribute(attrPath) {
  const openingElement = attrPath.parentPath && attrPath.parentPath.node;
  if (!openingElement || !t.isJSXOpeningElement(openingElement)) {
    return "unknown";
  }

  let idValue = null;
  let classValue = null;

  for (const item of openingElement.attributes) {
    if (!t.isJSXAttribute(item) || !t.isJSXIdentifier(item.name)) {
      continue;
    }

    if (item.name.name === "id") {
      const v = getStaticJSXAttributeValue(item.value);
      if (v) {
        idValue = v;
      }
    }

    if (item.name.name === "className") {
      const v = getStaticJSXAttributeValue(item.value);
      if (v) {
        classValue = v;
      }
    }
  }

  if (idValue) {
    return `#${idValue}`;
  }

  if (classValue) {
    return `.${classValue}`;
  }

  return jsxNameToString(openingElement.name);
}

// Extract visible text content from JSX element children (e.g. button label, link text)
function extractJSXChildrenText(attrPath) {
  const openingPath = attrPath.parentPath;
  if (!openingPath) return null;
  const jsxElementPath = openingPath.parentPath;
  if (!jsxElementPath || !jsxElementPath.isJSXElement()) return null;

  const parts = [];
  for (const child of jsxElementPath.node.children || []) {
    if (t.isJSXText(child)) {
      const trimmed = child.value.trim();
      if (trimmed) parts.push(trimmed);
    }
  }
  return parts.length > 0 ? parts.join(" ").slice(0, 60) : null;
}

function injectInteractionIntoFunction(fnNode, eventName, elementName, textContent) {
  const block = getFunctionBlock(fnNode);
  if (!block) {
    return false;
  }

  if (hasTelemetryLogInBlock(block, "Interaction")) {
    return false;
  }

  block.body.unshift(makeInteractionLogStatement(eventName, elementName, textContent));
  return true;
}

function resolveFunctionNodeFromExpressionPath(exprPath) {
  if (!exprPath || !exprPath.node) {
    return null;
  }

  if (exprPath.isArrowFunctionExpression() || exprPath.isFunctionExpression()) {
    return exprPath.node;
  }

  if (exprPath.isIdentifier()) {
    const binding = exprPath.scope.getBinding(exprPath.node.name);
    if (!binding || !binding.path) {
      return null;
    }

    if (binding.path.isFunctionDeclaration()) {
      return binding.path.node;
    }

    if (binding.path.isVariableDeclarator()) {
      const init = binding.path.node.init;
      if (t.isArrowFunctionExpression(init) || t.isFunctionExpression(init)) {
        return init;
      }
    }
  }

  return null;
}

function isEventAttributePath(pathRef) {
  if (!pathRef || !pathRef.node) {
    return false;
  }

  const node = pathRef.node;
  return t.isJSXIdentifier(node.name) && /^on/.test(node.name.name);
}

// Check if an if-statement path lives inside an inline JSX event handler (onClick={() => { ... }})
function isInsideEventHandler(ifPath) {
  return !!ifPath.findParent((p) => p.isJSXAttribute() && isEventAttributePath(p));
}

function isFetchCall(node) {
  return t.isCallExpression(node) && t.isIdentifier(node.callee, { name: "fetch" });
}

function isAxiosCall(node) {
  if (!t.isCallExpression(node)) {
    return false;
  }

  if (t.isIdentifier(node.callee, { name: "axios" })) {
    return true;
  }

  if (t.isMemberExpression(node.callee) && t.isIdentifier(node.callee.object, { name: "axios" })) {
    return true;
  }

  return false;
}

function isRequestCall(node) {
  return isFetchCall(node) || isAxiosCall(node);
}

function makeSafeStringifyExpression(exprNode) {
  return t.callExpression(
    t.arrowFunctionExpression(
      [],
      t.blockStatement([
        t.tryStatement(
          t.blockStatement([
            t.returnStatement(
              t.callExpression(t.memberExpression(t.identifier("JSON"), t.identifier("stringify")), [exprNode])
            ),
          ]),
          t.catchClause(t.identifier("e"), t.blockStatement([t.returnStatement(t.stringLiteral("[Unserializable]"))]))
        ),
      ])
    ),
    []
  );
}

function makeNetworkRequestLogStatement(kind, urlExpr, payloadExpr, argsExpr) {
  const payload = t.objectExpression([
    t.objectProperty(t.identifier("client"), t.stringLiteral(kind)),
    t.objectProperty(t.identifier("url"), t.cloneNode(urlExpr, true)),
    t.objectProperty(t.identifier("payload"), t.cloneNode(payloadExpr, true)),
    t.objectProperty(t.identifier("args"), t.cloneNode(argsExpr, true)),
  ]);

  return t.expressionStatement(
    t.callExpression(
      t.memberExpression(t.identifier("console"), t.identifier("log")),
      [
        t.stringLiteral("[Telemetry] Network Request:"),
        makeSafeStringifyExpression(payload),
      ]
    )
  );
}

function getRequestArgsAsExpressions(callNode) {
  const args = Array.isArray(callNode.arguments) ? callNode.arguments : [];
  const clonedArgs = args.map((arg) => t.cloneNode(arg, true));
  const urlExpr = clonedArgs[0] || t.nullLiteral();
  const payloadExpr = clonedArgs[1] || t.nullLiteral();
  const argsExpr = t.arrayExpression(clonedArgs);
  return { urlExpr, payloadExpr, argsExpr };
}

function getStatementIndex(stmtPath) {
  const parentPath = stmtPath.parentPath;
  if (!parentPath || !parentPath.isBlockStatement()) {
    return -1;
  }

  const bodyPaths = parentPath.get("body");
  for (let i = 0; i < bodyPaths.length; i += 1) {
    if (bodyPaths[i].node === stmtPath.node) {
      return i;
    }
  }

  return -1;
}

function hasPreviousTelemetryRequestLog(stmtPath) {
  const parentPath = stmtPath.parentPath;
  if (!parentPath || !parentPath.isBlockStatement()) {
    return false;
  }

  const idx = getStatementIndex(stmtPath);
  if (idx <= 0) {
    return false;
  }

  const prevStmt = parentPath.node.body[idx - 1];
  return isTelemetryLog(prevStmt, "Network Request");
}

function injectNetworkRequestLog(callPath, kind) {
  const statementPath = callPath.getStatementParent();
  if (!statementPath) {
    return false;
  }

  if (!statementPath.parentPath || !statementPath.parentPath.isBlockStatement()) {
    return false;
  }

  if (hasPreviousTelemetryRequestLog(statementPath)) {
    return false;
  }

  const { urlExpr, payloadExpr, argsExpr } = getRequestArgsAsExpressions(callPath.node);
  const logStmt = makeNetworkRequestLogStatement(kind, urlExpr, payloadExpr, argsExpr);
  statementPath.insertBefore(logStmt);
  return true;
}

function isFunctionNode(node) {
  return (
    t.isFunctionExpression(node) ||
    t.isArrowFunctionExpression(node) ||
    t.isFunctionDeclaration(node)
  );
}

function functionContainsTelemetryResponseLog(fnNode) {
  if (!isFunctionNode(fnNode)) {
    return false;
  }

  const block = getFunctionBlock(fnNode);
  if (!block) {
    return false;
  }

  return hasTelemetryLogInBlock(block, "Network Response");
}

function isThenCallNode(node) {
  return (
    t.isCallExpression(node) &&
    t.isMemberExpression(node.callee) &&
    !node.callee.computed &&
    t.isIdentifier(node.callee.property, { name: "then" })
  );
}

function hasTelemetryResponseInCurrentThen(callNode) {
  const args = callNode.arguments || [];
  for (const arg of args) {
    if (functionContainsTelemetryResponseLog(arg)) {
      return true;
    }
  }
  return false;
}

function hasTelemetryResponseInChainedThen(callPath) {
  if (!callPath.parentPath || !callPath.parentPath.isMemberExpression()) {
    return false;
  }

  const member = callPath.parentPath.node;
  if (member.computed || !t.isIdentifier(member.property, { name: "then" })) {
    return false;
  }

  const parentCall = callPath.parentPath.parentPath;
  if (!parentCall || !parentCall.isCallExpression()) {
    return false;
  }

  return hasTelemetryResponseInCurrentThen(parentCall.node);
}

function makeNetworkResponseThenHandler() {
  const resId = t.identifier("res");
  const responsePayload = t.objectExpression([
    t.objectProperty(
      t.identifier("status"),
      t.conditionalExpression(
        t.logicalExpression(
          "&&",
          t.identifier("res"),
          t.binaryExpression(
            "!=",
            t.memberExpression(t.identifier("res"), t.identifier("status")),
            t.nullLiteral()
          )
        ),
        t.memberExpression(t.identifier("res"), t.identifier("status")),
        t.nullLiteral()
      )
    ),
  ]);

  return t.arrowFunctionExpression(
    [resId],
    t.blockStatement([
      t.expressionStatement(
        t.callExpression(
          t.memberExpression(t.identifier("console"), t.identifier("log")),
          [
            t.stringLiteral("[Telemetry] Network Response:"),
            makeSafeStringifyExpression(responsePayload),
          ]
        )
      ),
      t.returnStatement(t.identifier("res")),
    ])
  );
}

function appendResponseThenIfNeeded(callPath) {
  const callNode = callPath.node;
  if (!isThenCallNode(callNode)) {
    return false;
  }

  const originalTarget = callNode.callee.object;
  if (!t.isCallExpression(originalTarget) || !isRequestCall(originalTarget)) {
    return false;
  }

  if (hasTelemetryResponseInCurrentThen(callNode)) {
    return false;
  }

  if (hasTelemetryResponseInChainedThen(callPath)) {
    return false;
  }

  const replacement = t.callExpression(
    t.memberExpression(t.cloneNode(callNode, true), t.identifier("then")),
    [makeNetworkResponseThenHandler()]
  );

  callPath.replaceWith(replacement);
  callPath.skip();
  return true;
}

// --- Conditional Branch Tracking helpers ---

// Render condition AST node to compact source text (truncated)
function getConditionText(testNode) {
  try {
    const code = generate(testNode, { compact: true }).code;
    return code.length > 80 ? code.slice(0, 77) + "..." : code;
  } catch (e) {
    return "condition";
  }
}

// Check whether the if-condition references any navigation-related identifier
function conditionInvolvesNavigationState(node) {
  if (!node || typeof node !== "object") return false;
  if (t.isIdentifier(node) && NAVIGATION_STATE_RE.test(node.name)) return true;
  for (const key of Object.keys(node)) {
    if (key === "type" || key === "loc" || key === "start" || key === "end" || key === "extra") continue;
    const val = node[key];
    if (Array.isArray(val)) {
      if (val.some((v) => v && typeof v === "object" && conditionInvolvesNavigationState(v))) return true;
    } else if (val && typeof val === "object" && val.type) {
      if (conditionInvolvesNavigationState(val)) return true;
    }
  }
  return false;
}

function makeBranchLogStatement(conditionStr, branchName) {
  const payload = t.objectExpression([
    t.objectProperty(t.identifier("condition"), t.stringLiteral(conditionStr)),
    t.objectProperty(t.identifier("branch"), t.stringLiteral(branchName)),
  ]);

  return t.expressionStatement(
    t.callExpression(
      t.memberExpression(t.identifier("console"), t.identifier("log")),
      [
        t.stringLiteral("[Telemetry] Branch:"),
        makeSafeStringifyExpression(payload),
      ]
    )
  );
}

// Generate: useEffect(() => { console.log("[Telemetry] StateChange:", ...) }, [stateVar])
function makeStateChangeEffectStatement(stateVarName) {
  const payload = t.objectExpression([
    t.objectProperty(t.identifier("state"), t.stringLiteral(stateVarName)),
    t.objectProperty(t.identifier("value"), t.identifier(stateVarName)),
  ]);

  const logCall = t.expressionStatement(
    t.callExpression(
      t.memberExpression(t.identifier("console"), t.identifier("log")),
      [
        t.stringLiteral("[Telemetry] StateChange:"),
        makeSafeStringifyExpression(payload),
      ]
    )
  );

  return t.expressionStatement(
    t.callExpression(t.identifier("useEffect"), [
      t.arrowFunctionExpression([], t.blockStatement([logCall])),
      t.arrayExpression([t.identifier(stateVarName)]),
    ])
  );
}

// Ensure useEffect is in the React named imports (adds it if missing)
function ensureUseEffectImported(ast) {
  traverse(ast, {
    ImportDeclaration(importPath) {
      if (importPath.node.source.value !== "react") return;
      const specs = importPath.node.specifiers;
      const alreadyHas = specs.some(
        (s) =>
          t.isImportSpecifier(s) &&
          ((t.isIdentifier(s.imported) && s.imported.name === "useEffect") ||
            (t.isStringLiteral(s.imported) && s.imported.value === "useEffect"))
      );
      if (alreadyHas) return;
      const hasNamedImport = specs.some((s) => t.isImportSpecifier(s));
      if (hasNamedImport) {
        specs.push(
          t.importSpecifier(t.identifier("useEffect"), t.identifier("useEffect"))
        );
      }
    },
  });
}

function processAst(ast, counters) {
  let changed = false;
  const stateChangePending = [];
  const ifBranchPending = [];

  traverse(ast, {
    JSXAttribute(attrPath) {
      if (!isEventAttributePath(attrPath)) {
        return;
      }

      const eventName = attrPath.node.name.name;
      const valuePath = attrPath.get("value");

      if (!valuePath || !valuePath.isJSXExpressionContainer()) {
        return;
      }

      const exprPath = valuePath.get("expression");
      const fnNode = resolveFunctionNodeFromExpressionPath(exprPath);
      if (!fnNode) {
        return;
      }

      const elementName = resolveElementLabelFromJSXAttribute(attrPath);
      const textContent = extractJSXChildrenText(attrPath);
      const wasArrowExpr = t.isArrowFunctionExpression(fnNode) && !t.isBlockStatement(fnNode.body);
      const injected = injectInteractionIntoFunction(fnNode, eventName, elementName, textContent);

      if (wasArrowExpr && injected) {
        counters.arrowWrapped += 1;
      }

      if (injected) {
        changed = true;
        counters.interactionInjected += 1;
      }
    },

    CallExpression(callPath) {
      const callNode = callPath.node;

      if (isRequestCall(callNode)) {
        const kind = isFetchCall(callNode) ? "fetch" : "axios";
        const injected = injectNetworkRequestLog(callPath, kind);
        if (injected) {
          changed = true;
          counters.networkRequestInjected += 1;
        }
      }

      const responseInjected = appendResponseThenIfNeeded(callPath);
      if (responseInjected) {
        changed = true;
        counters.networkResponseInjected += 1;
      }
    },

    VariableDeclarator(varPath) {
      // Detect: const [stateVar, setter] = useState(...) where stateVar is navigation-related
      const { id, init } = varPath.node;
      if (!t.isArrayPattern(id) || !init || !t.isCallExpression(init)) return;
      if (!t.isIdentifier(init.callee, { name: "useState" })) return;

      const stateVarId = id.elements[0];
      if (!stateVarId || !t.isIdentifier(stateVarId)) return;
      const stateVarName = stateVarId.name;
      if (!NAVIGATION_STATE_RE.test(stateVarName)) return;

      const declPath = varPath.parentPath;
      if (!declPath || !declPath.parentPath || !declPath.parentPath.isBlockStatement()) return;

      const blockNode = declPath.parentPath.node;

      // Skip if a useEffect with this var in deps already exists in the same block
      const alreadyHas = blockNode.body.some((stmt) => {
        if (!t.isExpressionStatement(stmt) || !t.isCallExpression(stmt.expression)) return false;
        const call = stmt.expression;
        if (!t.isIdentifier(call.callee, { name: "useEffect" })) return false;
        const deps = call.arguments[1];
        if (!t.isArrayExpression(deps)) return false;
        return deps.elements.some((el) => t.isIdentifier(el, { name: stateVarName }));
      });
      if (alreadyHas) return;

      stateChangePending.push({ blockNode, afterNode: declPath.node, stateVarName });
      counters.stateChangeInjected += 1;
    },

    IfStatement(ifPath) {
      const test = ifPath.node.test;
      // Only track: inside inline event handler OR condition references navigation state
      if (!isInsideEventHandler(ifPath) && !conditionInvolvesNavigationState(test)) return;
      // Avoid re-processing if already instrumented
      const consequent = ifPath.node.consequent;
      const block = t.isBlockStatement(consequent) ? consequent : null;
      if (block && hasTelemetryLogInBlock(block, "Branch")) return;
      ifBranchPending.push({ ifNode: ifPath.node, condText: getConditionText(test) });
    },
  });

  // Apply useState monitors after traversal to avoid mutation-during-traversal issues
  for (const { blockNode, afterNode, stateVarName } of stateChangePending) {
    const idx = blockNode.body.indexOf(afterNode);
    if (idx !== -1) {
      blockNode.body.splice(idx + 1, 0, makeStateChangeEffectStatement(stateVarName));
      changed = true;
    }
  }

  if (counters.stateChangeInjected > 0) {
    ensureUseEffectImported(ast);
  }

  // Apply branch instrumentation after traversal
  for (const { ifNode, condText } of ifBranchPending) {
    // Instrument 'then' branch
    let thenBlock = ifNode.consequent;
    if (!t.isBlockStatement(thenBlock)) {
      thenBlock = t.blockStatement([thenBlock]);
      ifNode.consequent = thenBlock;
    }
    if (!hasTelemetryLogInBlock(thenBlock, "Branch")) {
      thenBlock.body.unshift(makeBranchLogStatement(condText, "then"));
      counters.branchInjected += 1;
      changed = true;
    }

    // Instrument 'else' branch — skip else-if chains (they'll be handled as separate IfStatements)
    const alt = ifNode.alternate;
    if (alt && !t.isIfStatement(alt)) {
      let elseBlock = alt;
      if (!t.isBlockStatement(alt)) {
        elseBlock = t.blockStatement([alt]);
        ifNode.alternate = elseBlock;
      }
      if (!hasTelemetryLogInBlock(elseBlock, "Branch")) {
        elseBlock.body.unshift(makeBranchLogStatement(condText, "else"));
        counters.branchInjected += 1;
        changed = true;
      }
    }
  }

  return changed;
}

async function processFile(filePath, workspaceRoot, stats) {
  const rel = path.relative(workspaceRoot, filePath);

  // CRITICAL: per-file error isolation. Any parse/traverse error must skip file.
  try {
    const sourceCode = await fs.readFile(filePath, "utf8");
    let ast;

    try {
      ast = parser.parse(sourceCode, PARSER_OPTIONS);
    } catch (err) {
      console.warn(`[WARN] Parse failed, skip file: ${rel}`);
      console.warn(`       ${String(err.message || err)}`);
      stats.skipped += 1;
      return null;
    }

    const counters = {
      interactionInjected: 0,
      networkRequestInjected: 0,
      networkResponseInjected: 0,
      arrowWrapped: 0,
      stateChangeInjected: 0,
      branchInjected: 0,
    };

    let changed;
    try {
      changed = processAst(ast, counters);
    } catch (err) {
      console.warn(`[WARN] Traverse failed, skip file: ${rel}`);
      console.warn(`       ${String(err.message || err)}`);
      stats.skipped += 1;
      return null;
    }

    if (!changed) {
      return null;
    }

    const output = generate(
      ast,
      {
        retainLines: true,
        comments: true,
      },
      sourceCode
    );

    stats.modified += 1;
    stats.interactionInjected += counters.interactionInjected;
    stats.networkRequestInjected += counters.networkRequestInjected;
    stats.networkResponseInjected += counters.networkResponseInjected;
    stats.arrowWrapped += counters.arrowWrapped;
    stats.stateChangeInjected += counters.stateChangeInjected;
    stats.branchInjected += counters.branchInjected;

    return {
      filePath,
      code: output.code,
    };
  } catch (err) {
    console.warn(`[WARN] File processing failed, skip file: ${rel}`);
    console.warn(`       ${String(err.message || err)}`);
    stats.skipped += 1;
    return null;
  }
}

async function main() {
  const workspaceRoot = path.resolve(process.argv[2] || process.cwd());
  const files = collectSourceFiles(workspaceRoot);

  const stats = {
    total: files.length,
    modified: 0,
    skipped: 0,
    interactionInjected: 0,
    networkRequestInjected: 0,
    networkResponseInjected: 0,
    arrowWrapped: 0,
    stateChangeInjected: 0,
    branchInjected: 0,
  };

  console.log(`[INFO] Workspace: ${workspaceRoot}`);
  console.log(`[INFO] Source files discovered: ${files.length}`);

  const pendingWrites = [];

  for (const filePath of files) {
    const result = await processFile(filePath, workspaceRoot, stats);
    if (result) {
      pendingWrites.push(result);
    }
  }

  for (const item of pendingWrites) {
    await fs.writeFile(item.filePath, item.code, "utf8");
  }

  console.log("[INFO] AST injection complete.");
  console.log(`[INFO] Files modified: ${stats.modified}`);
  console.log(`[INFO] Files skipped: ${stats.skipped}`);
  console.log(`[INFO] Interaction logs injected: ${stats.interactionInjected}`);
  console.log(`[INFO] Network request logs injected: ${stats.networkRequestInjected}`);
  console.log(`[INFO] Network response logs injected: ${stats.networkResponseInjected}`);
  console.log(`[INFO] Arrow functions block-wrapped: ${stats.arrowWrapped}`);
  console.log(`[INFO] State change monitors injected: ${stats.stateChangeInjected}`);
  console.log(`[INFO] Branch logs injected: ${stats.branchInjected}`);
}

main().catch((err) => {
  console.error("[FATAL] ast_injector failed:", err);
  process.exit(1);
});
