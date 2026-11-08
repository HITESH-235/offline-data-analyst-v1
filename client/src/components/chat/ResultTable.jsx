import { useMemo, useState } from "react";

const PAGE_SIZE = 10;

function displayValue(value) {
  if (value == null) return "";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function compareValues(left, right) {
  if (typeof left === "number" && typeof right === "number") return left - right;
  return displayValue(left).localeCompare(displayValue(right), undefined, { numeric: true });
}

export default function ResultTable({ result }) {
  const [sort, setSort] = useState(null);
  const [page, setPage] = useState(0);
  const columns = result?.columns;
  const rows = result?.data;

  const sortedRows = useMemo(() => sort
    ? [...rows].sort((a, b) => sort.direction * compareValues(a[sort.column], b[sort.column]))
    : rows, [rows, sort]);

  if (!Array.isArray(columns) || !columns.length || !Array.isArray(rows)) return null;

  const numericColumns = columns.filter((column) => rows.some((row) => typeof row[column] === "number"));
  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const start = currentPage * PAGE_SIZE;

  function sortBy(column) {
    setSort((previous) => ({
      column,
      direction: previous?.column === column ? -previous.direction : 1,
    }));
    setPage(0);
  }

  return (
    <section className="chat-result" aria-label="Computed result">
      <div className="table-container" tabIndex={0} role="region" aria-label="Result table">
        <table className="data-table">
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column} scope="col" className={numericColumns.includes(column) ? "numeric" : undefined} aria-sort={sort?.column === column
                  ? (sort.direction === 1 ? "ascending" : "descending")
                  : undefined}>
                  <button type="button" className="btn btn-secondary" onClick={() => sortBy(column)}>
                    {column}{result.units?.[column] && !column.includes(result.units[column]) ? ` (${result.units[column]})` : ''}{sort?.column === column && (sort.direction === 1 ? " ↑" : " ↓")}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedRows.slice(start, start + PAGE_SIZE).map((row, index) => (
              <tr key={start + index}>
                {columns.map((column) => {
                  const raw = row[column];
                  const value = result.analysis_kind === 'correlation' && typeof raw === 'number' ? raw.toFixed(4) : result.units?.[column] === 'BRL' && typeof raw === 'number' ? raw.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}) : displayValue(raw);
                  return <td key={column} className={numericColumns.includes(column) ? "numeric" : undefined} title={displayValue(raw)}>{value}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="chat-result-footer">
        <span>{rows.length ? `Rows ${start + 1}–${Math.min(start + PAGE_SIZE, rows.length)} of ${rows.length}` : "No rows returned"}</span>
        {pageCount > 1 && (
          <div>
            <button type="button" className="btn btn-secondary" disabled={!currentPage} onClick={() => setPage(currentPage - 1)}>Previous</button>
            <button type="button" className="btn btn-secondary" disabled={currentPage === pageCount - 1} onClick={() => setPage(currentPage + 1)}>Next</button>
          </div>
        )}
      </div>
    </section>
  );
}
