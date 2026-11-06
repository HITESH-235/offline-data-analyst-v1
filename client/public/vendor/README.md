# Offline Plotly renderer

`plotly.min.js` is the unmodified MIT-licensed Plotly.js bundle supplied by the
installed Python Plotly 7.1.0 package (`plotly/package_data/plotly.min.js`). Its
version and license attribution are retained in the bundle header.

The Result workspace lazy-loads this local asset on first opening a chart.
There are no CDN, model, or backend chart-generation requests. The existing
Python ChartEngine also uses Plotly for standalone HTML artifacts; it does not
choose charts for the Result workspace. Result selection and transformations
live in `src/components/dataset/charts/chartModel.js`, tested with Node's built-in
test runner. When upgrading Python Plotly, refresh this bundle deliberately and
run the chart tests and browser checks together.
