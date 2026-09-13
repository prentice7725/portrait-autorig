/* DOM-free bounded history for authored Rig Studio edits. */

function cloneJson(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value));
}

function equalJson(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function createAuthoringHistory(limit = 50) {
  return { limit: Math.max(1, Number(limit) || 50), undo: [], redo: [] };
}

export function pushAuthoringHistory(history, before, after) {
  if (equalJson(before, after)) return false;
  history.undo.push({ before: cloneJson(before), after: cloneJson(after) });
  while (history.undo.length > history.limit) history.undo.shift();
  history.redo.length = 0;
  return true;
}

export function undoAuthoringHistory(history, current) {
  const entry = history.undo.pop();
  if (!entry) return null;
  history.redo.push({ before: cloneJson(entry.before), after: cloneJson(current) });
  return cloneJson(entry.before);
}

export function redoAuthoringHistory(history, current) {
  const entry = history.redo.pop();
  if (!entry) return null;
  history.undo.push({ before: cloneJson(current), after: cloneJson(entry.after) });
  return cloneJson(entry.after);
}

