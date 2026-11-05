import { useMemo, useState } from "react";

const LIMITS = [5, 10, 20];
const isCategory = (value) =>
  (typeof value === "string" && value.trim() !== "") || typeof value === "boolean";

export default function ResultChart({ result }) {
  const { columns, data } = result;
  const { categories, numbers, hasPair } = useMemo(() => {
    const categorical = new Set();
    const numeric = new Set();
    for (const row of data) {
      for (const column of columns) {
        if (Number.isFinite(row[column])) numeric.add(column);
        else if (isCategory(row[column])) categorical.add(column);
      }
    }
    const categories = columns.filter((column) => categorical.has(column) && !numeric.has(column));
    const numbers = columns.filter((column) => numeric.has(column) && !categorical.has(column));
    const hasPair = categories.length > 0 && numbers.length > 0 && data.some((row) =>
      categories.some((column) => isCategory(row[column])) &&
      numbers.some((column) => Number.isFinite(row[column]))
    );
    return { categories, numbers, hasPair };
  }, [columns, data]);

  const clearPair = categories.length === 1 && numbers.length === 1 && hasPair;
  const [category, setCategory] = useState(clearPair ? categories[0] : "");
  const [number, setNumber] = useState(clearPair ? numbers[0] : "");
  const [limit, setLimit] = useState(10);

  const ranking = useMemo(() => {
    if (!category || !number) return [];
    // Keep the best 20 rows, preserving source order for ties.
    const top = [];
    for (let index = 0; index < data.length; index++) {
      const label = data[index][category];
      const value = data[index][number];
      if (!isCategory(label) || !Number.isFinite(value)) continue;
      if (top.length === 20 && value <= top[19].value) continue;
      const position = top.findIndex((entry) => value > entry.value);
      top.splice(position === -1 ? top.length : position, 0, { label, value, index });
      if (top.length > 20) top.pop();
    }
    return top;
  }, [data, category, number]);

  if (!hasPair) {
    return <p>Chart unavailable. The result needs a text or boolean category and a finite numeric value on at least one shared row.</p>;
  }

  const bars = ranking.slice(0, limit);
  const min = Math.min(0, ...bars.map(({ value }) => value));
  const max = Math.max(0, ...bars.map(({ value }) => value));
  const scale = Math.max(Math.abs(min), max) || 1;
  const span = max / scale - min / scale || 1;
  const position = (value) => ((value / scale - min / scale) / span) * 100;
  const zero = position(0);

  return (
    <section className="result-chart" aria-label="Horizontal bar chart">
      <div className="result-chart-controls">
        <label>Category
          <select className="input-text" value={category} onChange={(event) => setCategory(event.target.value)}>
            <option value="">Choose a column</option>
            {categories.map((column) => <option key={column}>{column}</option>)}
          </select>
        </label>
        <label>Numeric value
          <select className="input-text" value={number} onChange={(event) => setNumber(event.target.value)}>
            <option value="">Choose a column</option>
            {numbers.map((column) => <option key={column}>{column}</option>)}
          </select>
        </label>
        <label>Show
          <select className="input-text" value={limit} onChange={(event) => setLimit(Number(event.target.value))}>
            {LIMITS.map((count) => <option key={count} value={count}>Top {count}</option>)}
          </select>
        </label>
      </div>
      {!category || !number ? <p>Choose a category and numeric column to rank the result rows.</p> :
        !bars.length ? <p>These columns have no rows with both a category and a finite numeric value.</p> : (
          <>
            <p className="result-chart-axis">Category axis: {category} · Value axis: {number}</p>
            <ol className="result-chart-bars">
              {bars.map(({ label, value, index }) => (
                <li key={index}>
                  <span className="result-chart-label">{String(label)}</span>
                  <span className="result-chart-track" aria-hidden="true">
                    <span className="result-chart-zero" style={{ left: `${zero}%` }} />
                    <span className="result-chart-fill" style={{
                      left: `${Math.min(zero, position(value))}%`,
                      width: `${Math.abs(position(value) - zero)}%`,
                    }} />
                  </span>
                  <span className="result-chart-value">{String(value)}</span>
                </li>
              ))}
            </ol>
          </>
        )}
    </section>
  );
}
