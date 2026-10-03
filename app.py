import os
import sqlite3
from datetime import date
from functools import wraps

from flask import (Flask, g, render_template, request, redirect,
                   url_for, flash, session, abort)
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE, "seguro_campesino.db"))

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cambia-esta-clave-por-otra-larga")

SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  usuario TEXT UNIQUE NOT NULL,
  clave_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS config (
  clave TEXT PRIMARY KEY,
  valor TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS socios (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cedula TEXT UNIQUE NOT NULL,
  nombres TEXT NOT NULL,
  apellidos TEXT NOT NULL,
  telefono TEXT,
  comunidad TEXT,
  fecha_ingreso TEXT,
  estado TEXT NOT NULL DEFAULT 'activo'
);
CREATE TABLE IF NOT EXISTS reuniones (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fecha TEXT NOT NULL,
  titulo TEXT NOT NULL,
  tipo TEXT NOT NULL DEFAULT 'reunion'
);
CREATE TABLE IF NOT EXISTS asistencias (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  reunion_id INTEGER NOT NULL REFERENCES reuniones(id) ON DELETE CASCADE,
  socio_id INTEGER NOT NULL REFERENCES socios(id),
  estado TEXT NOT NULL,
  UNIQUE (reunion_id, socio_id)
);
CREATE TABLE IF NOT EXISTS movimientos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tipo TEXT NOT NULL CHECK (tipo IN ('ingreso', 'gasto')),
  fecha TEXT NOT NULL,
  categoria TEXT NOT NULL,
  descripcion TEXT NOT NULL,
  monto REAL NOT NULL,
  comprobante TEXT,
  anulado INTEGER NOT NULL DEFAULT 0,
  registrado_por TEXT
);
CREATE TABLE IF NOT EXISTS pagos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  socio_id INTEGER NOT NULL REFERENCES socios(id),
  mes TEXT NOT NULL,
  concepto TEXT NOT NULL,
  monto REAL NOT NULL,
  fecha TEXT NOT NULL,
  forma_pago TEXT NOT NULL DEFAULT 'efectivo',
  observacion TEXT,
  anulado INTEGER NOT NULL DEFAULT 0,
  registrado_por TEXT
);
"""

CONCEPTO_CUOTA = "Cuota mensual"
CATEGORIAS_GASTO = ["Suministros y papelería", "Transporte", "Alimentación y refrigerios",
                    "Mantenimiento", "Servicios básicos", "Honorarios", "Eventos y mingas", "Otros gastos"]
CATEGORIAS_INGRESO = ["Donaciones", "Multas", "Eventos y rifas", "Aportes extraordinarios", "Otros ingresos"]
MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
         "Septiembre", "Octubre", "Noviembre", "Diciembre"]


@app.template_filter("money")
def f_money(v):
    v = float(v or 0)
    return f"-$ {abs(v):,.2f}" if v < 0 else f"$ {v:,.2f}"


@app.template_filter("fdate")
def f_fdate(s):
    try:
        y, m, d = s.split("-")
        return f"{d}/{m}/{y}"
    except Exception:
        return s or ""


@app.template_filter("mes_largo")
def f_mes_largo(ym):
    try:
        return f"{MESES[int(ym[5:7]) - 1]} {ym[:4]}"
    except Exception:
        return ym


# ---- monto en letras (para el recibo) ----
_UNI = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once",
        "doce", "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve", "veinte",
        "veintiuno", "veintidós", "veintitrés", "veinticuatro", "veinticinco", "veintiséis", "veintisiete",
        "veintiocho", "veintinueve"]
_DEC = {3: "treinta", 4: "cuarenta", 5: "cincuenta", 6: "sesenta", 7: "setenta", 8: "ochenta", 9: "noventa"}
_CEN = {1: "ciento", 2: "doscientos", 3: "trescientos", 4: "cuatrocientos", 5: "quinientos",
        6: "seiscientos", 7: "setecientos", 8: "ochocientos", 9: "novecientos"}


def _cientos(n):
    if n == 100:
        return "cien"
    c, r = divmod(n, 100)
    partes = [_CEN[c]] if c else []
    if r:
        if r < 30:
            partes.append(_UNI[r])
        else:
            d, u = divmod(r, 10)
            partes.append(_DEC[d] + (" y " + _UNI[u] if u else ""))
    return " ".join(partes)


def _apo(t):
    if t.endswith("veintiuno"):
        return t[:-9] + "veintiún"
    return t[:-3] + "un" if t.endswith("uno") else t


def monto_en_letras(v):
    ent, cts = int(v), int(round((v - int(v)) * 100))
    if ent == 0:
        txt = "cero"
    elif ent < 1000:
        txt = _cientos(ent)
    else:
        m, r = divmod(ent, 1000)
        txt = ("mil" if m == 1 else _apo(_cientos(m)) + " mil") + (" " + _cientos(r) if r else "")
    txt = _apo(txt)
    return f"{txt.upper()} CON {cts:02d}/100 DÓLAR{'ES' if ent != 1 else ''}"


# ---------------------------------------------------------------- base de datos
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    db.execute("INSERT OR IGNORE INTO config VALUES ('organizacion', 'Organización del Seguro Social Campesino')")
    db.execute("INSERT OR IGNORE INTO config VALUES ('cuota', '1.00')")
    if not db.execute("SELECT 1 FROM usuarios").fetchone():
        db.execute("INSERT INTO usuarios (usuario, clave_hash) VALUES (?, ?)",
                   ("admin", generate_password_hash("admin123")))
    db.commit()
    db.close()


def cfg(clave):
    r = get_db().execute("SELECT valor FROM config WHERE clave = ?", (clave,)).fetchone()
    return r["valor"] if r else ""


def set_cfg(clave, valor):
    get_db().execute("INSERT OR REPLACE INTO config (clave, valor) VALUES (?, ?)", (clave, valor))


@app.context_processor
def inyectar():
    return {"org": cfg("organizacion")}


# ---------------------------------------------------------------- utilidades
def login_required(f):
    @wraps(f)
    def envoltura(*a, **kw):
        if "usuario" not in session:
            return redirect(url_for("login"))
        return f(*a, **kw)
    return envoltura


def cedula_valida(c):
    """Validación de cédula ecuatoriana (módulo 10)."""
    if not (c.isdigit() and len(c) == 10):
        return False
    prov = int(c[:2])
    if prov < 1 or (prov > 24 and prov != 30) or int(c[2]) > 5:
        return False
    total = 0
    for i, d in enumerate(c[:9]):
        n = int(d) * (2 if i % 2 == 0 else 1)
        total += n - 9 if n > 9 else n
    return (10 - total % 10) % 10 == int(c[9])


def morosos(mes):
    """Socios activos sin pago de cuota mensual en el mes indicado (YYYY-MM)."""
    return get_db().execute(
        """SELECT s.* FROM socios s
           WHERE s.estado = 'activo' AND NOT EXISTS (
             SELECT 1 FROM pagos p
             WHERE p.socio_id = s.id AND p.mes = ? AND p.anulado = 0 AND p.concepto = ?)
           ORDER BY s.apellidos, s.nombres""", (mes, CONCEPTO_CUOTA)).fetchall()


def mes_actual():
    return date.today().strftime("%Y-%m")


def meses_atras(n):
    hoy = date.today()
    y, m, out = hoy.year, hoy.month, []
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return out[::-1]


def mes_anterior(ym):
    y, m = int(ym[:4]), int(ym[5:7]) - 1
    return f"{y - 1}-12" if m == 0 else f"{y}-{m:02d}"


def serie_mensual(meses):
    """Ingresos (cuotas + otros) y gastos por mes, para los diagramas."""
    db = get_db()
    ing = {m: 0.0 for m in meses}
    gas = {m: 0.0 for m in meses}
    desde = meses[0] + "-01"
    for r in db.execute("SELECT substr(fecha,1,7) AS m, SUM(monto) AS t FROM pagos "
                        "WHERE anulado=0 AND fecha>=? GROUP BY m", (desde,)):
        if r["m"] in ing:
            ing[r["m"]] += r["t"]
    for r in db.execute("SELECT substr(fecha,1,7) AS m, tipo, SUM(monto) AS t FROM movimientos "
                        "WHERE anulado=0 AND fecha>=? GROUP BY m, tipo", (desde,)):
        if r["m"] in ing:
            (ing if r["tipo"] == "ingreso" else gas)[r["m"]] += r["t"]
    return {"labels": [MESES[int(m[5:7]) - 1][:3] for m in meses],
            "ingresos": [round(ing[m], 2) for m in meses],
            "gastos": [round(gas[m], 2) for m in meses]}


def totales_mes(ym):
    db = get_db()
    cuotas = db.execute("SELECT COALESCE(SUM(monto),0) FROM pagos WHERE anulado=0 AND substr(fecha,1,7)=?",
                        (ym,)).fetchone()[0]
    otros = db.execute("SELECT COALESCE(SUM(monto),0) FROM movimientos WHERE anulado=0 AND tipo='ingreso' "
                       "AND substr(fecha,1,7)=?", (ym,)).fetchone()[0]
    gastos = db.execute("SELECT COALESCE(SUM(monto),0) FROM movimientos WHERE anulado=0 AND tipo='gasto' "
                        "AND substr(fecha,1,7)=?", (ym,)).fetchone()[0]
    return cuotas, otros, gastos


def saldo_total():
    db = get_db()
    ing = db.execute("SELECT COALESCE(SUM(monto),0) FROM pagos WHERE anulado=0").fetchone()[0]
    mov = db.execute("SELECT tipo, COALESCE(SUM(monto),0) AS t FROM movimientos WHERE anulado=0 "
                     "GROUP BY tipo").fetchall()
    m = {r["tipo"]: r["t"] for r in mov}
    return ing + m.get("ingreso", 0) - m.get("gasto", 0)


def variacion(actual, previo):
    return None if not previo else round((actual - previo) / previo * 100)


def gastos_por_categoria(ym):
    return [{"label": r["categoria"], "value": round(r["total"], 2)} for r in get_db().execute(
        "SELECT categoria, SUM(monto) AS total FROM movimientos WHERE tipo='gasto' AND anulado=0 "
        "AND substr(fecha,1,7)=? GROUP BY categoria ORDER BY total DESC", (ym,))]


# ---------------------------------------------------------------- acceso
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = get_db().execute("SELECT * FROM usuarios WHERE usuario = ?",
                             (request.form["usuario"].strip(),)).fetchone()
        if u and check_password_hash(u["clave_hash"], request.form["clave"]):
            session["usuario"] = u["usuario"]
            return redirect(url_for("inicio"))
        flash("Usuario o contraseña incorrectos.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------- inicio
@app.route("/")
@login_required
def inicio():
    db = get_db()
    mes = mes_actual()
    activos = db.execute("SELECT COUNT(*) FROM socios WHERE estado = 'activo'").fetchone()[0]
    cuotas, otros, gastos = totales_mes(mes)
    ingresos = cuotas + otros
    pc, po, pg = totales_mes(mes_anterior(mes))
    pendientes = len(morosos(mes))
    recientes = db.execute(
        """SELECT * FROM (
             SELECT p.fecha, 'ingreso' AS tipo, (s.apellidos || ' ' || s.nombres) AS descripcion,
                    p.concepto AS categoria, p.monto, p.id FROM pagos p
                    JOIN socios s ON s.id = p.socio_id WHERE p.anulado = 0
             UNION ALL
             SELECT m.fecha, m.tipo, m.descripcion, m.categoria, m.monto, m.id FROM movimientos m
                    WHERE m.anulado = 0)
           ORDER BY fecha DESC, id DESC LIMIT 6""").fetchall()
    return render_template(
        "inicio.html", mes=mes, activos=activos, ingresos=ingresos, gastos=gastos,
        saldo=saldo_total(), pendientes=pendientes, pagaron=max(activos - pendientes, 0),
        var_ing=variacion(ingresos, pc + po), var_gas=variacion(gastos, pg),
        serie=serie_mensual(meses_atras(6)), cats=gastos_por_categoria(mes), recientes=recientes)


# ---------------------------------------------------------------- socios
@app.route("/socios")
@login_required
def socios():
    q = request.args.get("q", "").strip()
    sql = ("SELECT s.*, EXISTS(SELECT 1 FROM pagos p WHERE p.socio_id = s.id AND p.mes = ? "
           "AND p.anulado = 0 AND p.concepto = ?) AS al_dia FROM socios s")
    params = (mes_actual(), CONCEPTO_CUOTA)
    if q:
        sql += " WHERE cedula LIKE ? OR nombres LIKE ? OR apellidos LIKE ? OR comunidad LIKE ?"
        params += (f"%{q}%",) * 4
    sql += " ORDER BY apellidos, nombres"
    return render_template("socios.html", lista=get_db().execute(sql, params).fetchall(), q=q)


@app.route("/socios/nuevo", methods=["GET", "POST"])
@app.route("/socios/<int:sid>/editar", methods=["GET", "POST"])
@login_required
def socio_form(sid=None):
    db = get_db()
    socio = db.execute("SELECT * FROM socios WHERE id = ?", (sid,)).fetchone() if sid else None
    if sid and not socio:
        abort(404)
    if request.method == "POST":
        f = request.form
        datos = (f["cedula"].strip(), f["nombres"].strip(), f["apellidos"].strip(),
                 f["telefono"].strip(), f["comunidad"].strip(),
                 f["fecha_ingreso"], f["estado"])
        if not cedula_valida(datos[0]):
            flash("Aviso: la cédula no parece válida (se guardó igual, revísala).", "error")
        try:
            if socio:
                db.execute("""UPDATE socios SET cedula=?, nombres=?, apellidos=?, telefono=?,
                              comunidad=?, fecha_ingreso=?, estado=? WHERE id=?""", datos + (sid,))
            else:
                db.execute("""INSERT INTO socios (cedula, nombres, apellidos, telefono,
                              comunidad, fecha_ingreso, estado) VALUES (?,?,?,?,?,?,?)""", datos)
            db.commit()
            flash("Socio guardado.", "ok")
            return redirect(url_for("socios"))
        except sqlite3.IntegrityError:
            flash("Ya existe un socio con esa cédula.", "error")
    return render_template("socio_form.html", s=socio, hoy=date.today().isoformat())


@app.route("/socios/<int:sid>")
@login_required
def socio_detalle(sid):
    db = get_db()
    s = db.execute("SELECT * FROM socios WHERE id = ?", (sid,)).fetchone()
    if not s:
        abort(404)
    pagos = db.execute("SELECT * FROM pagos WHERE socio_id = ? ORDER BY mes DESC, id DESC", (sid,)).fetchall()
    asis = db.execute("""SELECT estado, COUNT(*) AS n FROM asistencias
                         WHERE socio_id = ? GROUP BY estado""", (sid,)).fetchall()
    return render_template("socio_detalle.html", s=s, pagos=pagos,
                           asis={r["estado"]: r["n"] for r in asis})


# ---------------------------------------------------------------- reuniones y asistencia
@app.route("/reuniones", methods=["GET", "POST"])
@login_required
def reuniones():
    db = get_db()
    if request.method == "POST":
        db.execute("INSERT INTO reuniones (fecha, titulo, tipo) VALUES (?,?,?)",
                   (request.form["fecha"], request.form["titulo"].strip(), request.form["tipo"]))
        db.commit()
        flash("Reunión creada. Ahora toma la asistencia.", "ok")
    lista = db.execute("""SELECT r.*,
              (SELECT COUNT(*) FROM asistencias a WHERE a.reunion_id = r.id AND a.estado='presente') AS presentes
              FROM reuniones r ORDER BY fecha DESC, id DESC""").fetchall()
    return render_template("reuniones.html", lista=lista, hoy=date.today().isoformat())


@app.route("/reuniones/<int:rid>", methods=["GET", "POST"])
@login_required
def reunion(rid):
    db = get_db()
    r = db.execute("SELECT * FROM reuniones WHERE id = ?", (rid,)).fetchone()
    if not r:
        abort(404)
    if request.method == "POST":
        for s in db.execute("SELECT id FROM socios WHERE estado = 'activo'").fetchall():
            estado = request.form.get(f"socio_{s['id']}", "falta")
            db.execute("""INSERT INTO asistencias (reunion_id, socio_id, estado) VALUES (?,?,?)
                          ON CONFLICT(reunion_id, socio_id) DO UPDATE SET estado = excluded.estado""",
                       (rid, s["id"], estado))
        db.commit()
        flash("Asistencia guardada.", "ok")
        return redirect(url_for("reunion", rid=rid))
    lista = db.execute("""SELECT s.id, s.cedula, s.nombres, s.apellidos, s.comunidad, a.estado
                          FROM socios s
                          LEFT JOIN asistencias a ON a.socio_id = s.id AND a.reunion_id = ?
                          WHERE s.estado = 'activo' ORDER BY s.apellidos, s.nombres""", (rid,)).fetchall()
    return render_template("reunion.html", r=r, lista=lista)


# ---------------------------------------------------------------- pagos y recibos
@app.route("/pagos")
@login_required
def pagos():
    mes = request.args.get("mes", mes_actual())
    lista = get_db().execute(
        """SELECT p.*, s.nombres, s.apellidos, s.cedula FROM pagos p
           JOIN socios s ON s.id = p.socio_id
           WHERE p.mes = ? ORDER BY p.id DESC""", (mes,)).fetchall()
    total = sum(p["monto"] for p in lista if not p["anulado"])
    return render_template("pagos.html", lista=lista, mes=mes, total=total)


@app.route("/pagos/nuevo", methods=["GET", "POST"])
@login_required
def pago_nuevo():
    db = get_db()
    if request.method == "POST":
        f = request.form
        try:
            monto = float(f["monto"].replace(",", "."))
        except ValueError:
            monto = 0
        if monto <= 0:
            flash("El monto debe ser mayor a cero.", "error")
        elif f["concepto"].strip() == CONCEPTO_CUOTA and db.execute(
                "SELECT 1 FROM pagos WHERE socio_id=? AND mes=? AND concepto=? AND anulado=0",
                (f["socio_id"], f["mes"], CONCEPTO_CUOTA)).fetchone():
            flash("Ese socio ya pagó la cuota de ese mes.", "error")
        else:
            cur = db.execute(
                """INSERT INTO pagos (socio_id, mes, concepto, monto, fecha, forma_pago,
                                      observacion, registrado_por) VALUES (?,?,?,?,?,?,?,?)""",
                (f["socio_id"], f["mes"], f["concepto"].strip(), monto, f["fecha"],
                 f["forma_pago"], f["observacion"].strip(), session["usuario"]))
            db.commit()
            return redirect(url_for("recibo", pid=cur.lastrowid))
    lista = db.execute("SELECT id, cedula, nombres, apellidos FROM socios WHERE estado='activo' "
                       "ORDER BY apellidos, nombres").fetchall()
    return render_template("pago_form.html", socios=lista, mes=mes_actual(),
                           hoy=date.today().isoformat(), cuota=cfg("cuota"),
                           sel=request.args.get("socio_id", type=int), concepto=CONCEPTO_CUOTA)


@app.route("/pagos/<int:pid>/recibo")
@login_required
def recibo(pid):
    p = get_db().execute(
        """SELECT p.*, s.nombres, s.apellidos, s.cedula, s.comunidad FROM pagos p
           JOIN socios s ON s.id = p.socio_id WHERE p.id = ?""", (pid,)).fetchone()
    if not p:
        abort(404)
    return render_template("recibo.html", p=p, letras=monto_en_letras(p["monto"]),
                           formato=request.args.get("formato", "a4"))


@app.route("/pagos/<int:pid>/anular", methods=["POST"])
@login_required
def pago_anular(pid):
    db = get_db()
    db.execute("UPDATE pagos SET anulado = 1 WHERE id = ?", (pid,))
    db.commit()
    flash(f"Recibo {pid:06d} anulado.", "ok")
    return redirect(request.referrer or url_for("pagos"))


# ---------------------------------------------------------------- ingresos y gastos
@app.route("/finanzas")
@login_required
def finanzas():
    db = get_db()
    mes = request.args.get("mes", mes_actual())
    filas = db.execute(
        """SELECT 'pago' AS origen, p.id, p.fecha, 'ingreso' AS tipo, p.concepto AS categoria,
                  (s.apellidos || ' ' || s.nombres) AS descripcion, p.monto, p.anulado, '' AS comprobante
             FROM pagos p JOIN socios s ON s.id = p.socio_id WHERE substr(p.fecha,1,7) = ?
           UNION ALL
           SELECT 'mov', m.id, m.fecha, m.tipo, m.categoria, m.descripcion, m.monto, m.anulado,
                  COALESCE(m.comprobante, '') FROM movimientos m WHERE substr(m.fecha,1,7) = ?
           ORDER BY fecha DESC, id DESC""", (mes, mes)).fetchall()
    cuotas = sum(f["monto"] for f in filas if f["origen"] == "pago" and not f["anulado"])
    otros = sum(f["monto"] for f in filas if f["origen"] == "mov" and f["tipo"] == "ingreso" and not f["anulado"])
    gastos = sum(f["monto"] for f in filas if f["tipo"] == "gasto" and not f["anulado"])
    return render_template("finanzas.html", mes=mes, filas=filas, cuotas=cuotas, otros=otros,
                           gastos=gastos, saldo=saldo_total(), serie=serie_mensual(meses_atras(12)),
                           cats=gastos_por_categoria(mes), hoy=date.today().isoformat(),
                           cat_gasto=CATEGORIAS_GASTO, cat_ingreso=CATEGORIAS_INGRESO)


@app.route("/finanzas/nuevo", methods=["POST"])
@login_required
def movimiento_nuevo():
    f = request.form
    try:
        monto = float(f["monto"].replace(",", "."))
    except ValueError:
        monto = 0
    if f["tipo"] not in ("ingreso", "gasto") or monto <= 0 or not f["descripcion"].strip():
        flash("Revisa los datos: falta la descripción o el monto no es válido.", "error")
        return redirect(url_for("finanzas"))
    db = get_db()
    db.execute("""INSERT INTO movimientos (tipo, fecha, categoria, descripcion, monto, comprobante, registrado_por)
                  VALUES (?,?,?,?,?,?,?)""", (f["tipo"], f["fecha"], f["categoria"], f["descripcion"].strip(),
                                              monto, f["comprobante"].strip(), session["usuario"]))
    db.commit()
    flash("Ingreso registrado." if f["tipo"] == "ingreso" else "Gasto registrado.", "ok")
    return redirect(url_for("finanzas", mes=f["fecha"][:7]))


@app.route("/finanzas/<int:mid>/anular", methods=["POST"])
@login_required
def movimiento_anular(mid):
    db = get_db()
    db.execute("UPDATE movimientos SET anulado = 1 WHERE id = ?", (mid,))
    db.commit()
    flash("Movimiento anulado.", "ok")
    return redirect(request.referrer or url_for("finanzas"))


# ---------------------------------------------------------------- reportes
@app.route("/reportes")
@login_required
def reportes():
    db = get_db()
    mes = request.args.get("mes", mes_actual())
    deudores = morosos(mes)
    recaudado = db.execute("SELECT COALESCE(SUM(monto), 0) FROM pagos WHERE mes=? AND anulado=0",
                           (mes,)).fetchone()[0]
    resumen = db.execute(
        """SELECT s.id, s.apellidos, s.nombres, s.cedula,
             SUM(a.estado='presente') AS presentes,
             SUM(a.estado='falta') AS faltas,
             SUM(a.estado='justificada') AS justificadas
           FROM socios s LEFT JOIN asistencias a ON a.socio_id = s.id
           WHERE s.estado = 'activo' GROUP BY s.id ORDER BY s.apellidos, s.nombres""").fetchall()
    return render_template("reportes.html", mes=mes, deudores=deudores,
                           recaudado=recaudado, resumen=resumen, cuota=float(cfg("cuota") or 0))


# ---------------------------------------------------------------- configuración
@app.route("/configuracion", methods=["GET", "POST"])
@login_required
def configuracion():
    db = get_db()
    if request.method == "POST":
        if request.form["accion"] == "datos":
            set_cfg("organizacion", request.form["organizacion"].strip())
            set_cfg("cuota", request.form["cuota"].replace(",", "."))
            db.commit()
            flash("Configuración guardada.", "ok")
        else:
            u = db.execute("SELECT * FROM usuarios WHERE usuario = ?", (session["usuario"],)).fetchone()
            nueva = request.form["nueva"]
            if not check_password_hash(u["clave_hash"], request.form["actual"]):
                flash("La contraseña actual es incorrecta.", "error")
            elif len(nueva) < 6:
                flash("La nueva contraseña debe tener al menos 6 caracteres.", "error")
            else:
                db.execute("UPDATE usuarios SET clave_hash = ? WHERE id = ?",
                           (generate_password_hash(nueva), u["id"]))
                db.commit()
                flash("Contraseña cambiada.", "ok")
        return redirect(url_for("configuracion"))
    return render_template("configuracion.html", cuota=cfg("cuota"))


init_db()

if __name__ == "__main__":
    # host 0.0.0.0 permite entrar desde otros equipos de la misma red (ej. http://192.168.1.10:5000)
    app.run(host="0.0.0.0", port=5000, debug=False)
