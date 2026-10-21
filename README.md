# Agente de rifa por WhatsApp (demo)

Agente de chat con validación de comprobantes simulada y creación de boletos en la
API real de Bonanza. El chat no envía mensajes por WhatsApp. Los boletos que crea
Bonanza son reales aunque el banco de esta demo solo acepta datos ficticios: nunca
interpretes una validación de prueba como un pago real ni transfieras dinero.

## Requisitos y arranque

- Python 3.10 o superior.
- Una clave de API de OpenAI configurada localmente. No la envies por WhatsApp ni la
  agregues al repositorio.

En la carpeta raíz del proyecto, crea un archivo `.env` copiando `.env.example`.
Configura `OPENAI_API_KEY` y las credenciales de una cuenta de Bonanza autorizada
para crear boletos (`BONANZA_API_USER` y `BONANZA_API_PASSWORD`). El valor
predeterminado de `BONANZA_API_BASE_URL` es `http://127.0.0.1:3000/api`; cámbialo
si Bonanza se ejecuta en otra dirección. Usa HTTPS si la API está en otra máquina.
El archivo `.env` está excluido de Git. No pegues claves ni contraseñas en el
código, en `.env.example` ni en el chat.

El agente solo lee `OPENAI_API_KEY` de este archivo `.env`; una variable heredada
por PowerShell o VS Code no la habilita. Déjala vacía o elimina la entrada para
desactivar OpenAI y reinicia el agente para aplicar el cambio.

Antes de iniciar el agente, arranca la aplicación Bonanza y configura también
`JWT_SECRET` en el `.env` de `BONANZATODO-ULTIMAUPDATE`. Crea un usuario Bonanza
dedicado con permisos limitados y usa sus credenciales locales en el `.env` del
agente. Sin estas credenciales, el chat permanece disponible pero no puede crear
boletos.

En otra terminal de PowerShell, inicia Bonanza desde su carpeta:

```powershell
Set-Location ".\BONANZATODO-ULTIMAUPDATE"
npm install
npm start
```

El agente obtiene el token con `POST /api/login` y crea los boletos con
`POST /api/tickets`.

Antes de ofrecer un número, el agente también consulta el endpoint autenticado
`GET /api/tickets/{Numero}/disponibilidad?ValorBoleto={valor}&Cifra=2`. Este suma
el valor de los tickets activos con el mismo número y aplica el cupo de $6
utilizado por la creación. La consulta es informativa y no reserva el cupo; `POST
/api/tickets` vuelve a validarlo al crear.

También puedes iniciar ambos servicios desde la raíz del proyecto con el script
`iniciar-todo.ps1`. Abre dos ventanas separadas de PowerShell para ver los logs;
cierra cada ventana para detener su servidor:

```powershell
.\iniciar-todo.ps1
```

Las direcciones locales son `http://127.0.0.1:3000/login` (Bonanza) y
`http://127.0.0.1:8765/` (chat del agente).

En PowerShell, instala las dependencias y arranca el servidor:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
py -m uvicorn app.main:app --reload --port 8765
```

La documentacion interactiva queda en `http://127.0.0.1:8765/docs`.
El simulador visual de chat queda en `http://127.0.0.1:8765/`.

El chat permite enviar mensajes al agente, adjuntar un comprobante con datos
ficticios y reiniciar la sesión local. El botón de comprobante no sube ni analiza
una imagen real. Solo se admiten números de dos cifras (`00`-`99`) y valores de
`$0.50` a `$6.00` en saltos de `$0.50`. La disponibilidad/cupo se valida al crear
el boleto en Bonanza. Tras pasar el banco ficticio, el agente crea el boleto por
`POST /api/tickets` y presenta un enlace al ticket con el diseño de impresión de
la página Bonanza, incluyendo código, agencia y tabla de premios.
No se envía WhatsApp. La validación bancaria acepta una referencia de demo y
un monto igual al valor del boleto en dólares (por ejemplo, `$4.50` para un
boleto de `$4.50`); por eso no acredita dinero ni debe usarse para ventas reales.

## API de entrada

`POST /webhook/whatsapp` acepta un webhook simplificado:

```json
{
  "from_number": "demo-cliente-1",
  "text": "Quiero un boleto de $4.50 con el número 07"
}
```

Para simular el envio de un comprobante, marca `image_attached` y proporciona
**datos ficticios** que el OCR simulado leeria. La imagen en si no se sube ni se
procesa:

```json
{
  "from_number": "demo-cliente-1",
  "text": "Adjunto el comprobante",
  "image_attached": true,
  "simulated_receipt": {
    "reference": "DEMO-2026-0001",
    "amount": "4.50",
    "date": "2026-10-19"
  }
}
```

Para probar el rechazo, cambia la referencia o el monto. El flujo de pago solo
se confirma si existe un numero apartado y coinciden la referencia unica que
se entregó al apartar y el monto exacto del boleto en dólares (en el ejemplo,
`4.50`). El mismo comprobante no se puede reutilizar. Para probar rápidamente el
caso exitoso, también se acepta una referencia que contenga `pago` (sin distinguir
mayúsculas/minúsculas), siempre que el monto coincida exactamente con el precio
del boleto. Esta referencia de prueba puede reutilizarse; las referencias únicas
generadas al apartar siguen siendo de un solo uso. Este atajo solo existe en la
simulación.

`GET /api/tickets/{id}.html` muestra el ticket emitido con la plantilla térmica de
Bonanza. `GET /health` comprueba que la API está activa. Sin `OPENAI_API_KEY`, el
webhook responde `503`; no hay respuesta simulada de respaldo.

## Alcance y siguientes integraciones

- El webhook usa un formato propio y no valida firmas de Meta/Twilio.
- El historial y los enlaces de vista previa se pierden al reiniciar el agente;
  los boletos creados permanecen en la base de datos de Bonanza.
- El banco, OCR y entrega por WhatsApp siguen simulados. La validación de prueba
  puede activar la creación de un boleto real, así que no lo uses para ventas ni
  para recibir pagos reales.
- El monto del comprobante de prueba debe ser igual al valor del boleto, expresado
  en dólares; esto solo valida el flujo ficticio y no confirma transferencias reales.
- El API de tickets no admite una clave de idempotencia. Si se pierde la conexión
  durante un POST, revisa Bonanza antes de reintentar para evitar duplicados.

Pruebas locales de las reglas simuladas:

```powershell
py -m unittest discover -s tests -v
```
