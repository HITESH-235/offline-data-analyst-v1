import json
import logging
from typing import Dict, Any, List
from app.llm.client import OllamaClient
from app.llm.prompts import TABLE_SELECTOR_SYSTEM_PROMPT
from app.services.metadata_service import MetadataService

logger = logging.getLogger(__name__)

class TableSelector:
    @staticmethod
    def select_tables(user_query: str, active_dataset_id: str, analysis_context=None, resolved_source=None) -> Dict[str, Any]:
        """
        Inspects user query, active dataset, and compact catalog index to select
        the minimal set of dataset_ids and join keys needed to answer the question.
        """
        catalog_index = MetadataService.get_catalog_index()
        tables_meta = catalog_index.get("tables", {})
        relationships = catalog_index.get("relationships", [])
        if resolved_source is not None:
            selection={'tables_needed':resolved_source.get('tables',[]),'join_keys':resolved_source.get('join_keys',[])}
            selection=TableSelector.resolve_selection(selection,tables_meta,active_dataset_id,resolved_source.get('database'))
            TableSelector.validate_selection(selection,tables_meta)
            return selection

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
        if analysis_context:
            user_prompt += '\nRelevant project analysis context: '+json.dumps(analysis_context)

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
        logger.info('Table selector output: %s',selection)
        if not isinstance(tables, list) or not tables or not all(isinstance(table, str) and table for table in tables):
            raise ValueError("The model did not select valid tables. The analysis stopped.")
        selection=TableSelector.resolve_selection(selection,tables_meta,active_dataset_id)
        TableSelector.validate_selection(selection,tables_meta)
        return selection

    @staticmethod
    def resolve_selection(selection,tables_meta,active_dataset_id,database=None):
        """Resolve bare names only within a known database; never rewrite qualified IDs."""
        import copy
        result=copy.deepcopy(selection)
        names=result.get('tables_needed')
        if not isinstance(names,list) or not names or any(not isinstance(n,str) or not n for n in names):
            raise ValueError('Select a nonempty list of catalog table identifiers.')
        databases={name.split('::',1)[0] for name in tables_meta if '::' in name}
        if database is not None and database not in databases:
            raise ValueError(f'Unknown source database {database!r}. Use a database from the catalog.')
        if database and any('::' in name and name.split('::',1)[0]!=database for name in names):
            raise ValueError('Source database conflicts with explicit qualified table identifiers.')
        scope=database or (active_dataset_id.split('::',1)[0] if '::' in active_dataset_id else None)
        if scope is None:
            qualified={name.split('::',1)[0] for name in names if name in tables_meta and '::' in name}
            if len(qualified)==1:scope=qualified.pop()
        mapping={}
        for name in names:
            if name in tables_meta:
                mapping[name]=name
                continue
            if '::' in name:
                raise ValueError(f'Unknown qualified table ID {name!r}; explicit database IDs are never redirected.')
            candidates=[key for key in tables_meta if '::' in key and key.split('::',1)[0]==scope and key.split('::',1)[1].casefold()==name.casefold()]
            if len(candidates)!=1:
                raise ValueError(f'Cannot resolve table {name!r} unambiguously in database {scope!r}. Use its full catalog ID.')
            mapping[name]=candidates[0]
        result['tables_needed']=list(dict.fromkeys(mapping.values()))
        keys=result.get('join_keys',[])
        if not isinstance(keys,list):raise ValueError('join_keys must be a list.')
        for key in keys:
            if not isinstance(key,dict):raise ValueError('Each join key must be an object.')
            for side in ('from_table','to_table'):
                name=key.get(side)
                if not isinstance(name,str):raise ValueError(f'Join key requires {side}.')
                if name in mapping:name=mapping[name]
                elif name not in result['tables_needed'] and '::' not in name:
                    candidates=[t for t in result['tables_needed'] if '::' in t and t.split('::',1)[1].casefold()==name.casefold()]
                    if len(candidates)!=1:raise ValueError(f'Ambiguous or unselected join endpoint {name!r}.')
                    name=candidates[0]
                key[side]=name
        result['join_keys']=keys
        return result

    @staticmethod
    def validate_selection(selection,tables_meta):
        tables=selection.get('tables_needed')
        if not isinstance(tables,list) or not tables or any(not isinstance(t,str) or t not in tables_meta for t in tables):
            raise ValueError(f"Invalid selected table identifiers: {tables!r}. Use concrete catalog table IDs, including database.db::Table for SQLite, not a whole database ID or invented alias.")
        for key in selection.get('join_keys',[]):
            if not isinstance(key,dict) or key.get('from_table') not in tables or key.get('to_table') not in tables:
                raise ValueError(f'Join keys must reference selected catalog IDs: {tables!r}.')
