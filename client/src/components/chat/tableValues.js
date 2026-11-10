export function displayValue(value) {
  if (value == null) return 'Undefined';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

export function sortResultRows(rows, sort) {
  if (!sort) return rows;
  return [...rows].sort((a, b) => {
    const left = a[sort.column], right = b[sort.column];
    // An undefined measure always follows defined values in either direction.
    if (left == null) return right == null ? 0 : 1;
    if (right == null) return -1;
    const comparison = typeof left === 'number' && typeof right === 'number'
      ? left - right
      : displayValue(left).localeCompare(displayValue(right), undefined, { numeric: true });
    return sort.direction * comparison;
  });
}
