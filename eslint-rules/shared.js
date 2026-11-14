export function normalizeFilename(filename) {
  return String(filename || "").replaceAll("\\", "/");
}

export function getTypeArguments(node) {
  if (!node || typeof node !== "object") {
    return [];
  }
  const container = node.typeArguments ?? node.typeParameters ?? null;
  if (!container) {
    return [];
  }
  if (Array.isArray(container)) {
    return container;
  }
  return Array.isArray(container.params) ? container.params : [];
}

export function getTypeName(typeNode) {
  if (!typeNode) {
    return "";
  }

  switch (typeNode.type) {
    case "Identifier":
      return typeNode.name;
    case "TSQualifiedName":
      return `${getTypeName(typeNode.left)}.${getTypeName(typeNode.right)}`;
    case "TSTypeReference":
      return getTypeName(typeNode.typeName);
    default:
      return "";
  }
}

export function unwrapExpression(node) {
  let current = node;
  while (current?.type === "ChainExpression" || current?.type === "TSAsExpression") {
    current = current.expression;
  }
  if (current?.type === "AwaitExpression") {
    return unwrapExpression(current.argument);
  }
  return current;
}

export function isResponseMethodCall(node, methodName) {
  const expression = unwrapExpression(node);
  if (expression?.type !== "CallExpression") {
    return false;
  }
  const callee = expression.callee;
  if (callee?.type !== "MemberExpression") {
    return false;
  }
  return callee.property?.type === "Identifier" && callee.property.name === methodName;
}

export function isJsonParseCall(node) {
  if (node?.type !== "CallExpression") {
    return false;
  }
  const callee = node.callee;
  return (
    callee?.type === "MemberExpression" &&
    callee.object?.type === "Identifier" &&
    callee.object.name === "JSON" &&
    callee.property?.type === "Identifier" &&
    callee.property.name === "parse"
  );
}

export function isPromptCall(node) {
  if (node?.type !== "CallExpression") {
    return false;
  }

  if (node.callee?.type === "Identifier" && node.callee.name === "prompt") {
    return true;
  }

  return (
    node.callee?.type === "MemberExpression" &&
    node.callee.object?.type === "Identifier" &&
    node.callee.object.name === "window" &&
    node.callee.property?.type === "Identifier" &&
    node.callee.property.name === "prompt"
  );
}

export function isUnsafeBoundaryType(typeNode) {
  if (!typeNode) {
    return false;
  }

  switch (typeNode.type) {
    case "TSAnyKeyword":
    case "TSUnknownKeyword":
      return true;
    case "TSParenthesizedType":
    case "TSOptionalType":
    case "TSRestType":
    case "TSTypeOperator":
      return isUnsafeBoundaryType(typeNode.typeAnnotation);
    case "TSArrayType":
      return isUnsafeBoundaryType(typeNode.elementType);
    case "TSUnionType":
    case "TSIntersectionType":
      return typeNode.types.some(isUnsafeBoundaryType);
    case "TSTypeReference": {
      const typeName = getTypeName(typeNode.typeName);
      const params = getTypeArguments(typeNode);
      if (typeName === "Record" && params.length === 2) {
        return isUnsafeBoundaryType(params[1]);
      }
      return params.some(isUnsafeBoundaryType);
    }
    case "TSTypeLiteral":
      return typeNode.members.some((member) => {
        if (member.type === "TSPropertySignature") {
          return isUnsafeBoundaryType(member.typeAnnotation?.typeAnnotation);
        }
        if (member.type === "TSIndexSignature") {
          return isUnsafeBoundaryType(member.typeAnnotation?.typeAnnotation);
        }
        return false;
      });
    default:
      return false;
  }
}
