"""
App web para el agente de análisis de ventas
Requiere: pip install flask groq pandas matplotlib openpyxl python-dotenv flask-login werkzeug
Correr: python app.py
Abrir: http://localhost:5000
"""

import json
import os
import uuid
import base64
import re
import io
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, session
from flask_login import login_user, logout_user, login_required, current_user
from groq import Groq
from dotenv import load_dotenv
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, HRFlowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from auth import init_db, create_user, get_user_by_username, get_all_users, delete_user, setup_login_manager

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cambiar-esto-en-produccion-" + uuid.uuid4().hex)
UPLOAD_FOLDER = "uploads_temp"
RESULTS_FOLDER = "resultados"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESULTS_FOLDER, exist_ok=True)

# Inicializar DB y login manager
init_db()
setup_login_manager(app)

# Límite de tamaño de archivos: 50MB
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024


# ─────────────────────────────────────────────
# HELPER: lectura de archivos con multi-hoja
# ─────────────────────────────────────────────

def leer_archivo(ruta: str) -> pd.DataFrame:
    """
    Lee CSV o Excel.
    Para Excel con múltiples hojas, combina todas en un único DataFrame
    agregando la columna 'hoja' con el nombre de cada hoja como contexto
    temporal (ej: '2023', 'Enero 2024').
    """
    if ruta.endswith(".csv"):
        return pd.read_csv(ruta)

    hojas = pd.read_excel(ruta, sheet_name=None)  # dict {nombre: DataFrame}

    if len(hojas) == 1:
        return list(hojas.values())[0]

    partes = []
    for nombre_hoja, df_hoja in hojas.items():
        if df_hoja.empty:
            continue
        df_hoja = df_hoja.copy()
        df_hoja["hoja"] = str(nombre_hoja)
        partes.append(df_hoja)

    if not partes:
        return pd.DataFrame()

    df_combined = pd.concat(partes, ignore_index=True)
    return df_combined

def cargar_datos(ruta: str) -> dict:
    try:
        df = leer_archivo(ruta)

        resultado = {
            "ok": True,
            "filas": len(df),
            "columnas": list(df.columns),
            "tipos": {col: str(df[col].dtype) for col in df.columns},
            "muestra": df.head(3).to_dict(orient="records"),
            "nulos": df.isnull().sum().to_dict(),
        }

        # Si tiene columna 'hoja', informar las hojas disponibles
        if "hoja" in df.columns:
            hojas = df["hoja"].unique().tolist()
            resultado["hojas_detectadas"] = hojas
            resultado["nota"] = (
                "El archivo tiene múltiples hojas combinadas. "
                "La columna 'hoja' contiene el nombre de cada hoja original "
                "(puede representar el período, año o mes de los datos). "
                "Usá esta columna para agrupar por período cuando sea relevante."
            )

        return resultado
    except Exception as e:
        return {"ok": False, "error": str(e)}


def calcular_metricas(ruta: str, col_ventas: str, col_fecha: str = None, col_producto: str = None) -> dict:
    try:
        df = leer_archivo(ruta)
        metricas = {
            "total_ventas": float(df[col_ventas].sum()),
            "promedio_venta": float(df[col_ventas].mean()),
            "venta_maxima": float(df[col_ventas].max()),
            "venta_minima": float(df[col_ventas].min()),
            "cantidad_registros": len(df),
        }
        if col_producto and col_producto in df.columns:
            top = df.groupby(col_producto)[col_ventas].sum().sort_values(ascending=False).head(5)
            metricas["top_5_productos"] = top.to_dict()

        # Si hay columna 'hoja' y no hay fecha, usar hoja como agrupador temporal
        if col_fecha and col_fecha in df.columns:
            df[col_fecha] = pd.to_datetime(df[col_fecha], errors="coerce")
            mensuales = df.groupby(df[col_fecha].dt.to_period("M"))[col_ventas].sum().astype(float)
            mensuales.index = mensuales.index.astype(str)
            metricas["ventas_por_mes"] = mensuales.to_dict()
        elif "hoja" in df.columns:
            por_hoja = df.groupby("hoja")[col_ventas].sum().astype(float)
            metricas["ventas_por_hoja"] = por_hoja.to_dict()
            metricas["nota_agrupacion"] = (
                "No se encontró columna de fecha. Se agruparon las ventas por nombre de hoja "
                "como referencia temporal. Usá 'ventas_por_hoja' para graficar la evolución."
            )

        return {"ok": True, **metricas}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def generar_grafico(etiquetas: list, valores: list, tipo: str, titulo: str, archivo_salida: str = "grafico.png") -> dict:
    try:
        os.makedirs(RESULTS_FOLDER, exist_ok=True)
        ruta_salida = os.path.join(RESULTS_FOLDER, os.path.basename(archivo_salida))

        # ── Paleta dark acorde a la web ──
        BG        = "#0e0e16"
        SURFACE   = "#13131a"
        ACCENT    = "#7c6ff7"
        GREEN     = "#4fd1a5"
        CORAL     = "#f07070"
        TEXT      = "#e8e8f0"
        TEXT_MUTED= "#6b6b80"
        GRID      = "#1e1e2e"
        COLORES   = ["#7c6ff7","#4fd1a5","#f0997b","#d4537e","#378add","#ba7517","#a78bfa"]

        fig, ax = plt.subplots(figsize=(11, 5.5))
        fig.patch.set_facecolor(BG)
        ax.set_facecolor(SURFACE)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID)
            spine.set_linewidth(0.5)
        ax.tick_params(colors=TEXT_MUTED, labelsize=9)
        ax.yaxis.grid(True, color=GRID, linewidth=0.5, linestyle="--", alpha=0.6)
        ax.set_axisbelow(True)

        def anotar_variaciones(ax, valores):
            if len(valores) < 2:
                return
            y_max = max(valores)
            for i in range(1, len(valores)):
                if valores[i - 1] != 0:
                    var = ((valores[i] - valores[i - 1]) / valores[i - 1]) * 100
                    color = GREEN if var >= 0 else CORAL
                    simbolo = "▲" if var >= 0 else "▼"
                    ax.text(i, valores[i] + y_max * 0.055,
                            f"{simbolo} {abs(var):.1f}%",
                            ha="center", va="bottom", fontsize=8,
                            fontweight="600", color=color)

        if tipo == "barras":
            bar_colors = [ACCENT] * len(etiquetas)
            bars = ax.bar(etiquetas, valores, color=bar_colors,
                          width=0.6, zorder=3,
                          linewidth=0, edgecolor="none")
            # Highlight barra máxima
            max_idx = valores.index(max(valores))
            bars[max_idx].set_color(GREEN)
            # Valor encima
            for bar, val in zip(bars, valores):
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + max(valores) * 0.012,
                        f"{val:,.0f}", ha="center", va="bottom",
                        fontsize=8, color=TEXT_MUTED)
            if len(valores) > 2:
                anotar_variaciones(ax, valores)
                ax.set_ylim(0, max(valores) * 1.30)
            plt.xticks(rotation=30, ha="right", color=TEXT_MUTED)

        elif tipo == "linea":
            x = range(len(etiquetas))
            ax.plot(x, valores, marker="o", color=ACCENT,
                    linewidth=2, markersize=6,
                    markerfacecolor=BG, markeredgecolor=ACCENT,
                    markeredgewidth=2, zorder=4)
            ax.fill_between(x, valores, alpha=0.07, color=ACCENT)
            for i, val in enumerate(valores):
                ax.text(i, val + max(valores) * 0.018, f"{val:,.0f}",
                        ha="center", va="bottom", fontsize=8, color=TEXT_MUTED)
            if len(valores) > 2:
                anotar_variaciones(ax, valores)
                ax.set_ylim(0, max(valores) * 1.30)
            plt.xticks(rotation=30, ha="right", color=TEXT_MUTED)
            ax.set_xticks(list(x))
            ax.set_xticklabels(etiquetas)

        elif tipo == "torta":
            wedge_colors = COLORES[:len(etiquetas)]
            wedges, texts, autotexts = ax.pie(
                valores, labels=etiquetas, autopct="%1.1f%%",
                colors=wedge_colors, startangle=90,
                wedgeprops={"linewidth": 2, "edgecolor": BG},
                pctdistance=0.75,
            )
            for t in texts: t.set_color(TEXT_MUTED); t.set_fontsize(9)
            for at in autotexts: at.set_color(TEXT); at.set_fontsize(8); at.set_fontweight("600")

        ax.set_title(titulo, fontsize=13, fontweight="600", pad=16,
                     color=TEXT, loc="left")
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines[["left", "bottom"]].set_color(GRID)
        plt.tight_layout(pad=1.5)
        plt.savefig(ruta_salida, dpi=150, bbox_inches="tight",
                    facecolor=BG, edgecolor="none")
        plt.close()
        return {"ok": True, "archivo": ruta_salida}
    except Exception as e:
        return {"ok": False, "error": str(e)}


TOOL_MAP = {
    "cargar_datos": cargar_datos,
    "calcular_metricas": calcular_metricas,
    "generar_grafico": generar_grafico,
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "cargar_datos",
            "description": "Carga un CSV o Excel y devuelve columnas, tipos y muestra. Usar primero.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ruta": {"type": "string", "description": "Ruta al archivo"},
                },
                "required": ["ruta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calcular_metricas",
            "description": "Calcula total, promedio, maximo, minimo, top productos y ventas por mes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ruta": {"type": "string", "description": "Ruta al archivo"},
                    "col_ventas": {"type": "string", "description": "Columna de ventas/monto"},
                    "col_fecha": {"type": "string", "description": "Columna de fecha (opcional)"},
                    "col_producto": {"type": "string", "description": "Columna de producto (opcional)"},
                },
                "required": ["ruta", "col_ventas"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generar_grafico",
            "description": "Genera un grafico (barras, linea o torta) y lo guarda como PNG.",
            "parameters": {
                "type": "object",
                "properties": {
                    "etiquetas": {"type": "array", "items": {"type": "string"}, "description": "Etiquetas EXACTAS de calcular_metricas"},
                    "valores": {"type": "array", "items": {"type": "number"}, "description": "Valores EXACTOS de calcular_metricas"},
                    "tipo": {"type": "string", "enum": ["barras", "linea", "torta"]},
                    "titulo": {"type": "string"},
                    "archivo_salida": {"type": "string"},
                },
                "required": ["etiquetas", "valores", "tipo", "titulo"],
            },
        },
    },
]


# ─────────────────────────────────────────────
# LOOP DEL AGENTE
# ─────────────────────────────────────────────

def ejecutar_agente(ruta_archivo: str, graficos_seleccionados: list = None):
    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    GRAF_LABELS = {
        "mes_barras":      "Un gráfico de BARRAS con los períodos temporales: usá 'ventas_por_mes' si existe, sino usá 'ventas_por_hoja'",
        "mes_linea":       "Un gráfico de LINEA con los períodos temporales: usá 'ventas_por_mes' si existe, sino usá 'ventas_por_hoja'",
        "top_productos":   "Un gráfico de BARRAS con los productos del campo top_5_productos",
        "categoria_torta": "Un gráfico de TORTA agrupando monto por la columna de categoría si existe",
    }
    if not graficos_seleccionados:
        graficos_seleccionados = list(GRAF_LABELS.keys())

    instrucciones_graf = "\n".join(
        f"   - {GRAF_LABELS[g]}" for g in graficos_seleccionados if g in GRAF_LABELS
    )

    pregunta = (
        "Analizá el archivo de ventas en '" + ruta_archivo + "' siguiendo estos pasos en orden:\n"
        "1. Llamá a cargar_datos para ver las columnas disponibles. "
        "   Si el resultado incluye 'hojas_detectadas', el archivo tiene múltiples hojas combinadas "
        "   y la columna 'hoja' representa el período de cada registro.\n"
        "2. Llamá a calcular_metricas usando las columnas reales que encontraste. "
        "   Si no hay columna de fecha, el resultado tendrá 'ventas_por_hoja' en lugar de 'ventas_por_mes'.\n"
        "3. Con los resultados EXACTOS de calcular_metricas, generá ÚNICAMENTE estos gráficos:\n"
        + instrucciones_graf + "\n"
        "4. Escribí un reporte ejecutivo completo con esta estructura EXACTA:\n"
        "   ## Resumen General\n"
        "   Un párrafo que sintetice el desempeño global: total de ventas, período analizado, volumen de registros y tendencia general.\n\n"
        "   ## Puntos Clave\n"
        "   Entre 4 y 6 puntos clave con insights concretos del análisis. Pueden incluir:\n"
        "   - Producto o categoría con mejor/peor desempeño\n"
        "   - Mes o período pico y valle\n"
        "   - Variaciones relevantes entre períodos\n"
        "   - Concentración de ventas (ej: top 2 productos representan X% del total)\n"
        "   - Cualquier anomalía o patrón destacable\n\n"
        "   ## Propuesta\n"
        "   Entre 3 y 5 recomendaciones accionables y específicas basadas en los datos analizados. "
        "   Deben ser concretas, no genéricas. Usá los nombres reales de productos, meses y valores.\n\n"
        "   Usá solo datos reales. No inventes valores ni conclusiones que no estén respaldadas por los números."
    )

    mensajes = [
        {
            "role": "system",
            "content": (
                "Sos un agente experto en análisis de datos de ventas. "
                "REGLAS ESTRICTAS:\n"
                "1. NUNCA inventes datos, nombres de productos, valores ni etiquetas.\n"
                "2. Las etiquetas y valores de generar_grafico deben ser EXACTAMENTE los de calcular_metricas.\n"
                "3. Si el resultado tiene 'ventas_por_mes', usá ese campo para gráficos temporales con TODOS los meses.\n"
                "4. Si el resultado tiene 'ventas_por_hoja', usá ese campo para gráficos temporales con TODAS las hojas.\n"
                "5. Usa los nombres reales de top_5_productos.\n"
                "6. El reporte debe tener SIEMPRE las tres secciones: ## Resumen General, ## Puntos Clave y ## Propuesta.\n"
                "7. Los Puntos Clave deben ser insights reales y específicos, no descripciones genéricas.\n"
                "8. La Propuesta debe citar productos, meses o valores reales, no dar consejos vagos."
            ),
        },
        {"role": "user", "content": pregunta},
    ]

    graficos = []

    while True:
        respuesta = client.chat.completions.create(
            model="llama3-groq-70b-8192-tool-use-preview",
            messages=mensajes,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=4096,
        )

        mensaje = respuesta.choices[0].message
        mensajes.append({
            "role": "assistant",
            "content": mensaje.content,
            "tool_calls": mensaje.tool_calls,
        })

        if not mensaje.tool_calls:
            reporte = mensaje.content or ""
            return reporte, graficos

        for tool_call in mensaje.tool_calls:
            nombre_tool = tool_call.function.name
            inputs = json.loads(tool_call.function.arguments)
            fn = TOOL_MAP.get(nombre_tool)
            resultado = fn(**inputs) if fn else {"error": "Tool no encontrada"}

            if nombre_tool == "generar_grafico" and resultado.get("ok"):
                graficos.append(resultado["archivo"])

            mensajes.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(resultado, ensure_ascii=False),
            })


def comparar_metricas(ruta1: str, ruta2: str) -> dict:
    """Calcula métricas de ambos archivos y las compara."""
    try:
        df1 = leer_archivo(ruta1)
        df2 = leer_archivo(ruta2)

        def detectar_col_ventas(df):
            candidatos = ["monto", "monto_final", "ventas", "total", "importe", "revenue", "amount"]
            for c in candidatos:
                if c in [col.lower() for col in df.columns]:
                    return next(col for col in df.columns if col.lower() == c)
            for col in df.columns:
                if df[col].dtype in ["float64", "int64"]:
                    return col
            return None

        def detectar_col_fecha(df):
            for col in df.columns:
                if "fecha" in col.lower() or "date" in col.lower():
                    return col
            return None

        def detectar_col_producto(df):
            for col in df.columns:
                if "producto" in col.lower() or "product" in col.lower() or "item" in col.lower():
                    return col
            return None

        col_v1 = detectar_col_ventas(df1)
        col_v2 = detectar_col_ventas(df2)
        col_f1 = detectar_col_fecha(df1)
        col_f2 = detectar_col_fecha(df2)
        col_p1 = detectar_col_producto(df1)
        col_p2 = detectar_col_producto(df2)

        resultado = {
            "archivo1": {
                "filas": len(df1),
                "columnas": list(df1.columns),
                "col_ventas": col_v1,
                "col_fecha": col_f1,
                "col_producto": col_p1,
            },
            "archivo2": {
                "filas": len(df2),
                "columnas": list(df2.columns),
                "col_ventas": col_v2,
                "col_fecha": col_f2,
                "col_producto": col_p2,
            }
        }

        if col_v1:
            resultado["archivo1"]["total_ventas"] = float(df1[col_v1].sum())
            resultado["archivo1"]["promedio_venta"] = float(df1[col_v1].mean())
            resultado["archivo1"]["venta_maxima"] = float(df1[col_v1].max())

        if col_v2:
            resultado["archivo2"]["total_ventas"] = float(df2[col_v2].sum())
            resultado["archivo2"]["promedio_venta"] = float(df2[col_v2].mean())
            resultado["archivo2"]["venta_maxima"] = float(df2[col_v2].max())

        if col_v1 and col_v2:
            t1 = resultado["archivo1"]["total_ventas"]
            t2 = resultado["archivo2"]["total_ventas"]
            resultado["variacion_total_pct"] = round(((t2 - t1) / t1) * 100, 2) if t1 else 0

        if col_v1 and col_f1:
            df1[col_f1] = pd.to_datetime(df1[col_f1], errors="coerce")
            men1 = df1.groupby(df1[col_f1].dt.to_period("M"))[col_v1].sum().astype(float)
            men1.index = men1.index.astype(str)
            resultado["archivo1"]["ventas_por_mes"] = men1.to_dict()

        if col_v2 and col_f2:
            df2[col_f2] = pd.to_datetime(df2[col_f2], errors="coerce")
            men2 = df2.groupby(df2[col_f2].dt.to_period("M"))[col_v2].sum().astype(float)
            men2.index = men2.index.astype(str)
            resultado["archivo2"]["ventas_por_mes"] = men2.to_dict()

        if col_v1 and col_p1:
            top1 = df1.groupby(col_p1)[col_v1].sum().sort_values(ascending=False).head(5)
            resultado["archivo1"]["top_productos"] = top1.to_dict()

        if col_v2 and col_p2:
            top2 = df2.groupby(col_p2)[col_v2].sum().sort_values(ascending=False).head(5)
            resultado["archivo2"]["top_productos"] = top2.to_dict()

        return {"ok": True, **resultado}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def generar_grafico_comparativo(
    etiquetas: list, valores1: list, valores2: list,
    label1: str, label2: str, titulo: str, archivo_salida: str
) -> dict:
    """Genera un gráfico de barras agrupadas comparando dos series."""
    try:
        os.makedirs(RESULTS_FOLDER, exist_ok=True)
        ruta_salida = os.path.join(RESULTS_FOLDER, os.path.basename(archivo_salida))

        BG       = "#0e0e16"
        SURFACE  = "#13131a"
        ACCENT   = "#7c6ff7"
        GREEN    = "#4fd1a5"
        TEXT     = "#e8e8f0"
        TEXT_M   = "#6b6b80"
        GRID     = "#1e1e2e"

        n = len(etiquetas)
        x = range(n)
        ancho = 0.35

        fig, ax = plt.subplots(figsize=(12, 5.5))
        fig.patch.set_facecolor(BG)
        ax.set_facecolor(SURFACE)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID); spine.set_linewidth(0.5)
        ax.tick_params(colors=TEXT_M, labelsize=9)
        ax.yaxis.grid(True, color=GRID, linewidth=0.5, linestyle="--", alpha=0.6)
        ax.set_axisbelow(True)

        b1 = ax.bar([i - ancho/2 for i in x], valores1, ancho, label=label1, color=ACCENT, linewidth=0)
        b2 = ax.bar([i + ancho/2 for i in x], valores2, ancho, label=label2, color=GREEN,  linewidth=0)

        for bar, val in zip(b1, valores1):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(max(valores1), max(valores2)) * 0.01,
                    f"{val:,.0f}", ha="center", va="bottom", fontsize=7.5, color=TEXT_M)
        for bar, val in zip(b2, valores2):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(max(valores1), max(valores2)) * 0.01,
                    f"{val:,.0f}", ha="center", va="bottom", fontsize=7.5, color=TEXT_M)

        ax.set_xticks(list(x))
        ax.set_xticklabels(etiquetas, rotation=30, ha="right", color=TEXT_M)
        ax.set_title(titulo, fontsize=13, fontweight="600", pad=16, color=TEXT, loc="left")
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines[["left", "bottom"]].set_color(GRID)

        legend = ax.legend(fontsize=10, framealpha=0,
                           labelcolor=TEXT, loc="upper right")

        plt.tight_layout(pad=1.5)
        plt.savefig(ruta_salida, dpi=150, bbox_inches="tight", facecolor=BG, edgecolor="none")
        plt.close()
        return {"ok": True, "archivo": ruta_salida}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def ejecutar_comparacion(ruta1: str, ruta2: str, nombre1: str, nombre2: str):
    """Corre el análisis comparativo entre dos archivos."""
    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    metricas = comparar_metricas(ruta1, ruta2)

    tools_comp = [
        {
            "type": "function",
            "function": {
                "name": "generar_grafico_comparativo",
                "description": "Genera un gráfico de barras agrupadas comparando dos períodos.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "etiquetas": {"type": "array", "items": {"type": "string"}, "description": "Etiquetas del eje X"},
                        "valores1":  {"type": "array", "items": {"type": "number"}, "description": "Valores del primer período"},
                        "valores2":  {"type": "array", "items": {"type": "number"}, "description": "Valores del segundo período"},
                        "label1":    {"type": "string", "description": "Nombre del primer período"},
                        "label2":    {"type": "string", "description": "Nombre del segundo período"},
                        "titulo":    {"type": "string", "description": "Título del gráfico"},
                        "archivo_salida": {"type": "string", "description": "Nombre del PNG de salida"},
                    },
                    "required": ["etiquetas", "valores1", "valores2", "label1", "label2", "titulo"],
                },
            },
        }
    ]

    tool_map_comp = {"generar_grafico_comparativo": generar_grafico_comparativo}

    pregunta = (
        f"Tenés los datos comparativos de dos períodos:\n"
        f"- Período A: '{nombre1}'\n"
        f"- Período B: '{nombre2}'\n\n"
        f"Datos calculados:\n{json.dumps(metricas, ensure_ascii=False, indent=2)}\n\n"
        "Usando SOLO los datos anteriores (no inventes ningún valor):\n"
        "1. Generá un gráfico comparativo de ventas por mes si hay datos de ambos períodos.\n"
        "2. Generá un gráfico comparativo de top productos si hay datos de ambos.\n"
        "3. Escribí un reporte ejecutivo comparativo que incluya:\n"
        "   - Variación del total de ventas entre períodos (usa el campo variacion_total_pct)\n"
        "   - Comparación de promedios y máximos\n"
        "   - Productos que mejoraron o empeoraron\n"
        "   - Tendencia mensual comparada\n"
        "   - Conclusión y recomendaciones\n"
        "Usá EXACTAMENTE los números de los datos proporcionados."
    )

    mensajes = [
        {
            "role": "system",
            "content": (
                "Sos un analista experto en comparación de datos de ventas entre períodos. "
                "NUNCA inventes datos. Usá SOLO los valores del JSON proporcionado. "
                "Cuando llames a generar_grafico_comparativo, los valores deben coincidir exactamente con los datos del JSON."
            ),
        },
        {"role": "user", "content": pregunta},
    ]

    graficos = []
    while True:
        respuesta = client.chat.completions.create(
            model="llama3-groq-70b-8192-tool-use-preview",
            messages=mensajes,
            tools=tools_comp,
            tool_choice="auto",
            max_tokens=4096,
        )
        mensaje = respuesta.choices[0].message
        mensajes.append({"role": "assistant", "content": mensaje.content, "tool_calls": mensaje.tool_calls})

        if not mensaje.tool_calls:
            return mensaje.content or "", graficos

        for tc in mensaje.tool_calls:
            inputs    = json.loads(tc.function.arguments)
            fn        = tool_map_comp.get(tc.function.name)
            resultado = fn(**inputs) if fn else {"error": "Tool no encontrada"}
            if tc.function.name == "generar_grafico_comparativo" and resultado.get("ok"):
                graficos.append(resultado["archivo"])
            mensajes.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(resultado, ensure_ascii=False),
            })


# ─────────────────────────────────────────────
# RUTAS DE AUTENTICACIÓN
# ─────────────────────────────────────────────

@app.route("/setup-admin")
def setup_admin():
    """Ruta de un solo uso para crear el primer admin. Borrar después del primer uso."""
    token = request.args.get("token", "")
    if token != os.environ.get("SETUP_TOKEN", ""):
        return "Acceso denegado", 403
    from auth import get_all_users
    if get_all_users():
        return "Ya existen usuarios. Esta ruta está deshabilitada.", 403
    username = request.args.get("username", "admin")
    password = request.args.get("password", "")
    if len(password) < 6:
        return "Especificá ?username=xxx&password=yyy&token=zzz (mínimo 6 caracteres)", 400
    ok, msg = create_user(username, password, is_admin=True)
    return f"{'OK' if ok else 'ERROR'}: {msg}"


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_user_by_username(username)
        if user and user.check_password(password):
            login_user(user, remember=True)
            return redirect(url_for("index"))
        error = "Usuario o contraseña incorrectos."
    return render_template("login.html", error=error)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/admin", methods=["GET", "POST"])
@login_required
def admin():
    if not current_user.is_admin:
        return redirect(url_for("index"))
    mensaje = None
    error   = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "crear":
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            ok, msg  = create_user(username, password, is_admin=False)
            if ok: mensaje = msg
            else:  error   = msg
        elif action == "eliminar":
            uid = request.form.get("user_id")
            if uid == current_user.id:
                error = "No podés eliminar tu propio usuario."
            else:
                delete_user(uid)
                mensaje = "Usuario eliminado."
    users = get_all_users()
    return render_template("admin.html", users=users, mensaje=mensaje,
                           error=error, current_user=current_user)


# ─────────────────────────────────────────────
# RUTAS PRINCIPALES
# ─────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    return render_template("index.html", username=current_user.username,
                           is_admin=current_user.is_admin)


@app.route("/comparar", methods=["POST"])
@login_required
def comparar():
    if "archivo1" not in request.files or "archivo2" not in request.files:
        return jsonify({"error": "Se necesitan dos archivos"}), 400

    a1 = request.files["archivo1"]
    a2 = request.files["archivo2"]

    for a in [a1, a2]:
        if Path(a.filename).suffix.lower() not in [".csv", ".xlsx", ".xls"]:
            return jsonify({"error": f"Formato no válido: {a.filename}"}), 400

    ext1 = Path(a1.filename).suffix.lower()
    ext2 = Path(a2.filename).suffix.lower()
    ruta1 = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4()}{ext1}")
    ruta2 = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4()}{ext2}")
    a1.save(ruta1); a2.save(ruta2)

    try:
        reporte, graficos = ejecutar_comparacion(ruta1, ruta2, a1.filename, a2.filename)
        graficos_b64 = []
        for ruta_g in graficos:
            if os.path.exists(ruta_g):
                with open(ruta_g, "rb") as f:
                    graficos_b64.append(base64.b64encode(f.read()).decode("utf-8"))
        return jsonify({"reporte": reporte, "graficos": graficos_b64,
                        "nombre1": a1.filename, "nombre2": a2.filename})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        for r in [ruta1, ruta2]:
            if os.path.exists(r): os.remove(r)
@app.route("/analizar", methods=["POST"])
@login_required
def analizar():
    if "archivo" not in request.files:
        return jsonify({"error": "No se recibió ningún archivo"}), 400

    archivo = request.files["archivo"]
    if archivo.filename == "":
        return jsonify({"error": "Nombre de archivo vacío"}), 400

    extension = Path(archivo.filename).suffix.lower()
    if extension not in [".csv", ".xlsx", ".xls"]:
        return jsonify({"error": "Solo se aceptan archivos CSV o Excel"}), 400

    # Gráficos seleccionados por el usuario
    graficos_raw = request.form.get("graficos", "[]")
    try:
        graficos_seleccionados = json.loads(graficos_raw)
    except Exception:
        graficos_seleccionados = ["mes_barras", "mes_linea", "top_productos", "categoria_torta"]

    nombre_temp = f"{uuid.uuid4()}{extension}"
    ruta_temp = os.path.join(UPLOAD_FOLDER, nombre_temp)
    archivo.save(ruta_temp)

    try:
        reporte, graficos = ejecutar_agente(ruta_temp, graficos_seleccionados)

        graficos_b64 = []
        for ruta_grafico in graficos:
            if os.path.exists(ruta_grafico):
                with open(ruta_grafico, "rb") as f:
                    encoded = base64.b64encode(f.read()).decode("utf-8")
                    graficos_b64.append(encoded)

        os.remove(ruta_temp)
        return jsonify({"reporte": reporte, "graficos": graficos_b64})

    except Exception as e:
        if os.path.exists(ruta_temp):
            os.remove(ruta_temp)
        return jsonify({"error": str(e)}), 500


@app.route("/preguntar", methods=["POST"])
@login_required
def preguntar():
    try:
        data         = request.get_json()
        pregunta     = data.get("pregunta", "")
        reporte      = data.get("reporte", "")
        historial_chat = data.get("historial", [])

        if not pregunta.strip():
            return jsonify({"error": "Pregunta vacía"}), 400

        client = Groq(api_key=os.environ["GROQ_API_KEY"])

        mensajes = [
            {
                "role": "system",
                "content": (
                    "Sos un analista de ventas experto. El usuario ya tiene un reporte generado "
                    "y te hace preguntas sobre ese análisis. Respondé de forma concisa y clara, "
                    "usando solo la información del reporte. Si la pregunta no puede responderse "
                    "con los datos disponibles, decilo amablemente.\n\n"
                    f"REPORTE DISPONIBLE:\n{reporte}"
                ),
            }
        ]

        for msg in historial_chat:
            mensajes.append({"role": msg["role"], "content": msg["content"]})

        mensajes.append({"role": "user", "content": pregunta})

        respuesta = client.chat.completions.create(
            model="llama3-groq-70b-8192-tool-use-preview",
            messages=mensajes,
            max_tokens=1024,
        )

        return jsonify({"respuesta": respuesta.choices[0].message.content})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/exportar-pdf", methods=["POST"])
@login_required
def exportar_pdf():
    try:
        data = request.get_json()
        reporte_md  = data.get("reporte", "")
        graficos_b64 = data.get("graficos", [])
        filename    = data.get("filename", "reporte")
        nombre_base = Path(filename).stem

        from datetime import datetime
        fecha = datetime.now().strftime("%d/%m/%Y %H:%M")

        # ── Colores dark ──
        COLOR_BG      = colors.HexColor("#0a0a0f")
        COLOR_SURFACE = colors.HexColor("#13131a")
        COLOR_ACCENT  = colors.HexColor("#7c6ff7")
        COLOR_TEXT    = colors.HexColor("#e8e8f0")
        COLOR_MUTED   = colors.HexColor("#6b6b80")
        COLOR_GREEN   = colors.HexColor("#4fd1a5")
        COLOR_BORDER  = colors.HexColor("#1e1e2e")

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            leftMargin=2*cm, rightMargin=2*cm,
            topMargin=2*cm, bottomMargin=2*cm,
        )

        # ── Estilos ──
        def estilo(name, parent="Normal", **kwargs):
            s = ParagraphStyle(name, parent=getSampleStyleSheet()[parent])
            for k, v in kwargs.items():
                setattr(s, k, v)
            return s

        s_tag     = estilo("tag",     fontSize=8,  textColor=COLOR_ACCENT, fontName="Helvetica", spaceBefore=0, spaceAfter=4)
        s_titulo  = estilo("titulo",  fontSize=24, textColor=COLOR_TEXT,   fontName="Helvetica-Bold", spaceBefore=0, spaceAfter=4, leading=28)
        s_meta    = estilo("meta",    fontSize=9,  textColor=COLOR_MUTED,  fontName="Courier", spaceBefore=8, spaceAfter=0)
        s_label   = estilo("label",   fontSize=8,  textColor=COLOR_MUTED,  fontName="Courier", spaceBefore=16, spaceAfter=8, letterSpacing=1)
        s_h2      = estilo("h2",      fontSize=14, textColor=COLOR_ACCENT, fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=5)
        s_h3      = estilo("h3",      fontSize=12, textColor=COLOR_ACCENT, fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=4)
        s_h4      = estilo("h4",      fontSize=11, textColor=colors.HexColor("#a78bfa"), fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=3)
        s_body    = estilo("body",    fontSize=10, textColor=colors.HexColor("#c0c0d0"), fontName="Helvetica", spaceBefore=0, spaceAfter=5, leading=16)
        s_li      = estilo("li",      fontSize=10, textColor=colors.HexColor("#c0c0d0"), fontName="Helvetica", spaceBefore=0, spaceAfter=3, leftIndent=14, leading=15)
        s_footer  = estilo("footer",  fontSize=8,  textColor=COLOR_MUTED,  fontName="Courier", alignment=TA_CENTER, spaceBefore=0, spaceAfter=0)

        story = []

        # ── Portada ──
        story.append(Paragraph("SALES INTELLIGENCE — REPORTE DE ANÁLISIS", s_tag))
        story.append(Spacer(1, 6))
        story.append(Paragraph("Reporte de <font color='#7c6ff7'>ventas</font>", s_titulo))
        story.append(HRFlowable(width="100%", thickness=1, color=COLOR_ACCENT, spaceAfter=8))
        story.append(Paragraph(f"Archivo: {nombre_base}　·　Generado: {fecha}", s_meta))
        story.append(Spacer(1, 24))

        # ── Gráficos ──
        if graficos_b64:
            story.append(Paragraph("VISUALIZACIONES", s_label))
            story.append(HRFlowable(width="100%", thickness=0.5, color=COLOR_BORDER, spaceAfter=10))
            page_w = A4[0] - 4*cm
            for b64 in graficos_b64:
                img_data = base64.b64decode(b64)
                img_buf  = io.BytesIO(img_data)
                img = RLImage(img_buf, width=page_w, height=page_w * 0.5)
                story.append(img)
                story.append(Spacer(1, 10))
            story.append(Spacer(1, 8))

        # ── Reporte ──
        story.append(Paragraph("REPORTE EJECUTIVO", s_label))
        story.append(HRFlowable(width="100%", thickness=0.5, color=COLOR_BORDER, spaceAfter=10))

        # Parsear markdown básico línea por línea
        for linea in reporte_md.split("\n"):
            linea = linea.strip()
            if not linea:
                story.append(Spacer(1, 4))
                continue
            # Negrita inline
            linea = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', linea)
            if linea.startswith("#### "):
                story.append(Paragraph(linea[5:], s_h4))
            elif linea.startswith("### "):
                story.append(Paragraph(linea[4:], s_h3))
            elif linea.startswith("## "):
                story.append(Paragraph(linea[3:], s_h2))
            elif linea.startswith(("- ", "* ")):
                story.append(Paragraph("• " + linea[2:], s_li))
            elif re.match(r'^\d+\. ', linea):
                story.append(Paragraph("• " + re.sub(r'^\d+\. ', '', linea), s_li))
            else:
                story.append(Paragraph(linea, s_body))

        story.append(Spacer(1, 20))
        story.append(HRFlowable(width="100%", thickness=0.5, color=COLOR_BORDER, spaceAfter=6))
        story.append(Paragraph(f"Sales Intelligence — powered by AI　·　{fecha}", s_footer))

        # ── Fondo dark en cada página ──
        def fondo_oscuro(canvas, doc):
            canvas.saveState()
            canvas.setFillColor(COLOR_BG)
            canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
            canvas.restoreState()

        doc.build(story, onFirstPage=fondo_oscuro, onLaterPages=fondo_oscuro)
        buffer.seek(0)

        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"reporte_{nombre_base}.pdf",
            mimetype="application/pdf",
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
