const snapshot = (columns, data, tool, extra = {}) => ({ result: { columns, data }, tables: ['Captured fixture'], calculation: { steps: [{ tool, status: 'succeeded', parameters: {} }] }, ...extra });
export const fixtures = {
  ranking: snapshot(['ProductName','Quantity'], [{ProductName:'A very long product name that needs more than one line',Quantity:20},{ProductName:'Negative',Quantity:-10},{ProductName:'Missing',Quantity:null},{ProductName:'Zero',Quantity:0}], 'aggregation', {question:'Which products sold the most units?'}),
  monthly: snapshot(['Month','Revenue'], [{Month:'2025-12',Revenue:42},{Month:'2025-02',Revenue:-8},{Month:'2025-01',Revenue:15},{Month:'2025-03',Revenue:null}], 'aggregation', { result: { columns:['Month','Revenue'], data:[{Month:'2025-12',Revenue:42},{Month:'2025-02',Revenue:-8},{Month:'2025-01',Revenue:15},{Month:'2025-03',Revenue:null}], units: {Revenue:'USD'} } }),
  scatter: snapshot(['RecordID','Height','Weight'], [{RecordID:1,Height:150,Weight:45},{RecordID:2,Height:170,Weight:68},{RecordID:3,Height:180,Weight:80},{RecordID:4,Height:null,Weight:90}], 'filtering'),
  distribution: snapshot(['Value'], [-4,-2,-2,0,0,1,2,4,8,null].map(Value=>({Value})), 'filtering'),
  grouped: snapshot(['Region','Value'], [{Region:'West',Value:-4},{Region:'West',Value:1},{Region:'West',Value:3},{Region:'West',Value:100},{Region:'East',Value:2},{Region:'East',Value:3},{Region:'East',Value:4},{Region:'East',Value:5},{Region:'East',Value:null}], 'filtering'),
  correlation: snapshot(['Height','Weight'], [{Height:150,Weight:45}], 'correlation', { result: {columns:['Height','Weight'],data:[{Height:150,Weight:45}],correlation:{columns:['Height','Weight'],matrix:[[1,-.75],[-.75,1]]}} }),
  empty: snapshot(['Name','Value'], [], 'filtering'),
  ambiguous: snapshot(['Name','First','Second'], [{Name:'A',First:2,Second:4},{Name:'B',First:5,Second:6}], 'aggregation'),
};
