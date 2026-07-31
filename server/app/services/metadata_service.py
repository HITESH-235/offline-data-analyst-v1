import os
import json
import logging
import datetime
import duckdb
from typing import Optional, Any, Dict, List
from app.core.config import settings
from app.core.constants import ALLOWED_EXTENSIONS

logger = logging.getLogger(__name__)

class MetadataService:
    @staticmethod
    def _get_metadata_dir() -> str:
        meta_dir = os.path.join(settings.WORKSPACE_DIR, "catalog_metadata")
        os.makedirs(meta_dir, exist_ok=True)
        return meta_dir

    @staticmethod
    def _get_profile_path(dataset_id: str) -> str:
        safe_id = dataset_id.replace("::", "__").replace("/", "_").replace("\\", "_")
        return os.path.join(MetadataService._get_metadata_dir(), f"profile_{safe_id}.json")

    @staticmethod
    def _get_file_info(filepath: str) -> Dict[str, Any]:
        stat = os.stat(filepath)
        return {
            "size_bytes": stat.st_size,
            "mtime": stat.st_mtime
        }

    @staticmethod
    def generate_profile(filepath: str, dataset_id: str) -> Dict[str, Any]:
        """
        Generates statistical profile using DuckDB's native SUMMARIZE and SQL queries.
        """
        filename = os.path.basename(filepath)
        ext = filename.split(".")[-1].lower() if "." in filename else ""
        file_info = MetadataService._get_file_info(filepath)
        
        con = duckdb.connect(database=":memory:")

        parent_db = None
        table_name = None

        if "::" in dataset_id:
            parts = dataset_id.split("::", 1)
            parent_db = parts[0]
            table_name = parts[1]
            display_name = table_name
        else:
            display_name = filename
        
        # Form DuckDB read expression based on file extension
        if ext == "csv":
            read_expr = f"read_csv_auto('{filepath}')"
        elif ext == "json":
            read_expr = f"read_json_auto('{filepath}')"
        elif ext == "xlsx":
            read_expr = f"read_csv_auto('{filepath}')"
        elif ext in ["db", "sqlite"]:
            import sqlite3
            s_conn = sqlite3.connect(filepath)
            s_cur = s_conn.cursor()
            if not table_name:
                s_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
                s_tables = [r[0] for r in s_cur.fetchall()]
                target_table = "Orders" if "Orders" in s_tables else (s_tables[0] if s_tables else "")
            else:
                target_table = table_name
            s_conn.close()

            try:
                con.execute("INSTALL sqlite; LOAD sqlite;")
                con.execute(f"ATTACH '{filepath}' AS sqlite_db (TYPE SQLITE);")
                read_expr = f"sqlite_db.\"{target_table}\""
            except Exception:
                import pandas as pd
                s_conn = sqlite3.connect(filepath)
                df_temp = pd.read_sql_query(f"SELECT * FROM \"{target_table}\"", s_conn)
                s_conn.close()
                con.register("temp_sqlite_tbl", df_temp)
                read_expr = "temp_sqlite_tbl"
        else:
            raise ValueError(f"Unsupported format '.{ext}' for profiling.")

        # 1. Total row count
        count_res = con.execute(f"SELECT COUNT(*) FROM {read_expr}").fetchone()
        row_count = count_res[0] if count_res else 0

        # 2. Run SUMMARIZE to get column statistics
        summarize_query = f"SUMMARIZE SELECT * FROM {read_expr}"
        rows = con.execute(summarize_query).fetchall()
        col_names = [desc[0] for desc in con.description]
        
        columns = []
        dtypes_map = {}
        missing_values = {}
        unique_values = {}
        numeric_summary = {}
        categorical_summary = {}
        
        had_invalid_values = False

        for row in rows:
            row_dict = dict(zip(col_names, row))
            col = str(row_dict.get("column_name"))
            columns.append(col)
            
            col_type = str(row_dict.get("column_type", "")).upper()
            dtypes_map[col] = col_type
            
            # Missing count
            null_pct = row_dict.get("null_percentage")
            if null_pct is not None:
                try:
                    null_pct_float = float(null_pct)
                    missing_cnt = int(round((null_pct_float / 100.0) * row_count))
                except Exception:
                    missing_cnt = 0
            else:
                missing_cnt = 0
            missing_values[col] = missing_cnt

            # Unique count
            approx_unique = row_dict.get("approx_unique")
            uniques_cnt = int(approx_unique) if approx_unique is not None else 0
            unique_values[col] = uniques_cnt

            # Check if identifier-like (high cardinality: >90% unique)
            is_identifier_like = (row_count > 0) and ((uniques_cnt / float(row_count)) > 0.90)

            # Determine numeric vs categorical
            is_numeric_type = any(t in col_type for t in ["INT", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "BIGINT", "HUGEINT", "TINYINT", "SMALLINT", "REAL"])

            if is_numeric_type and not is_identifier_like:
                # Process numeric summary stats
                def parse_stat_val(val):
                    nonlocal had_invalid_values
                    if val is None:
                        return None
                    try:
                        f_val = float(val)
                        if f_val != f_val or f_val == float("inf") or f_val == float("-inf"): # NaN or Inf check
                            had_invalid_values = True
                            return None
                        return f_val
                    except (ValueError, TypeError):
                        had_invalid_values = True
                        return None

                mean_val = parse_stat_val(row_dict.get("avg"))
                std_val = parse_stat_val(row_dict.get("std"))
                min_val = parse_stat_val(row_dict.get("min"))
                max_val = parse_stat_val(row_dict.get("max"))
                q25_val = parse_stat_val(row_dict.get("q25"))
                q50_val = parse_stat_val(row_dict.get("q50"))
                q75_val = parse_stat_val(row_dict.get("q75"))

                numeric_summary[col] = {
                    "mean": mean_val,
                    "std": std_val,
                    "min": min_val,
                    "max": max_val,
                    "25%": q25_val,
                    "50%": q50_val,
                    "75%": q75_val,
                    "is_identifier_like": False
                }
            else:
                # Categorical or Identifier-like column
                top_val = "N/A"
                top_freq = 0
                top_frequent_values = []
                
                try:
                    # Targeted Top-N query capped at 15
                    cat_query = f"SELECT \"{col}\" AS val, COUNT(*) AS cnt FROM {read_expr} WHERE \"{col}\" IS NOT NULL GROUP BY \"{col}\" ORDER BY cnt DESC LIMIT 15"
                    top_rows = con.execute(cat_query).fetchall()
                    
                    if top_rows:
                        top_val = str(top_rows[0][0])
                        top_freq = int(top_rows[0][1])
                        top_frequent_values = [{"value": str(r[0]), "frequency": int(r[1])} for r in top_rows]
                except Exception as cat_err:
                    logger.warning(f"Could not compute top values for column '{col}': {cat_err}")

                categorical_summary[col] = {
                    "top": top_val,
                    "frequency": top_freq,
                    "top_frequent_values": top_frequent_values,
                    "unique_values_count": uniques_cnt,
                    "is_identifier_like": is_identifier_like
                }

        con.close()

        profile = {
            "dataset_id": dataset_id,
            "filename": filename,
            "filepath": filepath,
            "row_count": row_count,
            "columns": columns,
            "data_types": dtypes_map,
            "missing_values": missing_values,
            "unique_values": unique_values,
            "numeric_summary": numeric_summary,
            "categorical_summary": categorical_summary,
            "had_invalid_values": had_invalid_values,
            "file_info": file_info,
            "generated_at": datetime.datetime.utcnow().isoformat()
        }
        return profile

    @staticmethod
    def get_profile(dataset_id: str) -> Optional[Dict[str, Any]]:
        """
        Reads cached profile JSON for dataset_id. Returns None if missing.
        Does NOT trigger profiling.
        """
        profile_path = MetadataService._get_profile_path(dataset_id)
        if os.path.exists(profile_path):
            try:
                with open(profile_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to read cached profile '{profile_path}': {e}")
        return None

    @staticmethod
    def scan_and_profile_catalog() -> Dict[str, Any]:
        """
        Scans datasets catalog. Profiles missing or stale datasets/tables.
        """
        from app.services.dataset_manager import DatasetManager
        catalog_datasets = DatasetManager.get_catalog_datasets()
        
        newly_profiled = []
        skipped_unchanged = []
        re_profiled = []

        for db_dataset in catalog_datasets:
            dataset_id = db_dataset.id
            filepath = db_dataset.filepath
            
            profile_path = MetadataService._get_profile_path(dataset_id)
            current_file_info = MetadataService._get_file_info(filepath)
            
            # Check cache validity
            if os.path.exists(profile_path):
                try:
                    with open(profile_path, "r", encoding="utf-8") as f:
                        cached = json.load(f)
                    cached_file_info = cached.get("file_info", {})
                    
                    if (cached_file_info.get("size_bytes") == current_file_info["size_bytes"] and
                        cached_file_info.get("mtime") == current_file_info["mtime"]):
                        skipped_unchanged.append(dataset_id)
                        continue
                    else:
                        logger.info(f"Dataset '{dataset_id}' changed. Re-profiling...")
                        profile = MetadataService.generate_profile(filepath, dataset_id)
                        with open(profile_path, "w", encoding="utf-8") as f:
                            json.dump(profile, f, indent=4)
                        re_profiled.append(dataset_id)
                        continue
                except Exception as e:
                    logger.warning(f"Error reading cache for '{dataset_id}': {e}. Re-generating.")
            
            # Missing cache -> generate new profile
            logger.info(f"Generating profile for '{dataset_id}'...")
            profile = MetadataService.generate_profile(filepath, dataset_id)
            with open(profile_path, "w", encoding="utf-8") as f:
                json.dump(profile, f, indent=4)
            newly_profiled.append(dataset_id)

        logger.info(
            f"Catalog scan: {len(newly_profiled)} new, "
            f"{len(skipped_unchanged)} unchanged, "
            f"{len(re_profiled)} re-profiled"
        )

        return {
            "newly_profiled": newly_profiled,
            "skipped": skipped_unchanged,
            "re_profiled": re_profiled,
        }

    @staticmethod
    def list_available_datasets() -> List[str]:
        """
        Returns list of dataset_ids currently profiled and available in catalog.
        """
        meta_dir = MetadataService._get_metadata_dir()
        dataset_ids = []
        if os.path.exists(meta_dir):
            for meta_file in sorted(os.listdir(meta_dir)):
                if meta_file.startswith("profile_") and meta_file.endswith(".json"):
                    try:
                        with open(os.path.join(meta_dir, meta_file), "r", encoding="utf-8") as f:
                            data = json.load(f)
                            ds_id = data.get("dataset_id")
                            if ds_id:
                                dataset_ids.append(ds_id)
                    except Exception:
                        pass
        return dataset_ids
