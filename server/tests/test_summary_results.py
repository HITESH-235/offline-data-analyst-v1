import json
import unittest

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.analysis_engine import AnalysisEngine
from app.api.v1.projects import list_saved_analyses
from app.models.chat import DBChatHistory
from app.models.project import DBProject
from app.storage.sqlite.session import Base


class SummaryResultsTest(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({'ProductName': ['A', 'B', 'A'], 'Quantity': [2, 4, 6]})

    def execute(self, plan):
        return AnalysisEngine.execute_plan(None, 'fixture', plan, dataframe=self.frame,
                                           validate_tool_arguments=True)

    def test_narrative_has_statistics_without_input_rows(self):
        result = self.execute({'statistics': {'columns': ['Quantity']}})
        self.assertEqual(result['statistics']['Quantity']['mean'], 4)
        self.assertNotIn('data', result)
        self.assertNotIn('columns', result)

    def test_explicit_statistics_table_contains_calculations(self):
        result = self.execute({'statistics': {'columns': ['Quantity'], 'return_table': True}})
        self.assertEqual(result['row_count'], 1)
        self.assertEqual(result['data'][0]['column'], 'Quantity')
        self.assertEqual(result['data'][0]['mean'], 4)
        self.assertNotIn('ProductName', result['columns'])

    def test_ranked_totals_still_return_a_table(self):
        result = self.execute({'aggregation': {'group_by': ['ProductName'],
            'aggregations': {'Quantity': 'sum'}, 'sort_by': 'Quantity', 'ascending': False}})
        self.assertEqual(result['data'], [{'ProductName': 'A', 'Quantity': 8},
                                          {'ProductName': 'B', 'Quantity': 4}])

    def test_filter_still_returns_matching_rows(self):
        result = self.execute({'filters': [{'column': 'Quantity', 'operator': '>', 'value': 4}]})
        self.assertEqual(result['data'], [{'ProductName': 'A', 'Quantity': 6}])

    def test_saved_library_excludes_legacy_summary_rows(self):
        engine = create_engine('sqlite://')
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(DBProject(id='test', name='Test'))
            for ident, tool, params in [('legacy', 'statistics', {}),
                                        ('explicit', 'statistics', {'return_table': True}),
                                        ('ranking', 'aggregation', {})]:
                db.add(DBChatHistory(id=ident, project_id='test', role='assistant', content='Test',
                    metadata_json=json.dumps({'results': {'columns': ['value'], 'data': [{'value': 1}]},
                        'calculation': {'steps': [{'tool': tool, 'status': 'succeeded', 'parameters': params}]}})))
            db.commit()
            self.assertEqual({item['id'] for item in list_saved_analyses('test', db)}, {'explicit', 'ranking'})
        engine.dispose()


if __name__ == '__main__':
    unittest.main()
