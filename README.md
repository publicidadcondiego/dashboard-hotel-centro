# Dashboard semanal — Hotel Centro Huancayo (Google Ads)

Dashboard HTML que se **regenera solo cada lunes** con los datos de la última
semana (Google Ads vía Windsor.ai) y se publica en GitHub Pages.

## Cómo funciona
1. **GitHub Actions** corre cada lunes (`.github/workflows/weekly-dashboard.yml`).
2. `generate_dashboard.py` llama a la **API de Windsor.ai** con la API key guardada
   como secreto, trae la última semana (lun–dom), calcula KPIs, detecta cortes de
   entrega y topes de presupuesto, y arma `index.html`.
3. El histórico se guarda en `data/history.json` para el gráfico de tendencia.
4. **GitHub Pages** sirve `index.html` en una URL pública.

## Archivos
- `generate_dashboard.py` — genera el dashboard. Ajusta la config arriba del archivo
  (cuenta, tope de presupuesto, nombre).
- `.github/workflows/weekly-dashboard.yml` — automatización semanal.
- `data/history.json` — histórico (lo escribe el script solo).
- `index.html` — el dashboard (lo escribe el script solo).

## Nota sobre las observaciones
Las observaciones se generan por **reglas automáticas** (corte de entrega, tope de
presupuesto, eficiencia, mix de dispositivo). No reemplazan tu criterio: si quieres
observaciones a medida una semana puntual, edita `index.html` después de que corra,
o ajusta la función `build_observations()` del script.
