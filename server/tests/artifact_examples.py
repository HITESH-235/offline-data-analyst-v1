"""Controlled Python programs, executed by the real sandbox (no model needed)."""
EXAMPLES = {
 'line': """fig=go.Figure()
fig.add_scatter(x=['2022-01-01','2022-02-01','2022-03-01','2022-04-01'],y=[1200,-200,1600,1900],name='North — established customer revenue')
fig.add_scatter(x=['2022-01-01','2022-02-01','2022-03-01','2022-04-01'],y=[500,800,950,1100],name='South — recently acquired customer revenue')
fig.update_layout(title='Monthly revenue · custom Python',xaxis_title='Month',yaxis_title='Revenue (USD)',annotations=[dict(x='2022-02-01',y=-200,text='Refund period',showarrow=True)])
fig.write_html('output_chart.html')""",
 'scatter': """x=np.linspace(-10,10,1500)
fig=go.Figure(go.Scatter(x=x,y=np.sin(x)*x,mode='markers',marker=dict(size=5,color='#007D73'),name='Observations'))
fig.update_layout(title='Dense observations · custom Python',xaxis_title='Input',yaxis_title='Response')""",
 'histogram': """fig=go.Figure(go.Histogram(x=np.linspace(-20,40,400),nbinsx=18,name='Measurements'))
fig.update_layout(title='Measurement distribution',xaxis_title='Measurement',yaxis_title='Observations')""",
 'box': """fig=go.Figure()
fig.add_box(y=[-10,2,3,7,12,50],name='West region — established accounts',boxpoints='all')
fig.add_box(y=[-4,4,5,8,10,20],name='East region — recently acquired accounts',boxpoints='all')
fig.update_layout(title='Spread by region',yaxis_title='Revenue (USD)')""",
 'heatmap': """fig=go.Figure(go.Heatmap(z=[[1,-0.7,0.3],[-0.7,1,0.5],[0.3,0.5,1]],x=['Price','Quantity','Revenue'],y=['Price','Quantity','Revenue'],zmin=-1,zmax=1,colorscale=[[0,'#14212B'],[0.5,'#F5F3EE'],[1,'#007D73']]))
fig.update_layout(title='Correlation matrix · supplied coefficients')""",
 'pie': """fig=go.Figure(go.Pie(labels=['Existing customers','New customers','Other channels'],values=[60,30,10],hole=0.45))
fig.update_layout(title='Revenue share · donut outside table chart types')""",
 'dense': """fig=go.Figure(go.Bar(x=['Product category '+str(i)+' with a descriptive long name' for i in range(25)],y=[i-6 for i in range(25)]))
fig.update_layout(title='All 25 product categories',xaxis_title='Product category',yaxis_title='Quantity (units)')""",
 'png': """fig,ax=plt.subplots()
ax.plot(['Jan','Feb','Mar','Apr'],[10,-3,15,22],marker='o',label='North')
ax.plot(['Jan','Feb','Mar','Apr'],[4,7,9,14],marker='o',label='South')
ax.set_title('Matplotlib revenue · static image');ax.set_xlabel('Month');ax.set_ylabel('Revenue (USD)');ax.legend();ax.grid(alpha=0.2)
plt.savefig('output_chart.png')""",
 'empty': """fig=go.Figure();fig.update_layout(title='Empty figure')""",
 'no_chart': """print('No chart requested or generated.')""",
 'unsupported': """fig=go.Figure(go.Scattergeo(lon=[0,10],lat=[0,20]));fig.update_layout(title='Geographic chart needs external geometry')""",
}

EXAMPLES['capture_failed'] = """fig=go.Figure(go.Scatter(x=[1,2],y=[3,4]))
fig.update_layout(title='Capture unavailable — export retained')
def unavailable(*args,**kwargs):
    raise ValueError('Controlled JSON capture failure')
fig.write_json=unavailable"""
