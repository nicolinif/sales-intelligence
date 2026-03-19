"""
Agente de análisis de ventas con Groq API
Requiere: pip install groq pandas matplotlib openpyxl python-dotenv
"""

import json
import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from groq import Groq
from dotenv import load_dotenv

load_dotenv()


# ─────────────────────────────────────────────
# 1. HERRAMIENTAS que el agente puede usar
# ─────────────────────────────────────────────

def cargar_datos(ruta: str) -> dict:
    try:
        df = pd.read_csv(ruta) if ruta.endswith(".csv") else pd.read_excel(ruta)
        return {
            "ok": True,
            "filas": len(df),
            "columnas": list(df.columns),
            "tipos": {col: str(df[col].dtype) for col in df.columns},
            "muestra": df.head(3).to_dict(orient="records"),
            "nulos": df.isnull().sum().to_dict(),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def calcular_metricas(ruta: str, col_ventas: str, col_fecha: str = None, col_producto: str = None) -> dict:
    try:
        df = pd.read_csv(ruta) if ruta.endswith(".csv") else pd.read_excel(ruta)
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
        if col_fecha and col_fecha in df.columns:
            df[col_fecha] = pd.to_datetime(df[col_fecha], errors="coerce")
            mensuales = df.groupby(df[col_fecha].dt.to_period("M"))[col_ventas].sum().astype(float)
            mensuales.index = mensuales.index.astype(str)
            metricas["ventas_por_mes"] = mensuales.to_dict()
        return {"ok": True, **metricas}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def generar_grafico(etiquetas: list, valores: list, tipo: str, titulo: str, archivo_salida: str = "grafico.png") -> dict:
    try:
        os.makedirs("resultados", exist_ok=True)
        archivo_salida = os.path.join("resultados", os.path.basename(archivo_salida))

        fig, ax = plt.subplots(figsize=(10, 5))
        fig.patch.set_facecolor("#f8f8f8")
        ax.set_facecolor("#f0f0f0")
        colores = ["#534AB7", "#1D9E75", "#D85A30", "#D4537E", "#378ADD"]
        if tipo == "barras":
            bars = ax.bar(etiquetas, valores, color=colores[:len(etiquetas)])
            ax.bar_label(bars, fmt="%.0f", padding=3, fontsize=9)
            plt.xticks(rotation=30, ha="right")
        elif tipo == "linea":
            ax.plot(etiquetas, valores, marker="o", color=colores[0], linewidth=2)
            ax.fill_between(range(len(etiquetas)), valores, alpha=0.1, color=colores[0])
            plt.xticks(rotation=30, ha="right")
        elif tipo == "torta":
            ax.pie(valores, labels=etiquetas, autopct="%1.1f%%", colors=colores)
        ax.set_title(titulo, fontsize=14, fontweight="bold", pad=15)
        ax.spines[["top", "right"]].set_visible(False)
        plt.tight_layout()
        plt.savefig(archivo_salida, dpi=150, bbox_inches="tight")
        plt.close()
        return {"ok": True, "archivo": archivo_salida}
    except Exception as e:
        return {"ok": False, "error": str(e)}


TOOL_MAP = {
    "cargar_datos": cargar_datos,
    "calcular_metricas": calcular_metricas,
    "generar_grafico": generar_grafico,
}


# ─────────────────────────────────────────────
# 2. DEFINICIÓN DE TOOLS para Groq
# ─────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "cargar_datos",
            "description": "Carga un CSV o Excel y devuelve columnas, tipos y muestra. Usar primero para entender el dataset.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ruta": {"type": "string", "description": "Ruta al archivo CSV o Excel"},
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
            "description": "Genera un grafico (barras, linea o torta) y lo guarda como PNG en la carpeta resultados/.",
            "parameters": {
                "type": "object",
                "properties": {
                    "etiquetas": {"type": "array", "items": {"type": "string"}, "description": "Lista de etiquetas con los valores EXACTOS devueltos por calcular_metricas"},
                    "valores": {"type": "array", "items": {"type": "number"}, "description": "Lista de valores numericos EXACTOS devueltos por calcular_metricas"},
                    "tipo": {"type": "string", "enum": ["barras", "linea", "torta"], "description": "Tipo de grafico"},
                    "titulo": {"type": "string", "description": "Titulo del grafico"},
                    "archivo_salida": {"type": "string", "description": "Nombre del archivo PNG"},
                },
                "required": ["etiquetas", "valores", "tipo", "titulo"],
            },
        },
    },
]


# ─────────────────────────────────────────────
# 3. LOOP DEL AGENTE
# ─────────────────────────────────────────────

def ejecutar_agente(ruta_archivo: str, pregunta: str = None) -> str:
    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    if pregunta is None:
        pregunta = (
            "Analizá el archivo de ventas en '" + ruta_archivo + "' siguiendo estos pasos en orden:\n"
            "1. Llamá a cargar_datos para ver las columnas disponibles.\n"
            "2. Llamá a calcular_metricas usando las columnas reales que encontraste.\n"
            "3. Con los resultados EXACTOS de calcular_metricas, llamá a generar_grafico para:\n"
            "   - Un grafico de barras con TODOS los meses del campo ventas_por_mes\n"
            "   - Un grafico de barras con los productos del campo top_5_productos\n"
            "4. Escribi un reporte ejecutivo usando solo los numeros y nombres reales de los datos."
        )

    mensajes = [
        {
            "role": "system",
            "content": (
                "Sos un agente experto en analisis de datos de ventas. "
                "REGLAS ESTRICTAS que debes seguir siempre:\n"
                "1. NUNCA inventes datos, nombres de productos, valores ni etiquetas. "
                "Todos los datos que uses en los graficos deben provenir EXCLUSIVAMENTE "
                "de los resultados de las herramientas.\n"
                "2. Cuando llames a generar_grafico, las etiquetas y valores deben ser copiados "
                "EXACTAMENTE de los resultados devueltos por cargar_datos o calcular_metricas. "
                "Nunca uses ejemplos como Producto A, Producto B ni valores como 1000, 1200, 1500 "
                "a menos que esos valores exactos hayan aparecido en los resultados de las herramientas.\n"
                "3. Para el grafico de ventas por mes, usa TODOS los meses devueltos por calcular_metricas, "
                "no solo los primeros tres.\n"
                "4. Para el grafico de top productos, usa los nombres reales del campo top_5_productos "
                "devuelto por calcular_metricas.\n"
                "5. El reporte final debe describir unicamente lo que encontraste en los datos reales."
            ),
        },
        {"role": "user", "content": pregunta},
    ]

    print("Agente iniciado...\n")

    while True:
        respuesta = client.chat.completions.create(
            model="moonshotai/kimi-k2-instruct",
            messages=mensajes,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=4096,
        )

        mensaje = respuesta.choices[0].message
        mensajes.append({
            "role": "assistant",
            "content": mensaje.content,
            "tool_calls": mensaje.tool_calls
        })

        if not mensaje.tool_calls:
            print("Analisis completado.\n")
            return mensaje.content

        for tool_call in mensaje.tool_calls:
            nombre_tool = tool_call.function.name
            inputs = json.loads(tool_call.function.arguments)
            print(f"  Ejecutando: {nombre_tool}({list(inputs.keys())})")

            fn = TOOL_MAP.get(nombre_tool)
            resultado = fn(**inputs) if fn else {"error": f"Tool '{nombre_tool}' no encontrada"}

            mensajes.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(resultado, ensure_ascii=False),
            })


# ─────────────────────────────────────────────
# 4. PUNTO DE ENTRADA
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python agente_ventas_groq.py <ruta_al_archivo.csv>")
        print("Ejemplo: python agente_ventas_groq.py ventas_ejemplo.csv")
        sys.exit(1)

    archivo = sys.argv[1]
    reporte = ejecutar_agente(archivo)

    print("=" * 60)
    print("REPORTE FINAL")
    print("=" * 60)
    print(reporte)

    os.makedirs("resultados", exist_ok=True)
    ruta_reporte = os.path.join("resultados", "reporte_ventas.txt")
    with open(ruta_reporte, "w", encoding="utf-8") as f:
        f.write(reporte)
    print("\nReporte guardado en resultados/reporte_ventas.txt")
