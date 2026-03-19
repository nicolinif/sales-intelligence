# Sales Intelligence

Aplicación web para análisis automático de archivos de ventas. Subís un CSV o Excel, y el sistema calcula métricas, genera gráficos y produce un reporte ejecutivo usando IA.

## Funcionalidades

- **Análisis automático** de archivos CSV y Excel (incluye archivos con múltiples hojas)
- **Gráficos** de barras, línea y torta generados automáticamente
- **Reporte ejecutivo** con Resumen General, Puntos Clave y Propuesta de acción
- **Comparación** entre dos archivos de ventas
- **Sistema de usuarios** con roles admin y usuario estándar
- **Exportación** del reporte a PDF

## Stack

- **Backend**: Python / Flask
- **Auth**: Flask-Login + PostgreSQL
- **IA**: Groq API (LLaMA 3.3 70B)
- **Gráficos**: Matplotlib
- **PDF**: ReportLab
- **Deploy**: Railway

## Variables de entorno

| Variable | Descripción |
|---|---|
| `GROQ_API_KEY` | API key de [Groq](https://console.groq.com) |
| `DATABASE_URL` | URL de conexión PostgreSQL (Railway lo setea automáticamente) |
| `SECRET_KEY` | Clave secreta de Flask para sesiones |
| `SETUP_TOKEN` | Token para crear el primer usuario admin vía `/setup-admin` |

## Deploy en Railway

1. Forkeá o cloná este repositorio
2. Creá un proyecto en [Railway](https://railway.app) y conectá el repo
3. Agregá el plugin de **PostgreSQL** al proyecto
4. Seteá las variables de entorno (`GROQ_API_KEY`, `SECRET_KEY`, `SETUP_TOKEN`)
5. Railway detecta el `Procfile` y despliega automáticamente

**Primer usuario admin:** una vez desplegado, visitá `/setup-admin?token=TU_SETUP_TOKEN` para crear el usuario inicial.

## Desarrollo local

```bash
# Clonar
git clone https://github.com/tu-usuario/sales-intelligence.git
cd sales-intelligence

# Entorno virtual
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Dependencias
pip install -r requirements.txt

# Variables de entorno
cp .env.example .env
# Editá .env con tus claves

# Correr
python app.py
```

## Formato de archivos soportados

El sistema detecta automáticamente las columnas de ventas, fecha y producto. Funciona mejor cuando las columnas tienen nombres claros como `monto`, `fecha`, `producto`, `categoria`, etc.

Los archivos Excel con múltiples hojas son tratados como períodos distintos (ej: una hoja por año o mes).
