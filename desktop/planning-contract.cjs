'use strict';
const schema = require('./planning-protocol.json');
function requireValid(ok) { if (!ok) throw new Error('invalid_contract'); }
function validate(value, rule) {
  if (rule.$ref) return validate(value, schema.$defs[rule.$ref.split('/').at(-1)]);
  if (rule.oneOf) {
    const matches = rule.oneOf.filter(branch => { try { validate(value, branch); return true; } catch { return false; } });
    requireValid(matches.length === 1); return value;
  }
  if (Object.hasOwn(rule, 'const')) requireValid(value === rule.const);
  if (rule.enum) requireValid(rule.enum.includes(value));
  if (rule.type === 'object') {
    requireValid(value !== null && typeof value === 'object' && !Array.isArray(value));
    const fields = rule.properties || {};
    requireValid((rule.required || []).every(key => Object.hasOwn(value, key)));
    requireValid(Object.keys(value).length >= (rule.minProperties || 0) && Object.keys(value).length <= (rule.maxProperties || 1000));
    for (const [key, item] of Object.entries(value)) {
      if (rule.propertyNames) validate(key, rule.propertyNames);
      if (Object.hasOwn(fields, key)) validate(item, fields[key]);
      else { requireValid(typeof rule.additionalProperties === 'object'); validate(item, rule.additionalProperties); }
    }
  } else if (rule.type === 'array') {
    requireValid(Array.isArray(value) && value.length >= (rule.minItems || 0) && value.length <= rule.maxItems);
    value.forEach(item => validate(item, rule.items));
  } else if (rule.type === 'string') {
    // Schema lengths use Unicode code points on both sides.
    requireValid(typeof value === 'string' && [...value].length >= (rule.minLength || 0) && [...value].length <= rule.maxLength);
    if (rule.pattern) requireValid(new RegExp(rule.pattern, 'u').test(value) && !value.endsWith('\n'));
  } else if (rule.type === 'integer') requireValid(Number.isSafeInteger(value) && value >= rule.minimum && value <= rule.maximum);
  return value;
}
function strictJSON(bytes) {
  const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  let position = 0;
  function space() { while (/[\x20\t\r\n]/.test(text[position] || 'x')) position++; }
  function string() {
    const match = /"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"/y;
    match.lastIndex = position; const result = match.exec(text); requireValid(result);
    position = match.lastIndex; return JSON.parse(result[0]);
  }
  function item(depth = 0) {
    requireValid(depth <= 32); space(); const token = text[position];
    if (token === '"') return string();
    if (token === '{' || token === '[') {
      const object = token === '{', result = object ? Object.create(null) : [];
      const end = object ? '}' : ']'; position++; space();
      if (text[position] === end) { position++; return result; }
      while (true) {
        space(); let key;
        if (object) { key = string(); requireValid(!Object.hasOwn(result, key)); space(); requireValid(text[position++] === ':'); }
        const child = item(depth + 1); if (object) result[key] = child; else result.push(child);
        space(); const next = text[position++]; if (next === end) return result;
        requireValid(next === ',');
      }
    }
    for (const [literal, value] of [['true', true], ['false', false], ['null', null]]) {
      if (text.startsWith(literal, position)) { position += literal.length; return value; }
    }
    const number = /-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/y;
    number.lastIndex = position; const match = number.exec(text); requireValid(match);
    position = number.lastIndex; const value = Number(match[0]); requireValid(Number.isFinite(value)); return value;
  }
  const result = item(); space(); requireValid(position === text.length); return result;
}
function source(value) {
  validate(value, schema.$defs.source);
  const reserved = /^(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9]|LPT[1-9])(?:\.|$)/i;
  requireValid(value.path.split('/').length <= 16 && value.repository.split('/').every(p => p !== '.' && p !== '..' && !p.endsWith('.git')));
  for (const part of value.path.split('/')) requireValid(/^[A-Za-z0-9_.-]{1,240}$/.test(part) && !['.', '..', '.git'].includes(part.toLowerCase()) && !part.endsWith('.') && !reserved.test(part));
  return value;
}
function response(value, request) {
  validate(value, schema.$defs.response);
  requireValid(value.requestId === request.requestId);
  const allowed = {'planning.importPublicPlan':['imported','already_present'], 'planning.listImports':['listed'], 'planning.getImport':['loaded']};
  requireValid(value.outcome === 'refused' || allowed[request.operation].includes(value.outcome));
  if (value.snapshot) {
    source({repository:value.snapshot.source.repository,commit_sha:value.snapshot.source.commit_sha,path:value.snapshot.source.path});
    if (request.source) for (const key of Object.keys(request.source)) requireValid(value.snapshot.source[key] === request.source[key]);
    if (request.id) requireValid(value.snapshot.id === request.id);
    const seen = new Set();
    for (const milestone of value.snapshot.milestones) {
      requireValid(!seen.has(milestone.id) && milestone.dependencies.every(id => seen.has(id)) && new Set(milestone.dependencies).size === milestone.dependencies.length);
      seen.add(milestone.id);
    }
  }
  return value;
}
module.exports = {schema, validate, strictJSON, source, response};
