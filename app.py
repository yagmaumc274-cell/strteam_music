import os
import sqlite3
from flask import Flask, g, jsonify, render_template_string

app = Flask(__name__)
DATABASE = "ficam.db"


def get_db():
  db = getattr(g, "_database", None)
  if db is None:
    db = g._database = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
  return db


@app.teardown_appcontext
def close_connection(exception):
  db = getattr(g, "_database", None)
  if db is not None:
    db.close()


def init_db():
  """Crea la base de datos y carga datos de prueba si está vacía"""
  with app.app_context():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
            CREATE TABLE IF NOT EXISTS materias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sigla TEXT NOT NULL,
                nombre TEXT NOT NULL,
                carrera TEXT NOT NULL,
                dia TEXT NOT NULL,
                hora_inicio TEXT NOT NULL,
                hora_fin TEXT NOT NULL,
                aula TEXT NOT NULL
            )
        """)

    # Verificar si ya tiene datos
    cursor.execute("SELECT COUNT(*) FROM materias")
    if cursor.fetchone()[0] == 0:
      sample_data = [
          (
              "MEC-101",
              "Física I",
              "Mecatrónica",
              "Lunes",
              "07:00",
              "09:00",
              "AULA-3",
          ),
          (
              "MEC-102",
              "Cálculo I",
              "Mecatrónica",
              "Lunes",
              "09:00",
              "11:00",
              "b007",
          ),
          (
              "ELT-201",
              "Circuitos",
              "Eléctrica",
              "Martes",
              "08:00",
              "10:00",
              "LAB-1",
          ),
          (
              "ELT-202",
              "Electromagnetismo",
              "Eléctrica",
              "Martes",
              "09:00",
              "11:00",
              "AULA-5",
          ),
      ]
      cursor.executemany(
          """
                INSERT INTO materias (sigla, nombre, carrera, dia, hora_inicio, hora_fin, aula)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
          sample_data,
      )
      db.commit()


# --- RUTA PRINCIPAL (FRONTEND) ---
@app.route("/")
def index():
  html = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>FICAM - Horarios</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-900 text-slate-100 min-h-screen p-4">
        <div class="max-w-4xl mx-auto">
            <header class="mb-6 text-center">
                <h1 class="text-3xl font-bold text-red-500">FICAM USFX</h1>
                <p class="text-slate-400">Simulador de Horarios y Detección de Cruces</p>
            </header>
            
            <div class="grid md:grid-cols-2 gap-6">
                <!-- Columna Izquierda: Catálogo de Materias -->
                <div class="bg-slate-800 p-4 rounded-xl shadow border border-slate-700">
                    <h2 class="text-xl font-semibold mb-3 border-b border-slate-700 pb-2">Materias Disponibles</h2>
                    <div id="lista-materias" class="space-y-2 max-h-[450px] overflow-y-auto pr-1">
                        Cargando materias...
                    </div>
                </div>
                
                <!-- Columna Derecha: Mi Horario Personal -->
                <div class="bg-slate-800 p-4 rounded-xl shadow border border-slate-700 flex flex-col justify-between">
                    <div>
                        <h2 class="text-xl font-semibold mb-3 border-b border-slate-700 pb-2">Mi Horario Personal</h2>
                        <div id="mi-horario" class="space-y-2 mb-4">
                            <p class="text-slate-400 text-sm">No has seleccionado materias.</p>
                        </div>
                    </div>
                    
                    <!-- Alerta de Choque de Horarios -->
                    <div id="alerta-choque" class="hidden bg-red-600/20 border border-red-500 text-red-300 p-3 rounded-lg text-sm font-medium">
                        ⚠️ ¡Atención! Tienes un cruce de horarios en este combo.
                    </div>
                </div>
            </div>
        </div>

        <script>
            let todasLasMaterias = [];
            let seleccionadas = JSON.parse(localStorage.getItem('mi_horario_ficam') || '[]');

            async function cargarMaterias() {
                const res = await fetch('/api/materias');
                todasLasMaterias = await res.json();
                renderizar();
            }

            function renderizar() {
                const contenedor = document.getElementById('lista-materias');
                contenedor.innerHTML = '';
                
                todasLasMaterias.forEach(m => {
                    const estaSeleccionada = seleccionadas.includes(m.id);
                    const div = document.createElement('div');
                    div.className = `p-3 rounded-lg border transition cursor-pointer flex justify-between items-center ${estaSeleccionada ? 'bg-red-950/40 border-red-500' : 'bg-slate-700/40 border-slate-600 hover:bg-slate-700'}`;
                    div.innerHTML = `
                        <div>
                            <span class="font-bold text-red-400">${m.sigla}</span> - ${m.nombre}
                            <div class="text-xs text-slate-400 mt-0.5">${m.dia} | ${m.hora_inicio} - ${m.hora_fin} | Aula: <span class="text-white font-semibold">${m.aula}</span></div>
                        </div>
                        <input type="checkbox" ${estaSeleccionada ? 'checked' : ''} onclick="toggleMateria(${m.id})" class="w-5 h-5 accent-red-500 cursor-pointer">
                    `;
                    contenedor.appendChild(div);
                });
                renderizarMiHorario();
            }

            function toggleMateria(id) {
                const index = seleccionadas.indexOf(id);
                if (index > -1) {
                    seleccionadas.splice(index, 1);
                } else {
                    seleccionadas.push(id);
                }
                localStorage.setItem('mi_horario_ficam', JSON.stringify(seleccionadas));
                renderizar();
            }

            function renderizarMiHorario() {
                const contenedor = document.getElementById('mi-horario');
                const alerta = document.getElementById('alerta-choque');
                const elegidas = todasLasMaterias.filter(m => seleccionadas.includes(m.id));
                
                if (elegidas.length === 0) {
                    contenedor.innerHTML = '<p class="text-slate-400 text-sm">No has seleccionado materias.</p>';
                    alerta.classList.add('hidden');
                    return;
                }

                let html = '';
                let hayChoque = false;
                
                // Lógica de detección de choques
                for (let i = 0; i < elegidas.length; i++) {
                    for (let j = i + 1; j < elegidas.length; j++) {
                        let m1 = elegidas[i];
                        let m2 = elegidas[j];
                        if (m1.dia === m2.dia) {
                            if (m1.hora_inicio < m2.hora_fin && m2.hora_inicio < m1.hora_fin) {
                                hayChoque = true;
                            }
                        }
                    }
                }

                elegidas.forEach(m => {
                    html += `
                        <div class="bg-slate-700/80 p-2.5 rounded-lg text-sm flex justify-between items-center border border-slate-600">
                            <div>
                                <span class="font-bold text-red-300">${m.sigla}</span>
                                <div class="text-xs text-slate-300">${m.dia} de ${m.hora_inicio} a ${m.hora_fin}</div>
                            </div>
                            <span class="text-xs bg-slate-900 px-2 py-1 rounded text-red-400 font-mono">${m.aula}</span>
                        </div>
                    `;
                });

                contenedor.innerHTML = html;
                if (hayChoque) {
                    alerta.classList.remove('hidden');
                } else {
                    alerta.classList.add('hidden');
                }
            }

            cargarMaterias();
        </script>
    </body>
    </html>
    """
  return html


# --- RUTA DE API (DEVUELVE JSON DESDE SQLITE) ---
@app.route("/api/materias")
def api_materias():
  db = get_db()
  cursor = db.cursor()
  cursor.execute("SELECT * FROM materias")
  rows = cursor.fetchall()
  materias = [dict(row) for row in rows]
  return jsonify(materias)


if __name__ == "__main__":
  init_db()
  print("🚀 Servidor Flask activo en: http://127.0.0.1:5000")
  app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
