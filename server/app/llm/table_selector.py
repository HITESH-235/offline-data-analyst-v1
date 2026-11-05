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

        try:
            raw_response = OllamaClient.call_model(
                prompt=user_prompt,
                system_prompt=TABLE_SELECTOR_SYSTEM_PROMPT,
                json_format=True
            )
            logger.debug(f"TableSelector raw output: {raw_response}")
            selection = json.loads(raw_response)
            
            # Ensure active_dataset_id is included if tables_needed is empty or missing
            tables_needed = selection.get("tables_needed", [])
            if not isinstance(tables_needed, list) or len(tables_needed) == 0:
                selection["tables_needed"] = [active_dataset_id]
                
            return selection
        except Exception as e:
            logger.error(f"TableSelector failed or connection error: {e}. Defaulting to active dataset.")
            return {
                "tables_needed": [active_dataset_id],
                "join_keys": [],
                "reasoning": f"Fallback to active dataset due to TableSelector error: {e}"
            }
