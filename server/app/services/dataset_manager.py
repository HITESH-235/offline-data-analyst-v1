"""
DatasetManager: Handles loading and validating dataset files from the catalog.
"""

import os
import pandas as pd
import logging
from datetime import datetime
from typing import Optional, List
from app.core.config import settings
from app.core.constants import ALLOWED_EXTENSIONS
from app.models.dataset import DBDataset

logger = logging.getLogger(__name__)


class DatasetManager:
    @staticmethod
    def get_dataset(db, dataset_id: str) -> Optional[DBDataset]:
        """
        Returns a DBDataset object for the given dataset_id (filename or db_file::table_name).
        """
        parent_db = None
        table_name = None

        if "::" in dataset_id:
            parts = dataset_id.split("::", 1)
            parent_db = os.path.basename(parts[0])
            table_name = parts[1]
            db_filename = parent_db
        else:
            db_filename = os.path.basename(dataset_id)

        ext = db_filename.split(".")[-1].lower() if "." in db_filename else ""

        if ext not in ALLOWED_EXTENSIONS:
            logger.warning(f"Unsupported file format: .{ext}")
            return None

        filepath = os.path.join(settings.DATASETS_DIR, db_filename)

        if not os.path.exists(filepath):
            logger.warning(f"Dataset file not found: {filepath}")
            return None

        display_filename = table_name if table_name else db_filename

        return DBDataset(
            id=dataset_id,
            project_id="catalog",
            filename=display_filename,
            filepath=filepath,
            file_size_bytes=os.path.getsize(filepath),
            row_count=0,
            parent_db=parent_db,
            table_name=table_name,
            created_at=datetime.utcnow(),
        )

    @staticmethod
    def get_catalog_datasets() -> List[DBDataset]:
        """
        Scans datasets/ directory. Expands .db / .sqlite files into selectable table datasets.
        """
        datasets_dir = settings.DATASETS_DIR
        catalog = []

        if not os.path.exists(datasets_dir):
            logger.warning(f"Datasets directory '{datasets_dir}' does not exist.")
            return catalog

        for filename in sorted(os.listdir(datasets_dir)):
            ext = filename.split(".")[-1].lower() if "." in filename else ""
            if ext in ALLOWED_EXTENSIONS:
                filepath = os.path.join(datasets_dir, filename)
                if ext in ["db", "sqlite"]:
                    try:
                        import sqlite3
                        conn = sqlite3.connect(filepath)
                        cursor = conn.cursor()
                        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
                        tables = [r[0] for r in cursor.fetchall()]
                        for tbl in sorted(tables):
                            try:
                                count_res = cursor.execute(f"SELECT COUNT(*) FROM \"{tbl}\"").fetchone()
                                r_count = count_res[0] if count_res else 0
                            except Exception:
                                r_count = 0
                            catalog.append(DBDataset(
                                id=f"{filename}::{tbl}",
                                project_id="catalog",
                                filename=tbl,
                                filepath=filepath,
                                file_size_bytes=os.path.getsize(filepath),
                                row_count=r_count,
                                parent_db=filename,
                                table_name=tbl,
                                created_at=datetime.utcnow(),
                            ))
                        conn.close()
                    except Exception as err:
                        logger.error(f"Failed to scan tables in '{filename}': {err}")
                else:
                    catalog.append(DBDataset(
                        id=filename,
                        project_id="catalog",
                        filename=filename,
                        filepath=filepath,
                        file_size_bytes=os.path.getsize(filepath),
                        row_count=0,
                        parent_db=None,
                        table_name=None,
                        created_at=datetime.utcnow(),
                    ))

        return catalog

    @staticmethod
    def load_dataset_dataframe(db_dataset: DBDataset, nrows: Optional[int] = None) -> pd.DataFrame:
        """
        Loads dataset file or database table into a Pandas DataFrame.
        """
        filepath = db_dataset.filepath
        ext = filepath.split(".")[-1].lower()

        if "::" in db_dataset.id or db_dataset.table_name:
            table_name = db_dataset.table_name or db_dataset.id.split("::")[-1]
            import sqlite3
            conn = sqlite3.connect(filepath)
            query = f"SELECT * FROM \"{table_name}\""
            if nrows:
                query += f" LIMIT {nrows}"
            df = pd.read_sql_query(query, conn)
            conn.close()
            return df

        if ext == "csv":
            return pd.read_csv(filepath, nrows=nrows)
        elif ext == "xlsx":
            return pd.read_excel(filepath, nrows=nrows)
        elif ext == "json":
            df = pd.read_json(filepath)
            return df.head(nrows) if nrows else df
        elif ext in ["db", "sqlite"]:
            import sqlite3
            conn = sqlite3.connect(filepath)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
            tables = [r[0] for r in cursor.fetchall()]
            if not tables:
                conn.close()
                return pd.DataFrame()
            target_table = "Orders" if "Orders" in tables else tables[0]
            query = f"SELECT * FROM \"{target_table}\""
            if nrows:
                query += f" LIMIT {nrows}"
            df = pd.read_sql_query(query, conn)
            conn.close()
            return df

        raise ValueError(f"Unsupported format: .{ext}")

    @staticmethod
    def load_joined_dataframe(table_ids: List[str], join_keys: List[dict] = None, nrows: Optional[int] = None) -> pd.DataFrame:
        """
        Loads and auto-joins multiple database tables into a single analytical DataFrame.
        """
        import sqlite3
        from contextlib import closing
        from pathlib import Path

        datasets = [DatasetManager.get_dataset(None, table_id) for table_id in table_ids]
        if not datasets or any(dataset is None for dataset in datasets):
            raise ValueError("The selected dataset could not be found.")
        if len(datasets) == 1:
            return DatasetManager.load_dataset_dataframe(datasets[0], nrows=nrows)

        first = datasets[0]
        if any(dataset.filepath != first.filepath or not dataset.table_name for dataset in datasets):
            raise ValueError("Joined tables must belong to the same SQLite database.")

        def quote(identifier):
            return '"' + identifier.replace('"', '""') + '"'

        with closing(sqlite3.connect(Path(first.filepath).resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            from app.services.olist_import import APPLICATION_ID, validate_join_grain
            if conn.execute('PRAGMA application_id').fetchone()[0] == APPLICATION_ID:
                validate_join_grain([dataset.table_name for dataset in datasets])
            tables = {dataset.id: dataset.table_name for dataset in datasets}
            columns = {
                table_id: [row[1] for row in conn.execute(f"PRAGMA table_info({quote(table)})")]
                for table_id, table in tables.items()
            }
            relationships = {
                (table_id, row[3], f"{first.parent_db}::{row[2]}", row[4])
                for table_id, table in tables.items()
                for row in conn.execute(f"PRAGMA foreign_key_list({quote(table)})")
            }
            edges = []
            for key in join_keys or []:
                edge = (key["from_table"], key["from_column"], key["to_table"], key["to_column"])
                left, left_col, right, right_col = edge
                if left_col not in columns.get(left, []) or right_col not in columns.get(right, []):
                    raise ValueError("A join key references an unknown table or column.")
                if edge not in relationships and (right, right_col, left, left_col) not in relationships:
                    raise ValueError("A join key does not match a declared foreign key.")
                edges.append(edge)

            # Apply every relationship, including multiple predicates between two tables.
            joined = {first.id}
            joins = []
            while joined != set(tables):
                next_table = next((
                    right if left in joined else left
                    for left, _, right, _ in edges
                    if (left in joined) != (right in joined)
                ), None)
                if next_table is None:
                    raise ValueError("The selected tables have no complete foreign-key join path.")
                predicates = [
                    f"{quote(tables[left])}.{quote(left_col)} = {quote(tables[right])}.{quote(right_col)}"
                    for left, left_col, right, right_col in edges
                    if (left == next_table and right in joined) or (right == next_table and left in joined)
                ]
                joins.append(f"JOIN {quote(tables[next_table])} ON " + " AND ".join(predicates))
                joined.add(next_table)

            projection = []
            used_names = set()
            for table_id, table in tables.items():
                for column in columns[table_id]:
                    label = f"{table}.{column}" if column.lower() in used_names else column
                    projection.append(f"{quote(table)}.{quote(column)} AS {quote(label)}")
                    used_names.add(label.lower())
            sql = f"SELECT {', '.join(projection)} FROM {quote(first.table_name)} " + " ".join(joins)
            if nrows is not None:
                return pd.read_sql_query(sql + " LIMIT ?", conn, params=(nrows,))
            return pd.read_sql_query(sql, conn)

    @staticmethod
    def get_preview(db_dataset: DBDataset) -> dict:
        """
        Returns a preview of the dataset (first 100 rows).
        """
        df = DatasetManager.load_dataset_dataframe(db_dataset, nrows=100)
        return {
            "columns": list(df.columns),
            "data": df.fillna("").to_dict(orient="records"),
            "row_count": len(df),
        }
