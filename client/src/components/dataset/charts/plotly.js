let loading;
export function loadPlotly() {
  if (window.Plotly) return Promise.resolve(window.Plotly);
  if (!loading) loading = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = `${import.meta.env.BASE_URL}vendor/plotly.min.js`;
    script.onload = () => resolve(window.Plotly);
    script.onerror = () => { script.remove(); loading = null; reject(new Error('The local chart renderer could not load. Reload the page or use Table.')); };
    document.head.append(script);
  });
  return loading;
}
