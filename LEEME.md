# Sistema de control – Seguro Social Campesino

Hecho con **Python + Flask** y base de datos **SQLite** (un solo archivo, sin instalar servidor de base de datos).

## Cómo ponerlo a funcionar

1. Instala Python 3.10 o superior desde https://www.python.org/downloads/ (marca "Add Python to PATH").
2. Abre una terminal (CMD) en esta carpeta y ejecuta:

       pip install -r requirements.txt
       python app.py

3. Abre el navegador en  http://localhost:5000
4. Usuario: **admin**   Contraseña: **admin123**  (cámbiala en Configuración).

Para usarlo desde otros equipos de la misma red (por ejemplo el celular del tesorero),
entra a  http://IP-DEL-COMPUTADOR:5000  (ej. http://192.168.1.10:5000).

## Dónde se guardan los datos
En el archivo `seguro_campesino.db` (se crea solo al iniciar). **Haz copias de respaldo de ese archivo
regularmente** (cópialo a una memoria USB o a la nube).

## Qué incluye
- Socios: registro, búsqueda, edición, validación de cédula ecuatoriana.
- Asistencias: crear reuniones/asambleas/mingas y marcar presente, falta o justificada.
- Pagos: cuota mensual, otros conceptos, anulación de recibos y control de duplicados.
- Recibos imprimibles con el monto en letras: en hoja (original y copia) o en formato ticket.
- Ingresos y gastos: registra gastos y otros ingresos (donaciones, multas, rifas) por categoría; las cuotas de los socios
  entran solas como ingreso. Muestra balance del mes, saldo en caja y diagramas de los últimos meses.
- Inicio con indicadores y diagramas: ingresos vs. gastos, gastos por categoría y porcentaje de cuotas cobradas.
- Reportes: socios que no han pagado en un mes, total recaudado y resumen de asistencia.
- Configuración: nombre de la organización, cuota por defecto y cambio de contraseña.

## Archivos
- `app.py` – toda la lógica y la base de datos.
- `templates/` – las pantallas (HTML).
