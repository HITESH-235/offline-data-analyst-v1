import json
import logging
from typing import Dict, Any, List
from app.llm.client import OllamaClient
from app.llm.prompts import TABLE_SELECTOR_SYSTEM_PROMPT
from app.services.metadata_service import MetadataService

logger = logging.getLogger(__name__)

class TableSelector:
    @staticmethod
    def select_tables(user_query: str, active_dataset_id: str) -> Dict[str, Any]:
        """
        Inspects user query, active dataset, and compact catalog index to select
        the minimal set of dataset_ids and join keys needed to answer the question.
        """
        catalog_index = MetadataService.get_catalog_index()
        tables_meta = catalog_index.get("tables", {})
        relationships = catalog_index.get("relationships", [])

        # Build compact catalog description for prompt
        compact_summary_lines = []
        for tbl_id, tbl_info in tables_meta.items():
            cols_str = ", ".join(tbl_info.get("columns", []))
            r_cnt = tbl_info.get("row_count", 0)
            compact_summary_lines.append(f"- Table ID: '{tbl_id}' ({r_cnt} rows) | Columns: [{cols_str}]")
            
        compact_catalog_desc = "\n".join(compact_summary_lines)

        rel_lines = []
        for rel in relationships:
            rel_lines.append(f"- {rel['from_table']}.{rel['from_column']} -> {rel['to_table']}.{rel['to_column']}")
        relationships_desc = "\n".join(rel_lines) if rel_lines else "None"

        user_prompt = (
            f"Active Dataset ID: {active_dataset_id}\n\n"
            f"Compact Catalog Index (ALL Tables):\n{compact_catalog_desc}\n\n"
            f"Available Foreign Key Relationships:\n{relationships_desc}\n\n"
            f"User Query:\n\"{user_query}\"\n\n"
            "Select the minimal required tables_needed and join_keys now:"
        )

        logger.info(f"Selecting required tables for query: '{user_query}'")

        raw_response = OllamaClient.call_model(
            prompt=user_prompt, system_prompt=TABLE_SELECTOR_SYSTEM_PROMPT, json_format=True
        )
        try:
            selection = json.loads(raw_response)
        except (json.JSONDecodeError, TypeError):
            raise ValueError("The model returned invalid table selection. The analysis stopped.") from None
        if not isinstance(selection, dict):
            raise ValueError("The model returned invalid table selection. The analysis stopped.")
        tables = selection.get("tables_needed", [])
        if not isinstance(tables, list) or not tables or not all(isinstance(table, str) and table for table in tables):
            raise ValueError("The model did not select valid tables. The analysis stopped.")
        return selection
